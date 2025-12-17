import React from 'react';
import { AlertsWidget } from './widgets/AlertsWidget';
import { InventoryWidget } from './widgets/InventoryWidget';
import { GanttWidget } from './widgets/GanttWidget';
import { GenieWidget } from './widgets/GenieWidget';
import { ActionWidget } from './widgets/ActionWidget';
import { SupplierFormWidget } from './widgets/SupplierFormWidget';
import { ExternalWidget } from './widgets/ExternalWidget';
import { SupplierScorecardWidget } from './widgets/SupplierScorecardWidget';
import { RiskHeatmapWidget } from './widgets/RiskHeatmapWidget';
import { ShipmentTrackingWidget } from './widgets/ShipmentTrackingWidget';
import { WarehouseCapacityWidget } from './widgets/WarehouseCapacityWidget';
import { DemandForecastWidget } from './widgets/DemandForecastWidget';
import { SupplyChainKPIsWidget } from './widgets/SupplyChainKPIsWidget';
import { CostBreakdownWidget } from './widgets/CostBreakdownWidget';
import { ProductionLinesWidget } from './widgets/ProductionLinesWidget';
import { DataTableWidget } from './widgets/DataTableWidget';

export interface WidgetProps {
  id: string;
  data?: any;
}

export interface WidgetDefinition {
  id: string;
  name: string;
  component: React.ComponentType<WidgetProps>;
  defaultW: number;
  defaultH: number;
  description?: string;
  category?: string; // New: category for organizing widgets
}

export const widgetRegistry: Record<string, WidgetDefinition> = {};

export const registerWidget = (def: WidgetDefinition) => {
  widgetRegistry[def.id] = def;
};

// Register Widgets
registerWidget({
  id: 'alerts',
  name: 'Problem Alerts',
  component: AlertsWidget,
  defaultW: 4,
  defaultH: 4,
  description: 'Real-time supply chain alerts and risks.',
  category: 'Monitoring'
});

registerWidget({
  id: 'inventory',
  name: 'Inventory Levels',
  component: InventoryWidget,
  defaultW: 6,
  defaultH: 6,
  description: 'Line graph of inventory across regions.',
  category: 'Analytics'
});

registerWidget({
  id: 'gantt',
  name: 'Production Schedule',
  component: GanttWidget,
  defaultW: 8,
  defaultH: 6,
  description: 'Gantt chart of production phases.',
  category: 'Planning'
});

registerWidget({
  id: 'genie',
  name: 'Ask Genie',
  component: GenieWidget,
  defaultW: 3,
  defaultH: 6,
  description: 'AI-powered supply chain assistant.',
  category: 'AI & Automation'
});

registerWidget({
  id: 'action',
  name: 'Job Trigger',
  component: ActionWidget,
  defaultW: 3,
  defaultH: 4,
  description: 'Trigger Databricks synchronization jobs.',
  category: 'Actions'
});

registerWidget({
  id: 'supplier_form',
  name: 'Supplier Survey',
  component: SupplierFormWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Feedback form for suppliers.',
  category: 'Forms'
});

registerWidget({
  id: 'external',
  name: 'Rapid Response',
  component: ExternalWidget,
  defaultW: 3,
  defaultH: 3,
  description: 'Link to external planning tools.',
  category: 'External'
});

registerWidget({
  id: 'supplier_scorecard',
  name: 'Supplier Scorecard',
  component: SupplierScorecardWidget,
  defaultW: 5,
  defaultH: 5,
  description: 'Performance scores for key suppliers.',
  category: 'Analytics'
});

registerWidget({
  id: 'risk_heatmap',
  name: 'Risk Heatmap',
  component: RiskHeatmapWidget,
  defaultW: 6,
  defaultH: 5,
  description: 'Quarterly risk assessment across categories.',
  category: 'Monitoring'
});

registerWidget({
  id: 'shipment_tracking',
  name: 'Shipment Tracking',
  component: ShipmentTrackingWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Real-time tracking of global shipments.',
  category: 'Logistics'
});

registerWidget({
  id: 'warehouse_capacity',
  name: 'Warehouse Capacity',
  component: WarehouseCapacityWidget,
  defaultW: 5,
  defaultH: 5,
  description: 'Capacity utilization across warehouse locations.',
  category: 'Analytics'
});

registerWidget({
  id: 'demand_forecast',
  name: 'Demand Forecast',
  component: DemandForecastWidget,
  defaultW: 6,
  defaultH: 5,
  description: '12-month demand forecast vs actuals.',
  category: 'Planning'
});

registerWidget({
  id: 'supply_chain_kpis',
  name: 'Supply Chain KPIs',
  component: SupplyChainKPIsWidget,
  defaultW: 4,
  defaultH: 4,
  description: 'Key performance indicators dashboard.',
  category: 'Monitoring'
});

registerWidget({
  id: 'cost_breakdown',
  name: 'Cost Breakdown',
  component: CostBreakdownWidget,
  defaultW: 4,
  defaultH: 5,
  description: 'Pie chart of supply chain cost distribution.',
  category: 'Analytics'
});

registerWidget({
  id: 'production_lines',
  name: 'Production Lines',
  component: ProductionLinesWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Real-time status of manufacturing lines.',
  category: 'Monitoring'
});

registerWidget({
  id: 'data_table',
  name: 'Supplier Performance',
  component: DataTableWidget,
  defaultW: 8,
  defaultH: 8,
  description: 'Searchable, sortable table of supplier performance data.',
  category: 'Analytics'
});

export const getAvailableWidgets = () => Object.values(widgetRegistry);

export const getWidgetCategories = () => {
  const categories = new Set<string>();
  Object.values(widgetRegistry).forEach(w => {
    categories.add(w.category || 'Uncategorized');
  });
  return Array.from(categories).sort();
};

export const getWidgetsByCategory = (category: string) => {
  return Object.values(widgetRegistry).filter(w => (w.category || 'Uncategorized') === category);
};
