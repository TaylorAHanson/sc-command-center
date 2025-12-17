import React, { useState } from 'react';
import { Activity, CheckCircle2, Clock, XCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface ProductionLine {
  id: string;
  name: string;
  status: 'running' | 'idle' | 'maintenance' | 'error';
  utilization: number;
  output: number;
  target: number;
}

export const ProductionLinesWidget: React.FC<WidgetProps> = () => {
  const [lines] = useState<ProductionLine[]>([
    { id: 'L1', name: 'Line 1 - Snapdragon 8 Gen 3', status: 'running', utilization: 92, output: 1840, target: 2000 },
    { id: 'L2', name: 'Line 2 - Snapdragon 8 Gen 2', status: 'running', utilization: 87, output: 1740, target: 2000 },
    { id: 'L3', name: 'Line 3 - Snapdragon 7+ Gen 3', status: 'maintenance', utilization: 0, output: 0, target: 1500 },
    { id: 'L4', name: 'Line 4 - Snapdragon X Elite', status: 'running', utilization: 78, output: 1170, target: 1500 },
  ]);

  const getStatusConfig = (status: ProductionLine['status']) => {
    switch (status) {
      case 'running':
        return { icon: <CheckCircle2 className="w-4 h-4" />, color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200' };
      case 'idle':
        return { icon: <Clock className="w-4 h-4" />, color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' };
      case 'maintenance':
        return { icon: <Activity className="w-4 h-4" />, color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200' };
      case 'error':
        return { icon: <XCircle className="w-4 h-4" />, color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200' };
    }
  };

  return (
    <div className="h-full flex flex-col gap-3 overflow-y-auto">
      {lines.map(line => {
        const statusConfig = getStatusConfig(line.status);
        const efficiency = line.target > 0 ? (line.output / line.target) * 100 : 0;
        
        return (
          <div key={line.id} className={`bg-white border ${statusConfig.border} rounded-lg p-4 hover:shadow-md transition-shadow`}>
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className={`${statusConfig.color} ${statusConfig.bg} p-1.5 rounded`}>
                  {statusConfig.icon}
                </div>
                <div>
                  <div className="font-semibold text-sm text-qualcomm-navy">{line.name}</div>
                  <div className="text-xs text-gray-500">{line.id}</div>
                </div>
              </div>
              <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusConfig.bg} ${statusConfig.color}`}>
                {line.status}
              </span>
            </div>
            
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <div className="text-xs text-gray-500 mb-1">Utilization</div>
                <div className="text-lg font-bold text-qualcomm-navy">{line.utilization}%</div>
              </div>
              <div>
                <div className="text-xs text-gray-500 mb-1">Output</div>
                <div className="text-lg font-bold text-qualcomm-navy">{line.output.toLocaleString()}</div>
              </div>
            </div>
            
            <div>
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Efficiency: {efficiency.toFixed(1)}%</span>
                <span>Target: {line.target.toLocaleString()}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div 
                  className={`h-2 rounded-full transition-all ${
                    efficiency >= 90 ? 'bg-green-500' :
                    efficiency >= 75 ? 'bg-blue-500' :
                    'bg-amber-500'
                  }`}
                  style={{ width: `${Math.min(efficiency, 100)}%` }}
                />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

