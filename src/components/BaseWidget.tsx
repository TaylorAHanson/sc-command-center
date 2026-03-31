import React from 'react';
import { X, GripHorizontal, Maximize2, Minimize2, Settings } from 'lucide-react';
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
  isFullscreen?: boolean;
  version?: number;
  latestVersion?: number;
  availableVersions?: number[];
  onChangeVersion?: (version: number) => void;

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
  isFullscreen,
  version,
  latestVersion,
  availableVersions,
  onChangeVersion,
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
      <div className={`drag-handle select-none h-8 bg-gray-50 border-b border-gray-100 flex items-center justify-between px-3 ${className?.includes('locked-widget') ? 'cursor-default pointer-events-none' : 'cursor-move'}`}>
        <div className="flex items-center gap-2 text-xs font-semibold text-gray-600 uppercase tracking-wide">
          <GripHorizontal className="w-4 h-4 text-gray-400" />
          {title}
        </div>
        <div className="flex items-center gap-1">
          {availableVersions && availableVersions.length > 0 && version !== undefined && (
            <div className="relative mr-1 flex items-center bg-gray-100 rounded px-1" title={latestVersion && latestVersion > version ? `Update available: v${latestVersion}` : "Widget Version"}>
              <select
                value={version}
                onChange={(e) => {
                  e.stopPropagation();
                  onChangeVersion?.(Number(e.target.value));
                }}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
                disabled={!onChangeVersion}
                className={`text-[10px] font-medium bg-transparent border-none text-gray-500 py-0.5 pl-1 pr-4 focus:ring-0 cursor-pointer ${!onChangeVersion ? 'appearance-none pr-1' : ''}`}
                style={!onChangeVersion ? { WebkitAppearance: 'none', MozAppearance: 'none' } : {}}
              >
                {availableVersions.map((v: number) => (
                  <option key={v} value={v}>v{v}</option>
                ))}
              </select>
              {latestVersion && latestVersion > version && (
                <span className="absolute top-1 right-1 flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-qualcomm-blue opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-qualcomm-blue"></span>
                </span>
              )}
            </div>
          )}
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
              title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            >
              {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
          )}
          {onRemove && (
            <button
              onClick={(e) => {
                e.stopPropagation(); // prevent drag start
                if (isFullscreen && onFullscreen) {
                  onFullscreen();
                } else {
                  onRemove();
                }
              }}
              className="text-gray-400 hover:text-red-500 transition-colors"
              title={isFullscreen ? "Close" : "Remove Widget"}
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      <div 
        className="flex-1 p-4 overflow-auto relative min-h-0 min-w-0"
        onDoubleClick={(e) => {
          if (e.target === e.currentTarget) {
            window.getSelection()?.removeAllRanges();
          }
        }}
      >
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
