import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { widgetRegistry } from '../widgetRegistry';
import { newAppSpec, shownTab, withTab, type App, type AppTab, type WidgetLayout } from './appSpec';

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
  fetchApps: () => Promise<void>;

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

export const DashboardProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeDomain, setActiveDomain] = useState<string | null>(null);
  const [apps, setApps] = useState<App[]>([]);
  const [activeAppId, setActiveAppId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [username, setUsername] = useState('unknown');
  const [domainPermissions, setDomainPermissions] = useState<Record<string, string>>({});
  const [variables, setVariables] = useState<Record<string, any>>({});

  const activeApp = apps.find(a => a.id === activeAppId) || null;
  const activeAppTab = shownTab(activeApp);

  const setVariable = useCallback((key: string, value: any) => {
    // Skip the update when the value is unchanged. Widgets share this map, so a
    // new `variables` object re-renders every widget on the app; an unguarded
    // write of the SAME value from a widget effect (a common generated-widget
    // pattern) would otherwise loop forever — new object -> new widget `data`
    // -> effect re-runs -> writes again -> ... pegging a CPU core and dragging
    // the whole machine down the longer the app stays open.
    setVariables(prev => (Object.is(prev[key], value) ? prev : { ...prev, [key]: value }));
  }, []);

  const fetchPermissions = useCallback(async () => {
    try {
      const response = await fetch('/api/roles/my-permissions');
      if (response.ok) {
        const data = await response.json();
        setIsAdmin(data.is_admin);
        setUsername(data.username || 'unknown');
        setDomainPermissions(data.domain_permissions || {});
      }
    } catch (e) {
      console.error('Failed to load permissions:', e);
    }
  }, []);

  const fetchApps = useCallback(async () => {
    try {
      const response = await fetch('/api/apps/');
      if (response.ok) {
        const data = await response.json();
        const loadedApps: App[] = (data.apps || []).map((a: any) => ({
          ...a,
          locked: a.is_locked || a.is_shared // Shared apps are always locked for the subscriber
        }));
        setApps(loadedApps);

        // Only set default app if we don't have one and we're not loading a shared URL
        const urlParams = new URLSearchParams(window.location.search);
        const hasShare = urlParams.get('share');

        if (!hasShare && loadedApps.length > 0) {
          // Check hash
          const hash = window.location.hash;
          if (hash.startsWith('#/view/')) {
            const id = hash.replace('#/view/', '');
            if (loadedApps.some(a => a.id === id)) {
              setActiveAppId(id);
            }
            return; // Don't fall back to app 0 if a specific hash was requested
          }
          // A selection the server no longer returns (a global app someone has
          // since archived) falls back to the first app instead of leaving the
          // dashboard pointing at nothing.
          setActiveAppId(prev => {
            if (!prev || !loadedApps.some(a => a.id === prev)) return loadedApps[0].id;
            return prev;
          });
        }
      }
    } catch (e) {
      console.error('Failed to load apps:', e);
    } finally {
      setIsLoading(false);
    }
  }, []); // No activeAppId dependency, so setting it doesn't refetch

  useEffect(() => {
    fetchPermissions();
    fetchApps();
  }, [fetchPermissions, fetchApps]);

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const shareParam = urlParams.get('shared_view');
    if (shareParam) {
      // Clear shared_view from the query string but preserve any other params
      // (e.g. ?widget=... is consumed by App.tsx after the app loads).
      urlParams.delete('shared_view');
      const remaining = urlParams.toString();
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (remaining ? `?${remaining}` : '') + `#/view/${shareParam}`
      );

      const subscribeAndLoad = async () => {
        try {
          await fetch(`/api/apps/${encodeURIComponent(shareParam)}/subscribe`, { method: 'POST' });
          await fetchApps(); // Refresh apps to pull the newly shared one in
          setActiveAppId(shareParam);
        } catch (e) {
          console.error('Failed to subscribe to shared app', e);
        }
      };
      subscribeAndLoad();
    }
  }, [fetchApps]);

  // Saves to one app go one at a time, in order. Each lands the next version
  // number, which the server reads off the newest row, so two in flight at once
  // claim the same number and Postgres refuses one — and if that was the newer,
  // its change is gone. StrictMode runs the updaters that schedule saves twice in
  // development, so there overlap is every save, not a rare one.
  const saveQueue = useRef(new Map<string, Promise<void>>());
  const apiSyncApp = (app: App, method: 'PUT' | 'POST' = 'PUT'): Promise<void> => {
    const previous = saveQueue.current.get(app.id) ?? Promise.resolve();
    const next = previous.then(() => sendApp(app, method));
    saveQueue.current.set(app.id, next);
    return next;
  };

  // Every save sends the whole spec, including tabs this screen doesn't show, so
  // a drag on the first tab can't drop the others. The server reads an absent
  // field as "keep it", so the pin is always sent: an empty string is the only
  // way a save can clear one. Never rejects, so one failure can't stall the queue.
  const sendApp = async (app: App, method: 'PUT' | 'POST') => {
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
        console.error(`Failed to save app ${app.id}: ${data?.detail || `HTTP ${res.status}`}`);
      }
    } catch (e) {
      console.error('Failed to save app:', e);
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
    setActiveAppId(newApp.id);
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
      setActiveAppId(newApp.id);
      apiSyncApp(newApp, 'POST');
    }
  };

  const handleSetActiveAppId = (id: string) => {
    setActiveAppId(id);
  };

  const removeApp = async (id: string) => {
    const appToRemove = apps.find(a => a.id === id);
    const newApps = apps.filter(a => a.id !== id);
    setApps(newApps);
    if (activeAppId === id && newApps.length > 0) {
      setActiveAppId(newApps[0].id);
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
  const generateShareLink = (): string => {
    if (!activeApp) return '';
    return `${window.location.origin}${window.location.pathname}?shared_view=${activeApp.id}`;
  };

  // Build a URL that opens a specific widget within the active app, fullscreened.
  // We piggy-back on shared_view so non-owners subscribe to it automatically.
  const generateWidgetShareLink = (widgetId: string): string => {
    if (!activeApp) return '';
    return `${window.location.origin}${window.location.pathname}?shared_view=${activeApp.id}&widget=${widgetId}`;
  };

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
      apps, activeAppId, activeApp, activeAppTab, activeDomain, setActiveDomain, isLoading, isAdmin, username, domainPermissions, fetchApps,
      variables, setVariable,
      addApp, removeApp, renameApp, reorderApps, setActiveAppId: handleSetActiveAppId,
      duplicateApp, addWidget, removeWidget, updateWidget, updateLayout,
      toggleLock, setPinnedAgent, canEditApp, canEditDomain, generateShareLink, generateWidgetShareLink, configModal, openConfigModal, closeConfigModal
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
