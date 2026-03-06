import React from 'react';
import { useScript } from './hooks/useScript';

// Define types broadly since we only need component matching
export interface WidgetProps {
  id: string;
  data?: any;
  executeAction?: (actionName: string, callback: () => void) => void;
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
  defaultProps?: Record<string, any>; // Default props passed to the component as `data` when placed on a dashboard
  createdBy?: string; // Username of whoever published this widget (custom widgets only)
}

export const widgetRegistry: Record<string, WidgetDefinition> = {};
let registryVersion = 0;
let isRegistryLoading = false;
const listeners = new Set<() => void>();

export const getRegistryLoading = () => isRegistryLoading;

export const registerWidget = (def: WidgetDefinition) => {
  widgetRegistry[def.id] = def;
  registryVersion++;
  listeners.forEach(l => l());
};

export const useWidgetRegistry = () => {
  const [state, setState] = React.useState({ version: registryVersion, loading: isRegistryLoading });
  React.useEffect(() => {
    const listener = () => setState({ version: registryVersion, loading: isRegistryLoading });
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return state;
};

export const loadCustomWidgets = async () => {
  if (isRegistryLoading) return;
  isRegistryLoading = true;
  listeners.forEach(l => l());

  try {
    const res = await fetch('/api/widgets/custom');
    if (!res.ok) return;
    const data = await res.json();
    data.widgets.forEach((w: any) => {
      try {
        let Component;
        if (w.tsx_code) {
          // @ts-ignore
          if (!window.Babel) return;
          // @ts-ignore
          const transpiled = window.Babel.transform(w.tsx_code, {
            filename: `${w.id}.tsx`,
            presets: ['react', 'typescript']
          }).code;
          // Convert `export default function Foo` → `var __widget = function Foo ...; return __widget`
          let executableCode = transpiled
            .replace(/export\s+default\s+function\s*(\w*)/, 'var __widget = function $1')
            .replace(/export\s+default\s+class\s*(\w*)/, 'var __widget = class $1')
            .replace(/export\s+default\s+/, 'var __widget = ');
          executableCode += '\nreturn __widget;';
          // eslint-disable-next-line no-new-func
          const createComponent = new (Function as any)('React', 'useScript', executableCode);
          Component = createComponent(React, useScript);
        } else {
          console.warn(`Widget ${w.id} has no tsx_code to evaluate.`);
          return;
        }

        registerWidget({
          id: w.id,
          name: w.name,
          description: w.description,
          category: w.category,
          domain: w.domain,
          defaultW: w.default_w || 6,
          defaultH: w.default_h || 6,
          component: Component,
          configurationMode: w.configuration_mode || 'none',
          configSchema: w.config_schema ? JSON.parse(w.config_schema) : undefined,
          defaultProps: w.data_source ? {
            dataSource: w.data_source,
            dataSourceType: w.data_source_type || 'none'
          } : undefined,
          isCertified: w.is_certified === 1,
          isExecutable: w.is_executable === 1,
          createdBy: w.created_by || undefined,
          accessControl: { mockHasAccess: true }
        });
      } catch (err) {
        console.error(`Failed to load widget ${w.id}:`, err);
      }
    });
  } catch (err) {
    console.error("Failed to load widgets:", err);
  } finally {
    isRegistryLoading = false;
    listeners.forEach(l => l());
  }
};

// The widgetMap is completely dynamic, no hardcoded definitions here.

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
