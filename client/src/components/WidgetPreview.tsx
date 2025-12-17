import React, { type ErrorInfo } from 'react';
import type { WidgetProps } from '../widgetRegistry';

interface WidgetPreviewProps {
  widgetId: string;
  component: React.ComponentType<WidgetProps>;
  className?: string;
}

class WidgetPreviewErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.warn('Widget preview error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-full text-gray-400 text-xs">
          Preview unavailable
        </div>
      );
    }
    return this.props.children;
  }
}

export const WidgetPreview: React.FC<WidgetPreviewProps> = ({ widgetId, component: Component, className }) => {
  return (
    <WidgetPreviewErrorBoundary>
      <div className={`relative overflow-hidden bg-white border border-gray-200 rounded ${className || ''} h-full`}>
        <div className="absolute inset-0 pointer-events-none" style={{ 
          transform: 'scale(0.75)', 
          transformOrigin: 'top left',
          width: '133.33%',
          height: '133.33%'
        }}>
          <div className="h-full w-full">
            <Component id={`preview-${widgetId}`} data={{}} />
          </div>
        </div>
      </div>
    </WidgetPreviewErrorBoundary>
  );
};

