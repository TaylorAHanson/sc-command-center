import React, { useState, useEffect, useRef } from 'react';
import { Responsive } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { ExternalLink, Link2, Check } from 'lucide-react';
import { useDashboardStore, type WidgetLayout } from './store/dashboardStore';
import { widgetRegistry, useWidgetRegistry } from './widgetRegistry';
import { Layout } from './components/Layout';
import { BaseWidget } from './components/BaseWidget';
import { ExecuteActionPropInjector } from './contexts/ActionContext';
import { ThumbnailCaptureHost } from './components/ThumbnailCapture';

// Custom WidthProvider since it's missing in RGL v2.1.0 exports
const WidthProvider = (ComposedComponent: React.ComponentType<any>) => {
  return (props: any) => {
    const [width, setWidth] = useState(1200);
    const elementRef = useRef<HTMLDivElement>(null);
    const mounted = useRef(false);

    useEffect(() => {
      mounted.current = true;
      if (elementRef.current) {
        setWidth(elementRef.current.offsetWidth);
      }

      const resizeObserver = new ResizeObserver((entries) => {
        if (!mounted.current) return;
        for (const entry of entries) {
          // use contentBoxSize or contentRect
          setWidth(entry.contentRect.width);
        }
      });

      if (elementRef.current) {
        resizeObserver.observe(elementRef.current);
      }

      return () => {
        mounted.current = false;
        resizeObserver.disconnect();
      };
    }, []);

    return (
      <div ref={elementRef} className={props.className} style={{ ...props.style, width: '100%' }}>
        <ComposedComponent
          {...props}
          width={width}
          // Remove className/style from child to avoid duplication if RGL applies them
          className=""
          style={{}}
        />
      </div>
    );
  };
};

const ResponsiveGridLayout = WidthProvider(Responsive);

const ShareWidgetButton: React.FC<{ onShare: () => Promise<boolean> }> = ({ onShare }) => {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async (e) => {
        e.stopPropagation();
        const ok = await onShare();
        if (ok) {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1800);
        }
      }}
      className={`transition-colors ${copied ? 'text-green-600' : 'text-gray-400 hover:text-qualcomm-blue'}`}
      title={copied ? 'Link copied!' : 'Copy direct link to this widget'}
    >
      {copied ? <Check className="w-4 h-4" /> : <Link2 className="w-4 h-4" />}
    </button>
  );
};

const DashboardGrid: React.FC = () => {
  const { tabs, activeTabId, updateLayout, removeWidget, addWidget, openConfigModal, updateWidget, activeDomain, isAdmin, username, variables, setVariable, generateWidgetShareLink } = useDashboardStore();
  const { loading: isRegistryLoading } = useWidgetRegistry();
  const [droppingItem, setDroppingItem] = useState<{ i: string; w: number; h: number } | undefined>();
  const [draggedWidget, setDraggedWidget] = useState<{ type: string; w: number; h: number } | null>(null);
  const [fullscreenWidget, setFullscreenWidget] = useState<{ id: string; type: string; title: string } | null>(null);
  const [sharedWidgetId, setSharedWidgetId] = useState<string | null>(null);

  // Get active tab
  const activeTab = tabs.find(t => t.id === activeTabId);
  const isReadOnly = (activeTab?.is_global && !isAdmin) || activeTab?.locked === true;

  // Once the widget registry is loaded, any widget on the current tab whose type no
  // longer exists in the registry is an orphan (widget was deleted). We clean those
  // up automatically and persist the cleanup so empty placeholders never appear.
  useEffect(() => {
    if (isRegistryLoading || !activeTab || isReadOnly) return;
    const orphans = activeTab.widgets.filter(w => {
      const versionedKey = w.props?._version ? `${w.type}@${w.props._version}` : w.type;
      return !widgetRegistry[versionedKey] && !widgetRegistry[w.type];
    });
    if (orphans.length === 0) return;
    const cleaned = activeTab.widgets.filter(w => !orphans.includes(w));
    updateLayout(activeTab.id, cleaned as WidgetLayout[]);
  }, [isRegistryLoading, activeTab?.id, activeTab?.widgets, isReadOnly]);

  const visibleWidgets = React.useMemo(() => {
    return activeTab?.widgets.filter(widget => {
      const versionedKey = widget.props?._version ? `${widget.type}@${widget.props._version}` : widget.type;
      const def = widgetRegistry[versionedKey] || widgetRegistry[widget.type];
      // Hide widgets whose definition is missing once the registry has finished loading.
      // While loading we keep them so we don't render an empty grid mid-load.
      if (!def) return isRegistryLoading;
      if (activeDomain && def.domain && def.domain !== activeDomain) return false;
      return true;
    }) || [];
  }, [activeTab?.widgets, activeDomain, isRegistryLoading]);

  const layouts = React.useMemo(() => {
    return {
      lg: visibleWidgets.map(w => ({
        ...w,
        static: isReadOnly || false
      }))
    };
  }, [visibleWidgets, isReadOnly]);

  // Stable `data` object per widget. Previously we built `{ ...props, username,
  // variables, setVariable }` inline in the render map, so EVERY DashboardGrid
  // re-render (drag-hover, fullscreen toggle, share-copy, any store change)
  // handed each widget a brand-new object reference. Widgets that key an effect
  // on `data` (a common generated pattern) then re-ran that effect — refetching
  // SQL / redrawing charts — on every render, which compounds into the gradual
  // slowdown. Memoizing keeps each widget's `data` referentially stable unless
  // its own props (or the shared username/variables) actually change.
  const dataById = React.useMemo(() => {
    const map: Record<string, any> = {};
    for (const w of visibleWidgets) {
      map[w.i] = { ...w.props, username, variables, setVariable };
    }
    return map;
  }, [visibleWidgets, username, variables, setVariable]);

  const handleLayoutChange = (layout: WidgetLayout[]) => {
    if (activeTab && !isReadOnly) {
      // Remove static property before saving (we add it dynamically)
      const layoutWithoutStatic = layout.map(({ static: _, ...rest }) => rest);
      updateLayout(activeTab.id, layoutWithoutStatic as WidgetLayout[]);
    }
  };

  // Native HTML5 drop handler
  const handleNativeDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();

    console.log('🎯 Native drop event triggered!', {
      draggedWidget,
      activeTab: !!activeTab,
      target: e.target,
      currentTarget: e.currentTarget,
      dataTransferTypes: Array.from(e.dataTransfer.types)
    });

    // Try to get widget data from dataTransfer as fallback
    let widgetType = draggedWidget?.type;
    let w = draggedWidget?.w || 4;
    let h = draggedWidget?.h || 4;

    try {
      const typeFromTransfer = e.dataTransfer.getData('application/widget-type');
      if (typeFromTransfer) widgetType = typeFromTransfer;

      const wStr = e.dataTransfer.getData('application/widget-w');
      const hStr = e.dataTransfer.getData('application/widget-h');
      if (wStr) w = parseInt(wStr, 10);
      if (hStr) h = parseInt(hStr, 10);
    } catch (err) {
      console.warn('Could not read from dataTransfer:', err);
    }

    if (!widgetType || !activeTab) {
      console.warn('Drop failed - missing widget type or active tab', { widgetType, activeTab: !!activeTab });
      setDroppingItem(undefined);
      setDraggedWidget(null);
      return;
    }

    // Calculate grid position from mouse coordinates
    // Find the actual grid layout element
    const gridElement = e.currentTarget.querySelector('.react-grid-layout') as HTMLElement;
    if (!gridElement) {
      console.warn('Could not find grid element');
      setDroppingItem(undefined);
      setDraggedWidget(null);
      return;
    }

    // Get the grid container's position
    const gridRect = gridElement.getBoundingClientRect();
    // Use the actual drop position relative to the grid
    const x = e.clientX - gridRect.left;
    const y = e.clientY - gridRect.top;

    // Grid properties
    const cols = 12; // lg breakpoint
    const rowHeight = 60;
    const margin = [16, 16];
    const colWidth = (gridRect.width - margin[0] * (cols + 1)) / cols;

    // Calculate grid coordinates
    const gridX = Math.max(0, Math.min(Math.floor((x - margin[0]) / (colWidth + margin[0])), cols - w));
    const gridY = Math.max(0, Math.floor((y - margin[1]) / (rowHeight + margin[1])));

    console.log('Adding widget at grid position', {
      widgetType,
      x: gridX,
      y: gridY,
      w,
      h,
      activeTabId: activeTab.id
    });

    const def = widgetRegistry[widgetType];
    if (def?.configurationMode === 'config_required') {
      openConfigModal(widgetType, (config) => {
        addWidget(activeTab.id, widgetType, {
          x: gridX,
          y: gridY,
          w,
          h
        }, config);
      });
    } else {
      const initialConfig: Record<string, any> = {};
      // Merge in any defaultProps from the widget definition (e.g., dataSource for custom widgets)
      if (def?.defaultProps) {
        Object.assign(initialConfig, def.defaultProps);
      }
      if (def?.configSchema) {
        def.configSchema.forEach(field => {
          if (field.defaultValue !== undefined) {
            initialConfig[field.key] = field.defaultValue;
          }
        });
      }
      addWidget(activeTab.id, widgetType, {
        x: gridX,
        y: gridY,
        w,
        h
      }, initialConfig);
    }

    console.log('Widget added - check dashboard for widget at position', { gridX, gridY });

    // Clean up
    setDroppingItem(undefined);
    setDraggedWidget(null);
  };

  const handleNativeDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    // Always prevent default if this is a widget drag to allow drop
    if (e.dataTransfer.types.includes('application/widget-type')) {
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'copy';
      // Log occasionally to verify it's being called (throttle to avoid spam)
      if (Math.random() < 0.01) {
        // console.log('DragOver on grid container');
      }
    }
  };

  const handleDropDragOver = (e: DragEvent) => {
    // Allow drop and return widget dimensions for preview
    e.preventDefault();

    // Try to get from dataTransfer, but also use stored state
    let w = 4;
    let h = 4;

    try {
      const wStr = e.dataTransfer?.getData('application/widget-w');
      const hStr = e.dataTransfer?.getData('application/widget-h');
      if (wStr) w = parseInt(wStr, 10);
      if (hStr) h = parseInt(hStr, 10);
    } catch (err) {
      // Fallback to stored state
      if (draggedWidget) {
        w = draggedWidget.w;
        h = draggedWidget.h;
      }
    }

    return { w, h };
  };

  // Set up global drag listeners to track widget being dragged
  // MUST be called before any early returns to maintain hooks order
  useEffect(() => {
    const handleGlobalDragStart = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('application/widget-type')) {
        try {
          const widgetType = e.dataTransfer.getData('application/widget-type');
          const w = parseInt(e.dataTransfer.getData('application/widget-w') || '4', 10);
          const h = parseInt(e.dataTransfer.getData('application/widget-h') || '4', 10);
          setDraggedWidget({ type: widgetType, w, h });
          setDroppingItem({ i: 'dropping', w, h });
        } catch (err) {
          console.warn('Could not read drag data:', err);
        }
      }
    };

    const handleGlobalDragEnd = () => {
      // Clear state if drag ends without drop (give drop handler time to fire)
      // Use a longer timeout to ensure drop handler completes first
      setTimeout(() => {
        // Only clear if still set (drop handler will clear it if drop succeeded)
        setDroppingItem(prev => {
          if (prev) {
            return undefined;
          }
          return prev;
        });
        setDraggedWidget(prev => {
          if (prev) {
            return null;
          }
          return prev;
        });
      }, 500);
    };

    document.addEventListener('dragstart', handleGlobalDragStart);
    document.addEventListener('dragend', handleGlobalDragEnd);

    return () => {
      document.removeEventListener('dragstart', handleGlobalDragStart);
      document.removeEventListener('dragend', handleGlobalDragEnd);
    };
  }, []);

  // Look for a ?widget=... param on initial load. When present, store it so we
  // can auto-fullscreen the widget once the targeted view has been loaded.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const w = params.get('widget');
    if (w) {
      setSharedWidgetId(w);
      // Clean it out of the URL once captured so refreshes don't repeatedly fullscreen.
      params.delete('widget');
      const qs = params.toString();
      const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
      window.history.replaceState({}, '', newUrl);
    }
  }, []);

  // When the desired shared widget appears in the active tab, fullscreen it.
  useEffect(() => {
    if (!sharedWidgetId || !activeTab) return;
    const target = activeTab.widgets.find(w => w.i === sharedWidgetId);
    if (!target) return;
    const def = widgetRegistry[target.type];
    setFullscreenWidget({ id: target.i, type: target.type, title: def?.name || target.type });
    setSharedWidgetId(null);
  }, [sharedWidgetId, activeTab?.id, activeTab?.widgets.length]);

  // Handle escape key for fullscreen
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreenWidget) {
        setFullscreenWidget(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    if (fullscreenWidget) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [fullscreenWidget]);

  // Use a ref to track if we're dragging over
  const containerRef = useRef<HTMLDivElement>(null);

  // Early return after all hooks
  if (!activeTab) return null;

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      onDrop={(e) => {
        if (isReadOnly) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        handleNativeDrop(e);
      }}
      onDragOver={(e) => {
        if (isReadOnly) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (e.dataTransfer.types.includes('application/widget-type')) {
          e.preventDefault();
          e.stopPropagation();
          e.dataTransfer.dropEffect = 'copy';
        }
        handleNativeDragOver(e);
      }}
      onDragEnter={(e) => {
        if (isReadOnly) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        if (e.dataTransfer.types.includes('application/widget-type')) {
          e.preventDefault();
          e.stopPropagation();
        }
      }}
      style={{ position: 'relative', minHeight: '100%' }}
    >
      {/*
        We use a single breakpoint so the user's layout is the single source of truth.
        The grid is always 12 columns wide; column width simply scales with viewport
        width. This eliminates the previous behavior where shrinking below 1200px
        triggered RGL to re-flow widgets into an "md" layout that then never reverted
        when the window widened again. The result: drag/resize-friendly at any size
        and an automatic snap-back when the window grows because the saved layout
        never changes with viewport width.
      */}
      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        useCSSTransforms={false}
        breakpoints={{ lg: 0 }}
        cols={{ lg: 12 }}
        rowHeight={60}
        onLayoutChange={(currentLayout: any) => {
          handleLayoutChange(currentLayout as WidgetLayout[]);
        }}
        draggableHandle={isReadOnly ? "" : ".drag-handle"}
        margin={[8, 8]}
        containerPadding={[4, 4]}
        isDroppable={!isReadOnly}
        isDraggable={!isReadOnly}
        isResizable={!isReadOnly}
        droppingItem={droppingItem}
        onDropDragOver={handleDropDragOver as any}
      >
        {visibleWidgets.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <p className="text-lg mb-2">Empty Dashboard</p>
              <p className="text-sm">
                {isReadOnly
                  ? "Dashboard is read-only."
                  : "Drag widgets from the library to get started"}
              </p>
            </div>
          </div>
        )}
        {visibleWidgets.map((widget: WidgetLayout) => {
          const versionToUse = widget.props?._version;
          const lookupKey = versionToUse ? `${widget.type}@${versionToUse}` : widget.type;
          const def = widgetRegistry[lookupKey] || widgetRegistry[widget.type];
          
          if (!def) {
            // Registry is still loading - render a lightweight skeleton placeholder.
            // Once loading completes the parent effect removes the widget entirely.
            return (
              <div key={widget.i} className="bg-gray-50 border border-gray-100 p-4 rounded h-full animate-pulse flex flex-col justify-center items-center">
                <div className="w-8 h-8 bg-gray-200 rounded-full mb-2"></div>
                <div className="h-2 bg-gray-200 rounded w-24"></div>
              </div>
            );
          }

          const Component = def.component;

          const extraActions: React.ReactNode[] = [];
          if (def.openInNewTabLink || widget.type === 'iframe') {
            const url = def.openInNewTabLink || widget.props?.url || 'https://forecast.weather.gov/MapClick.php?lat=32.7157&lon=-117.1611';
            if (url) {
              extraActions.push(
                <button
                  key="open-new-tab"
                  onClick={(e) => {
                    e.stopPropagation();
                    window.open(url, '_blank');
                  }}
                  className="text-gray-400 hover:text-qualcomm-blue transition-colors"
                  title="Open in New Tab"
                >
                  <ExternalLink className="w-4 h-4" />
                </button>
              );
            }
          }
          extraActions.push(
            <ShareWidgetButton
              key="share-widget"
              onShare={async () => {
                const link = generateWidgetShareLink(widget.i);
                if (!link) return false;
                try {
                  await navigator.clipboard.writeText(link);
                } catch {
                  const ta = document.createElement('textarea');
                  ta.value = link;
                  document.body.appendChild(ta);
                  ta.select();
                  document.execCommand('copy');
                  document.body.removeChild(ta);
                }
                return true;
              }}
            />
          );
          const customActions = extraActions.length > 0 ? <>{extraActions}</> : null;

          return (
            <div 
              key={widget.i}
              className={fullscreenWidget?.id === widget.i ? '!fixed z-[9999] bg-black/90 p-4 flex items-center justify-center !transform-none !top-0 !left-0 !w-[100vw] !h-[100vh]' : ''}
            >
              <div className={fullscreenWidget?.id === widget.i ? 'w-full h-full bg-white rounded-lg shadow-2xl flex flex-col overflow-hidden' : 'w-full h-full'}>
                <BaseWidget
                  id={widget.i}
                  title={def.name}
                  version={def.version}
                  latestVersion={def.latestVersion}
                  availableVersions={def.availableVersions}
                  helpText={def.helpText}
                  onChangeVersion={isReadOnly ? undefined : (version: number) => {
                    updateWidget(activeTabId, widget.i, {
                      props: { ...widget.props, _version: version }
                    });
                  }}
                  customActions={customActions}
                  isFullscreen={fullscreenWidget?.id === widget.i}
                  onRemove={isReadOnly && fullscreenWidget?.id !== widget.i ? undefined : () => removeWidget(activeTabId, widget.i)}
                  onFullscreen={() => {
                    if (fullscreenWidget?.id === widget.i) {
                      setFullscreenWidget(null);
                    } else {
                      setFullscreenWidget({ id: widget.i, type: widget.type, title: def.name });
                    }
                  }}
                  onConfigure={
                  (def.configurationMode === 'config_required' || def.configurationMode === 'config_allowed') && !isReadOnly
                    ? () => openConfigModal(widget.type, (config) => updateWidget(activeTabId, widget.i, { props: config }), widget.props)
                    : undefined
                }
                className={`h-full w-full ${isReadOnly ? 'locked-widget' : ''}`}
              >
                <React.Suspense fallback={
                  <div className="flex items-center justify-center h-full w-full text-gray-400">
                    <div className="animate-pulse flex flex-col items-center">
                      <div className="w-6 h-6 border-2 border-qualcomm-blue border-t-transparent rounded-full animate-spin mb-2"></div>
                      <span className="text-xs">Loading Widget...</span>
                    </div>
                  </div>
                }>
                  <ExecuteActionPropInjector>
                    <Component
                      id={widget.i}
                      data={dataById[widget.i]}
                      key={widget.i}
                    />
                  </ExecuteActionPropInjector>
                </React.Suspense>
              </BaseWidget>
              </div>
            </div>
          );
        })}
      </ResponsiveGridLayout>
    </div>
  );
};

import { loadCustomWidgets } from './widgetRegistry';

function App() {
  useEffect(() => {
    loadCustomWidgets();
  }, []);

  return (
    <>
      <Layout>
        <DashboardGrid />
      </Layout>
      {/* Mounted as a SIBLING of Layout — not as one of its children — because
          Layout only renders its `children` when no full-page (admin/studio/
          settings/etc.) is active. Putting the host inside `children` made it
          unmount the moment the user navigated to the Admin page, which is
          exactly where backfill is invoked. Sitting outside Layout keeps it
          alive across all routes while remaining inside the DashboardProvider
          tree set up in main.tsx (so BaseWidget's hooks still work). */}
      <ThumbnailCaptureHost />
    </>
  );
}

export default App;
