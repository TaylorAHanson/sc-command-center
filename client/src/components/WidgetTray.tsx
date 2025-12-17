import React, { useState } from 'react';
import { X, LayoutGrid, GripVertical, Lock } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import { getWidgetCategories, getWidgetsByCategory } from '../widgetRegistry';
import { WidgetPreview } from './WidgetPreview';
import clsx from 'clsx';

interface WidgetTrayProps {
  isOpen: boolean;
  onClose: () => void;
}

export const WidgetTray: React.FC<WidgetTrayProps> = ({ isOpen, onClose }) => {
  const { tabs, activeTabId, viewingTemplate, addWidget } = useDashboardStore();
  const activeTab = viewingTemplate ? null : tabs.find(t => t.id === activeTabId);
  const isLocked = !viewingTemplate && activeTab?.locked === true;
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const categories = getWidgetCategories();

  // Close tray when drag starts (with delay to not interfere)
  React.useEffect(() => {
    if (!isOpen) return;
    
    const handleDragStart = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('application/widget-type')) {
        // Close tray after drag is fully initialized (200ms delay)
        // This ensures the drag operation isn't interrupted
        const timeoutId = setTimeout(() => {
          onClose();
        }, 200);
        
        // Store timeout ID on the event so we can clear it if needed
        (e as any).__trayCloseTimeout = timeoutId;
      }
    };

    document.addEventListener('dragstart', handleDragStart);
    
    return () => {
      document.removeEventListener('dragstart', handleDragStart);
    };
  }, [isOpen, onClose]);

  const handleCategoryClick = (category: string) => {
    if (activeCategory === category) {
      setActiveCategory(null); // Close if clicking same category
    } else {
      setActiveCategory(category);
    }
  };


  const handleDragStart = (e: React.DragEvent, widgetId: string, defaultW: number, defaultH: number) => {
    if (isLocked) {
      e.preventDefault();
      return;
    }
    
    // Required for Firefox
    e.dataTransfer.setData('text/plain', '');
    e.dataTransfer.setData('application/widget-type', widgetId);
    e.dataTransfer.effectAllowed = 'copy';
    
    // Store widget dimensions for the drop preview
    e.dataTransfer.setData('application/widget-w', defaultW.toString());
    e.dataTransfer.setData('application/widget-h', defaultH.toString());
    
    // Create a custom drag image
    const dragImage = e.currentTarget.cloneNode(true) as HTMLElement;
    dragImage.style.position = 'absolute';
    dragImage.style.top = '-1000px';
    dragImage.style.opacity = '0.8';
    dragImage.style.transform = 'rotate(5deg)';
    dragImage.style.pointerEvents = 'none';
    document.body.appendChild(dragImage);
    const rect = e.currentTarget.getBoundingClientRect();
    e.dataTransfer.setDragImage(dragImage, rect.width / 2, rect.height / 2);
    setTimeout(() => document.body.removeChild(dragImage), 0);
    
    // Trigger tray close after drag is initialized
    // Use a small delay to ensure drag operation isn't interrupted
    setTimeout(() => {
      if (isOpen) {
        onClose();
      }
    }, 250);
  };
  
  const handleWidgetClick = (widgetId: string) => {
    if (isLocked) return;
    addWidget(activeTabId, widgetId);
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/20 z-40 transition-opacity pointer-events-none"
          onClick={onClose}
        />
      )}

      {/* Tray Container */}
      <div
        className={clsx(
          "fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-2xl z-50 transition-transform duration-300 ease-out",
          isOpen ? "translate-y-0" : "translate-y-full"
        )}
        style={{ height: isOpen ? '60vh' : '0' }}
      >
        {/* Tray Header - Always fully opaque */}
        <div className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-gray-50 relative z-20">
          <h2 className="text-lg font-semibold text-qualcomm-navy">Widget Library</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-200 rounded-md transition-colors z-30 relative"
          >
            <X className="w-5 h-5 text-gray-600" />
          </button>
        </div>
        
        {/* Lock Message Overlay - Only show when tray is open and locked */}
        {isOpen && isLocked && (
          <div className="absolute inset-0 bg-white/95 z-10 flex items-center justify-center">
            <div className="text-center max-w-md px-6">
              <Lock className="w-12 h-12 mx-auto mb-4 text-gray-400" />
              <h3 className="text-lg font-semibold text-gray-700 mb-2">Dashboard is Locked</h3>
              <p className="text-sm text-gray-600 mb-4">
                Unlock the dashboard using the lock button in the top right corner to add or modify widgets.
              </p>
            </div>
          </div>
        )}

        <div className={clsx(
          "flex h-[calc(60vh-3.5rem)] overflow-hidden relative",
          isLocked && "opacity-50"
        )}>
          {/* Category Navigation */}
          <div className="w-48 border-r border-gray-200 bg-gray-50 overflow-y-auto">
            <div className="p-3">
              <div className="text-xs font-semibold text-gray-500 uppercase mb-2 px-2">
                Categories
              </div>
              <div className="space-y-1">
                {categories.map(category => {
                  const widgets = getWidgetsByCategory(category);
                  const isActive = activeCategory === category;
                  return (
                    <button
                      key={category}
                      onClick={() => handleCategoryClick(category)}
                      className={clsx(
                        "w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center justify-between",
                        isActive
                          ? "bg-qualcomm-blue text-white"
                          : "text-gray-700 hover:bg-gray-200"
                      )}
                    >
                      <span className="font-medium">{category}</span>
                      <span className={clsx(
                        "text-xs px-1.5 py-0.5 rounded",
                        isActive ? "bg-white/20" : "bg-gray-300"
                      )}>
                        {widgets.length}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Widget Grid */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeCategory ? (
              <div>
                <h3 className="text-lg font-semibold text-qualcomm-navy mb-4">
                  {activeCategory} Widgets
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                  {getWidgetsByCategory(activeCategory).map(widget => (
                    <div
                      key={widget.id}
                      draggable={!isLocked}
                      onDragStart={(e) => handleDragStart(e, widget.id, widget.defaultW, widget.defaultH)}
                      onClick={() => handleWidgetClick(widget.id)}
                      className={clsx(
                        "p-4 bg-white border border-gray-200 rounded-lg transition-all group relative",
                        isLocked 
                          ? "opacity-50 cursor-not-allowed" 
                          : "hover:border-qualcomm-blue hover:shadow-md cursor-move"
                      )}
                    >
                      {/* Drag Handle Indicator */}
                      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <GripVertical className="w-4 h-4 text-gray-400" />
                      </div>
                      
                      {/* Widget Preview */}
                      <div className="mb-3 h-32 bg-gray-50 rounded border border-gray-100 overflow-hidden relative">
                        <WidgetPreview 
                          widgetId={widget.id} 
                          component={widget.component}
                          className="h-full"
                        />
                      </div>
                      
                      {/* Widget Info */}
                      <div className="flex items-start gap-2 mb-2">
                        <div className="p-1.5 bg-qualcomm-navy/10 rounded group-hover:bg-qualcomm-blue/20 transition-colors">
                          <LayoutGrid className="w-4 h-4 text-qualcomm-navy group-hover:text-qualcomm-blue" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="font-semibold text-sm text-qualcomm-navy mb-1">
                            {widget.name}
                          </h4>
                          <p className="text-xs text-gray-500 line-clamp-2">
                            {widget.description}
                          </p>
                        </div>
                      </div>
                      <div className="text-xs text-gray-400">
                        {widget.defaultW}×{widget.defaultH} grid
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400">
                <div className="text-center">
                  <LayoutGrid className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p className="text-sm">Select a category to view widgets</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

