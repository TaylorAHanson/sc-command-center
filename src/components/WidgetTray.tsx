import React, { useState, useMemo, useEffect } from 'react';
import { X, GripVertical, Lock, Search, ShieldCheck, Filter, Activity, LayoutList, Grid } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import { getWidgetCategories, getWidgetDomains, getAvailableWidgets } from '../widgetRegistry';
import type { WidgetDefinition } from '../widgetRegistry';
import { WidgetPreview } from './WidgetPreview';
import { logWidgetRun, getPopularityScores } from '../api';
import clsx from 'clsx';

interface WidgetTrayProps {
  isOpen: boolean;
  onClose: () => void;
}

export const WidgetTray: React.FC<WidgetTrayProps> = ({ isOpen, onClose }) => {
  const { tabs, activeTabId, viewingTemplate, addWidget, openConfigModal } = useDashboardStore();
  const activeTab = viewingTemplate ? null : tabs.find(t => t.id === activeTabId);
  const isLocked = !viewingTemplate && activeTab?.locked === true;

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [grouping, setGrouping] = useState<'category' | 'domain'>('domain');
  const [showCertifiedOnly, setShowCertifiedOnly] = useState(false);
  const [showMyAccessOnly, setShowMyAccessOnly] = useState(false);
  const [popularityScores, setPopularityScores] = useState<Record<string, number>>({});
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  // Reset selected group when grouping changes
  React.useEffect(() => {
    setSelectedGroup(null);
  }, [grouping]);

  // Fetch popularity scores on mount and when tray opens
  useEffect(() => {
    if (isOpen) {
      getPopularityScores().then(setPopularityScores);
    }
  }, [isOpen]);

  // Close tray when drag starts (with delay to not interfere) and on Escape key
  React.useEffect(() => {
    if (!isOpen) return;

    const handleDragStart = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('application/widget-type')) {
        const timeoutId = setTimeout(() => {
          onClose();
        }, 200);
        (e as any).__trayCloseTimeout = timeoutId;
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('dragstart', handleDragStart);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('dragstart', handleDragStart);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen, onClose]);

  const allWidgets = useMemo(() => getAvailableWidgets(), []);
  const groups = useMemo(() => grouping === 'category' ? getWidgetCategories() : getWidgetDomains(), [grouping]);

  const filteredWidgets = useMemo(() => {
    let widgets = allWidgets;

    // Filter by Group (if no search)
    if (!searchQuery && selectedGroup) {
      widgets = widgets.filter(w =>
        grouping === 'category'
          ? (w.category || 'Uncategorized') === selectedGroup
          : (w.domain || 'Uncategorized') === selectedGroup
      );
    }

    // Filter by Search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      widgets = widgets.filter(w =>
        w.name.toLowerCase().includes(query) ||
        w.description?.toLowerCase().includes(query)
      );
    }

    // Filter by Toggles
    if (showCertifiedOnly) {
      widgets = widgets.filter(w => w.isCertified);
    }
    if (showMyAccessOnly) {
      widgets = widgets.filter(w => w.accessControl?.mockHasAccess !== false);
    }

    // Sort by popularity desc
    return widgets.sort((a, b) => {
      const scoreA = popularityScores[a.id] || 0;
      const scoreB = popularityScores[b.id] || 0;
      return scoreB - scoreA;
    });
  }, [allWidgets, searchQuery, selectedGroup, grouping, showCertifiedOnly, showMyAccessOnly, popularityScores]);

  const handleDragStart = (e: React.DragEvent, widget: WidgetDefinition) => {
    if (isLocked) {
      e.preventDefault();
      return;
    }

    if (widget.accessControl?.mockHasAccess === false) {
      e.preventDefault();
      alert("You do not have access to this widget.");
      return;
    }

    // Log run
    logWidgetRun(widget.id);

    // Required for Firefox
    e.dataTransfer.setData('text/plain', '');
    e.dataTransfer.setData('application/widget-type', widget.id);
    e.dataTransfer.effectAllowed = 'copy';

    // Store widget dimensions
    e.dataTransfer.setData('application/widget-w', widget.defaultW.toString());
    e.dataTransfer.setData('application/widget-h', widget.defaultH.toString());

    // Custom drag image
    const dragImage = e.currentTarget.cloneNode(true) as HTMLElement;
    dragImage.style.position = 'absolute';
    dragImage.style.top = '-1000px';
    dragImage.style.opacity = '0.8';
    dragImage.style.transform = 'rotate(5deg)';
    document.body.appendChild(dragImage);
    const rect = e.currentTarget.getBoundingClientRect();
    e.dataTransfer.setDragImage(dragImage, rect.width / 2, rect.height / 2);
    setTimeout(() => document.body.removeChild(dragImage), 0);

    setTimeout(() => {
      if (isOpen) onClose();
    }, 250);
  };

  const handleWidgetClick = (widget: WidgetDefinition) => {
    if (isLocked) return;
    if (widget.accessControl?.mockHasAccess === false) return;
    logWidgetRun(widget.id);

    if (widget.configurationMode === 'config_required') {
      openConfigModal(widget.id, (config) => {
        addWidget(activeTabId, widget.id, undefined, config);
      });
    } else {
      addWidget(activeTabId, widget.id);
    }
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-40 transition-opacity"
          onClick={onClose}
        />
      )}

      {/* Tray Container */}
      <div
        className={clsx(
          "fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-2xl z-50 transition-transform duration-300 ease-out",
          isOpen ? "translate-y-0" : "translate-y-full"
        )}
        style={{ height: isOpen ? '75vh' : '0' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Tray Header */}
        <div className="h-16 border-b border-gray-200 flex items-center justify-between px-6 bg-gray-50 relative z-20">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-qualcomm-navy">Widget Library</h2>

            {/* Search Bar */}
            <div className="relative w-64">
              <input
                type="text"
                placeholder="Search widgets..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-1.5 rounded-md border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
              />
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
            </div>

            {/* View Toggle */}
            <div className="flex items-center bg-gray-200 rounded-lg p-1 border border-gray-300 ml-4">
              <button
                onClick={() => setViewMode('grid')}
                className={clsx(
                  "p-1.5 rounded-md transition-all",
                  viewMode === 'grid' ? "bg-white text-qualcomm-blue shadow-sm" : "text-gray-500 hover:text-gray-700"
                )}
                title="Grid View"
              >
                <Grid className="w-4 h-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={clsx(
                  "p-1.5 rounded-md transition-all",
                  viewMode === 'list' ? "bg-white text-qualcomm-blue shadow-sm" : "text-gray-500 hover:text-gray-700"
                )}
                title="List View"
              >
                <LayoutList className="w-4 h-4" />
              </button>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-2 border-l border-gray-300 pl-4 ml-2">
              <button
                onClick={() => setShowCertifiedOnly(!showCertifiedOnly)}
                className={clsx(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors border",
                  showCertifiedOnly
                    ? "bg-green-50 text-green-700 border-green-200"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                )}
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Certified Only
              </button>
              <button
                onClick={() => setShowMyAccessOnly(!showMyAccessOnly)}
                className={clsx(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors border",
                  showMyAccessOnly
                    ? "bg-blue-50 text-blue-700 border-blue-200"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                )}
              >
                <Lock className="w-3.5 h-3.5" />
                My Access Only
              </button>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-200 rounded-md transition-colors"
          >
            <X className="w-5 h-5 text-gray-600" />
          </button>
        </div>

        {/* Lock Overlay */}
        {isOpen && isLocked && (
          <div className="absolute inset-0 bg-white/95 z-30 flex items-center justify-center top-16">
            <div className="text-center max-w-md px-6">
              <Lock className="w-12 h-12 mx-auto mb-4 text-gray-400" />
              <h3 className="text-lg font-semibold text-gray-700 mb-2">View is Locked</h3>
              <p className="text-sm text-gray-600 mb-4">
                Unlock the view using the lock button in the top right corner to add or modify widgets.
              </p>
            </div>
          </div>
        )}

        <div className={clsx(
          "flex h-[calc(75vh-4rem)] overflow-hidden relative",
          isLocked && "opacity-50"
        )}>
          {/* Sidebar */}
          <div className="w-56 border-r border-gray-200 bg-gray-50 overflow-y-auto flex flex-col">
            <div className="p-3 border-b border-gray-200">
              <div className="flex rounded-md bg-gray-200 p-1 mb-2">
                <button
                  onClick={() => setGrouping('domain')}
                  className={clsx(
                    "flex-1 text-xs font-medium py-1 rounded transition-all",
                    grouping === 'domain' ? "bg-white shadow text-qualcomm-navy" : "text-gray-500 hover:text-gray-700"
                  )}
                >
                  Domains
                </button>
                <button
                  onClick={() => setGrouping('category')}
                  className={clsx(
                    "flex-1 text-xs font-medium py-1 rounded transition-all",
                    grouping === 'category' ? "bg-white shadow text-qualcomm-navy" : "text-gray-500 hover:text-gray-700"
                  )}
                >
                  Categories
                </button>
              </div>
            </div>

            <div className="p-2 space-y-0.5 overflow-y-auto flex-1">
              <button
                onClick={() => setSelectedGroup(null)}
                className={clsx(
                  "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                  !selectedGroup && !searchQuery
                    ? "bg-qualcomm-navy/10 text-qualcomm-navy font-semibold"
                    : "text-gray-700 hover:bg-gray-200"
                )}
              >
                <span>All {grouping === 'domain' ? 'Domains' : 'Categories'}</span>
              </button>

              {!searchQuery && groups.map(group => {
                const count = allWidgets.filter(w =>
                  grouping === 'category' ? (w.category || 'Uncategorized') === group : (w.domain || 'Uncategorized') === group
                ).length;

                return (
                  <button
                    key={group}
                    onClick={() => setSelectedGroup(group)}
                    className={clsx(
                      "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                      selectedGroup === group
                        ? "bg-qualcomm-blue text-white"
                        : "text-gray-700 hover:bg-gray-200"
                    )}
                  >
                    <span className="truncate">{group}</span>
                    <span className={clsx(
                      "text-xs px-1.5 py-0.5 rounded ml-2",
                      selectedGroup === group ? "bg-white/20" : "bg-gray-300"
                    )}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Widget Grid/List */}
          <div className="flex-1 overflow-y-auto p-6 bg-gray-50/30">
            {filteredWidgets.length > 0 ? (
              <div>
                <h3 className="text-lg font-semibold text-qualcomm-navy mb-4 flex items-center gap-2">
                  {searchQuery ? `Search Results for "${searchQuery}"` : (selectedGroup || `All ${grouping === 'domain' ? 'Domains' : 'Categories'}`)}
                  <span className="text-sm font-normal text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                    {filteredWidgets.length}
                  </span>
                </h3>

                {viewMode === 'grid' ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
                    {filteredWidgets.map(widget => {
                      const hasAccess = widget.accessControl?.mockHasAccess !== false;
                      const popularity = popularityScores[widget.id] || 0;

                      return (
                        <div
                          key={widget.id}
                          draggable={!isLocked && hasAccess}
                          onDragStart={(e) => handleDragStart(e, widget)}
                          onClick={() => handleWidgetClick(widget)}
                          className={clsx(
                            "bg-white border rounded-lg transition-all group relative overflow-hidden flex flex-col",
                            isLocked
                              ? "opacity-50 cursor-not-allowed border-gray-200"
                              : hasAccess
                                ? "hover:border-qualcomm-blue hover:shadow-lg cursor-move border-gray-200"
                                : "cursor-not-allowed border-gray-200 bg-gray-50"
                          )}
                        >
                          {/* Badge: Certified */}
                          {widget.isCertified && (
                            <div className="absolute top-2 left-2 z-10 bg-green-100 text-green-700 text-[10px] font-bold px-1.5 py-0.5 rounded border border-green-200 flex items-center gap-1">
                              <ShieldCheck className="w-3 h-3" />
                              CERTIFIED
                            </div>
                          )}

                          {/* Restricted Overlay */}
                          {!hasAccess && (
                            <div className="absolute inset-0 bg-white/60 z-20 flex flex-col items-center justify-center backdrop-blur-[1px] opacity-0 group-hover:opacity-100 transition-opacity">
                              <Lock className="w-8 h-8 text-gray-400 mb-2" />
                              <span className="text-xs font-semibold text-gray-600 mb-3">Access Restricted</span>
                              <button className="px-3 py-1.5 bg-qualcomm-blue text-white text-xs rounded hover:bg-blue-600 shadow-sm transition-colors">
                                Request Access
                              </button>
                            </div>
                          )}

                          {!hasAccess && (
                            <div className="absolute top-2 right-2 text-gray-400 z-10">
                              <Lock className="w-4 h-4" />
                            </div>
                          )}

                          {/* Drag Handle */}
                          {hasAccess && (
                            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                              <GripVertical className="w-4 h-4 text-gray-400" />
                            </div>
                          )}

                          {/* Preview */}
                          <div className="h-32 bg-gray-50 border-b border-gray-100 relative">
                            <WidgetPreview
                              widgetId={widget.id}
                              component={widget.component}
                              className={clsx("h-full", !hasAccess && "opacity-50 grayscale")}
                            />
                          </div>

                          {/* Info */}
                          <div className="p-3 flex-1 flex flex-col">
                            <div className="flex items-start justify-between gap-2 mb-1">
                              <h4 className="font-semibold text-sm text-qualcomm-navy leading-tight">
                                {widget.name}
                              </h4>
                              {/* Always show popularity */}
                              <div className="flex items-center gap-0.5 text-[10px] text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200" title={`${popularity} runs`}>
                                <Activity className="w-3 h-3" />
                                <span className="font-medium">{popularity}</span>
                              </div>
                            </div>

                            <p className="text-xs text-gray-500 line-clamp-2 mb-3 flex-1">
                              {widget.description}
                            </p>

                            <div className="flex items-center justify-between pt-2 border-t border-gray-50 mt-auto">
                              <span className="text-[10px] uppercase font-semibold text-gray-400 tracking-wider">
                                {widget.domain || 'General'}
                              </span>
                              <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                                {widget.defaultW}×{widget.defaultH}
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex flex-col">
                    {/* List Header */}
                    <div className="grid grid-cols-[1fr_120px_140px_80px_60px_40px] gap-4 px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 bg-gray-100/50 rounded-t-lg">
                      <div>Widget Name</div>
                      <div>{grouping === 'domain' ? 'Category' : 'Domain'}</div>
                      <div>Status</div>
                      <div className="text-right">Popularity</div>
                      <div className="text-center">Size</div>
                      <div></div>
                    </div>

                    {/* List Rows */}
                    <div className="bg-white border-x border-b border-gray-200 rounded-b-lg divide-y divide-gray-100">
                      {filteredWidgets.map(widget => {
                        const hasAccess = widget.accessControl?.mockHasAccess !== false;
                        const popularity = popularityScores[widget.id] || 0;

                        return (
                          <div
                            key={widget.id}
                            draggable={!isLocked && hasAccess}
                            onDragStart={(e) => handleDragStart(e, widget)}
                            onClick={() => handleWidgetClick(widget)}
                            className={clsx(
                              "grid grid-cols-[1fr_120px_140px_80px_60px_40px] gap-4 px-4 py-3 items-center transition-all group",
                              isLocked
                                ? "opacity-50 cursor-not-allowed bg-gray-50"
                                : hasAccess
                                  ? "hover:bg-blue-50/50 cursor-move"
                                  : "cursor-not-allowed bg-gray-50/50"
                            )}
                          >
                            {/* Name & Desc */}
                            <div className="min-w-0">
                              <h4 className={clsx("font-semibold text-sm truncate", hasAccess ? "text-qualcomm-navy" : "text-gray-500")}>
                                {widget.name}
                              </h4>
                              <p className="text-xs text-gray-500 truncate">
                                {widget.description}
                              </p>
                            </div>

                            {/* Domain/Category */}
                            <div className="text-xs text-gray-500 truncate">
                              {grouping === 'domain' ? (widget.category || '-') : (widget.domain || 'General')}
                            </div>

                            {/* Status */}
                            <div className="flex items-center gap-2">
                              {widget.isCertified && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-green-100 text-green-700 border border-green-200">
                                  <ShieldCheck className="w-3 h-3" />
                                  CERTIFIED
                                </span>
                              )}
                              {!hasAccess && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-700 border border-red-200">
                                  <Lock className="w-3 h-3" />
                                  RESTRICTED
                                </span>
                              )}
                              {hasAccess && !widget.isCertified && (
                                <span className="text-[10px] text-gray-400">Available</span>
                              )}
                            </div>

                            {/* Popularity */}
                            <div className="text-right">
                              <div className="inline-flex items-center gap-1.5" title={`${popularity} popularity`}>
                                <span className="text-sm font-medium text-gray-600">{popularity}</span>
                                <Activity className="w-3.5 h-3.5 text-gray-400" />
                              </div>
                            </div>

                            {/* Size */}
                            <div className="text-center">
                              <span className="text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded font-mono">
                                {widget.defaultW}×{widget.defaultH}
                              </span>
                            </div>

                            {/* Drag Handle */}
                            <div className="flex justify-center">
                              <div className={clsx(
                                "p-1 rounded hover:bg-gray-200 transition-colors",
                                hasAccess ? "text-gray-400 cursor-move group-hover:text-qualcomm-blue" : "text-gray-200 cursor-not-allowed"
                              )}>
                                <GripVertical className="w-4 h-4" />
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400">
                <div className="text-center">
                  {searchQuery ? (
                    <>
                      <Search className="w-12 h-12 mx-auto mb-3 opacity-20" />
                      <p className="text-sm">No widgets found matching "{searchQuery}"</p>
                    </>
                  ) : (
                    <>
                      <Filter className="w-12 h-12 mx-auto mb-3 opacity-20" />
                      <p className="text-sm">No widgets in this group</p>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};
