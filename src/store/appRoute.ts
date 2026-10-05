// What a link to an app says. The link the app hands out is
// `#/app/<appId>[/<tabId>[/w/<widgetId>]]`, which shows the app the way it
// presents itself: on its own if it is standalone, else inside the workspace.
// `#/workspace/<appId>/...` is the same place shown inside the workspace
// whatever the app is, which is where its editors build it. Everything handed
// out before — `?shared_view=<id>`, `#/view/<id>`, `#/template/<id>` and
// `?widget=<id>` — is still in people's bookmarks, chats and emails, and opens
// the same app forever.
import type { App, AppTab } from './appSpec';

export interface AppRoute {
  appId: string;
  /** Null means the app's first tab. */
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

/**
 * The hash for an app, one of its tabs, or a widget on one. A view's only tab is
 * named by the view's id, so a link to it is just the app's.
 */
export const appHash = (appId: string, tabId?: string | null, widgetId?: string | null, workspace = false): string => {
  const parts = [workspace ? '#/workspace' : '#/app', encodeURIComponent(appId)];
  if (widgetId) parts.push(encodeURIComponent(tabId || appId), 'w', encodeURIComponent(widgetId));
  else if (tabId && tabId !== appId) parts.push(encodeURIComponent(tabId));
  return parts.join('/');
};

/** The tab a link to what is on screen names: none when it is the first. */
export const linkTab = (app: App, tab: AppTab | null): string | null =>
  tab && tab.id !== app.spec.tabs[0]?.id ? tab.id : null;

/** Whether an app shows on its own when a link to it is opened. */
export const isStandalone = (app?: App | null): boolean => app?.spec?.presentation === 'standalone';

export const appLink = (appId: string, tabId?: string | null, widgetId?: string | null): string =>
  `${window.location.origin}${window.location.pathname}${appHash(appId, tabId, widgetId)}`;

/** The query string once a link has been read, so a reload doesn't act on it again. */
export const withoutRouteParams = (search: string): string => {
  const params = new URLSearchParams(search);
  params.delete('shared_view');
  params.delete('widget');
  const rest = params.toString();
  return rest ? `?${rest}` : '';
};
