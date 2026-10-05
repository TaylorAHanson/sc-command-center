import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { widgetRegistry } from '../widgetRegistry';
import { newAppSpec, shownTab, withTab, type App, type AppSpec, type AppTab, type WidgetLayout } from './appSpec';
import { appHash, appLink, isStandalone, linkTab, parseAppRoute, withoutRouteParams, type AppRoute } from './appRoute';
import { useShell } from '../shell';

// An app can pin the built-in agent just as deliberately as an authored one, so
// "no pin" and "pinned to the default" have to be different values. Authored
// agents are UUIDs, so this word can never collide with one.
export const DEFAULT_AGENT_PIN = 'default';

export type { WidgetLayout, App, AppTab, AppSpec, AppBranding } from './appSpec';

interface DashboardContextType {
  apps: App[]; // All apps (user + global + subscribed)
  activeAppId: string;
  activeApp: App | null;
  activeAppTab: AppTab | null;
  activeDomain: string | null;
  setActiveDomain: (domainId: string | null) => void;
  isLoading: boolean;
  isAdmin: boolean;
  username: string;
  domainPermissions: Record<string, string>;
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

  addApp: (name: string, domain?: string, is_global?: boolean) => void;
  removeApp: (id: string) => void;
  renameApp: (id: string, newName: string) => void;
  reorderApps: (fromIndex: number, toIndex: number) => void;
  setActiveAppId: (id: string) => void;
  duplicateApp: (appId: string) => void;
  toggleLock: (appId: string) => void;
  setPinnedAgent: (appId: string, tabId: string | null, agentId: string | null) => void;
  /** Save a change to an app's spec; resolves to the server's refusal, if any. */
  updateAppSpec: (appId: string, spec: AppSpec) => Promise<string | null>;
  /** Whether the signed-in user may change this app's settings (not its layout). */
  canEditApp: (app?: App | null) => boolean;
  /** Whether the signed-in user may change a widget belonging to this domain. */
  canEditDomain: (domain?: string | null) => boolean;

  addWidget: (appId: string, tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => void;
  removeWidget: (appId: string, tabId: string, widgetId: string) => void;
  updateWidget: (appId: string, tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => void;
  updateLayout: (appId: string, tabId: string, newLayout: WidgetLayout[]) => void;

  generateShareLink: () => string;
  generateWidgetShareLink: (widgetId: string) => string;

  configModal: { isOpen: boolean; widgetId: string | null; initialConfig: any; onSave: ((config: any) => void) | null };
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
  const [domainPermissions, setDomainPermissions] = useState<Record<string, string>>({});
  const [variables, setVariables] = useState<Record<string, any>>({});

  const activeApp = apps.find(a => a.id === activeAppId) || null;
  const activeAppTab = shownTab(activeApp, activeTabId);
  const appsRef = useRef(apps);
  useEffect(() => { appsRef.current = apps; }, [apps]);

  const selectApp = useCallback((id: string, tabId: string | null = null) => {
    setActiveAppIdState(id);
    setActiveTabId(tabId);
  }, []);

  const setVariable = useCallback((key: string, value: any) => {
    // Skip the update when the value is unchanged. Widgets share this map, so a
    // new `variables` object re-renders every widget on the app; an unguarded
    // write of the SAME value from a widget effect (a common generated-widget
    // pattern) would otherwise loop forever — new object -> new widget `data`
    // -> effect re-runs -> writes again -> ... pegging a CPU core and dragging
    // the whole machine down the longer the app stays open.
    setVariables(prev => (Object.is(prev[key], value) ? prev : { ...prev, [key]: value }));
  }, []);

  const fetchPermissions = useCallback(async (): Promise<string | null> => {
    try {
      const response = await fetch('/api/roles/my-permissions');
      if (response.ok) {
        const data = await response.json();
        setIsAdmin(data.is_admin);
        setUsername(data.username || 'unknown');
        setDomainPermissions(data.domain_permissions || {});
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
      const loadedApps: App[] = (data.apps || []).map((a: any) => ({
        ...a,
        locked: a.is_locked || a.is_shared // Shared apps are always locked for the subscriber
      }));
      setApps(loadedApps);

      // While the address bar names an app, choosing one is `openRoute`'s job:
      // falling back to the first here would flash it, and its hash would race
      // the link's. A selection the server no longer returns (a global app
      // someone has since archived) falls back to the first app instead of
      // leaving the dashboard pointing at nothing.
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

  // A link to an app this person doesn't have puts it in their sidebar, as
  // `?shared_view=` always has: that is how a shared link reaches anyone. It
  // subscribes only after a fresh list says the app really isn't there, so a
  // link to your own app or a global one you can see never does.
  const openRoute = useCallback(async (route: AppRoute, known?: App[] | null) => {
    const canonical = appHash(route.appId, route.tabId, null, route.workspace);
    const search = withoutRouteParams(window.location.search);
    if (window.location.hash !== canonical || window.location.search !== search) {
      window.history.replaceState(window.history.state, '', window.location.pathname + search + canonical);
    }

    const find = (list?: App[] | null) => list?.find(a => a.id === route.appId);
    let list: App[] | null = known ?? appsRef.current;
    if (!find(list)) list = await fetchApps();
    if (list && !find(list)) {
      try {
        const res = await fetch(`/api/apps/${encodeURIComponent(route.appId)}/subscribe`, { method: 'POST' });
        if (res.ok) list = await fetchApps();
      } catch (e) {
        console.error('Failed to subscribe to shared app', e);
      }
    }
    const app = find(list);
    if (app && isStandalone(app) && !route.workspace) {
      shell.present(app, route.tabId, route.widgetId);
      return;
    }
    selectApp(route.appId, route.tabId);
    if (route.widgetId) setPendingWidgetId(route.widgetId);
  }, [fetchApps, selectApp, shell]);

  // The link the page opened with is acted on once, though StrictMode runs this
  // effect twice in development. A standalone app was read before this mounted,
  // so all that's left of its link is the subscription opening it has always
  // meant: someone else's personal app goes in your sidebar, as in the workspace.
  const initialRouteRead = useRef(false);
  useEffect(() => {
    if (standalone) {
      fetchPermissions().then(me => {
        const app = standalone.app;
        if (initialRouteRead.current || !me || app.is_global || app.is_shared || !app.username || app.username === me) return;
        initialRouteRead.current = true;
        fetch(`/api/apps/${encodeURIComponent(app.id)}/subscribe`, { method: 'POST' })
          .catch(e => console.error('Failed to subscribe to shared app', e));
      });
      return;
    }
    fetchPermissions();
    fetchApps().then(list => {
      if (!initialRoute || !list || initialRouteRead.current) return;
      initialRouteRead.current = true;
      openRoute(initialRoute, list);
    });
  }, [fetchPermissions, fetchApps, openRoute, initialRoute, standalone]);

  // Saves to one app go one at a time, in order. Each lands the next version
  // number, which the server reads off the newest row, so two in flight at once
  // claim the same number and Postgres refuses one — and if that was the newer,
  // its change is gone. StrictMode runs the updaters that schedule saves twice in
  // development, so there overlap is every save, not a rare one.
  const saveQueue = useRef(new Map<string, Promise<string | null>>());
  const apiSyncApp = (app: App, method: 'PUT' | 'POST' = 'PUT'): Promise<string | null> => {
    const previous = saveQueue.current.get(app.id) ?? Promise.resolve();
    const next = previous.then(() => sendApp(app, method));
    saveQueue.current.set(app.id, next);
    return next;
  };

  // Every save sends the whole spec, including tabs this screen doesn't show, so
  // a drag on the first tab can't drop the others. The server reads an absent
  // field as "keep it", so the pin is always sent: an empty string is the only
  // way a save can clear one. Never rejects, so one failure can't stall the queue;
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
          is_global: app.is_global || false,
          is_locked: app.locked || false,
          pinned_agent_id: app.pinned_agent_id || '',
          spec: app.spec
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const reason = typeof data?.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        console.error(`Failed to save app ${app.id}: ${reason}`);
        return reason;
      }
      return null;
    } catch (e) {
      console.error('Failed to save app:', e);
      return 'The save did not reach the server.';
    }
  };

  const addApp = (name: string, domain?: string, is_global: boolean = false) => {
    const id = uuidv4();
    const newApp: App = {
      id,
      name,
      // The one tab takes the app's id, as every view's tab does, so a link to
      // the app and a link to its tab are the same link.
      spec: newAppSpec(id),
      domain: domain || 'General',
      is_global
    };
    setApps([...apps, newApp]);
    selectApp(newApp.id);
    apiSyncApp(newApp, 'POST');
  };

  const duplicateApp = (appId: string) => {
    const template = apps.find(a => a.id === appId);
    if (template) {
      const id = uuidv4();
      const single = template.spec.tabs.length === 1;
      const newApp: App = {
        ...template,
        id,
        name: `${template.name} (Copy)`,
        is_global: false,
        username: undefined,
        spec: {
          ...template.spec,
          tabs: template.spec.tabs.map(tab => ({
            ...tab,
            id: single ? id : uuidv4(),
            widgets: tab.widgets.map(w => ({ ...w, i: uuidv4() })),
          })),
        },
      };
      setApps([...apps, newApp]);
      selectApp(newApp.id);
      apiSyncApp(newApp, 'POST');
    }
  };

  const removeApp = async (id: string) => {
    const appToRemove = apps.find(a => a.id === id);
    const newApps = apps.filter(a => a.id !== id);
    setApps(newApps);
    if (activeAppId === id && newApps.length > 0) {
      selectApp(newApps[0].id);
    }

    try {
      if (appToRemove?.is_shared) {
        await fetch(`/api/apps/${encodeURIComponent(id)}/subscribe`, { method: 'DELETE' });
      } else {
        await fetch(`/api/apps/${encodeURIComponent(id)}`, { method: 'DELETE' });
      }
    } catch (e) {
      console.error('Failed to delete app', e);
    }
  };

  const renameApp = (id: string, newName: string) => {
    if (!newName.trim()) return;
    const app = apps.find(a => a.id === id);
    if (app?.is_shared) return; // Cannot rename shared apps

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
    if (app?.is_shared) return; // Cannot unlock shared apps

    const newApps = apps.map(a => a.id === appId ? { ...a, locked: !a.locked } : a);
    setApps(newApps);
    const updatedApp = newApps.find(a => a.id === appId);
    if (updatedApp) apiSyncApp(updatedApp);
  };

  // Who may change an app's settings. Layout editing has its own rule (a locked
  // app is read-only even to its owner); this is about the app itself, which
  // is why a locked app still answers true — the lock is one of these settings.
  const canEditApp = useCallback((app?: App | null): boolean => {
    if (!app || app.is_shared) return false;
    if (app.is_global) {
      if (isAdmin) return true;
      const level = domainPermissions[app.domain || 'General'];
      return level === 'editor' || level === 'admin';
    }
    return !app.username || app.username === username;
  }, [isAdmin, domainPermissions, username]);

  // Who may edit a widget, mirroring `require_domain_editor` — the check its save
  // actually goes through. Editing a widget is a domain right, not an ownership
  // one: the server has never asked who wrote a widget before accepting a new
  // version of it, and a library that hides Edit from people the server would let
  // through just sends them the long way round. Deleting is the ownership one.
  const canEditDomain = useCallback((domain?: string | null): boolean => {
    if (isAdmin) return true;
    const level = domainPermissions[domain || 'General'];
    return level === 'editor' || level === 'admin';
  }, [isAdmin, domainPermissions]);

  // Pin an agent, or pass null to clear it. Saved like every other app setting:
  // optimistic locally, then a full PUT that lands a new version.
  //
  // The pin a change replaces is the one in force. A tab with its own pin
  // overrides the app's, so changing the app's there would change nothing the
  // user could see; every view's only tab has none, so for them this is the
  // app's pin, exactly as it was the view's.
  const setPinnedAgent = (appId: string, tabId: string | null, agentId: string | null) => {
    const app = apps.find(a => a.id === appId);
    if (!app || !canEditApp(app)) return;
    const tab = app.spec.tabs.find(t => t.id === tabId) || null;
    const onTab = Boolean(tab?.pinned_agent_id);

    const next = agentId || null;
    if (((onTab ? tab?.pinned_agent_id : app.pinned_agent_id) || null) === next) return;

    const updatedApp = onTab && tab
      ? withTab(app, tab.id, t => ({ ...t, pinned_agent_id: next }))
      : { ...app, pinned_agent_id: next };
    setApps(apps.map(a => a.id === appId ? updatedApp : a));
    apiSyncApp(updatedApp);
  };

  // How the app presents itself, its branding and its assistant. Optimistic like
  // the pin, but a refusal is handed back and undone, because the dialog that
  // made it is still open and can say why.
  const updateAppSpec = async (appId: string, spec: AppSpec): Promise<string | null> => {
    const app = apps.find(a => a.id === appId);
    if (!app || !canEditApp(app)) return 'You can’t change this view’s settings.';
    const updatedApp = { ...app, spec };
    setApps(prev => prev.map(a => a.id === appId ? updatedApp : a));
    const refusal = await apiSyncApp(updatedApp);
    if (refusal) setApps(prev => prev.map(a => (a === updatedApp ? app : a)));
    return refusal;
  };

  // Changes one tab's widgets and saves the app. Shared apps are read-only to
  // their subscribers, so nothing here touches one.
  const changeWidgets = (appId: string, tabId: string, change: (widgets: WidgetLayout[]) => WidgetLayout[] | null) => {
    const app = apps.find(a => a.id === appId);
    if (app?.is_shared) return;

    setApps(prevApps => {
      let updatedApp: App | null = null;
      const newApps = prevApps.map(a => {
        if (a.id !== appId) return a;
        const tab = a.spec.tabs.find(t => t.id === tabId);
        const widgets = tab ? change(tab.widgets) : null;
        if (!widgets) return a;
        updatedApp = withTab(a, tabId, t => ({ ...t, widgets }));
        return updatedApp;
      });
      if (!updatedApp) return prevApps;
      setTimeout(() => apiSyncApp(updatedApp!), 0);
      return newApps;
    });
  };

  const addWidget = (appId: string, tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => {
    changeWidgets(appId, tabId, widgets => {
      const def = widgetRegistry[type];
      const newWidget: WidgetLayout = {
        i: uuidv4(),
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
    // render, and each save lands a new version of the app.
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
  // Opening either link subscribes anyone who doesn't have the app; see `openRoute`.
  const generateShareLink = (): string => {
    if (!activeApp) return '';
    return appLink(activeApp.id, linkTab(activeApp, activeAppTab));
  };

  // A link that opens one widget, full-screen, on the tab it sits on.
  const generateWidgetShareLink = (widgetId: string): string => {
    if (!activeApp || !activeAppTab) return '';
    return appLink(activeApp.id, activeAppTab.id, widgetId);
  };

  const clearPendingWidget = useCallback(() => setPendingWidgetId(null), []);

  const [configModal, setConfigModal] = useState<{ isOpen: boolean; widgetId: string | null; initialConfig: any; onSave: ((config: any) => void) | null }>({
    isOpen: false, widgetId: null, initialConfig: {}, onSave: null
  });

  const openConfigModal = (widgetId: string, onSave: (config: any) => void, initialConfig: any = {}) => {
    setConfigModal({ isOpen: true, widgetId, initialConfig, onSave });
  };

  const closeConfigModal = () => {
    setConfigModal({ isOpen: false, widgetId: null, initialConfig: {}, onSave: null });
  };

  return (
    <DashboardContext.Provider value={{
      apps, activeAppId, activeApp, activeAppTab, activeDomain, setActiveDomain, isLoading, isAdmin, username, domainPermissions, fetchApps, openRoute, pendingWidgetId, clearPendingWidget,
      standalone: Boolean(standalone),
      variables, setVariable,
      addApp, removeApp, renameApp, reorderApps, setActiveAppId: selectApp,
      duplicateApp, addWidget, removeWidget, updateWidget, updateLayout,
      toggleLock, setPinnedAgent, updateAppSpec, canEditApp, canEditDomain, generateShareLink, generateWidgetShareLink, configModal, openConfigModal, closeConfigModal
    }}>
      {children}
    </DashboardContext.Provider>
  );
};

export const useDashboardStore = () => {
  const context = useContext(DashboardContext);
  if (!context) throw new Error('useDashboardStore must be used within a DashboardProvider');
  return context;
};
