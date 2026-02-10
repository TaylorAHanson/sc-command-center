import React from 'react';
import { AlertTriangle, TrendingDown, Clock } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

export const AlertsWidget: React.FC<WidgetProps> = () => {
  const alerts = [
    { id: 1, type: 'critical', message: 'TSMC Yield Drop detected on N3 node', time: '10m ago', icon: AlertTriangle },
    { id: 2, type: 'warning', message: 'Logistics delay: flight LAX->SFO cancelled', time: '32m ago', icon: Clock },
    { id: 3, type: 'info', message: 'Inventory levels low for Snapdragon 8 Gen 3', time: '1h ago', icon: TrendingDown },
  ];

  return (
    <div className="h-full flex flex-col gap-2">
      {alerts.map(alert => (
        <div key={alert.id} className={`p-3 rounded-md border flex items-start gap-3 ${
          alert.type === 'critical' ? 'bg-red-50 border-red-100 text-red-800' :
          alert.type === 'warning' ? 'bg-amber-50 border-amber-100 text-amber-800' :
          'bg-blue-50 border-blue-100 text-blue-800'
        }`}>
          <alert.icon className={`w-5 h-5 shrink-0 ${
             alert.type === 'critical' ? 'text-red-500' :
             alert.type === 'warning' ? 'text-amber-500' :
             'text-blue-500'
          }`} />
          <div>
            <div className="text-sm font-semibold">{alert.message}</div>
            <div className="text-xs opacity-70 mt-1">{alert.time}</div>
          </div>
        </div>
      ))}
    </div>
  );
};

