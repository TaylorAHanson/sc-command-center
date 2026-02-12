import React from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const IframeWidget: React.FC<WidgetProps> = ({ data }) => {
    const url = data?.url || 'https://forecast.weather.gov/MapClick.php?lat=32.7157&lon=-117.1611';
    const title = data?.title || 'Embedded Content';

    return (
        <div className="w-full h-full flex flex-col bg-white">
            <div className="flex-1 relative">
                <iframe
                    src={url}
                    title={title}
                    className="absolute inset-0 w-full h-full border-0"
                    sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
                    referrerPolicy="no-referrer"
                />
                {/* Interaction overlay for dragging (only covers when dragging, handled by parent usually but good to keep in mind) */}
            </div>
        </div>
    );
};
