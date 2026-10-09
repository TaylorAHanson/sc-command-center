import { isPerson } from './creators';
import { resetWidgetRegistry } from './widgetRegistry';

/**
 * The virtual workspace this session reads and writes: Dev, Test or Prod.
 *
 * That is not the Databricks App you deployed (`APP_ENVIRONMENT` / the amber
 * badge). Each physical app — our own Dev included — has all three workspaces,
 * and promotion copies between them inside that app. The live dashboard used to
 * omit `env`, so FastAPI defaulted everything to Dev even on the prod app.
 *
 * Which workspace a page opens on is settled once, by `resolveWorkspace`,
 * before anything that reads stored data mounts: a link's `?env=` first,
 * else the one this person last chose on this computer. Only an Editor or Admin
 * on a domain may open Dev or Test; everyone else is held on Prod. That is a
 * UI rule — the server still answers any `env` a caller names.
 */
export type ContentEnv = 'dev' | 'test' | 'prod';

export const CONTENT_ENVS: readonly ContentEnv[] = ['dev', 'test', 'prod'];

export const CONTENT_ENV_LABELS: Record<ContentEnv, string> = {
  dev: 'Dev',
  test: 'Test',
  prod: 'Prod',
};

/**
 * Browser query so a shared link opens the same workspace: `?env=test`, the
 * same name and values as the API's `env`. Not `workspace`, which a link's hash
 * already uses (`#/workspace/<view>`) to mean "open in the editor".
 */
export const CONTENT_ENV_PARAM = 'env';

// Per person, so a shared computer keeps each person's own choice.
const storageKey = (user: string | null) => (user ? `sccc-content-env:${user}` : 'sccc-content-env');

export const parseContentEnv = (value: string | null | undefined): ContentEnv | null => {
  const v = (value || '').trim().toLowerCase();
  return v === 'dev' || v === 'test' || v === 'prod' ? v : null;
};

const fromUrl = (): ContentEnv | null => {
  try {
    return parseContentEnv(new URLSearchParams(window.location.search).get(CONTENT_ENV_PARAM));
  } catch {
    return null;
  }
};

const readStorage = (key: string): ContentEnv | null => {
  try {
    return parseContentEnv(localStorage.getItem(key));
  } catch {
    return null;
  }
};

const writeStorage = (key: string, env: ContentEnv) => {
  try { localStorage.setItem(key, env); } catch { /* private browsing */ }
};

/** What the address named on load: a shared link, or a reload of a page we wrote it on. */
const linked = fromUrl();

let user: string | null = null;
let current: ContentEnv = linked || 'prod';
const listeners = new Set<() => void>();

export interface WorkspaceAccess {
  /** False until `resolveWorkspace` has settled the workspace. */
  resolved: boolean;
  /** Editor or Admin on some domain, in any workspace. */
  canSwitch: boolean;
  /** A workspace a link asked for that this person may not open. */
  refused: ContentEnv | null;
}

let access: WorkspaceAccess = { resolved: false, canSwitch: false, refused: null };

const persistUrl = (env: ContentEnv) => {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set(CONTENT_ENV_PARAM, env);
    const next = url.pathname + url.search + url.hash;
    if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== next) {
      window.history.replaceState(window.history.state, '', next);
    }
  } catch {
    /* file: or test */
  }
};

export const getContentEnv = (): ContentEnv => current;

export const getWorkspaceAccess = (): WorkspaceAccess => access;

export const subscribeContentEnv = (fn: () => void): (() => void) => {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
};

export const setContentEnv = (env: ContentEnv) => {
  if (access.resolved && !access.canSwitch && env !== 'prod') return;
  writeStorage(storageKey(user), env);
  persistUrl(env);
  if (env === current) return;
  current = env;
  resetWidgetRegistry();
  listeners.forEach(l => l());
};

/** Hides the note about a refused link. */
export const dismissRefusedWorkspace = () => {
  if (!access.refused) return;
  access = { ...access, refused: null };
  listeners.forEach(l => l());
};

type Permissions = { username?: string; is_admin?: boolean; domain_permissions?: Record<string, string> };

const isEditor = (p: Permissions | null) =>
  !!p?.is_admin || Object.values(p?.domain_permissions || {}).some(level => level === 'editor' || level === 'admin');

let resolving: Promise<void> | null = null;

/**
 * Settles the workspace before the dashboard mounts, so nobody's first requests
 * go to a workspace they're about to be moved out of. Permissions are the same
 * in every workspace. If they can't be read, the page opens on Prod.
 */
export const resolveWorkspace = (): Promise<void> => {
  resolving ??= (async () => {
    let me: Permissions | null = null;
    try {
      const res = await fetch('/api/roles/my-permissions');
      if (res.ok) me = await res.json();
    } catch {
      /* opens on Prod */
    }
    user = isPerson(me?.username) ? me!.username!.trim() : null;
    const canSwitch = isEditor(me);
    const target = canSwitch ? (linked || readStorage(storageKey(user)) || 'dev') : 'prod';
    const refused = !canSwitch && linked && linked !== 'prod' ? linked : null;
    if (canSwitch) writeStorage(storageKey(user), target);
    if (target !== current) resetWidgetRegistry();
    current = target;
    persistUrl(target);
    access = { resolved: true, canSwitch, refused };
    listeners.forEach(l => l());
  })();
  return resolving;
};

/** Query string for a link that should open this workspace. */
export const contentEnvSearch = (): string => `?${CONTENT_ENV_PARAM}=${current}`;

const SKIP_ENV = (pathname: string) =>
  pathname === '/api/health' || pathname.startsWith('/api/health/')
  || pathname === '/api/settings' || pathname.startsWith('/api/settings/');

const BODY_ENV = (pathname: string) =>
  pathname === '/api/agent/chat' || pathname.startsWith('/api/agent/chat/')
  || pathname.startsWith('/api/agent/widget')
  || pathname.startsWith('/api/agent/uploads');

const stampUrl = (url: URL): URL => {
  if (!url.pathname.startsWith('/api/') || SKIP_ENV(url.pathname)) return url;
  if (!url.searchParams.has('env')) url.searchParams.set('env', current);
  return url;
};

const stampInitBody = (pathname: string, init: RequestInit): RequestInit => {
  if (!BODY_ENV(pathname)) return init;
  const body = init.body;
  if (body instanceof FormData) {
    if (!body.has('env')) body.append('env', current);
    return init;
  }
  if (typeof body !== 'string') return init;
  try {
    const parsed = JSON.parse(body);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || parsed.env != null) return init;
    return { ...init, body: JSON.stringify({ ...parsed, env: current }) };
  } catch {
    return init;
  }
};

/**
 * Every `/api` call that stores widgets, views or chats gets this session's
 * workspace, unless the URL already named one (promotion fetches all three).
 * Widget-generated `fetch('/api/...')` is covered too.
 */
export const installContentEnvFetch = () => {
  const flag = '__scccContentEnvFetch' as const;
  if ((window as unknown as Record<string, boolean>)[flag]) return;
  (window as unknown as Record<string, boolean>)[flag] = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    try {
      if (input instanceof Request) {
        const url = stampUrl(new URL(input.url, window.location.origin));
        if (url.href === input.url) return original(input, init);
        return original(new Request(url.href, input), init);
      }
      const raw = input instanceof URL ? input.href : String(input);
      const url = stampUrl(new URL(raw, window.location.origin));
      const nextInit = init ? stampInitBody(url.pathname, init) : init;
      return original(url.toString(), nextInit);
    } catch {
      return original(input as RequestInfo, init);
    }
  };
};

installContentEnvFetch();
