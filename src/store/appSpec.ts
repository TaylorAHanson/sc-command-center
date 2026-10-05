// What an app is on the client. Mirrors `server/services/app_spec.py`, which
// validates every save; keep the two in step.

export interface WidgetLayout {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  type: string;
  props?: Record<string, any>;
  static?: boolean;
}

/** One canvas of an app — what used to be a whole view. */
export interface AppTab {
  id: string;
  name: string;
  widgets: WidgetLayout[];
  /** Overrides the app's agent on this tab. Null = use the app's. */
  pinned_agent_id?: string | null;
}

export interface AppBranding {
  title?: string | null;
  logo?: string | null;
  favicon?: string | null;
  assistant_name?: string | null;
}

export interface AppSpec {
  schema: number;
  presentation: 'workspace' | 'standalone';
  assistant: 'on' | 'off';
  branding: AppBranding | null;
  tabs: AppTab[];
  /** Reserved: carried through every save, not yet interpreted. */
  nav: Record<string, unknown> | null;
  theme: Record<string, unknown> | null;
  filters: unknown[];
}

/**
 * What the sidebar lists and the canvas shows. A view is an app with one tab,
 * and every app stored before apps existed reads that way, under its old id.
 */
export interface App {
  id: string;
  name: string;
  spec: AppSpec;
  locked?: boolean;
  domain?: string;
  is_global?: boolean;
  is_shared?: boolean;
  username?: string;
  version?: number;
  timestamp?: string | null;
  /** Agent Studio profile the assistant opens with on this app. Null = no pin. */
  pinned_agent_id?: string | null;
}

export const newAppSpec = (tabId: string): AppSpec => ({
  schema: 1,
  presentation: 'workspace',
  assistant: 'on',
  branding: null,
  tabs: [{ id: tabId, name: '', widgets: [], pinned_agent_id: null }],
  nav: null,
  theme: null,
  filters: [],
});

/**
 * The tab the canvas shows. There is no tab bar yet, so it is the first, which
 * is also the only tab `/api/views` and the bundle before apps ever knew about.
 */
export const shownTab = (app?: App | null): AppTab | null => app?.spec?.tabs?.[0] ?? null;

/** The agent the drawer opens with: the tab's own pin, else the app's. */
export const pinnedAgentOf = (app?: App | null, tab?: AppTab | null): string =>
  tab?.pinned_agent_id || app?.pinned_agent_id || '';

export const withTab = (app: App, tabId: string, change: (tab: AppTab) => AppTab): App => ({
  ...app,
  spec: { ...app.spec, tabs: app.spec.tabs.map(t => (t.id === tabId ? change(t) : t)) },
});
