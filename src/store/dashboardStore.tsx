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
  domainPermissions: Record<string, string>;
  fetchViews: () => Promise<void>;

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
  loadSharedDashboard: (sharedData: string) => void;

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
  const [domainPermissions, setDomainPermissions] = useState<Record<string, string>>({});

  const fetchPermissions = useCallback(async () => {
    try {
      const response = await fetch('/api/roles/my-permissions');
      if (response.ok) {
        const data = await response.json();
        setIsAdmin(data.is_admin);
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
          locked: v.is_locked
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
              return;
            }
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
    const shareParam = urlParams.get('share');
    if (shareParam && !isLoading) {
      setTimeout(() => {
        loadSharedDashboard(shareParam);
        window.history.replaceState({}, '', window.location.pathname);
      }, 0);
    }
  }, [isLoading]);

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
    const newTabs = tabs.filter(t => t.id !== id);
    setTabs(newTabs);
    if (activeTabId === id && newTabs.length > 0) {
      setActiveTabId(newTabs[0].id);
    }

    try {
      await fetch(`/api/views/${id}`, { method: 'DELETE' });
    } catch (e) {
      console.error('Failed to delete view', e);
    }
  };

  const renameTab = (id: string, newName: string) => {
    if (!newName.trim()) return;
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
    const newTabs = tabs.map(t => t.id === tabId ? { ...t, locked: !t.locked } : t);
    setTabs(newTabs);
    const updatedTab = newTabs.find(t => t.id === tabId);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const addWidget = (tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }, props?: Record<string, any>) => {
    let updatedTab: Tab | null = null;
    const newTabs = tabs.map(tab => {
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
    setTabs(newTabs);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const updateWidget = (tabId: string, widgetId: string, updates: Partial<WidgetLayout>) => {
    let updatedTab: Tab | null = null;
    const newTabs = tabs.map(tab => {
      if (tab.id !== tabId) return tab;
      updatedTab = {
        ...tab,
        widgets: tab.widgets.map(w => w.i === widgetId ? { ...w, ...updates } : w)
      };
      return updatedTab;
    });
    setTabs(newTabs);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const removeWidget = (tabId: string, widgetId: string) => {
    let updatedTab: Tab | null = null;
    const newTabs = tabs.map(tab => {
      if (tab.id !== tabId) return tab;
      updatedTab = { ...tab, widgets: tab.widgets.filter(w => w.i !== widgetId) };
      return updatedTab;
    });
    setTabs(newTabs);
    if (updatedTab) apiSyncView(updatedTab);
  };

  const updateLayout = (tabId: string, newLayout: WidgetLayout[]) => {
    let updatedTab: Tab | null = null;
    let hasChanges = false;
    const newTabs = tabs.map(tab => {
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
      setTabs(newTabs);
      apiSyncView(updatedTab);
    }
  };

  // Remaining tools
  const generateShareLink = (): string => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return '';
    const shareData = {
      name: activeTab.name,
      widgets: activeTab.widgets.map(w => ({ type: w.type, x: w.x, y: w.y, w: w.w, h: w.h, props: w.props }))
    };
    const encoded = btoa(JSON.stringify(shareData)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
    return `${window.location.origin}${window.location.pathname}?share=${encoded}`;
  };

  const loadSharedDashboard = (sharedData: string) => {
    try {
      const decoded = atob(sharedData.replace(/-/g, '+').replace(/_/g, '/'));
      const parsedData = JSON.parse(decoded);
      const newTab: Tab = {
        id: uuidv4(),
        name: `${parsedData.name} (Shared)`,
        widgets: parsedData.widgets.map((w: any) => ({
          i: uuidv4(), type: w.type, x: w.x, y: w.y, w: w.w, h: w.h, props: w.props || {}
        }))
      };
      setTabs([...tabs, newTab]);
      setActiveTabId(newTab.id);
      apiSyncView(newTab, 'POST');
    } catch (error) {
      console.error('Failed to load shared dashboard:', error);
    }
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
      tabs, activeTabId, activeDomain, setActiveDomain, isLoading, isAdmin, domainPermissions, fetchViews,
      addTab, removeTab, renameTab, reorderTabs, setActiveTabId: handleSetActiveTabId,
      duplicateView, addWidget, removeWidget, updateWidget, updateLayout,
      toggleLock, generateShareLink, loadSharedDashboard, configModal, openConfigModal, closeConfigModal
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
