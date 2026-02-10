import React from 'react';
import { TrendingUp, TrendingDown, DollarSign, Package, AlertTriangle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface Metric {
  label: string;
  value: string;
  change: number;
  icon: React.ReactNode;
  color: string;
}

export const SupplyChainKPIsWidget: React.FC<WidgetProps> = () => {
  const metrics: Metric[] = [
    {
      label: 'On-Time Delivery',
      value: '94.2%',
      change: 2.3,
      icon: <Package className="w-5 h-5" />,
      color: 'text-green-600'
    },
    {
      label: 'Cost per Unit',
      value: '$12.45',
      change: -1.2,
      icon: <DollarSign className="w-5 h-5" />,
      color: 'text-blue-600'
    },
    {
      label: 'Inventory Turnover',
      value: '8.5x',
      change: 0.8,
      icon: <TrendingUp className="w-5 h-5" />,
      color: 'text-purple-600'
    },
    {
      label: 'Quality Defect Rate',
      value: '0.12%',
      change: -0.05,
      icon: <AlertTriangle className="w-5 h-5" />,
      color: 'text-amber-600'
    }
  ];

  return (
    <div className="h-full grid grid-cols-2 gap-3">
      {metrics.map((metric, idx) => (
        <div key={idx} className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between mb-2">
            <div className={`${metric.color} p-2 bg-gray-50 rounded-lg`}>
              {metric.icon}
            </div>
            <div className={`flex items-center gap-1 text-xs font-medium ${
              metric.change >= 0 ? 'text-green-600' : 'text-red-600'
            }`}>
              {metric.change >= 0 ? (
                <TrendingUp className="w-3 h-3" />
              ) : (
                <TrendingDown className="w-3 h-3" />
              )}
              {Math.abs(metric.change)}%
            </div>
          </div>
          <div className="text-2xl font-bold text-qualcomm-navy mb-1">{metric.value}</div>
          <div className="text-xs text-gray-500">{metric.label}</div>
        </div>
      ))}
    </div>
  );
};

