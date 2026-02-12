import React from 'react';
import { AlertsWidget } from './widgets/AlertsWidget';
import { InventoryWidget } from './widgets/InventoryWidget';
import { GanttWidget } from './widgets/GanttWidget';
import { GenieWidget } from './widgets/GenieWidget';
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
import { ExecuteNotebookWidget } from './widgets/ExecuteNotebookWidget';
import { DatabricksJobRunnerWidget } from './widgets/DatabricksJobRunnerWidget';
import { LineChartWidget } from './widgets/LineChartWidget';
import { N8NTriggerWidget } from './widgets/N8NTriggerWidget';
import { TableauWidget } from './widgets/TableauWidget';
import { IframeWidget } from './widgets/IframeWidget';

export interface WidgetProps {
  id: string;
  data?: any;
}

export interface ConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'textarea';
  required?: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>; // For select fields
  defaultValue?: any;
  helpText?: string;
}

export interface WidgetDefinition {
  id: string;
  name: string;
  component: React.ComponentType<WidgetProps>;
  defaultW: number;
  defaultH: number;
  description?: string;
  category?: string;
  domain?: string;
  isCertified?: boolean;
  configurationMode?: 'none' | 'config_allowed' | 'config_required';
  configSchema?: ConfigField[]; // Schema for structured configuration form
  accessControl?: {
    mockHasAccess?: boolean;
  };
  isExecutable?: boolean;
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
  category: 'Monitoring',
  domain: 'Supply Chain',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'inventory',
  name: 'Inventory Levels',
  component: InventoryWidget,
  defaultW: 6,
  defaultH: 6,
  description: 'Line graph of inventory across regions.',
  category: 'Analytics',
  domain: 'Logistics',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'gantt',
  name: 'Production Schedule',
  component: GanttWidget,
  defaultW: 8,
  defaultH: 6,
  description: 'Gantt chart of production phases.',
  category: 'Planning',
  domain: 'Manufacturing',
  isCertified: true,
  accessControl: { mockHasAccess: true }, // Mock restricted access
  configurationMode: 'none'
});

registerWidget({
  id: 'genie',
  name: 'Supply Chain Genie',
  component: (props) => React.createElement(GenieWidget, {
    ...props,
    data: {
      ...props.data,
      space_id: '01f106b447c7129b8f1dc466a177d9d7',
      name: 'Supply Chain Genie',
    }
  }),
  defaultW: 3,
  defaultH: 6,
  description: 'AI-powered supply chain assistant.',
  category: 'AI & Automation',
  domain: 'General',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_allowed'
});


registerWidget({
  id: 'supplier_form',
  name: 'Supplier Survey',
  component: SupplierFormWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Feedback form for suppliers.',
  category: 'Forms',
  domain: 'Procurement',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'external',
  name: 'Rapid Response',
  component: ExternalWidget,
  defaultW: 3,
  defaultH: 3,
  description: 'Link to external planning tools.',
  category: 'External',
  domain: 'Planning',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'supplier_scorecard',
  name: 'Supplier Scorecard',
  component: SupplierScorecardWidget,
  defaultW: 5,
  defaultH: 5,
  description: 'Performance scores for key suppliers.',
  category: 'Analytics',
  domain: 'Procurement',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'risk_heatmap',
  name: 'Risk Heatmap',
  component: RiskHeatmapWidget,
  defaultW: 6,
  defaultH: 5,
  description: 'Quarterly risk assessment across categories.',
  category: 'Monitoring',
  domain: 'Risk Management',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'shipment_tracking',
  name: 'Shipment Tracking',
  component: ShipmentTrackingWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Real-time tracking of global shipments.',
  category: 'Logistics',
  domain: 'Logistics',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'warehouse_capacity',
  name: 'Warehouse Capacity',
  component: WarehouseCapacityWidget,
  defaultW: 5,
  defaultH: 5,
  description: 'Capacity utilization across warehouse locations.',
  category: 'Analytics',
  domain: 'Logistics',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'demand_forecast',
  name: 'Demand Forecast',
  component: DemandForecastWidget,
  defaultW: 6,
  defaultH: 5,
  description: '12-month demand forecast vs actuals.',
  category: 'Planning',
  domain: 'Planning',
  isCertified: true,
  accessControl: { mockHasAccess: false }, // Mock restricted
  configurationMode: 'none'
});

registerWidget({
  id: 'supply_chain_kpis',
  name: 'Supply Chain KPIs',
  component: SupplyChainKPIsWidget,
  defaultW: 4,
  defaultH: 4,
  description: 'Key performance indicators dashboard.',
  category: 'Monitoring',
  domain: 'Supply Chain',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'cost_breakdown',
  name: 'Cost Breakdown',
  component: CostBreakdownWidget,
  defaultW: 4,
  defaultH: 5,
  description: 'Pie chart of supply chain cost distribution.',
  category: 'Analytics',
  domain: 'Finance',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'production_lines',
  name: 'Production Lines',
  component: ProductionLinesWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Real-time status of manufacturing lines.',
  category: 'Monitoring',
  domain: 'Manufacturing',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'none'
});

registerWidget({
  id: 'data_table',
  name: 'NYC Taxi Data',
  component: (props) => React.createElement(DataTableWidget, {
    ...props,
    data: {
      ...props.data,
      queryId: 'test_query',
    }
  }),
  defaultW: 8,
  defaultH: 8,
  description: 'Searchable, sortable table of data.',
  category: 'Analytics',
  domain: 'General',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_allowed',
  configSchema: [
    { key: 'queryId', label: 'SQL Query ID', type: 'text', required: true, defaultValue: 'test_query', placeholder: 'test_query', helpText: 'The ID of the SQL query to execute' }
  ]
});

registerWidget({
  id: 'execute_notebook',
  name: 'Execute Notebook',
  component: ExecuteNotebookWidget,
  defaultW: 5,
  defaultH: 8,
  description: 'Select and run Databricks notebooks, view execution results.',
  category: 'Actions',
  domain: 'IT',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_required',
  isExecutable: true
});

registerWidget({
  id: 'job_runner',
  name: 'Databricks Job Runner',
  component: DatabricksJobRunnerWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Run and monitor Databricks jobs.',
  category: 'Actions',
  domain: 'IT',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_allowed',
  isExecutable: true,
  configSchema: [
    { key: 'job_id', label: 'Job ID', type: 'number', required: true, defaultValue: 123456, placeholder: '123456', helpText: 'The Databricks job ID to run' },
    { key: 'job_name', label: 'Custom Name (Optional)', type: 'text', defaultValue: 'My Data Pipeline', placeholder: 'My Data Pipeline', helpText: 'Override the job name displayed in the widget' }
  ]
});

registerWidget({
  id: 'line_chart',
  name: 'Test Data Chart',
  component: (props) => React.createElement(LineChartWidget, {
    ...props,
    data: {
      queryId: 'test_query',
      xColumn: 'pickup_zip',
      yColumn: 'trip_count',
      yAxisTitle: 'Trip Count',
      chartType: 'line',
      ...props.data
    }
  }),
  defaultW: 6,
  defaultH: 6,
  description: 'Dynamic chart driven by SQL queries.',
  category: 'Analytics',
  domain: 'General',
  isCertified: true,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_allowed',
  configSchema: [
    { key: 'title', label: 'Title', type: 'text', placeholder: 'My Chart', helpText: 'Title of the chart' },
    { key: 'queryId', label: 'SQL Query ID', type: 'text', required: true, defaultValue: 'test_query', placeholder: 'test_query', helpText: 'The ID of the SQL query to execute' },
    { key: 'xColumn', label: 'X-Axis Column', type: 'text', required: true, defaultValue: 'pickup_zip', placeholder: 'pickup_zip', helpText: 'Column name for X-axis' },
    { key: 'yColumn', label: 'Y-Axis Column', type: 'text', required: true, defaultValue: 'trip_count', placeholder: 'trip_count', helpText: 'Column name for Y-axis' },
    { key: 'yAxisTitle', label: 'Y-Axis Title', type: 'text', defaultValue: 'Trip Count', placeholder: 'Trip Count', helpText: 'Label for the Y-axis' },
    {
      key: 'chartType', label: 'Chart Type', type: 'select', required: true, defaultValue: 'line', options: [
        { value: 'line', label: 'Line' },
        { value: 'bar', label: 'Bar' },
        { value: 'area', label: 'Area' }
      ]
    }
  ]
});

// N8N Trigger Widget
registerWidget({
  id: 'n8n_trigger',
  name: 'Run N8N Workflow',
  component: N8NTriggerWidget,
  defaultW: 4,
  defaultH: 6,
  description: 'Trigger N8N workflows with custom parameters.',
  category: 'Automation',
  domain: 'General',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_required',
  isExecutable: true,
  configSchema: [
    { key: 'workflow_id', label: 'Workflow ID', type: 'text', required: true, defaultValue: 'workflow-123', placeholder: 'workflow-123', helpText: 'The ID of the N8N workflow to trigger' }
  ]
});

// Tableau Dashboard Widget
registerWidget({
  id: 'tableau_dashboard',
  name: 'Tableau Dashboard',
  component: TableauWidget,
  defaultW: 8,
  defaultH: 8,
  description: 'Embed interactive Tableau Cloud dashboards.',
  category: 'Analytics',
  domain: 'General',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_required',
  configSchema: [
    { key: 'dashboard_id', label: 'Dashboard ID', type: 'text', required: true, defaultValue: 'dashboard-123', placeholder: 'dashboard-123', helpText: 'The ID of the Tableau dashboard to embed' }
  ]
});

// Iframe Widget
registerWidget({
  id: 'iframe',
  name: 'Embedded Page',
  component: IframeWidget,
  defaultW: 6,
  defaultH: 6,
  description: 'Embed external web pages.',
  category: 'External',
  domain: 'General',
  isCertified: false,
  accessControl: { mockHasAccess: true },
  configurationMode: 'config_allowed',
  configSchema: [
    { key: 'url', label: 'URL', type: 'text', required: true, defaultValue: 'https://forecast.weather.gov/MapClick.php?lat=32.7157&lon=-117.1611', placeholder: 'https://example.com', helpText: 'The URL to embed' },
    { key: 'title', label: 'Title', type: 'text', placeholder: 'My Widget', helpText: 'Hidden title for accessibility' }
  ]
});

export const getAvailableWidgets = () => Object.values(widgetRegistry);

export const getWidgetCategories = () => {
  const categories = new Set<string>();
  Object.values(widgetRegistry).forEach(w => {
    categories.add(w.category || 'Uncategorized');
  });
  return Array.from(categories).sort();
};

export const getWidgetDomains = () => {
  const domains = new Set<string>();
  Object.values(widgetRegistry).forEach(w => {
    if (w.domain) domains.add(w.domain);
  });
  return Array.from(domains).sort();
};

export const getWidgetsByCategory = (category: string) => {
  return Object.values(widgetRegistry).filter(w => (w.category || 'Uncategorized') === category);
};
