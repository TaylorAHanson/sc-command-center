import React, { createContext, useContext, useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { widgetRegistry } from '../widgetRegistry';
import { rememberedFilters, rememberFilters } from './rememberedFilters';
import { filterDefaults, isPage, MAX_NAME_LENGTH, MAX_TABS, newAppSpec, PAGE_WIDGET_PLACE, retargetLinks, shownTab, withTab, type App, type AppFilter, type AppSpec, type AppTab, type TabLayout, type WidgetLayout } from './appSpec';
import {
  appHash, appLink, isStandalone, linkTab, parseAppRoute, refersTo, routeHash, routeTab, tabIdOf, withoutRouteParams, type AppRoute,
} from './appRoute';
import { createLinkStateStore, instanceScope, linkStatePart, readLinkState, writeLinkState, type LinkState, type WidgetLinkState } from '../linkState';
import { LinkStateContext } from '../hooks/useLinkState';
import { useShell } from '../shell';
import { requestJson, type Acl, type Preflight, type PublishInclude, accessSummary } from '../sharing';

// An app can pin the built-in agent just as deliberately as an authored one, so
// "no pin" and "pinned to the default" have to be different values. Authored
// agents are UUIDs, so this word can never collide with one.
export const DEFAULT_AGENT_PIN = 'default';

const NO_VARIABLES = Object.freeze({}) as DashboardContextType['variables'];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const fromServer = (a: any): App => ({ ...a, locked: Boolean(a.is_locked) });

const reasonOf = (e: unknown): string => (e instanceof Error ? e.message : String(e));

// How long the address waits for what a view is set to to settle before it
// follows. Browsers refuse a page that rewrites its address a hundred-odd times
// in a few seconds, which a slider or a search box would otherwise do.
const MIRROR_DELAY_MS = 300;

const textKeysOf = (filters?: AppFilter[] | null) => new Set((filters || []).map(f => f.key));

// The address's link state as this page last wrote or read it, and whose it
// is. One per page rather than per provider: the workspace and a standalone
// shell hand the address to each other, and a hash link keeps the query
// string, so the state one app leaves behind would otherwise open the next.
let addressLink: { part: string; appId: string } | null = null;

// The mirror runs on every change, so an over-long view says so once.
let lastDropped = '';

/**
 * What a query string says `app` is set to, or null when it says nothing. A
 * filter only takes a value it offers ('' is All), as with remembered choices;
 * any other variable passes through to the widgets that read it.
 */
const linkedStateOf = (search: string, app: App): LinkState | null => {
  if (!linkStatePart(search)) return null;
  const filters = app.spec?.filters || [];
  const read = readLinkState(search, textKeysOf(filters));
  for (const f of filters) {
    if (!Object.prototype.hasOwnProperty.call(read.variables, f.key)) continue;
    const value = read.variables[f.key];
    if (!(typeof value === 'string' && (value === '' || f.options.includes(value)))) delete read.variables[f.key];
  }
  return read;
};

/** What the address says `app` is set to, unless another app left it there. */
const addressLinkFor = (app: App): LinkState | null => {
  const part = linkStatePart(window.location.search);
  if (!part || (addressLink?.part === part && addressLink.appId !== app.id)) return null;
  return linkedStateOf(window.location.search, app);
};

/**
 * The query string for a link to `app` as it is set: `variables` measured
 * against its filters' defaults, and the settings of widgets it places (or of
 * the one widget `only` names). `base` keeps whatever else the address holds.
 */
const linkSearch = (base: string, app: App, variables: Record<string, unknown>, widgets: WidgetLinkState, only?: string): string => {
  const filters = app.spec?.filters;
  const placed = new Set(only ? [instanceScope(only)] : app.spec.tabs.flatMap(t => t.widgets.map(w => instanceScope(w.i))));
  const { search, dropped } = writeLinkState(
    base,
    { variables, widgets: Object.fromEntries(Object.entries(widgets).filter(([scope]) => placed.has(scope))) },
    { defaults: filterDefaults(filters), textKeys: textKeysOf(filters) },
  );
  const left = dropped.join(', ');
  if (left && left !== lastDropped) console.warn(`Left out of the link to keep it short: ${left}`);
  lastDropped = left;
  return search;
};

export type { WidgetLayout, App, AppTab, AppSpec, AppBranding } from './appSpec';

/** Which version of a view a manager is looking at. Everyone else only ever sees the published one. */
export type ViewMode = 'draft' | 'published';

export interface AppVersion {
  version: number;
  name: string;
  published_by?: string | null;
  published_at?: string | null;
  timestamp?: string | null;
}

export interface ArchivedApp {
  id: string;
  name: string;
  domain?: string | null;
  version: number;
  archived_by?: string | null;
  archived_at?: string | null;
}

interface DashboardContextType {
  /** The caller's sidebar: views they own and views shared with them. */
  apps: App[];
  activeAppId: string;
  /** What the canvas shows: for a manager in Published mode, the published copy. */
  activeApp: App | null;
  activeAppTab: AppTab | null;
  activeDomain: string | null;
  setActiveDomain: (domainId: string | null) => void;
  isLoading: boolean;
  isAdmin: boolean;
  username: string;
  fetchApps: () => Promise<App[] | null>;
  /**
   * Show the app (and tab, and widget) a link names, adding it to the sidebar if
   * need be. A standalone app named by its own link is handed to the shell.
   */
  openRoute: (route: AppRoute) => Promise<void>;
  /** This provider serves one app shown on its own, not the workspace. */
  standalone: boolean;
  /** A widget a link asked to open full-screen, until the canvas has done so. */
  pendingWidgetId: string | null;
  clearPendingWidget: () => void;

  variables: Record<string, any>;
  setVariable: (key: string, value: any) => void;

  addApp: (name: string, domain?: string) => void;
  /** Deletes for good. The server refuses a view shared with others until it is archived. */
  deleteApp: (id: string) => Promise<string | null>;
  /** Takes a view out of every sidebar, keeping everything; managers only. */
  archiveApp: (id: string) => Promise<string | null>;
  restoreApp: (id: string) => Promise<string | null>;
  fetchArchived: () => Promise<ArchivedApp[]>;
  /** Closes a view shared with you: out of your sidebar, still shared with you. */
  hideApp: (id: string) => Promise<string | null>;
  renameApp: (id: string, newName: string) => void;
  reorderApps: (fromIndex: number, toIndex: number) => void;
  setActiveAppId: (id: string) => void;
  /** Show another tab of the app on screen. */
  selectTab: (tabId: string) => void;
  /** Adds an empty tab and shows it; returns its id, or null if it can't. */
  /** `firstName` names the existing first tab in the same save, when it has no name yet. */
  addTab: (appId: string, name: string, layout?: TabLayout, firstName?: string) => string | null;
  /** Turns a canvas into a page or back. A canvas with several widgets can't become a page. */
  setTabLayout: (appId: string, tabId: string, layout: TabLayout) => boolean;
  renameTab: (appId: string, tabId: string, name: string) => void;
  moveTab: (appId: string, fromIndex: number, toIndex: number) => void;
  removeTab: (appId: string, tabId: string) => void;
  duplicateApp: (appId: string) => void;
  toggleLock: (appId: string) => void;
  setPinnedAgent: (appId: string, tabId: string | null, agentId: string | null) => void;
  /** Save a change to an app's spec; resolves to the server's refusal, if any. */
  updateAppSpec: (appId: string, spec: AppSpec, pinnedAgentId?: string | null) => Promise<string | null>;
  /** Whether the signed-in user may change this app's settings (not its layout): Can manage, on the draft. */
  canEditApp: (app?: App | null) => boolean;
  /** Whether the signed-in user may change this app's widgets and tabs here. */
  canEditLayout: (app?: App | null) => boolean;

  /** Draft or Published, for a view the caller manages; always 'published' otherwise. */
  modeOf: (app?: App | null) => ViewMode;
  setAppMode: (appId: string, mode: ViewMode) => void;
  /** What publishing would leave behind, for the Publish dialog. Throws the server's reason. */
  loadPreflight: (appId: string) => Promise<Preflight>;
  /** Publishes the draft, with the widgets and agents ticked in the dialog. Throws the server's reason. */
  publishApp: (appId: string, include: PublishInclude[]) => Promise<void>;
  discardDraft: (appId: string) => Promise<string | null>;
  fetchHistory: (appId: string) => Promise<AppVersion[]>;
  /** Makes a published version the draft. Throws the server's reason. */
  revertApp: (appId: string, version: number) => Promise<void>;
  /** The share dialog saved a new access list; keeps the sidebar's icon in step. */
  sharingChanged: (appId: string, acl: Acl) => void;

  addWidget: (appId: string, tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => void;
  removeWidget: (appId: string, tabId: string, widgetId: string) => void;
  updateWidget: (appId: string, tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => void;
  updateLayout: (appId: string, tabId: string, newLayout: WidgetLayout[]) => void;

  generateShareLink: () => string;
  generateWidgetShareLink: (widgetId: string) => string;

  /** `editing`: changing a placed widget's settings, rather than placing it. */
  configModal: { isOpen: boolean; widgetId: string | null; initialConfig: any; onSave: ((config: any) => void) | null; editing: boolean };
  /** Pass `initialConfig` (even `{}`) when changing a placed widget; leave it out when placing one. */
  openConfigModal: (widgetId: string, onSave: (config: any) => void, initialConfig?: any) => void;
  closeConfigModal: () => void;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

/**
 * `standalone` serves one app on its own, already read by whoever chose that
 * shell: it never lists the workspace's apps, and nothing on it can be changed.
 */
export const DashboardProvider: React.FC<{
  children: React.ReactNode;
  standalone?: { app: App; route: AppRoute };
}> = ({ children, standalone }) => {
  const shell = useShell();
  const [activeDomain, setActiveDomain] = useState<string | null>(null);
  const [apps, setApps] = useState<App[]>(() => (standalone ? [standalone.app] : []));
  const [initialRoute] = useState(() => (standalone ? null : parseAppRoute(window.location.hash, window.location.search)));
  const [activeAppId, setActiveAppIdState] = useState<string>(standalone?.app.id ?? '');
  const [activeTabId, setActiveTabId] = useState<string | null>(standalone?.route.tabId ?? null);
  const [pendingWidgetId, setPendingWidgetId] = useState<string | null>(standalone?.route.widgetId ?? null);
  const [isLoading, setIsLoading] = useState(!standalone);
  const [isAdmin, setIsAdmin] = useState(false);
  const [username, setUsername] = useState('unknown');
  // Per view, for its managers; a view nobody chose a mode for opens on its draft.
  const [modes, setModes] = useState<Record<string, ViewMode>>({});
  // The published version of views whose managers switched to Published: the
  // sidebar's row is the draft, so this is read separately.
  const [publishedCopies, setPublishedCopies] = useState<Record<string, App>>({});
  // A standalone view's link is read as the shell opens it, so its first
  // render already shows what the link is set to.
  const [standaloneLink] = useState(() => (standalone ? addressLinkFor(standalone.app) : null));
  // Dashboard variables belong to the app on screen: its tabs share them, and
  // opening another app starts with none (or with what the link it was opened
  // by sets), so a filter chosen on one app can't quietly narrow another that
  // happens to read the same key. `linked` marks values a link set.
  const [appVariables, setAppVariables] = useState<{ appId: string; values: Record<string, any>; linked?: boolean }>(() => ({
    appId: standalone?.app.id ?? '', values: standaloneLink?.variables ?? NO_VARIABLES, linked: !!standaloneLink,
  }));
  const chosen = appVariables.appId === activeAppId ? appVariables.values : NO_VARIABLES;
  const linkedOpen = appVariables.appId === activeAppId && !!appVariables.linked;
  // Widgets' `useLinkState` settings, for the app in `linkHeldFor`.
  const [widgetLinkState] = useState(() => createLinkStateStore(standaloneLink?.widgets));
  const linkHeldFor = useRef(standalone?.app.id ?? '');
  const mirrorInputs = useRef<{ app: App | null; variables: Record<string, unknown> }>({ app: null, variables: NO_VARIABLES });
  const mirrorTimer = useRef<number | undefined>(undefined);

  const modeOf = useCallback((app?: App | null): ViewMode => {
    if (app?.access !== 'MANAGE') return 'published';
    return app.state === 'draft_only' ? 'draft' : (modes[app.id] ?? 'draft');
  }, [modes]);
  const listedApp = apps.find(a => a.id === activeAppId) || null;
  // Until the published copy arrives the draft stays on screen, read-only like the copy will be.
  const activeApp = listedApp && listedApp.access === 'MANAGE' && modeOf(listedApp) === 'published'
    ? (publishedCopies[listedApp.id] ?? listedApp)
    : listedApp;
  const activeAppTab = shownTab(activeApp, activeTabId);
  // A filter's default is what its variable holds until someone chooses; "All"
  // is a choice too (an empty string), so it is not overridden by the default.
  // The choice someone last left this view on outranks the default, except
  // when a link set the view: the link shows what its sender saw, whole.
  const filters = activeApp?.spec.filters;
  const me = username === 'unknown' ? null : username;
  const variables = useMemo(() => {
    const start = { ...filterDefaults(filters), ...(linkedOpen ? {} : rememberedFilters(me, activeAppId, filters)) };
    return Object.keys(start).length ? { ...start, ...chosen } : chosen;
  }, [filters, chosen, me, activeAppId, linkedOpen]);
  useEffect(() => {
    if (appVariables.appId) rememberFilters(me, appVariables.appId, apps.find(a => a.id === appVariables.appId)?.spec.filters, appVariables.values);
  }, [appVariables, me, apps]);
  const appsRef = useRef(apps);
  useEffect(() => { appsRef.current = apps; }, [apps]);

  // Mirror on change: the address follows what the app on screen is set to,
  // once it settles, with replaceState so settings add no Back steps. Only the
  // app whose settings are held writes, so one just left can't overwrite the
  // address of the one being opened.
  const mirrorLinkState = useCallback(() => {
    window.clearTimeout(mirrorTimer.current);
    mirrorTimer.current = window.setTimeout(() => {
      const { app, variables: shown } = mirrorInputs.current;
      if (!app || linkHeldFor.current !== app.id) return;
      const search = linkSearch(window.location.search, app, shown, widgetLinkState.snapshot());
      addressLink = { part: linkStatePart(search), appId: app.id };
      if (search === window.location.search) return;
      try {
        window.history.replaceState(window.history.state, '', `${window.location.pathname}${search}${window.location.hash}`);
      } catch (e) {
        console.warn('Could not update the address:', e);
      }
    }, MIRROR_DELAY_MS);
  }, [widgetLinkState]);
  useEffect(() => {
    mirrorInputs.current = { app: activeApp, variables };
    mirrorLinkState();
  }, [activeApp, variables, mirrorLinkState]);
  useEffect(() => {
    const unsubscribe = widgetLinkState.subscribe(mirrorLinkState);
    return () => {
      unsubscribe();
      window.clearTimeout(mirrorTimer.current);
    };
  }, [widgetLinkState, mirrorLinkState]);

  // Clear on app switch: another app starts with nothing set unless `linked`
  // (what its link says) sets it; the app already held keeps its settings,
  // which is what keeps them across tab switches. Nothing held yet means the
  // store has only ever served this app, so it is kept rather than cleared.
  const holdLinkState = useCallback((id: string, linked: LinkState | null) => {
    if (linked) {
      linkHeldFor.current = id;
      widgetLinkState.replace(linked.widgets);
      setAppVariables({ appId: id, values: linked.variables, linked: true });
    } else {
      if (linkHeldFor.current !== id) {
        if (linkHeldFor.current) widgetLinkState.replace({});
        linkHeldFor.current = id;
      }
      setAppVariables(prev => (prev.appId === id ? prev : { appId: id, values: NO_VARIABLES }));
    }
    mirrorLinkState();
  }, [widgetLinkState, mirrorLinkState]);

  // Read link state on open: what the address says `app` is set to, when a
  // navigation brought it (a pasted link, a reload, Back to another app). The
  // app already held keeps what it holds; the state another app left behind is
  // ignored, and the mirror writes over it.
  const takeLinkState = useCallback((app: App): LinkState | null => {
    if (linkHeldFor.current === app.id) return null;
    const linked = addressLinkFor(app);
    if (linked) addressLink = { part: linkStatePart(window.location.search), appId: app.id };
    return linked;
  }, []);

  const selectApp = useCallback((id: string, tabId: string | null = null, linked: LinkState | null = null) => {
    setActiveAppIdState(id);
    setActiveTabId(tabId);
    holdLinkState(id, linked);
  }, [holdLinkState]);

  const selectTab = useCallback((tabId: string) => setActiveTabId(tabId), []);

  // Bound to the app it was handed out on, so a widget seeding its variable as
  // it mounts on a newly opened app writes to that app, not the one just left.
  const setVariable = useCallback((key: string, value: any) => {
    // Skip the update when the value is unchanged. Widgets share this map, so a
    // new `variables` object re-renders every widget on the app; an unguarded
    // write of the SAME value from a widget effect (a common generated-widget
    // pattern) would otherwise loop forever — new object -> new widget `data`
    // -> effect re-runs -> writes again -> ... pegging a CPU core and dragging
    // the whole machine down the longer the app stays open.
    setAppVariables(prev => {
      const mine = prev.appId === activeAppId;
      const values = mine ? prev.values : NO_VARIABLES;
      if (mine && Object.is(values[key], value)) return prev;
      return { appId: activeAppId, values: { ...values, [key]: value }, linked: mine && prev.linked };
    });
  }, [activeAppId]);

  const fetchPermissions = useCallback(async (): Promise<string | null> => {
    try {
      const response = await fetch('/api/roles/my-permissions');
      if (response.ok) {
        const data = await response.json();
        setIsAdmin(Boolean(data.is_admin));
        setUsername(data.username || 'unknown');
        return data.username || null;
      }
    } catch (e) {
      console.error('Failed to load permissions:', e);
    }
    return null;
  }, []);

  const fetchApps = useCallback(async (): Promise<App[] | null> => {
    try {
      const response = await fetch('/api/apps/');
      if (!response.ok) return null;
      const data = await response.json();
      const loadedApps: App[] = (data.apps || []).map(fromServer);
      setApps(loadedApps);

      // While the address bar names an app, choosing one is `openRoute`'s job:
      // falling back to the first here would flash it, and its hash would race
      // the link's. A selection the server no longer returns (a view someone
      // has since archived or stopped sharing) falls back to the first app
      // instead of leaving the dashboard pointing at nothing.
      if (loadedApps.length > 0 && !parseAppRoute(window.location.hash, window.location.search)) {
        setActiveAppIdState(prev => (prev && loadedApps.some(a => a.id === prev) ? prev : loadedApps[0].id));
      }
      return loadedApps;
    } catch (e) {
      console.error('Failed to load apps:', e);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []); // No activeAppId dependency, so setting it doesn't refetch

  // A link opens only for people the view is shared with, and the sidebar
  // already lists those. A link to one that isn't listed is one this person
  // closed (it goes back in the sidebar), one named by a name it has since been
  // renamed from, or, for an admin, a view nobody shared with them; the server
  // says which view the link means. Anyone else gets nothing new.
  const openRoute = useCallback(async (route: AppRoute, known?: App[] | null) => {
    const canonicalize = (app?: App) => {
      const canonical = app
        ? appHash(app, routeTab(app, route.tabId), null, route.workspace)
        : routeHash(route);
      const search = withoutRouteParams(window.location.search);
      if (window.location.hash !== canonical || window.location.search !== search) {
        window.history.replaceState(window.history.state, '', window.location.pathname + search + canonical);
      }
    };

    // On its own, the page holds one app: a link to another is the shell's to follow.
    if (standalone) {
      const app = appsRef.current[0] ?? standalone.app;
      if (!refersTo(route.appId, app) || route.workspace) return;
      canonicalize(app);
      selectApp(app.id, tabIdOf(app, route.tabId), takeLinkState(app));
      if (route.widgetId) setPendingWidgetId(route.widgetId);
      return;
    }

    const find = (list?: App[] | null) => list?.find(a => refersTo(route.appId, a));
    canonicalize(find(appsRef.current));
    let list: App[] | null = known ?? appsRef.current;
    if (!find(list)) list = await fetchApps();
    let app = find(list);
    if (list && !app) {
      try {
        const res = await fetch(`/api/apps/${encodeURIComponent(route.appId)}`);
        const read: App | null = res.ok ? fromServer((await res.json()).app) : null;
        if (read) {
          app = list.find(a => a.id === read.id);
          if (!app) {
            const unhidden = await fetch(`/api/apps/${encodeURIComponent(read.id)}/hide`, { method: 'DELETE' });
            if (unhidden.ok) list = await fetchApps();
            app = list?.find(a => a.id === read.id);
          }
          if (!app) {
            app = read;
            setApps(prev => (prev.some(a => a.id === read.id) ? prev : [...prev, read]));
          }
        }
      } catch (e) {
        console.error('Failed to open the linked view', e);
      }
    }
    if (app) canonicalize(app);
    if (app && isStandalone(app) && !route.workspace) {
      shell.present(app, tabIdOf(app, route.tabId), route.widgetId);
      return;
    }
    selectApp(app?.id ?? route.appId, app ? tabIdOf(app, route.tabId) : null, app ? takeLinkState(app) : null);
    if (route.widgetId) setPendingWidgetId(route.widgetId);
  }, [fetchApps, selectApp, shell, standalone, takeLinkState]);

  // The link the page opened with is acted on once, though StrictMode runs this
  // effect twice in development. A standalone app was read before this mounted.
  const initialRouteRead = useRef(false);
  useEffect(() => {
    if (standalone) {
      fetchPermissions();
      return;
    }
    fetchPermissions();
    fetchApps().then(list => {
      if (!initialRoute || !list || initialRouteRead.current) return;
      initialRouteRead.current = true;
      openRoute(initialRoute, list);
    });
  }, [fetchPermissions, fetchApps, openRoute, initialRoute, standalone]);

  // Saves to one app go one at a time, in order. Each replaces the whole draft,
  // so two in flight at once could land in either order and the older would
  // win; publishing waits behind them too, so it publishes the last change.
  // Saves are started from handlers and from the effect on `apps`, never from
  // inside a state updater, which StrictMode runs twice.
  const saveQueue = useRef(new Map<string, Promise<string | null>>());
  const apiSyncApp = (app: App, method: 'PUT' | 'POST' = 'PUT'): Promise<string | null> => {
    const previous = saveQueue.current.get(app.id) ?? Promise.resolve();
    const next = previous.then(() => sendApp(app, method));
    saveQueue.current.set(app.id, next);
    return next;
  };

  // Apps whose widgets changed in a state update that has not been saved yet.
  // Marking one is idempotent, so an updater that runs twice marks it twice.
  const unsavedApps = useRef(new Set<string>());

  // Every save sends the whole spec, including tabs this screen doesn't show, so
  // a drag on the first tab can't drop the others. The server reads an absent
  // field as "keep it", so the pin is always sent: an empty string is the only
  // way a save can clear one. A save lands in the draft, which the server says
  // in its answer. Never rejects, so one failure can't stall the queue;
  // resolves to why the save failed, or null.
  const sendApp = async (app: App, method: 'PUT' | 'POST'): Promise<string | null> => {
    try {
      const res = await fetch(method === 'PUT' ? `/api/apps/${encodeURIComponent(app.id)}` : '/api/apps/', {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(method === 'POST' ? { id: app.id } : {}),
          name: app.name,
          domain: app.domain || "General",
          is_locked: app.locked || false,
          pinned_agent_id: app.pinned_agent_id || '',
          spec: app.spec
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const reason = typeof data?.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        console.error(`Failed to save app ${app.id}: ${reason}`);
        return reason;
      }
      if (data?.state) {
        setApps(prev => prev.map(a => (a.id === app.id ? { ...a, state: data.state, has_draft: true, is_draft: true } : a)));
      }
      return null;
    } catch (e) {
      console.error('Failed to save app:', e);
      return 'The save did not reach the server.';
    }
  };

  useEffect(() => {
    if (unsavedApps.current.size === 0) return;
    const ids = [...unsavedApps.current];
    unsavedApps.current.clear();
    for (const id of ids) {
      const app = apps.find(a => a.id === id);
      if (app) apiSyncApp(app);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps]);

  // What a view the caller just created is until the list is next read: theirs,
  // a draft, shared with nobody.
  const ownNewApp = (app: Omit<App, 'access' | 'state'>): App => ({
    ...app,
    access: 'MANAGE',
    state: 'draft_only',
    owner: me,
    username: me ?? undefined,
    published_version: null,
    has_draft: true,
    is_draft: true,
    shared_with_me: false,
    sharing: 'private',
    link: null,
    version: 0,
  });

  const addApp = (name: string, domain?: string) => {
    const id = uuidv4();
    const newApp = ownNewApp({
      id,
      name,
      // The one tab takes the app's id, as every view's tab does, so a link to
      // the app and a link to its tab are the same link.
      spec: newAppSpec(id),
      domain: domain || 'General',
    });
    setApps([...apps, newApp]);
    selectApp(newApp.id);
    apiSyncApp(newApp, 'POST');
  };

  const duplicateApp = (appId: string) => {
    const template = apps.find(a => a.id === appId);
    if (template) {
      const id = uuidv4();
      const single = template.spec.tabs.length === 1;
      const tabIds = new Map(template.spec.tabs.map(tab => [tab.id, single ? id : uuidv4()]));
      const newApp: App = ownNewApp({
        ...template,
        id,
        name: `${template.name} (Copy)`,
        locked: false,
        spec: {
          ...template.spec,
          tabs: template.spec.tabs.map(tab => ({
            ...tab,
            id: tabIds.get(tab.id)!,
            widgets: tab.widgets.map(w => ({ ...w, i: uuidv4(), props: retargetLinks(w.props, tabIds) })),
          })),
        },
      });
      setApps([...apps, newApp]);
      selectApp(newApp.id);
      apiSyncApp(newApp, 'POST');
    }
  };

  // Out of the sidebar at once; back in, with the server's reason, if it refuses.
  const dropApp = async (id: string, url: string, method: 'POST' | 'DELETE'): Promise<string | null> => {
    const index = appsRef.current.findIndex(a => a.id === id);
    const dropped = appsRef.current[index];
    const remaining = appsRef.current.filter(a => a.id !== id);
    setApps(remaining);
    if (activeAppId === id && remaining.length > 0) selectApp(remaining[0].id);
    try {
      await saveQueue.current.get(id);
      await requestJson(url, { method });
      return null;
    } catch (e) {
      console.error(`Failed to ${method === 'DELETE' ? 'delete' : 'remove'} app ${id}`, e);
      if (dropped) setApps(prev => (prev.some(a => a.id === id) ? prev : [...prev.slice(0, index), dropped, ...prev.slice(index)]));
      return reasonOf(e);
    }
  };

  const deleteApp = (id: string) => dropApp(id, `/api/apps/${encodeURIComponent(id)}`, 'DELETE');
  const archiveApp = (id: string) => dropApp(id, `/api/apps/${encodeURIComponent(id)}/archive`, 'POST');
  const hideApp = (id: string) => dropApp(id, `/api/apps/${encodeURIComponent(id)}/hide`, 'POST');

  const restoreApp = async (id: string): Promise<string | null> => {
    try {
      await requestJson(`/api/apps/${encodeURIComponent(id)}/restore`, { method: 'POST' });
      await fetchApps();
      return null;
    } catch (e) {
      return reasonOf(e);
    }
  };

  const fetchArchived = useCallback(async (): Promise<ArchivedApp[]> => {
    try {
      return (await requestJson<{ apps: ArchivedApp[] }>('/api/apps/archived')).apps || [];
    } catch (e) {
      console.error('Failed to load archived views', e);
      return [];
    }
  }, []);

  const renameApp = (id: string, newName: string) => {
    if (!newName.trim()) return;
    const app = apps.find(a => a.id === id);
    if (!canEditApp(app)) return;

    const newApps = apps.map(a => a.id === id ? { ...a, name: newName.trim() } : a);
    setApps(newApps);
    const updatedApp = newApps.find(a => a.id === id);
    if (updatedApp) apiSyncApp(updatedApp);
  };

  const reorderApps = (fromIndex: number, toIndex: number) => {
    // Only affect UI order, DB doesn't care for now
    const newApps = [...apps];
    const [removed] = newApps.splice(fromIndex, 1);
    newApps.splice(toIndex, 0, removed);
    setApps(newApps);
  };

  const toggleLock = (appId: string) => {
    const app = apps.find(a => a.id === appId);
    if (!canEditApp(app)) return;

    const newApps = apps.map(a => a.id === appId ? { ...a, locked: !a.locked } : a);
    setApps(newApps);
    const updatedApp = newApps.find(a => a.id === appId);
    if (updatedApp) apiSyncApp(updatedApp);
  };

  // Who may change an app's settings: its managers, on its draft. Every save
  // lands in the draft, so the published copy a manager switched to is
  // read-only, like it is to everyone else. Layout editing has its own rule (a
  // locked app is read-only even to its managers); a locked app still answers
  // true here, because the lock is one of these settings.
  const canEditApp = useCallback((app?: App | null): boolean => (
    app?.access === 'MANAGE' && modeOf(app) === 'draft'
  ), [modeOf]);

  // Who may change what is on an app's canvases: its widgets and its tabs. A
  // locked app is read-only to everyone, and an app shown on its own is built
  // in the workspace instead.
  const canEditLayout = useCallback((app?: App | null): boolean => {
    if (!app || standalone || app.locked) return false;
    return canEditApp(app);
  }, [standalone, canEditApp]);

  const refreshPublishedCopy = useCallback(async (appId: string) => {
    try {
      const { app } = await requestJson<{ app: App }>(`/api/apps/${encodeURIComponent(appId)}?mode=published`);
      setPublishedCopies(prev => ({ ...prev, [appId]: fromServer(app) }));
    } catch (e) {
      console.error(`Failed to load the published version of ${appId}`, e);
    }
  }, []);

  const setAppMode = useCallback((appId: string, mode: ViewMode) => {
    setModes(prev => ({ ...prev, [appId]: mode }));
    if (mode === 'published') refreshPublishedCopy(appId);
  }, [refreshPublishedCopy]);

  // After publishing, discarding or reverting, the draft and the published
  // version both moved: read the sidebar again, and the published copy if it's on screen.
  const afterVersionChange = async (appId: string) => {
    setPublishedCopies(prev => {
      const next = { ...prev };
      delete next[appId];
      return next;
    });
    await fetchApps();
    if (modes[appId] === 'published') await refreshPublishedCopy(appId);
  };

  const loadPreflight = async (appId: string): Promise<Preflight> => {
    await saveQueue.current.get(appId);
    return requestJson<Preflight>(`/api/apps/${encodeURIComponent(appId)}/publish/preflight`, { method: 'POST' });
  };

  const publishApp = async (appId: string, include: PublishInclude[]): Promise<void> => {
    await saveQueue.current.get(appId);
    await requestJson(`/api/apps/${encodeURIComponent(appId)}/publish`, {
      method: 'POST',
      body: JSON.stringify({ include }),
    });
    await afterVersionChange(appId);
  };

  const discardDraft = async (appId: string): Promise<string | null> => {
    try {
      await saveQueue.current.get(appId);
      await requestJson(`/api/apps/${encodeURIComponent(appId)}/discard`, { method: 'POST' });
      await afterVersionChange(appId);
      return null;
    } catch (e) {
      return reasonOf(e);
    }
  };

  const fetchHistory = useCallback(async (appId: string): Promise<AppVersion[]> => (
    (await requestJson<{ history: AppVersion[] }>(`/api/apps/history?app_id=${encodeURIComponent(appId)}`)).history || []
  ), []);

  const revertApp = async (appId: string, version: number): Promise<void> => {
    await saveQueue.current.get(appId);
    await requestJson(`/api/apps/${encodeURIComponent(appId)}/revert`, {
      method: 'POST',
      body: JSON.stringify({ version }),
    });
    setModes(prev => ({ ...prev, [appId]: 'draft' }));
    await afterVersionChange(appId);
  };

  const sharingChanged = useCallback((appId: string, acl: Acl) => {
    const sharing = accessSummary(acl.entries);
    setApps(prev => prev.map(a => (a.id === appId ? { ...a, sharing, owner: acl.owner ?? a.owner } : a)));
  }, []);

  // Pin an agent to the whole app (tabId null) or to one tab, which then
  // overrides the app's there; pass null as the agent to clear that pin. Saved
  // like every other app setting: optimistic locally, then a full PUT. Both are
  // the same right as renaming the app, as the view's pin always was.
  const setPinnedAgent = (appId: string, tabId: string | null, agentId: string | null) => {
    const app = apps.find(a => a.id === appId);
    if (!app || !canEditApp(app)) return;
    const tab = tabId ? app.spec.tabs.find(t => t.id === tabId) : null;
    if (tabId && !tab) return;

    const next = agentId || null;
    if (((tab ? tab.pinned_agent_id : app.pinned_agent_id) || null) === next) return;

    const updatedApp = tab
      ? withTab(app, tab.id, t => ({ ...t, pinned_agent_id: next }))
      : { ...app, pinned_agent_id: next };
    setApps(apps.map(a => a.id === appId ? updatedApp : a));
    apiSyncApp(updatedApp);
  };

  // How the app presents itself, its branding and its assistant, and optionally
  // its own agent pin (undefined leaves it). Optimistic like the pin, but a
  // refusal is handed back and undone, because the dialog that made it is still
  // open and can say why.
  const updateAppSpec = async (appId: string, spec: AppSpec, pinnedAgentId?: string | null): Promise<string | null> => {
    const app = apps.find(a => a.id === appId);
    if (!app || !canEditApp(app)) return 'You can’t change this view’s settings.';
    const updatedApp = pinnedAgentId === undefined
      ? { ...app, spec }
      : { ...app, spec, pinned_agent_id: pinnedAgentId || null };
    setApps(prev => prev.map(a => a.id === appId ? updatedApp : a));
    const refusal = await apiSyncApp(updatedApp);
    if (refusal) setApps(prev => prev.map(a => (a === updatedApp ? app : a)));
    return refusal;
  };

  // Changes an app's tabs and saves it, under the same rule as moving a widget.
  const changeTabs = (appId: string, change: (tabs: AppTab[]) => AppTab[] | null): boolean => {
    const app = apps.find(a => a.id === appId);
    if (!app || !canEditLayout(app)) return false;
    const tabs = change(app.spec.tabs);
    if (!tabs) return false;
    const updatedApp = { ...app, spec: { ...app.spec, tabs } };
    setApps(apps.map(a => a.id === appId ? updatedApp : a));
    apiSyncApp(updatedApp);
    return true;
  };

  const addTab = (appId: string, name: string, layout: TabLayout = 'canvas', firstName?: string): string | null => {
    const id = uuidv4();
    const first = firstName?.trim().slice(0, MAX_NAME_LENGTH);
    const added = changeTabs(appId, tabs => (tabs.length >= MAX_TABS ? null : [
      ...tabs.map((t, i) => (i === 0 && first && !t.name ? { ...t, name: first } : t)),
      { id, name: name.trim().slice(0, MAX_NAME_LENGTH), layout, widgets: [], pinned_agent_id: null },
    ]));
    if (!added) return null;
    selectApp(appId, id);
    return id;
  };

  const setTabLayout = (appId: string, tabId: string, layout: TabLayout): boolean => changeTabs(appId, tabs => {
    const tab = tabs.find(t => t.id === tabId);
    if (!tab || (tab.layout || 'canvas') === layout) return null;
    if (layout === 'page' && tab.widgets.length > 1) return null;
    const widgets = layout === 'page' ? tab.widgets : tab.widgets.map(w => ({ ...w, ...PAGE_WIDGET_PLACE }));
    return tabs.map(t => (t.id === tabId ? { ...t, layout, widgets } : t));
  });

  const renameTab = (appId: string, tabId: string, name: string) => {
    const next = name.trim().slice(0, MAX_NAME_LENGTH);
    changeTabs(appId, tabs => (tabs.some(t => t.id === tabId && t.name !== next)
      ? tabs.map(t => (t.id === tabId ? { ...t, name: next } : t))
      : null));
  };

  const moveTab = (appId: string, fromIndex: number, toIndex: number) => {
    changeTabs(appId, tabs => {
      if (fromIndex === toIndex || !tabs[fromIndex] || toIndex < 0 || toIndex >= tabs.length) return null;
      const next = [...tabs];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  };

  // The last tab can't go: an app is at least one canvas. Removing the tab on
  // screen shows the one that took its place.
  const removeTab = (appId: string, tabId: string) => {
    const app = apps.find(a => a.id === appId);
    const index = app?.spec.tabs.findIndex(t => t.id === tabId) ?? -1;
    const removed = changeTabs(appId, tabs => (tabs.length > 1 && index >= 0 ? tabs.filter(t => t.id !== tabId) : null));
    if (removed && app && activeAppId === appId && activeAppTab?.id === tabId) {
      const remaining = app.spec.tabs.filter(t => t.id !== tabId);
      selectApp(appId, remaining[Math.min(index, remaining.length - 1)].id);
    }
  };

  // Changes one tab's widgets and saves the app's draft, so only its managers
  // can, and only on the draft.
  // `change` runs inside a state updater, which React may run more than once
  // (StrictMode always does, and a rebased update does in production), so it
  // must be pure: no ids minted in it, no saves started from it. The save is
  // left to the effect on `apps`, which sees each committed state once and saves
  // that state, not whichever replay of the updater happened to run last.
  const changeWidgets = (appId: string, tabId: string, change: (widgets: WidgetLayout[], tab: AppTab) => WidgetLayout[] | null) => {
    const app = apps.find(a => a.id === appId);
    if (!canEditApp(app)) return;

    setApps(prevApps => {
      let changed = false;
      const newApps = prevApps.map(a => {
        if (a.id !== appId) return a;
        const tab = a.spec.tabs.find(t => t.id === tabId);
        const widgets = tab ? change(tab.widgets, tab) : null;
        if (!widgets) return a;
        changed = true;
        return withTab(a, tabId, t => ({ ...t, widgets }));
      });
      if (!changed) return prevApps;
      unsavedApps.current.add(appId);
      return newApps;
    });
  };

  const addWidget = (appId: string, tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => {
    // One id per call, minted here rather than in the updater: an updater that
    // runs again finds this instance already placed and adds nothing, while a
    // second call is a second drop and still gets its own widget.
    const instanceId = uuidv4();
    changeWidgets(appId, tabId, (widgets, tab) => {
      if (widgets.some(w => w.i === instanceId)) return null;
      const def = widgetRegistry[type];
      if (isPage(tab)) return [{ i: instanceId, ...PAGE_WIDGET_PLACE, type, props: props || {} }];
      const newWidget: WidgetLayout = {
        i: instanceId,
        x: position?.x ?? (widgets.length * 4) % 12,
        y: position?.y ?? Infinity,
        w: position?.w ?? def?.defaultW ?? 4,
        h: position?.h ?? def?.defaultH ?? 4,
        type,
        props: props || {}
      };
      return [...widgets, newWidget];
    });
  };

  const updateWidget = (appId: string, tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => {
    changeWidgets(appId, tabId, widgets => widgets.map(w => w.i === widgetId ? { ...w, ...updates } : w));
  };

  const removeWidget = (appId: string, tabId: string, widgetId: string) => {
    changeWidgets(appId, tabId, widgets => widgets.filter(w => w.i !== widgetId));
  };

  const updateLayout = (appId: string, tabId: string, newLayout: WidgetLayout[]) => {
    // Only a real move or resize saves: the grid reports its layout on every
    // render, and a save would turn a published view's state to Unpublished changes.
    changeWidgets(appId, tabId, widgets => {
      let hasChanges = false;
      const updatedWidgets = widgets.map(w => {
        const l = newLayout.find(nl => nl.i === w.i);
        if (l && (w.x !== l.x || w.y !== l.y || w.w !== l.w || w.h !== l.h)) {
          hasChanges = true;
          return { ...w, x: l.x, y: l.y, w: l.w, h: l.h };
        }
        return w;
      });
      return hasChanges ? updatedWidgets : null;
    });
  };

  // Remaining tools
  // Either link opens only for people the app is shared with; see `openRoute`.
  // Both open on what the view is set to now, not on what the address last
  // caught up with.
  const generateShareLink = (): string => {
    if (!activeApp) return '';
    return appLink(activeApp, linkTab(activeApp, activeAppTab), null, linkSearch('', activeApp, variables, widgetLinkState.snapshot()));
  };

  // A link that opens one widget, full-screen, on the tab it sits on, carrying
  // that widget's settings and none of its neighbours'.
  const generateWidgetShareLink = (widgetId: string): string => {
    if (!activeApp || !activeAppTab) return '';
    return appLink(activeApp, activeAppTab.id, widgetId, linkSearch('', activeApp, variables, widgetLinkState.snapshot(), widgetId));
  };

  const clearPendingWidget = useCallback(() => setPendingWidgetId(null), []);

  const [configModal, setConfigModal] = useState<DashboardContextType['configModal']>({
    isOpen: false, widgetId: null, initialConfig: {}, onSave: null, editing: false
  });

  const openConfigModal = (widgetId: string, onSave: (config: any) => void, initialConfig?: any) => {
    // Each opening saves at most once: for a dropped widget the callback adds it,
    // so a Save that reaches it twice before the modal unmounts would add two.
    let saved = false;
    const saveOnce = (config: Parameters<typeof onSave>[0]) => {
      if (saved) return;
      onSave(config);
      saved = true;
    };
    setConfigModal({ isOpen: true, widgetId, initialConfig: initialConfig ?? {}, onSave: saveOnce, editing: initialConfig !== undefined });
  };

  const closeConfigModal = () => {
    setConfigModal({ isOpen: false, widgetId: null, initialConfig: {}, onSave: null, editing: false });
  };

  return (
    <DashboardContext.Provider value={{
      apps, activeAppId, activeApp, activeAppTab, activeDomain, setActiveDomain, isLoading, isAdmin, username, fetchApps, openRoute, pendingWidgetId, clearPendingWidget,
      standalone: Boolean(standalone),
      variables, setVariable,
      addApp, deleteApp, archiveApp, restoreApp, fetchArchived, hideApp, renameApp, reorderApps, setActiveAppId: selectApp,
      selectTab, addTab, setTabLayout, renameTab, moveTab, removeTab,
      duplicateApp, addWidget, removeWidget, updateWidget, updateLayout,
      toggleLock, setPinnedAgent, updateAppSpec, canEditApp, canEditLayout,
      modeOf, setAppMode, loadPreflight, publishApp, discardDraft, fetchHistory, revertApp, sharingChanged,
      generateShareLink, generateWidgetShareLink, configModal, openConfigModal, closeConfigModal
    }}>
      <LinkStateContext.Provider value={widgetLinkState}>
        {children}
      </LinkStateContext.Provider>
    </DashboardContext.Provider>
  );
};

export const useDashboardStore = () => {
  const context = useContext(DashboardContext);
  if (!context) throw new Error('useDashboardStore must be used within a DashboardProvider');
  return context;
};
