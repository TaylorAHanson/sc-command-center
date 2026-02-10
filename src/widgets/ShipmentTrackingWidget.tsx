import React, { useState } from 'react';
import { MapPin, Package, Clock, CheckCircle, AlertCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface Shipment {
  id: string;
  origin: string;
  destination: string;
  status: 'in-transit' | 'delayed' | 'delivered' | 'at-risk';
  eta: string;
  progress: number;
}

export const ShipmentTrackingWidget: React.FC<WidgetProps> = () => {
  const [shipments] = useState<Shipment[]>([
    { id: 'SH-001', origin: 'Taipei, TW', destination: 'San Diego, US', status: 'in-transit', eta: '2 days', progress: 65 },
    { id: 'SH-002', origin: 'Seoul, KR', destination: 'Austin, US', status: 'delayed', eta: '5 days', progress: 40 },
    { id: 'SH-003', origin: 'Singapore', destination: 'Munich, DE', status: 'in-transit', eta: '3 days', progress: 80 },
    { id: 'SH-004', origin: 'Shanghai, CN', destination: 'San Jose, US', status: 'at-risk', eta: '7 days', progress: 25 },
  ]);

  const getStatusIcon = (status: Shipment['status']) => {
    switch (status) {
      case 'delivered': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'delayed': return <AlertCircle className="w-4 h-4 text-red-500" />;
      case 'at-risk': return <AlertCircle className="w-4 h-4 text-amber-500" />;
      default: return <Package className="w-4 h-4 text-blue-500" />;
    }
  };

  const getStatusColor = (status: Shipment['status']) => {
    switch (status) {
      case 'delivered': return 'bg-green-100 text-green-800';
      case 'delayed': return 'bg-red-100 text-red-800';
      case 'at-risk': return 'bg-amber-100 text-amber-800';
      default: return 'bg-blue-100 text-blue-800';
    }
  };

  return (
    <div className="h-full flex flex-col gap-3 overflow-y-auto">
      {shipments.map(shipment => (
        <div key={shipment.id} className="bg-white border border-gray-200 rounded-lg p-3 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {getStatusIcon(shipment.status)}
              <span className="font-semibold text-sm text-qualcomm-navy">{shipment.id}</span>
            </div>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${getStatusColor(shipment.status)}`}>
              {shipment.status.replace('-', ' ')}
            </span>
          </div>
          
          <div className="flex items-center gap-2 text-xs text-gray-600 mb-2">
            <MapPin className="w-3 h-3" />
            <span>{shipment.origin}</span>
            <span>→</span>
            <span>{shipment.destination}</span>
          </div>
          
          <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <Clock className="w-3 h-3" />
            <span>ETA: {shipment.eta}</span>
          </div>
          
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div 
              className={`h-2 rounded-full transition-all ${
                shipment.status === 'delayed' ? 'bg-red-500' :
                shipment.status === 'at-risk' ? 'bg-amber-500' :
                'bg-qualcomm-blue'
              }`}
              style={{ width: `${shipment.progress}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

