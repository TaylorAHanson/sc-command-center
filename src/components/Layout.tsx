import React, { useState, useEffect, useRef } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { ActionLogs } from '../pages/ActionLogs';
import { Plus, Settings, HelpCircle, Menu, LayoutGrid, Layers, Copy, Pencil, GripVertical, Share2, Check, Lock, Unlock, ChevronDown, Info, Shield, Code } from 'lucide-react';
import clsx from 'clsx';
import { WidgetTray } from './WidgetTray';
import { ConfigModal } from './ConfigModal';
import { widgetRegistry } from '../widgetRegistry';
import { SettingsPage } from '../pages/SettingsPage';
import { HelpPage } from '../pages/HelpPage';
import { AboutPage } from '../pages/AboutPage';
import { WidgetStudio } from '../pages/WidgetStudio';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentPage, setCurrentPage] = useState<string | null>(null);
  const { tabs, activeTabId, viewingTemplate, setActiveTabId, addTab, removeTab, renameTab, reorderTabs, loadTemplate, viewTemplate, generateShareLink, toggleLock, configModal, closeConfigModal } = useDashboardStore();
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [isTrayOpen, setTrayOpen] = useState(false);
  const [editingTabId, setEditingTabId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [draggedTabIndex, setDraggedTabIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [shareLinkCopied, setShareLinkCopied] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [editWidgetId, setEditWidgetId] = useState<string | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Close user menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    };

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

    if (isUserMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isUserMenuOpen, currentPage]);

  // Separate user tabs from global templates
  const userTabs = tabs.filter(t => !t.id.startsWith('temp-'));
  const globalTemplates = ['Executive View', 'Production'];

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Sidebar */}
      <div className={clsx(
        "bg-qualcomm-navy text-white transition-all duration-300 flex flex-col border-r border-gray-800",
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
                  {userTabs.map((tab, index) => {
                    const isEditing = editingTabId === tab.id;
                    const isDragging = draggedTabIndex === index;
                    const isDragOver = dragOverIndex === index;
                    const tabIndex = tabs.findIndex(t => t.id === tab.id);

                    return (
                      <div
                        key={tab.id}
                        className={clsx(
                          "group relative",
                          isDragging && "opacity-50",
                          isDragOver && draggedTabIndex !== null && draggedTabIndex !== index && "border-t-2 border-qualcomm-blue"
                        )}
                        draggable={!isEditing}
                        onDragStart={(e) => {
                          setDraggedTabIndex(tabIndex);
                          e.dataTransfer.effectAllowed = 'move';
                          e.dataTransfer.setData('text/plain', tabIndex.toString());
                        }}
                        onDragEnd={() => {
                          setDraggedTabIndex(null);
                          setDragOverIndex(null);
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = 'move';
                          if (draggedTabIndex !== null && draggedTabIndex !== index) {
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
                          if (draggedTabIndex !== null && draggedTabIndex !== index) {
                            reorderTabs(draggedTabIndex, index);
                          }
                          setDraggedTabIndex(null);
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
                                  renameTab(tab.id, editName);
                                  setEditingTabId(null);
                                  setEditName('');
                                } else if (e.key === 'Escape') {
                                  setEditingTabId(null);
                                  setEditName('');
                                }
                              }}
                              onBlur={() => {
                                if (editName.trim()) {
                                  renameTab(tab.id, editName);
                                }
                                setEditingTabId(null);
                                setEditName('');
                              }}
                              autoFocus
                              className="flex-1 bg-gray-700 text-white px-2 py-1 rounded border border-gray-600 focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
                              onClick={(e) => e.stopPropagation()}
                            />
                          </div>
                        ) : (
                          <div
                            onClick={() => {
                              setActiveTabId(tab.id);
                              setCurrentPage(null);
                            }}
                            className={clsx(
                              "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between cursor-pointer",
                              activeTabId === tab.id && currentPage === null
                                ? "bg-qualcomm-blue text-white"
                                : "text-gray-300 hover:bg-gray-800 hover:text-white"
                            )}
                          >
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <GripVertical
                                className={clsx(
                                  "w-4 h-4 flex-shrink-0 cursor-move",
                                  activeTabId === tab.id ? "text-white/60" : "text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                )}
                                onMouseDown={(e) => e.stopPropagation()}
                              />
                              <span className="truncate flex-1">{tab.name}</span>
                            </div>
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingTabId(tab.id);
                                  setEditName(tab.name);
                                }}
                                className="hover:bg-qualcomm-blue/20 rounded p-0.5 transition-colors"
                                title="Rename View"
                                type="button"
                              >
                                <Pencil className="w-3 h-3" />
                              </button>
                              {tabs.length > 1 && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removeTab(tab.id);
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
                    onClick={() => addTab(`View ${userTabs.length + 1}`)}
                    className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-400 hover:bg-gray-800 hover:text-white transition-colors flex items-center gap-2"
                  >
                    <Plus className="w-4 h-4" />
                    <span>New View</span>
                  </button>
                </div>
              </div>

              {/* Global Views (Templates) */}
              <div className="p-3 border-b border-gray-700">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1 flex items-center gap-2">
                  <LayoutGrid className="w-3 h-3" />
                  Global Views
                </div>
                <div className="space-y-1">
                  {globalTemplates.map(templateName => {
                    const isViewing = viewingTemplate === templateName;
                    return (
                      <div key={templateName} className="group relative">
                        <button
                          onClick={() => {
                            viewTemplate(templateName);
                            setCurrentPage(null);
                          }}
                          className={clsx(
                            "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                            isViewing && currentPage === null
                              ? "bg-qualcomm-blue text-white"
                              : "text-gray-300 hover:bg-gray-800 hover:text-white"
                          )}
                        >
                          <span className="truncate flex-1">{templateName}</span>
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            loadTemplate(templateName);
                          }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 hover:bg-qualcomm-blue/20 rounded transition-all text-gray-400 hover:text-qualcomm-blue"
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
                  className="w-full px-3 py-2 border border-gray-600 hover:border-qualcomm-blue hover:text-qualcomm-blue rounded-md text-sm text-gray-400 transition-colors flex items-center justify-center gap-2 group"
                >
                  <LayoutGrid className="w-4 h-4 group-hover:text-qualcomm-blue" />
                  Widget Library (w)
                </button>
                <button
                  onClick={() => setCurrentPage('studio')}
                  className={clsx("w-full mt-2 px-3 py-2 border rounded-md text-sm transition-colors flex items-center justify-center gap-2 group", currentPage === 'studio' ? "bg-qualcomm-blue border-transparent text-white" : "border-gray-600 hover:border-qualcomm-blue hover:text-qualcomm-blue text-gray-400")}
                >
                  <Code className="w-4 h-4 group-hover:text-qualcomm-blue" />
                  Widget Studio
                </button>
              </div>

              {/* Resources */}
              <div className="p-3 border-t border-gray-700 mt-auto">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1">
                  Resources
                </div>
                <div className="space-y-1">
                  <a href="https://docs.qualcomm.com/command-center" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-md transition-colors">
                    <HelpCircle className="w-4 h-4" />
                    <span>Documentation</span>
                  </a>
                  <a href="https://qualcomm.service-now.com/sp" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-md transition-colors">
                    <Settings className="w-4 h-4" />
                    <span>Self Service Hub</span>
                  </a>
                  <a href="https://qualcomm.service-now.com/sp?id=sc_cat_item&sys_id=e1d674121b64711099684197dc4bcb2a" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-md transition-colors">
                    <Info className="w-4 h-4" />
                    <span>Report Issue</span>
                  </a>
                  <button onClick={() => setCurrentPage('admin')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'admin' ? "bg-qualcomm-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <Shield className="w-4 h-4" />
                    <span>Admin Panel</span>
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-4 items-center p-3">
              <button
                onClick={() => setTrayOpen(true)}
                className="p-2 bg-gray-800 hover:bg-qualcomm-blue rounded-md border border-gray-700"
                title="Widget Library"
              >
                <LayoutGrid className="w-5 h-5" />
              </button>
              <button
                onClick={() => setCurrentPage('admin')}
                className={clsx("p-2 rounded-md border border-gray-700", currentPage === 'admin' ? "bg-qualcomm-blue border-transparent" : "bg-gray-800 hover:bg-qualcomm-blue")}
                title="Admin Panel"
              >
                <Shield className="w-5 h-5" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        {currentPage !== 'studio' && (
          <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 shadow-sm z-10">
            <div className="flex items-center gap-4">
              <h1 className="text-lg font-semibold text-qualcomm-navy">
                {currentPage === 'admin' ? 'Admin Panel' : (viewingTemplate
                  ? `${viewingTemplate} (Read-Only)`
                  : tabs.find(t => t.id === activeTabId)?.name || 'Command Center')}
              </h1>
            </div>

            <div className="flex items-center gap-3">
              {!viewingTemplate && (
                <>
                  <button
                    onClick={() => {
                      const activeTab = tabs.find(t => t.id === activeTabId);
                      if (activeTab) {
                        toggleLock(activeTabId);
                      }
                    }}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-qualcomm-blue hover:bg-gray-100 rounded-md transition-colors"
                    title={tabs.find(t => t.id === activeTabId)?.locked ? "Unlock View" : "Lock View"}
                  >
                    {tabs.find(t => t.id === activeTabId)?.locked ? (
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
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-qualcomm-blue hover:bg-gray-100 rounded-md transition-colors"
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
              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                  className="flex items-center gap-2 text-gray-500 hover:text-qualcomm-blue focus:outline-none"
                >
                  <div className="w-8 h-8 bg-qualcomm-blue rounded-full flex items-center justify-center text-white text-xs font-bold ring-2 ring-offset-2 ring-gray-100">
                    QH
                  </div>
                  <ChevronDown className={clsx("w-4 h-4 transition-transform", isUserMenuOpen && "rotate-180")} />
                </button>

                {isUserMenuOpen && (
                  <div className="absolute right-0 top-full mt-2 w-48 bg-white rounded-md shadow-lg border border-gray-200 py-1 z-50">
                    <button
                      onClick={() => {
                        setIsUserMenuOpen(false);
                        setCurrentPage('settings');
                      }}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2"
                    >
                      <Settings className="w-4 h-4" />
                      Settings
                    </button>
                    <button
                      onClick={() => {
                        setIsUserMenuOpen(false);
                        setCurrentPage('help');
                      }}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2"
                    >
                      <HelpCircle className="w-4 h-4" />
                      Help
                    </button>
                    <button
                      onClick={() => {
                        setIsUserMenuOpen(false);
                        setCurrentPage('about');
                      }}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-2"
                    >
                      <Info className="w-4 h-4" />
                      About
                    </button>
                  </div>
                )}
              </div>
            </div>
          </header>
        )}

        {/* Dashboard Canvas or Page */}
        {currentPage ? (
          <main className="flex-1 overflow-hidden bg-gray-50">
            {currentPage === 'settings' && <SettingsPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'help' && <HelpPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'about' && <AboutPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'admin' && <ActionLogs onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'studio' && <WidgetStudio editWidgetId={editWidgetId} onClose={() => { setCurrentPage(null); setEditWidgetId(null); }} />}
          </main>
        ) : (
          <main
            className="flex-1 overflow-auto bg-gray-50/50 p-6 relative"
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
            <div className="max-w-[1920px] mx-auto h-full">
              {children}
            </div>
          </main>
        )}
      </div>

      {/* Widget Tray */}
      <WidgetTray
        isOpen={isTrayOpen}
        onClose={() => setTrayOpen(false)}
        onEditWidget={(id) => {
          setEditWidgetId(id);
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
    </div >
  );
};
