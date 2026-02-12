import React, { useState, useEffect, useRef } from 'react';
import { Responsive } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { X, ExternalLink } from 'lucide-react';
import { useDashboardStore, type WidgetLayout, TEMPLATES } from './store/dashboardStore';
import { widgetRegistry } from './widgetRegistry';
import { Layout } from './components/Layout';
import { BaseWidget } from './components/BaseWidget';

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

const DashboardGrid: React.FC = () => {
  const { tabs, activeTabId, viewingTemplate, updateLayout, removeWidget, addWidget, openConfigModal, updateWidget } = useDashboardStore();
  const [droppingItem, setDroppingItem] = useState<{ i: string; w: number; h: number } | undefined>();
  const [draggedWidget, setDraggedWidget] = useState<{ type: string; w: number; h: number } | null>(null);
  const [fullscreenWidget, setFullscreenWidget] = useState<{ id: string; type: string; title: string } | null>(null);

  // Get active tab - either from user tabs or templates
  const activeTab = viewingTemplate
    ? TEMPLATES[viewingTemplate]
    : tabs.find(t => t.id === activeTabId);

  const handleLayoutChange = (layout: WidgetLayout[]) => {
    const isLockedCheck = !viewingTemplate && activeTab && (activeTab as any).locked === true;
    if (activeTab && !isLockedCheck) {
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

  // Use a ref to track if we're dragging over
  const containerRef = useRef<HTMLDivElement>(null);

  // Early return after all hooks
  if (!activeTab) return null;

  const isLocked = !viewingTemplate && activeTab?.locked === true;

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      onDrop={(e) => {
        if (isLocked) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        handleNativeDrop(e);
      }}
      onDragOver={(e) => {
        if (isLocked) {
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
        if (isLocked) {
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
      <ResponsiveGridLayout
        className="layout"
        layouts={{
          lg: activeTab.widgets.map(w => ({
            ...w,
            static: isLocked || false
          }))
        }}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
        rowHeight={60}
        onLayoutChange={(layout: any) => handleLayoutChange(layout as WidgetLayout[])}
        draggableHandle={isLocked ? "" : ".drag-handle"}
        margin={[16, 16]}
        isDroppable={!viewingTemplate && !isLocked} // Disable drops when viewing template or locked
        isDraggable={!viewingTemplate && !isLocked} // Disable dragging when viewing template or locked
        isResizable={!viewingTemplate && !isLocked} // Disable resizing when viewing template or locked
        droppingItem={droppingItem}
        onDropDragOver={handleDropDragOver as any}
      >
        {activeTab.widgets.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <p className="text-lg mb-2">Empty Dashboard</p>
              <p className="text-sm">
                {isLocked
                  ? "Dashboard is locked. Click 'Unlock' to edit."
                  : "Drag widgets from the library to get started"}
              </p>
            </div>
          </div>
        )}
        {activeTab.widgets.map((widget: WidgetLayout) => {
          const def = widgetRegistry[widget.type];
          if (!def) {
            return (
              <div key={widget.i} className="bg-red-50 border border-red-200 p-4 rounded text-red-500 h-full relative group">
                <p className="font-medium">Unknown Widget Type</p>
                <p className="text-xs mt-1 text-red-400">{widget.type}</p>
                {!viewingTemplate && !isLocked && (
                  <button
                    onClick={() => removeWidget(activeTabId, widget.i)}
                    className="absolute top-2 right-2 p-1.5 hover:bg-red-100 rounded-md transition-colors text-red-500"
                    title="Remove Widget"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>
            );
          }

          const Component = def.component;

          let customActions = null;
          if (widget.type === 'iframe') {
            const url = widget.props?.url || 'https://forecast.weather.gov/MapClick.php?lat=32.7157&lon=-117.1611';
            customActions = (
              <button
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

          return (
            <div key={widget.i}>
              <BaseWidget
                id={widget.i}
                title={def.name}
                customActions={customActions}
                onRemove={viewingTemplate || isLocked ? undefined : () => removeWidget(activeTabId, widget.i)}
                onFullscreen={() => setFullscreenWidget({ id: widget.i, type: widget.type, title: def.name })}
                onConfigure={
                  (def.configurationMode === 'config_required' || def.configurationMode === 'config_allowed') && (!viewingTemplate && !isLocked)
                    ? () => openConfigModal(widget.type, (config) => updateWidget(activeTabId, widget.i, { props: config }), widget.props)
                    : undefined
                }
                className={`h-full w-full ${isLocked ? 'locked-widget' : ''}`}
              >
                <Component
                  id={widget.i}
                  data={widget.props}
                  key={`${widget.i}-${JSON.stringify(widget.props)}`}
                />
              </BaseWidget>
            </div>
          );
        })}
      </ResponsiveGridLayout>

      {/* Fullscreen Widget Modal */}
      {fullscreenWidget && (
        <FullscreenWidgetModal
          widget={fullscreenWidget}
          onClose={() => setFullscreenWidget(null)}
        />
      )}
    </div>
  );
};

// Fullscreen Widget Modal Component
interface FullscreenWidgetModalProps {
  widget: { id: string; type: string; title: string };
  onClose: () => void;
}

const FullscreenWidgetModal: React.FC<FullscreenWidgetModalProps> = ({ widget, onClose }) => {
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handleEscape);
    // Prevent body scroll when modal is open
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [onClose]);

  const def = widgetRegistry[widget.type];
  if (!def) {
    return null;
  }

  const Component = def.component;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
      onClick={(e) => {
        // Close on backdrop click
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="w-full h-full max-w-[95vw] max-h-[95vh] bg-white rounded-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="h-14 bg-gray-50 border-b border-gray-200 flex items-center justify-between px-6">
          <h2 className="text-lg font-semibold text-qualcomm-navy">{widget.title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-red-500 transition-colors p-2 hover:bg-gray-100 rounded"
            title="Close (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Widget Content */}
        <div className="flex-1 overflow-auto p-6">
          <Component id={widget.id} data={undefined} />
        </div>
      </div>
    </div>
  );
};

function App() {
  return (
    <Layout>
      <DashboardGrid />
    </Layout>
  );
}

export default App;
