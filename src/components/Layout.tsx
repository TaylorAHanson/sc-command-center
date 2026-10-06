import React, { useState, useEffect, useRef } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { Plus, Menu, LayoutGrid, Layers, Copy, Pencil, GripVertical, Share2, Check, Lock, Unlock, Shield, Code, BookOpen, Bot, ScrollText, Settings2, AppWindow } from 'lucide-react';
import clsx from 'clsx';
import { WidgetTray } from './WidgetTray';
import { AgentDrawer } from './AgentDrawer';
import { AppSettingsModal } from './AppSettingsModal';
import { AddTabMenu, TabBar } from './TabBar';
import { FilterBar } from './FilterBar';
import { useAgentChat } from '../hooks/useAgentChat';
import { ConfigModal } from './ConfigModal';
import { widgetRegistry } from '../widgetRegistry';
import { isPage, layoutSwitch, shownTab, themeVariables } from '../store/appSpec';
import { WorkspaceToolsContext, type WorkspaceTools } from '../contexts/WorkspaceTools';
import { appHash, isStandalone, linkTab, parseAppRoute } from '../store/appRoute';
import { useShell } from '../shell';

// The full-page screens load when they are opened. Together they are most of the
// app's code — the editor, the markdown renderer, the admin tables — and a session
// that only looks at a dashboard should not wait for any of it. They are fetched
// again once the browser goes idle, so opening one still feels immediate.
const pageImports = {
  admin: () => import('../pages/AdminPage'),
  settings: () => import('../pages/SettingsPage'),
  help: () => import('../pages/HelpPage'),
  about: () => import('../pages/AboutPage'),
  studio: () => import('../pages/WidgetStudio'),
  'agent-studio': () => import('../pages/AgentStudio'),
  'user-guide': () => import('../pages/UserGuidePage'),
  'release-notes': () => import('../pages/ReleaseNotesPage'),
};

const AdminPage = React.lazy(() => pageImports.admin().then(m => ({ default: m.AdminPage })));
const SettingsPage = React.lazy(() => pageImports.settings().then(m => ({ default: m.SettingsPage })));
const HelpPage = React.lazy(() => pageImports.help().then(m => ({ default: m.HelpPage })));
const AboutPage = React.lazy(() => pageImports.about().then(m => ({ default: m.AboutPage })));
const WidgetStudio = React.lazy(() => pageImports.studio().then(m => ({ default: m.WidgetStudio })));
const AgentStudio = React.lazy(() => pageImports['agent-studio']().then(m => ({ default: m.AgentStudio })));
const UserGuidePage = React.lazy(() => pageImports['user-guide']().then(m => ({ default: m.UserGuidePage })));
const ReleaseNotesPage = React.lazy(() => pageImports['release-notes']().then(m => ({ default: m.ReleaseNotesPage })));

const PageLoading: React.FC = () => (
  <div className="flex items-center justify-center h-full w-full text-gray-400">
    <div className="w-6 h-6 border-2 border-brand-blue border-t-transparent rounded-full animate-spin" />
  </div>
);

// Every full-page screen `currentPage` can name. Reload and Back/Forward both
// read this list, so a page missing from it is one the browser can't return to.
const PAGES = ['admin', 'studio', 'agent-studio', 'settings', 'help', 'about', 'user-guide', 'release-notes'];
const pageOf = (hash: string): string | null => PAGES.find(p => hash === `#/${p}`) ?? null;

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentPage, setCurrentPage] = useState<string | null>(() => pageOf(window.location.hash));
  // Pages that take over the full screen (no header, no agent drawer).
  const isFullScreenStudio = currentPage === 'studio' || currentPage === 'agent-studio';
  const { apps, activeAppId, activeApp, activeAppTab, openRoute, setActiveAppId, addApp, removeApp, renameApp, reorderApps, duplicateApp, generateShareLink, toggleLock, configModal, closeConfigModal, activeDomain, isAdmin, domainPermissions, canEditApp, canEditLayout, addTab, setTabLayout } = useDashboardStore();
  const shell = useShell();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const canCreateWidgets = isAdmin || Object.values(domainPermissions || {}).some(p => p === 'admin' || p === 'editor');
  const canAccessAdmin = isAdmin || Object.values(domainPermissions || {}).some(p => p === 'admin');
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  // Persist the assistant drawer's open/closed state so it reopens if the user
  // left it open last session.
  const [isAgentOpen, setAgentOpen] = useState(() => {
    try { return localStorage.getItem('sccc-agent-open') === 'true'; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem('sccc-agent-open', String(isAgentOpen)); } catch { /* ignore */ }
  }, [isAgentOpen]);
  const [isTrayOpen, setTrayOpen] = useState(false);
  const [editingAppId, setEditingAppId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [draggedAppIndex, setDraggedAppIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [shareLinkCopied, setShareLinkCopied] = useState(false);
  const [editWidgetId, setEditWidgetId] = useState<string | null>(null);
  const [cloneWidgetId, setCloneWidgetId] = useState<string | null>(null);
  const workspaceTools = React.useMemo<WorkspaceTools>(() => ({
    openLibrary: () => setTrayOpen(true),
    editWidget: (id: string) => {
      setEditWidgetId(id);
      setCloneWidgetId(null);
      setCurrentPage('studio');
    },
  }), []);

  // Held at the Layout level so the conversation survives collapsing the panel.
  const agentChat = useAgentChat();

  // Fetch the pages behind the sidebar buttons once the dashboard has settled.
  // Splitting them out of the bundle is what makes the first load quick; pulling
  // them in during idle time is what stops that showing up as a wait later. Only
  // the ones this person can actually open.
  useEffect(() => {
    const prefetch = () => {
      pageImports.studio();
      pageImports['agent-studio']();
      pageImports.settings();
      if (canAccessAdmin) pageImports.admin();
    };
    const idle = (window as any).requestIdleCallback;
    const handle = idle ? idle(prefetch, { timeout: 8000 }) : window.setTimeout(prefetch, 4000);
    return () => {
      if (idle && (window as any).cancelIdleCallback) (window as any).cancelIdleCallback(handle);
      else window.clearTimeout(handle);
    };
  }, [canAccessAdmin]);

  // Sync state changes to URL hash. A hash that already names what is on screen
  // is left as it is, so a link spelling out the first tab isn't rewritten into
  // a second history entry for the same place. A standalone app's own link would
  // show it on its own, so here, where it is being built, its address is the
  // workspace one: reloading keeps its editor in the workspace.
  useEffect(() => {
    let newHash = '';
    if (currentPage) {
      newHash = `#/${currentPage}`;
    } else if (activeApp && activeAppTab) {
      const named = parseAppRoute(window.location.hash);
      const standalone = isStandalone(activeApp);
      const showing = named?.appId === activeApp.id
        && (named.workspace || !standalone)
        && shownTab(activeApp, named.tabId)?.id === activeAppTab.id;
      if (!showing) newHash = appHash(activeApp.id, linkTab(activeApp, activeAppTab), null, standalone);
    }

    if (newHash && window.location.hash !== newHash) {
      window.location.hash = newHash;
    }
  }, [currentPage, activeApp, activeAppTab]);

  // Auto-collapse the sidebar only in Agent Studio (it needs the full viewport),
  // and restore the user's previous sidebar state when they leave. Widget Studio
  // deliberately does NOT auto-collapse — users found that jarring.
  const autoCollapseSidebar = currentPage === 'agent-studio';
  const prevSidebarOpen = useRef<boolean | null>(null);
  useEffect(() => {
    if (autoCollapseSidebar) {
      if (prevSidebarOpen.current === null) {
        prevSidebarOpen.current = isSidebarOpen;
      }
      if (isSidebarOpen) setSidebarOpen(false);
    } else if (prevSidebarOpen.current !== null) {
      setSidebarOpen(prevSidebarOpen.current);
      prevSidebarOpen.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage]);

  // Handle browser back/forward buttons (hash changes)
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash;
      const page = pageOf(hash);
      const route = page ? null : parseAppRoute(hash);
      if (page) {
        setCurrentPage(page);
      } else if (route) {
        setCurrentPage(null);
        openRoute(route);
      } else if (hash === '' || hash === '#/') {
        // Default to first app
        setCurrentPage(null);
        if (apps.length > 0) setActiveAppId(apps[0].id);
      }
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [apps, setActiveAppId, openRoute]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Toggle widget tray on 'w' key press
      if (event.key.toLowerCase() === 'w' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        // Check if the user is typing in an input or textarea
        const activeElement = document.activeElement;
        const isTyping =
          activeElement instanceof HTMLInputElement ||
          activeElement instanceof HTMLTextAreaElement ||
          (activeElement as HTMLElement)?.isContentEditable;

        // Only open widget tray if there is no full screen page open, and not typing
        if (!isTyping && !currentPage) {
          setTrayOpen(true);
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [currentPage]);

  // Separate the user's apps from global templates
  const myApps = apps.filter(a => !a.is_global && !a.is_shared);
  const sharedApps = apps.filter(a => !a.is_global && a.is_shared);
  const effectiveDomain = activeDomain || 'All';
  const globalTemplates = apps.filter(a => a.is_global && (effectiveDomain === 'All' || !a.domain || a.domain === effectiveDomain));

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Sidebar */}
      <div className={clsx(
        "bg-brand-navy text-white transition-all duration-300 flex flex-col border-r border-gray-800",
        isSidebarOpen ? "w-64" : "w-16"
      )}>
        <div className="h-14 flex items-center px-4 border-b border-gray-700 bg-opacity-50">
          <div className="flex items-center gap-2 font-bold text-lg truncate">
            {isSidebarOpen && <span>Command Center</span>}
          </div>
          <button onClick={() => setSidebarOpen(!isSidebarOpen)} className="ml-auto text-gray-400 hover:text-white">
            <Menu className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto flex flex-col">
          {isSidebarOpen ? (
            <>
              {/* My Views */}
              <div className="p-3 border-b border-gray-700">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1 flex items-center gap-2">
                  <Layers className="w-3 h-3" />
                  My Views
                </div>
                <div className="space-y-1">
                  {myApps.map((app, index) => {
                    const isEditing = editingAppId === app.id;
                    const isDragging = draggedAppIndex === index;
                    const isDragOver = dragOverIndex === index;
                    const appIndex = apps.findIndex(a => a.id === app.id);

                    return (
                      <div
                        key={app.id}
                        className={clsx(
                          "group relative",
                          isDragging && "opacity-50",
                          isDragOver && draggedAppIndex !== null && draggedAppIndex !== index && "border-t-2 border-brand-blue"
                        )}
                        draggable={!isEditing}
                        onDragStart={(e) => {
                          setDraggedAppIndex(appIndex);
                          e.dataTransfer.effectAllowed = 'move';
                          e.dataTransfer.setData('text/plain', appIndex.toString());
                        }}
                        onDragEnd={() => {
                          setDraggedAppIndex(null);
                          setDragOverIndex(null);
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = 'move';
                          if (draggedAppIndex !== null && draggedAppIndex !== index) {
                            setDragOverIndex(index);
                          }
                        }}
                        onDragLeave={() => {
                          if (dragOverIndex === index) {
                            setDragOverIndex(null);
                          }
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          if (draggedAppIndex !== null && draggedAppIndex !== index) {
                            reorderApps(draggedAppIndex, index);
                          }
                          setDraggedAppIndex(null);
                          setDragOverIndex(null);
                        }}
                      >
                        {isEditing ? (
                          <div className="w-full px-3 py-2 rounded-md text-sm bg-gray-800 flex items-center gap-2">
                            <input
                              type="text"
                              value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  renameApp(app.id, editName);
                                  setEditingAppId(null);
                                  setEditName('');
                                } else if (e.key === 'Escape') {
                                  setEditingAppId(null);
                                  setEditName('');
                                }
                              }}
                              onBlur={() => {
                                if (editName.trim()) {
                                  renameApp(app.id, editName);
                                }
                                setEditingAppId(null);
                                setEditName('');
                              }}
                              autoFocus
                              className="flex-1 bg-gray-700 text-white px-2 py-1 rounded border border-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-blue"
                              onClick={(e) => e.stopPropagation()}
                            />
                          </div>
                        ) : (
                          <div
                            onClick={() => {
                              setActiveAppId(app.id);
                              setCurrentPage(null);
                            }}
                            className={clsx(
                              "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between cursor-pointer",
                              activeAppId === app.id && currentPage === null
                                ? "bg-brand-blue text-white"
                                : "text-gray-300 hover:bg-gray-800 hover:text-white"
                            )}
                          >
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <GripVertical
                                className={clsx(
                                  "w-4 h-4 flex-shrink-0 cursor-move",
                                  activeAppId === app.id ? "text-white/60" : "text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                )}
                                onMouseDown={(e) => e.stopPropagation()}
                              />
                              <span className="truncate flex-1">{app.name}</span>
                            </div>
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingAppId(app.id);
                                  setEditName(app.name);
                                }}
                                className="hover:bg-brand-blue/20 rounded p-0.5 transition-colors"
                                title="Rename View"
                                type="button"
                              >
                                <Pencil className="w-3 h-3" />
                              </button>
                              {apps.length > 1 && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removeApp(app.id);
                                  }}
                                  className="hover:bg-red-500/20 rounded p-0.5 transition-colors"
                                  title="Close View"
                                  type="button"
                                >
                                  <Plus className="w-3 h-3 rotate-45" />
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <button
                    onClick={() => addApp(`View ${myApps.length + 1}`)}
                    className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-400 hover:bg-gray-800 hover:text-white transition-colors flex items-center gap-2"
                  >
                    <Plus className="w-4 h-4" />
                    <span>New View</span>
                  </button>
                </div>
              </div>

              {/* Shared Views */}
              {sharedApps.length > 0 && (
                <div className="p-3 border-b border-gray-700">
                  <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1 flex items-center gap-2">
                    <Share2 className="w-3 h-3" />
                    Shared Views
                  </div>
                  <div className="space-y-1">
                    {sharedApps.map(app => {
                      const isViewing = activeAppId === app.id;
                      return (
                        <div key={app.id} className="group relative">
                          <button
                            onClick={() => {
                              setActiveAppId(app.id);
                              setCurrentPage(null);
                            }}
                            className={clsx(
                              "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                              isViewing && currentPage === null
                                ? "bg-brand-blue text-white"
                                : "text-gray-300 hover:bg-gray-800 hover:text-white"
                            )}
                          >
                            <span className="truncate flex-1">{app.name}</span>
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              removeApp(app.id);
                            }}
                            className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/20 rounded transition-all text-gray-400 hover:text-red-400"
                            title="Remove Shared View"
                          >
                            <Plus className="w-3.5 h-3.5 rotate-45" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Global Views (Templates) */}
              <div className="p-3 border-b border-gray-700">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1 flex items-center gap-2">
                  <LayoutGrid className="w-3 h-3" />
                  Global Views
                </div>
                <div className="space-y-1">
                  {globalTemplates.map(template => {
                    const isViewing = activeAppId === template.id;
                    return (
                      <div key={template.id} className="group relative">
                        <button
                          onClick={() => {
                            setActiveAppId(template.id);
                            setCurrentPage(null);
                          }}
                          className={clsx(
                            "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                            isViewing && currentPage === null
                              ? "bg-brand-blue text-white"
                              : "text-gray-300 hover:bg-gray-800 hover:text-white"
                          )}
                        >
                          <span className="truncate flex-1">{template.name}</span>
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            duplicateApp(template.id);
                          }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 hover:bg-brand-blue/20 rounded transition-all text-gray-400 hover:text-brand-blue"
                          title="Copy this template to My Views"
                        >
                          <Copy className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-gray-500 mt-2 px-1">
                  Click to view, hover to copy.
                </p>
              </div>

              {/* Widget Library Button */}
              <div className="p-3">
                <button
                  onClick={() => setTrayOpen(true)}
                  className="w-full px-3 py-2 border border-gray-600 hover:border-brand-blue hover:text-brand-blue rounded-md text-sm text-gray-400 transition-colors flex items-center justify-center gap-2 group"
                >
                  <LayoutGrid className="w-4 h-4 group-hover:text-brand-blue" />
                  Widget Library (w)
                </button>
                {canCreateWidgets && (
                  <button
                    onClick={() => setCurrentPage('studio')}
                    className={clsx("w-full mt-2 px-3 py-2 border rounded-md text-sm transition-colors flex items-center justify-center gap-2 group", currentPage === 'studio' ? "bg-brand-blue border-transparent text-white" : "border-gray-600 hover:border-brand-blue hover:text-brand-blue text-gray-400")}
                  >
                    <Code className="w-4 h-4 group-hover:text-brand-blue" />
                    Widget Studio
                  </button>
                )}
                {canCreateWidgets && (
                  <button
                    onClick={() => setCurrentPage('agent-studio')}
                    className={clsx("w-full mt-2 px-3 py-2 border rounded-md text-sm transition-colors flex items-center justify-center gap-2 group", currentPage === 'agent-studio' ? "bg-brand-blue border-transparent text-white" : "border-gray-600 hover:border-brand-blue hover:text-brand-blue text-gray-400")}
                  >
                    <Bot className="w-4 h-4 group-hover:text-brand-blue" />
                    Agent Studio
                  </button>
                )}
              </div>

              {/* Resources */}
              <div className="p-3 border-t border-gray-700 mt-auto">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1">
                  Resources
                </div>
                <div className="space-y-1">
                  <button onClick={() => setCurrentPage('user-guide')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'user-guide' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <BookOpen className="w-4 h-4" />
                    <span>User Guide</span>
                  </button>
                  <button onClick={() => setCurrentPage('release-notes')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'release-notes' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <ScrollText className="w-4 h-4" />
                    <span>Release Notes</span>
                  </button>
                  {canAccessAdmin && (
                    <button onClick={() => setCurrentPage('admin')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'admin' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                      <Shield className="w-4 h-4" />
                      <span>Admin Panel</span>
                    </button>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        {!isFullScreenStudio && (
          <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 shadow-sm z-10">
            <div className="flex items-center gap-4">
              <h1 className="text-lg font-semibold text-brand-navy">
                {currentPage === 'admin' ? 'Admin Panel' : (
                  activeApp?.is_global && !isAdmin
                    ? `${activeApp.name} (Read-Only)`
                    : activeApp?.name || 'Command Center'
                )}
              </h1>
            </div>

            <div className="flex items-center gap-3">
              {!currentPage && activeApp && isStandalone(activeApp) && (
                <button
                  onClick={() => shell.present(activeApp, linkTab(activeApp, activeAppTab))}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                  title="See this view on its own, as people with its link do"
                >
                  <AppWindow className="w-4 h-4" />
                  <span>Open</span>
                </button>
              )}
              {!currentPage && activeApp && activeAppTab && activeApp.spec.tabs.length === 1 && canEditLayout(activeApp) && (() => {
                const swap = layoutSwitch(activeAppTab);
                return (
                  <AddTabMenu
                    align="right"
                    onChoose={layout => addTab(activeApp.id, 'Tab 2', layout)}
                    button={open => (
                      <button
                        onClick={open}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                        title="Give this view a second tab"
                      >
                        <Plus className="w-4 h-4" />
                        <span>Add tab</span>
                      </button>
                    )}
                    extra={(
                      <button
                        type="button"
                        disabled={swap.blocked}
                        onClick={() => setTabLayout(activeApp.id, activeAppTab.id, swap.to)}
                        className="w-full px-3 py-2 text-left text-xs text-gray-600 hover:bg-gray-50 disabled:text-gray-300 disabled:hover:bg-transparent"
                        title={swap.title}
                      >
                        {swap.to === 'page' ? 'Or make this view itself a page' : 'Or make this view a canvas again'}
                      </button>
                    )}
                  />
                );
              })()}
              {!currentPage && activeApp && canEditApp(activeApp) && (
                <button
                  onClick={() => setSettingsOpen(true)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                  title="How this view opens from its link, its title and logo, and its assistant"
                >
                  <Settings2 className="w-4 h-4" />
                  <span>Settings</span>
                </button>
              )}
              {(!activeApp?.is_global || isAdmin) && !activeApp?.is_shared && (
                <>
                  <button
                    onClick={() => {
                      if (activeApp) {
                        toggleLock(activeApp.id);
                      }
                    }}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                    title={activeApp?.locked ? "Unlock View" : "Lock View"}
                  >
                    {activeApp?.locked ? (
                      <>
                        <Lock className="w-4 h-4" />
                        <span>Locked</span>
                      </>
                    ) : (
                      <>
                        <Unlock className="w-4 h-4" />
                        <span>Lock</span>
                      </>
                    )}
                  </button>
                  <button
                    onClick={async () => {
                      const link = generateShareLink();
                      if (link) {
                        try {
                          await navigator.clipboard.writeText(link);
                          setShareLinkCopied(true);
                          setTimeout(() => setShareLinkCopied(false), 2000);
                        } catch (err) {
                          // Fallback for older browsers
                          const textArea = document.createElement('textarea');
                          textArea.value = link;
                          document.body.appendChild(textArea);
                          textArea.select();
                          document.execCommand('copy');
                          document.body.removeChild(textArea);
                          setShareLinkCopied(true);
                          setTimeout(() => setShareLinkCopied(false), 2000);
                        }
                      }
                    }}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                    title="Share View"
                  >
                    {shareLinkCopied ? (
                      <>
                        <Check className="w-4 h-4" />
                        <span>Copied!</span>
                      </>
                    ) : (
                      <>
                        <Share2 className="w-4 h-4" />
                        <span>Share</span>
                      </>
                    )}
                  </button>
                </>
              )}

            </div>
          </header>
        )}

        {/* Dashboard Canvas or Page */}
        {currentPage ? (
          <main className="flex-1 overflow-hidden bg-gray-50">
            <React.Suspense fallback={<PageLoading />}>
            {currentPage === 'user-guide' && <UserGuidePage />}
            {currentPage === 'release-notes' && <ReleaseNotesPage />}
            {currentPage === 'settings' && <SettingsPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'help' && <HelpPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'about' && <AboutPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'admin' && <AdminPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'studio' && <WidgetStudio editWidgetId={editWidgetId} cloneWidgetId={cloneWidgetId} onClose={() => { setCurrentPage(null); setEditWidgetId(null); setCloneWidgetId(null); }} />}
            {currentPage === 'agent-studio' && <AgentStudio />}
            </React.Suspense>
          </main>
        ) : (
          // The view's theme covers its own tabs, filters and canvas; the sidebar
          // and header are Command Center's, so switching views doesn't repaint them.
          <div className="flex-1 flex flex-col min-h-0" style={themeVariables(activeApp?.spec.theme) as React.CSSProperties}>
            <TabBar placement="top" />
            <FilterBar />
            <div className="flex-1 flex min-h-0">
              <TabBar placement="side" />
              <main
                className="flex-1 min-w-0 overflow-auto bg-gray-50/50 relative"
                onDragOver={(e) => {
                  // Allow drops on main content area
                  if (e.dataTransfer.types.includes('application/widget-type')) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.dataTransfer.dropEffect = 'copy';
                  }
                }}
                onDrop={(e) => {
                  // Prevent main from intercepting - let it bubble to children
                  if (e.dataTransfer.types.includes('application/widget-type')) {
                    e.stopPropagation();
                  }
                }}
              >
                <div className={isPage(activeAppTab) ? 'w-full h-full' : 'w-full h-full px-2'}>
                  <WorkspaceToolsContext.Provider value={workspaceTools}>
                    {children}
                  </WorkspaceToolsContext.Provider>
                </div>
              </main>
            </div>
          </div>
        )}
      </div>

      {/* Agent Assistant (hidden in Studios, which need the full viewport) */}
      {!isFullScreenStudio && <AgentDrawer chat={agentChat} isOpen={isAgentOpen} onOpenChange={setAgentOpen} />}

      {/* Widget Tray */}
      <WidgetTray
        isOpen={isTrayOpen}
        onClose={() => setTrayOpen(false)}
        onEditWidget={(id) => {
          setEditWidgetId(id);
          setCloneWidgetId(null);
          setCurrentPage('studio');
        }}
        onCloneWidget={(id) => {
          setCloneWidgetId(id);
          setEditWidgetId(null);
          setCurrentPage('studio');
        }}
      />

      {/* Config Modal */}
      {/* Config Modal */}
      <ConfigModal
        isOpen={configModal.isOpen}
        onClose={closeConfigModal}
        onSave={(config) => {
          if (configModal.onSave) {
            configModal.onSave(config);
          }
          closeConfigModal();
        }}
        widget={configModal.widgetId ? widgetRegistry[configModal.widgetId] : null}
        initialConfig={configModal.initialConfig}
      />

      {settingsOpen && activeApp && (
        <AppSettingsModal
          app={activeApp}
          agents={agentChat.availableProfiles}
          loadAgents={agentChat.loadProfilesOnce}
          selectAgent={id => { if (!agentChat.isLoading) agentChat.setSelectedProfileId(id); }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div >
  );
};
