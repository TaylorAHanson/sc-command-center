import React from 'react';
import { X, GripHorizontal, Maximize2, Settings } from 'lucide-react';
import { useActionLogger } from '../hooks/useActionLogger';
import { ActionConfirmationModal } from './ActionConfirmationModal';
import { ActionProvider } from '../contexts/ActionContext';

interface BaseWidgetProps {
  id: string;
  title: string;
  children: React.ReactNode;
  onRemove?: () => void;
  onFullscreen?: () => void;
  onConfigure?: () => void;

  customActions?: React.ReactNode;
  className?: string;
  // react-grid-layout injects these props
  style?: React.CSSProperties;
  className_rgl?: string;
  onMouseDown?: React.MouseEventHandler;
  onMouseUp?: React.MouseEventHandler;
  onTouchEnd?: React.TouchEventHandler;
  [key: string]: any;
}

// Forward ref is required by react-grid-layout
export const BaseWidget = React.forwardRef<HTMLDivElement, BaseWidgetProps>(({
  id,
  title,
  children,
  onRemove,
  onFullscreen,
  onConfigure,
  customActions,
  className,
  style,
  className_rgl,
  onMouseDown,
  onMouseUp,
  onTouchEnd,
  ...props
}, ref) => {
  const { isConfirming, actionName, initiateAction, confirmAction, cancelAction } = useActionLogger({
    widgetId: id,
    widgetName: title
  });

  return (
    <div
      ref={ref}
      style={style}
      className={`${className} ${className_rgl} bg-white text-qualcomm-navy shadow-sm rounded-lg border border-gray-200 flex flex-col overflow-hidden`}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onTouchEnd={onTouchEnd}
      {...props}
    >
      <div className={`drag-handle h-8 bg-gray-50 border-b border-gray-100 flex items-center justify-between px-3 ${className?.includes('locked-widget') ? 'cursor-default pointer-events-none' : 'cursor-move'}`}>
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-600 uppercase tracking-wide">
          <GripHorizontal className="w-4 h-4 text-gray-400" />
          {title}
        </div>
        <div className="flex items-center gap-1">
          {customActions && (
            <div className="flex items-center gap-1 mr-1 border-r border-gray-200 pr-1">
              {customActions}
            </div>
          )}
          {onConfigure && (
            <button
              onClick={(e) => {
                e.stopPropagation(); // prevent drag start
                onConfigure();
              }}
              className="text-gray-400 hover:text-qualcomm-blue transition-colors"
              title="Configure Widget"
            >
              <Settings className="w-4 h-4" />
            </button>
          )}
          {onFullscreen && (
            <button
              onClick={(e) => {
                e.stopPropagation(); // prevent drag start
                onFullscreen();
              }}
              className="text-gray-400 hover:text-qualcomm-blue transition-colors"
              title="Fullscreen"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          )}
          {onRemove && (
            <button
              onClick={(e) => {
                e.stopPropagation(); // prevent drag start
                onRemove();
              }}
              className="text-gray-400 hover:text-red-500 transition-colors"
              title="Remove Widget"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      <div className="flex-1 p-4 overflow-auto relative">
        <ActionProvider value={initiateAction}>
          {children}
        </ActionProvider>
      </div>

      <ActionConfirmationModal
        isOpen={isConfirming}
        onClose={cancelAction}
        onConfirm={confirmAction}
        actionName={actionName}
        widgetName={title}
      />
    </div>
  );
});

BaseWidget.displayName = "BaseWidget";
