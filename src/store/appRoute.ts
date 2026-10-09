// What a link to an app says. The link the app hands out is
// `#/app/<app>[/<tab>[/w/<widgetId>]]`, which shows the app the way it
// presents itself: on its own if it is standalone, else inside the workspace.
// `#/workspace/<app>/...` is the same place shown inside the workspace
// whatever the app is, which is where its editors build it. Everything handed
// out before — `#/app/<id>/<tabId>`, `?shared_view=<id>`, `#/view/<id>`,
// `#/template/<id>` and `?widget=<id>` — is still in people's bookmarks, chats
// and emails, and opens the same app forever.
//
// Links name things rather than spell their ids. A global app goes by the name
// the server gave it (`app.link`, see server/services/app_links.py); a personal
// one by `<name>-<id>`, because a personal app opens for anyone holding its id
// and a name alone could be guessed. A tab goes by its name where that is unique
// in the app. A route read from an address holds those names until
// `resolvedRoute` turns them into ids; everything past that works in ids.
import { shownTab, type App, type AppTab } from './appSpec';

export interface AppRoute {
  /** As a link names it until resolved: id, link name or `<name>-<id>`. */
  appId: string;
  /** Null means the app's first tab. A tab's id once resolved, or its name before. */
  tabId: string | null;
  /** A widget to open full-screen once it is on screen. */
  widgetId: string | null;
  /** Inside the workspace even if the app is standalone. */
  workspace?: boolean;
}

const decode = (part: string): string => {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
};

export const parseAppRoute = (hash: string, search = ''): AppRoute | null => {
  const params = new URLSearchParams(search);
  const widgetParam = params.get('widget') || null;
  const shared = params.get('shared_view');
  if (shared) return { appId: shared, tabId: null, widgetId: widgetParam };

  const path = hash.replace(/^#\/?/, '');
  const alias = /^(view|template)\/(.+)$/.exec(path);
  if (alias) return { appId: decode(alias[2]), tabId: null, widgetId: widgetParam };

  const [kind, appId, tabId, marker, widgetId] = path.split('/');
  if ((kind !== 'app' && kind !== 'workspace') || !appId) return null;
  return {
    appId: decode(appId),
    tabId: tabId ? decode(tabId) : null,
    widgetId: marker === 'w' && widgetId ? decode(widgetId) : widgetParam,
    workspace: kind === 'workspace',
  };
};

/** A name as it reads in a link: lower case, accents dropped, words joined by '-'. */
export const slugify = (text: string | null | undefined): string =>
  (text || '')
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/, '');

const UUID_TAIL = /(?:^|-)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/** The id a `<name>-<id>` link ends in. */
const idIn = (ref: string): string | null => UUID_TAIL.exec(ref)?.[1].toLowerCase() ?? null;

/** What links name an app by: see the note at the top. */
export const appRef = (app: App): string => {
  if (app.is_global && app.link) return app.link;
  const name = slugify(app.name);
  return name && idIn(app.id) === app.id.toLowerCase() ? `${name}-${app.id}` : app.id;
};

/**
 * Whether the app part of a link names this app. A name a global app has since
 * been renamed from is the server's to recognise (`GET /api/apps/<ref>`).
 */
export const refersTo = (ref: string, app: App): boolean =>
  ref === app.id || ref === appRef(app) || (!!idIn(ref) && idIn(ref) === app.id.toLowerCase());

/** What links name a tab by: its name, unless another tab would answer to it too. */
export const tabRef = (app: App, tab: AppTab): string => {
  const name = slugify(tab.name);
  if (!name || idIn(name)) return tab.id;
  const clash = app.spec.tabs.some(t => t.id !== tab.id && (t.id === name || slugify(t.name) === name));
  return clash ? tab.id : name;
};

/** The id of the tab a link names, or null for one this app has no tab by. */
export const tabIdOf = (app: App, ref: string | null): string | null => {
  if (!ref) return null;
  const tabs = app.spec?.tabs ?? [];
  return tabs.find(t => t.id === ref)?.id ?? tabs.find(t => tabRef(app, t) === ref)?.id ?? null;
};

/** A route read from an address, in the ids of the app it turned out to name. */
export const resolvedRoute = (route: AppRoute, app: App): AppRoute => ({
  ...route,
  appId: app.id,
  tabId: tabIdOf(app, route.tabId),
});

/**
 * The hash for an app, one of its tabs (by id), or a widget on one. Pass the
 * tab from `linkTab`, which leaves out the first: a tab given here is always
 * written, since the tab a view started with keeps the view's id wherever it is
 * moved to.
 */
export const appHash = (app: App, tabId?: string | null, widgetId?: string | null, workspace = false): string => {
  const parts = [workspace ? '#/workspace' : '#/app', encodeURIComponent(appRef(app))];
  const tab = tabId ? app.spec.tabs.find(t => t.id === tabId) : null;
  const named = tab ? tabRef(app, tab) : tabId;
  if (widgetId) {
    const first = shownTab(app, null);
    parts.push(encodeURIComponent(named || (first ? tabRef(app, first) : app.id)), 'w', encodeURIComponent(widgetId));
  } else if (named) parts.push(encodeURIComponent(named));
  return parts.join('/');
};

/** The hash a route is written back as when no app it could name is loaded. */
export const routeHash = (route: AppRoute): string => {
  const parts = [route.workspace ? '#/workspace' : '#/app', encodeURIComponent(route.appId)];
  if (route.tabId) parts.push(encodeURIComponent(route.tabId));
  return parts.join('/');
};

/** The tab a link to what is on screen names: none when it is the first. */
export const linkTab = (app: App, tab: AppTab | null): string | null =>
  tab && tab.id !== app.spec.tabs[0]?.id ? tab.id : null;

/** The tab to write for a link once read: the one it opens, unless that is the first. */
export const routeTab = (app: App, tabRefOrId: string | null): string | null =>
  linkTab(app, shownTab(app, tabIdOf(app, tabRefOrId)));

/** Whether an app shows on its own when a link to it is opened. */
export const isStandalone = (app?: App | null): boolean => app?.spec?.presentation === 'standalone';

export const appLink = (app: App, tabId?: string | null, widgetId?: string | null): string =>
  `${window.location.origin}${window.location.pathname}${appHash(app, tabId, widgetId)}`;

/** The query string once a link has been read, so a reload doesn't act on it again. */
export const withoutRouteParams = (search: string): string => {
  const params = new URLSearchParams(search);
  params.delete('shared_view');
  params.delete('widget');
  const rest = params.toString();
  return rest ? `?${rest}` : '';
};
