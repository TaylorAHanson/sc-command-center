import React, { createContext, useContext, useEffect, useState } from 'react';
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
  static?: boolean; // For react-grid-layout to prevent dragging/resizing
}

export interface Tab {
  id: string;
  name: string;
  widgets: WidgetLayout[];
  locked?: boolean; // Lock state for preventing edits
}

interface DashboardContextType {
  tabs: Tab[];
  activeTabId: string;
  viewingTemplate: string | null; // Track if we're viewing a template (read-only)
  addTab: (name: string) => void;
  removeTab: (id: string) => void;
  renameTab: (id: string, newName: string) => void;
  reorderTabs: (fromIndex: number, toIndex: number) => void;
  setActiveTabId: (id: string) => void;
  viewTemplate: (templateName: string) => void;
  toggleLock: (tabId: string) => void;
  addWidget: (tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }) => void;
  removeWidget: (tabId: string, widgetId: string) => void;
  updateLayout: (tabId: string, newLayout: WidgetLayout[]) => void;
  loadTemplate: (templateName: string) => void;
  generateShareLink: () => string;
  loadSharedDashboard: (sharedData: string) => void;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

const STORAGE_KEY = 'sc_command_center_state';

export const TEMPLATES: Record<string, Tab> = {
  'Executive View': {
    id: 'temp-exec',
    name: 'Executive View',
    widgets: [
      { i: 'w1', x: 0, y: 0, w: 3, h: 6, type: 'alerts' },
      { i: 'w2', x: 3, y: 0, w: 6, h: 6, type: 'inventory' },
      { i: 'w3', x: 9, y: 0, w: 3, h: 6, type: 'genie' },
      { i: 'w4', x: 0, y: 6, w: 3, h: 3, type: 'external' }
    ]
  },
  'Production': {
    id: 'temp-prod',
    name: 'Production',
    widgets: [
      { i: 'p1', x: 0, y: 0, w: 8, h: 6, type: 'gantt' },
      { i: 'p2', x: 8, y: 0, w: 4, h: 4, type: 'action' },
      { i: 'p3', x: 8, y: 4, w: 4, h: 6, type: 'supplier_form' }
    ]
  }
};

const DEFAULT_TABS: Tab[] = [
  { ...TEMPLATES['Executive View'], id: 'default-1', name: 'Overview' }
];

export const DashboardProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [tabs, setTabs] = useState<Tab[]>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : DEFAULT_TABS;
  });

  const [activeTabId, setActiveTabId] = useState<string>(() => {
    // Check for shared dashboard in URL
    const urlParams = new URLSearchParams(window.location.search);
    const shareParam = urlParams.get('share');
    if (shareParam) {
      // Will be handled by useEffect
      return '';
    }
    return tabs[0]?.id || '';
  });

  const [viewingTemplate, setViewingTemplate] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs));
  }, [tabs]);

  // Load shared dashboard from URL on mount
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const shareParam = urlParams.get('share');
    if (shareParam) {
      // Use setTimeout to ensure state is initialized
      setTimeout(() => {
        loadSharedDashboard(shareParam);
        // Clean up URL
        window.history.replaceState({}, '', window.location.pathname);
      }, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount

  const addTab = (name: string) => {
    const newTab: Tab = {
      id: uuidv4(),
      name,
      widgets: []
    };
    setTabs([...tabs, newTab]);
    setActiveTabId(newTab.id);
  };

  const viewTemplate = (templateName: string) => {
    // View template in read-only mode
    setViewingTemplate(templateName);
    const template = TEMPLATES[templateName];
    if (template) {
      // Set active tab to template ID (temporary, won't be saved)
      setActiveTabId(template.id);
    }
  };

  const loadTemplate = (templateName: string) => {
    const template = TEMPLATES[templateName];
    if (template) {
      const newTab = { ...template, id: uuidv4(), name: `${template.name} (Copy)` };
      // Regenerate widget IDs to avoid conflicts
      newTab.widgets = newTab.widgets.map(w => ({ ...w, i: uuidv4() }));
      
      setTabs([...tabs, newTab]);
      setActiveTabId(newTab.id);
      setViewingTemplate(null); // Clear template view when cloning
    }
  };

  const handleSetActiveTabId = (id: string) => {
    // If switching to a user tab, clear template view
    const isTemplate = Object.values(TEMPLATES).some(t => t.id === id);
    if (!isTemplate) {
      setViewingTemplate(null);
    }
    setActiveTabId(id);
  };

  const removeTab = (id: string) => {
    const newTabs = tabs.filter(t => t.id !== id);
    setTabs(newTabs);
    if (activeTabId === id && newTabs.length > 0) {
      setActiveTabId(newTabs[0].id);
    }
  };

  const renameTab = (id: string, newName: string) => {
    if (!newName.trim()) return; // Don't allow empty names
    setTabs(tabs.map(t => t.id === id ? { ...t, name: newName.trim() } : t));
  };

  const reorderTabs = (fromIndex: number, toIndex: number) => {
    const newTabs = [...tabs];
    const [removed] = newTabs.splice(fromIndex, 1);
    newTabs.splice(toIndex, 0, removed);
    setTabs(newTabs);
  };

  const toggleLock = (tabId: string) => {
    setTabs(tabs.map(t => t.id === tabId ? { ...t, locked: !t.locked } : t));
  };

  const generateShareLink = (): string => {
    const activeTab = tabs.find(t => t.id === activeTabId);
    if (!activeTab) return '';
    
    // Create a shareable representation of the dashboard
    const shareData = {
      name: activeTab.name,
      widgets: activeTab.widgets.map(w => ({
        type: w.type,
        x: w.x,
        y: w.y,
        w: w.w,
        h: w.h,
        props: w.props
      }))
    };
    
    // Encode as base64 URL-safe string
    const encoded = btoa(JSON.stringify(shareData))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=/g, '');
    
    return `${window.location.origin}${window.location.pathname}?share=${encoded}`;
  };

  const loadSharedDashboard = (sharedData: string) => {
    try {
      // Decode base64 URL-safe string
      const decoded = atob(
        sharedData
          .replace(/-/g, '+')
          .replace(/_/g, '/')
      );
      const parsedData = JSON.parse(decoded);
      
      // Create a new tab from the shared data
      const newTab: Tab = {
        id: uuidv4(),
        name: `${parsedData.name} (Shared)`,
        widgets: parsedData.widgets.map((w: any) => ({
          i: uuidv4(),
          type: w.type,
          x: w.x,
          y: w.y,
          w: w.w,
          h: w.h,
          props: w.props || {}
        }))
      };
      
      setTabs([...tabs, newTab]);
      setActiveTabId(newTab.id);
      setViewingTemplate(null);
    } catch (error) {
      console.error('Failed to load shared dashboard:', error);
    }
  };

  const addWidget = (tabId: string, type: string, position?: { x: number; y: number; w?: number; h?: number }) => {
    setTabs(prev => prev.map(tab => {
      if (tab.id !== tabId) return tab;
      const def = widgetRegistry[type];
      const newWidget: WidgetLayout = {
        i: uuidv4(),
        x: position?.x ?? (tab.widgets.length * 4) % 12,
        y: position?.y ?? Infinity, // puts it at the bottom if no position
        w: position?.w ?? def?.defaultW ?? 4,
        h: position?.h ?? def?.defaultH ?? 4,
        type,
        props: {}
      };
      return { ...tab, widgets: [...tab.widgets, newWidget] };
    }));
  };

  const removeWidget = (tabId: string, widgetId: string) => {
    setTabs(prev => prev.map(tab => {
      if (tab.id !== tabId) return tab;
      return { ...tab, widgets: tab.widgets.filter(w => w.i !== widgetId) };
    }));
  };

  const updateLayout = (tabId: string, newLayout: WidgetLayout[]) => {
    setTabs(prev => prev.map(tab => {
      if (tab.id !== tabId) return tab;
      // Merge new layout positions with existing widget data (type, props)
      const updatedWidgets = newLayout.map(l => {
        const existing = tab.widgets.find(w => w.i === l.i);
        return existing ? { ...existing, ...l } : undefined;
      }).filter(Boolean) as WidgetLayout[];
      
      return { ...tab, widgets: updatedWidgets };
    }));
  };

  return (
    <DashboardContext.Provider value={{
      tabs,
      activeTabId,
      viewingTemplate,
      addTab,
      removeTab,
      renameTab,
      reorderTabs,
      setActiveTabId: handleSetActiveTabId,
      viewTemplate,
      addWidget,
      removeWidget,
      updateLayout,
      loadTemplate,
      generateShareLink,
      loadSharedDashboard,
      toggleLock
    }}>
      {children}
    </DashboardContext.Provider>
  );
};

export const useDashboardStore = () => {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error('useDashboardStore must be used within a DashboardProvider');
  }
  return context;
};

