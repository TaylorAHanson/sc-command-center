import React from 'react';
import { ExternalLink } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

export const ExternalWidget: React.FC<WidgetProps> = () => {
  return (
    <div className="h-full flex flex-col items-center justify-center bg-gray-900 text-white rounded-lg p-6 relative overflow-hidden group">
      <div className="absolute inset-0 bg-gradient-to-br from-qualcomm-navy to-black opacity-80" />
      <div className="relative z-10 text-center">
         <h3 className="text-xl font-bold mb-2">Rapid Response</h3>
         <p className="text-gray-300 mb-6 text-sm">Access the Kinaxis Rapid Response portal for deep supply chain planning.</p>
         <a 
           href="#" 
           target="_blank" 
           className="inline-flex items-center gap-2 px-5 py-2 bg-white text-qualcomm-navy rounded-full font-semibold hover:bg-gray-100 transition-colors"
         >
           Launch Portal <ExternalLink className="w-4 h-4" />
         </a>
      </div>
    </div>
  );
};

