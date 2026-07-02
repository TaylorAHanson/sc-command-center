import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { widgetRegistry } from '../widgetRegistry';

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

export interface Tab {
  id: string;
  name: string;
  widgets: WidgetLayout[];
  locked?: boolean;
  domain?: string;
  is_global?: boolean;
  is_shared?: boolean;
  username?: string;
  version?: number;
}

interface DashboardContextType {
  tabs: Tab[]; // All views (user + global)
  activeTabId: string;
  activeDomain: string | null;
  setActiveDomain: (domainId: string | null) => void;
  isLoading: boolean;
  isAdmin: boolean;
  username: string;
  domainPermissions: Record<string, string>;
  fetchViews: () => Promise<void>;
  
  variables: Record<string, any>;
  setVariable: (key: string, value: any) => void;

  addTab: (name: string, domain?: string, is_global?: boolean) => void;
  removeTab: (id: string) => void;
  renameTab: (id: string, newName: string) => void;
  reorderTabs: (fromIndex: number, toIndex: number) => void;
  setActiveTabId: (id: string) => void;
  duplicateView: (viewId: string) => void;
  toggleLock: (tabId: string) => void;

  addWidget: (tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => void;
  removeWidget: (tabId: string, widgetId: string) => void;
  updateWidget: (tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => void;
  updateLayout: (tabId: string, newLayout: WidgetLayout[]) => void;

  generateShareLink: () => string;
  generateWidgetShareLink: (widgetId: string) => string;

  configModal: { isOpen: boolean; widgetId: string | null; initialConfig: any; onSave: ((config: any) => void) | null };
  openConfigModal: (widgetId: string, onSave: (config: any) => void, initialConfig?: any) => void;
  closeConfigModal: () => void;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

export const DashboardProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeDomain, setActiveDomain] = useState<string | null>(null);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [username, setUsername] = useState('unknown');
  const [domainPermissions, setDomainPermissions] = useState<Record<string, string>>({});
  const [variables, setVariables] = useState<Record<string, any>>({});

  const setVariable = useCallback((key: string, value: any) => {
    // Skip the update when the value is unchanged. Widgets share this map, so a
    // new `variables` object re-renders every widget on the view; an unguarded
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

  const fetchViews = useCallback(async () => {
    try {
      const response = await fetch('/api/views/');
      if (response.ok) {
        const data = await response.json();
        const loadedTabs = data.views.map((v: any) => ({
          ...v,
          locked: v.is_locked || v.is_shared // Shared views are always locked for the subscriber
        }));
        setTabs(loadedTabs);

        // Only set default tab if we don't have one and we're not loading a shared URL
        const urlParams = new URLSearchParams(window.location.search);
        const hasShare = urlParams.get('share');

        if (!hasShare && loadedTabs.length > 0) {
          // Check hash
          const hash = window.location.hash;
          if (hash.startsWith('#/view/')) {
            const id = hash.replace('#/view/', '');
            if (loadedTabs.some((t: Tab) => t.id === id)) {
              setActiveTabId(id);
            }
            return; // Don't fall back to tab 0 if a specific hash was requested
          }
          setActiveTabId(prev => {
            if (!prev) return loadedTabs[0].id;
            return prev;
          });
        }
      }
    } catch (e) {
      console.error('Failed to load views:', e);
    } finally {
      setIsLoading(false);
    }
  }, []); // Remove activeTabId dependency so it doesn't loop when activeTabId is set

  useEffect(() => {
    fetchPermissions();
    fetchViews();
  }, [fetchPermissions, fetchViews]);

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const shareParam = urlParams.get('shared_view');
    if (shareParam) {
      // Clear shared_view from the query string but preserve any other params
      // (e.g. ?widget=... is consumed by App.tsx after the view loads).
      urlParams.delete('shared_view');
      const remaining = urlParams.toString();
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (remaining ? `?${remaining}` : '') + `#/view/${shareParam}`
      );
      
      const subscribeAndLoad = async () => {
        try {
          await fetch(`/api/views/shared/${shareParam}`, { method: 'POST' });
          await fetchViews(); // Refresh views to pull the new shared view in
          setActiveTabId(shareParam);
        } catch (e) {
          console.error('Failed to subscribe to shared view', e);
        }
      };
      subscribeAndLoad();
    }
  }, [fetchViews]);

  const apiSyncView = async (tab: Tab, method: string = 'PUT') => {
    try {
      await fetch(`/api/views/${method === 'PUT' ? `${tab.id}` : ''}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: tab.id,
          name: tab.name,
          domain: tab.domain || "General",
          is_global: tab.is_global || false,
          is_locked: tab.locked || false,
          widgets: tab.widgets
        })
      });
    } catch (e) {
      console.error('Failed to sync view:', e);
    }
  };

  const addTab = (name: string, domain?: string, is_global: boolean = false) => {
    const newTab: Tab = {
      id: uuidv4(),
      name,
      widgets: [],
      domain: domain || 'General',
      is_global
    };
    setTabs([...tabs, newTab]);
    setActiveTabId(newTab.id);
    apiSyncView(newTab, 'POST');
  };

  const duplicateView = (viewId: string) => {
    const template = tabs.find(t => t.id === viewId);
    if (template) {
      const newTab = {
        ...template,
        id: uuidv4(),
        name: `${template.name} (Copy)`,
        is_global: false,
        username: undefined
      };
      newTab.widgets = newTab.widgets.map(w => ({ ...w, i: uuidv4() }));
      setTabs([...tabs, newTab]);
      setActiveTabId(newTab.id);
      apiSyncView(newTab, 'POST');
    }
  };

  const handleSetActiveTabId = (id: string) => {
    setActiveTabId(id);
  };

  const removeTab = async (id: string) => {
    const tabToRemove = tabs.find(t => t.id === id);
    const newTabs = tabs.filter(t => t.id !== id);
    setTabs(newTabs);
    if (activeTabId === id && newTabs.length > 0) {
      setActiveTabId(newTabs[0].id);
    }

    try {
      if (tabToRemove?.is_shared) {
        await fetch(`/api/views/shared/${id}`, { method: 'DELETE' });
      } else {
        await fetch(`/api/views/${id}`, { method: 'DELETE' });
      }
    } catch (e) {
      console.error('Failed to delete view', e);
    }
  };

  const renameTab = (id: string, newName: string) => {
    if (!newName.trim()) return;
    const tab = tabs.find(t => t.id === id);
    if (tab?.is_shared) return; // Cannot rename shared tabs

    const newTabs = tabs.map(t => t.id === id ? { ...t, name: newName.trim() } : t);
    setTabs(newTabs);
    const updatedTab = newTabs.find(t => t.id === id);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const reorderTabs = (fromIndex: number, toIndex: number) => {
    // Only affect UI order, DB doesn't care for now
    const newTabs = [...tabs];
    const [removed] = newTabs.splice(fromIndex, 1);
    newTabs.splice(toIndex, 0, removed);
    setTabs(newTabs);
  };

  const toggleLock = (tabId: string) => {
    const tab = tabs.find(t => t.id === tabId);
    if (tab?.is_shared) return; // Cannot unlock shared tabs

    const newTabs = tabs.map(t => t.id === tabId ? { ...t, locked: !t.locked } : t);
    setTabs(newTabs);
    const updatedTab = newTabs.find(t => t.id === tabId);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const addWidget = (tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => {
    const tab = tabs.find(t => t.id === tabId);
    if (tab?.is_shared) return;

    setTabs(prevTabs => {
      let updatedTab: Tab | null = null;
      const newTabs = prevTabs.map(tab => {
        if (tab.id !== tabId) return tab;
        const def = widgetRegistry[type];
        const newWidget: WidgetLayout = {
          i: uuidv4(),
          x: position?.x ?? (tab.widgets.length * 4) % 12,
          y: position?.y ?? Infinity,
          w: position?.w ?? def?.defaultW ?? 4,
          h: position?.h ?? def?.defaultH ?? 4,
          type,
          props: props || {}
        };
        updatedTab = { ...tab, widgets: [...tab.widgets, newWidget] };
        return updatedTab;
      });
      if (updatedTab) {
        setTimeout(() => apiSyncView(updatedTab!), 0);
      }
      return newTabs;
    });
  };

  const updateWidget = (tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => {
    const tab = tabs.find(t => t.id === tabId);
    if (tab?.is_shared) return;

    setTabs(prevTabs => {
      let updatedTab: Tab | null = null;
      const newTabs = prevTabs.map(tab => {
        if (tab.id !== tabId) return tab;
        updatedTab = {
          ...tab,
          widgets: tab.widgets.map(w => w.i === widgetId ? { ...w, ...updates } : w)
        };
        return updatedTab;
      });
      if (updatedTab) {
        setTimeout(() => apiSyncView(updatedTab!), 0);
      }
      return newTabs;
    });
  };

  const removeWidget = (tabId: string, widgetId: string) => {
    const tab = tabs.find(t => t.id === tabId);
    if (tab?.is_shared) return;

    setTabs(prevTabs => {
      let updatedTab: Tab | null = null;
      const newTabs = prevTabs.map(tab => {
        if (tab.id !== tabId) return tab;
        updatedTab = { ...tab, widgets: tab.widgets.filter(w => w.i !== widgetId) };
        return updatedTab;
      });
      if (updatedTab) {
        setTimeout(() => apiSyncView(updatedTab!), 0);
      }
      return newTabs;
    });
  };

  const updateLayout = (tabId: string, newLayout: WidgetLayout[]) => {
    const tab = tabs.find(t => t.id === tabId);
    if (tab?.is_shared) return;

    setTabs(prevTabs => {
      let updatedTab: Tab | null = null;
      let hasChanges = false;
      const newTabs = prevTabs.map(tab => {
        if (tab.id !== tabId) return tab;
        const updatedWidgets = tab.widgets.map(w => {
          const l = newLayout.find(nl => nl.i === w.i);
          if (l && (w.x !== l.x || w.y !== l.y || w.w !== l.w || w.h !== l.h)) {
            hasChanges = true;
            return { ...w, x: l.x, y: l.y, w: l.w, h: l.h };
          }
          return w;
        });
        if (hasChanges) {
          updatedTab = { ...tab, widgets: updatedWidgets };
          return updatedTab;
        }
        return tab;
      });
      
      if (hasChanges && updatedTab) {
        setTimeout(() => apiSyncView(updatedTab!), 0);
        return newTabs;
      }
      return prevTabs;
    });
  };

  // Remaining tools
  const generateShareLink = (): string => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return '';
    return `${window.location.origin}${window.location.pathname}?shared_view=${activeTab.id}`;
  };

  // Build a URL that opens a specific widget within the active view, fullscreened.
  // We piggy-back on shared_view so non-owners subscribe to it automatically.
  const generateWidgetShareLink = (widgetId: string): string => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return '';
    return `${window.location.origin}${window.location.pathname}?shared_view=${activeTab.id}&widget=${widgetId}`;
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
      tabs, activeTabId, activeDomain, setActiveDomain, isLoading, isAdmin, username, domainPermissions, fetchViews,
      variables, setVariable,
      addTab, removeTab, renameTab, reorderTabs, setActiveTabId: handleSetActiveTabId,
      duplicateView, addWidget, removeWidget, updateWidget, updateLayout,
      toggleLock, generateShareLink, generateWidgetShareLink, configModal, openConfigModal, closeConfigModal
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
