import React from 'react';
import type { WidgetProps } from '../widgetRegistry';
import { LayoutTemplate } from 'lucide-react';

interface WidgetPreviewProps {
  widgetId: string;
  component: React.ComponentType<WidgetProps>;
  className?: string;
  defaultProps?: any;
  snapshot?: string;
}

export const WidgetPreview: React.FC<WidgetPreviewProps> = ({ widgetId, className, snapshot }) => {
  if (snapshot) {
    return (
      <div className={`relative overflow-hidden bg-white border border-gray-200 rounded ${className || ''} h-full flex items-center justify-center`}>
        <img src={snapshot} alt={`Preview of ${widgetId}`} className="max-w-full max-h-full object-contain" />
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden bg-gray-50 border border-gray-200 rounded ${className || ''} h-full flex flex-col items-center justify-center text-gray-400`}>
      <LayoutTemplate className="w-8 h-8 mb-2 opacity-30" />
      <span className="text-[10px] uppercase tracking-wider font-semibold opacity-50">No Preview</span>
    </div>
  );
};

