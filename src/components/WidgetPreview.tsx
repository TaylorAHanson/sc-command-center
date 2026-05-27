import React, { useState } from 'react';
import type { WidgetDefinition, WidgetProps } from '../widgetRegistry';
import { Camera, RefreshCw } from 'lucide-react';
import { captureWidgetThumbnail } from './ThumbnailCapture';

interface WidgetPreviewProps {
  widgetId: string;
  component: React.ComponentType<WidgetProps>;
  className?: string;
  defaultProps?: any;
  snapshot?: string;
  widget?: WidgetDefinition;
  // Owners can trigger an on-demand capture. Hidden otherwise.
  canRefresh?: boolean;
}

// Lightweight, non-rendering placeholder. We intentionally do NOT mount the
// widget component here, so the library tray stays cheap even with hundreds of
// cards. A snapshot is only generated when the owner explicitly requests one
// (or via the admin bulk backfill), then cached server-side.
const ThumbnailPlaceholder: React.FC<{ name?: string; subtitle?: string }> = ({ name, subtitle }) => {
  const initials = (name || '?')
    .split(/\s+/)
    .map(s => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
  return (
    <div className="flex flex-col items-center justify-center h-full w-full bg-gradient-to-br from-gray-50 to-gray-100 text-gray-400">
      <div className="w-12 h-12 mb-2 rounded-lg bg-white border border-gray-200 flex items-center justify-center shadow-sm">
        <span className="text-sm font-bold tracking-wider text-gray-400">{initials}</span>
      </div>
      <span className="text-[10px] uppercase tracking-wider font-semibold opacity-60">
        {subtitle || 'No Preview Yet'}
      </span>
    </div>
  );
};

export const WidgetPreview: React.FC<WidgetPreviewProps> = ({
  widgetId,
  className,
  snapshot: initialSnapshot,
  component,
  widget,
  canRefresh,
}) => {
  const [snapshot, setSnapshot] = useState<string | undefined>(initialSnapshot);
  const [isCapturing, setIsCapturing] = useState(false);

  React.useEffect(() => { setSnapshot(initialSnapshot); }, [initialSnapshot]);

  const handleCapture = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (isCapturing) return;
    setIsCapturing(true);
    try {
      const dataUrl = await captureWidgetThumbnail({
        component,
        defaultProps: widget?.defaultProps,
        widgetId,
        widgetName: widget?.name,
      });
      if (dataUrl) {
        setSnapshot(dataUrl);
        await fetch(`/api/widgets/custom/${widgetId}/snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ snapshot: dataUrl }),
        }).catch(() => { });
      }
    } catch (err) {
      console.warn('Thumbnail capture failed', err);
    } finally {
      setIsCapturing(false);
    }
  };

  return (
    <div className={`relative overflow-hidden bg-white border border-gray-200 rounded ${className || ''} h-full group/preview`}>
      {snapshot ? (
        <img
          src={snapshot}
          alt={`Preview of ${widget?.name || widgetId}`}
          className="absolute inset-0 w-full h-full object-contain"
        />
      ) : (
        <ThumbnailPlaceholder
          name={widget?.name}
          subtitle={isCapturing ? 'Generating…' : undefined}
        />
      )}
      {canRefresh && (
        <button
          type="button"
          onClick={handleCapture}
          disabled={isCapturing}
          className="absolute bottom-1 right-1 bg-white/95 border border-gray-200 rounded p-1 text-gray-500 hover:text-qualcomm-blue opacity-0 group-hover/preview:opacity-100 transition-opacity shadow-sm disabled:opacity-100 disabled:text-qualcomm-blue"
          title={snapshot ? 'Refresh thumbnail' : 'Generate thumbnail'}
        >
          {isCapturing ? (
            <RefreshCw className="w-3 h-3 animate-spin" />
          ) : snapshot ? (
            <RefreshCw className="w-3 h-3" />
          ) : (
            <Camera className="w-3 h-3" />
          )}
        </button>
      )}
    </div>
  );
};
