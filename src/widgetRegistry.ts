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
  snapshot?: string; // Base64 image snapshot of the widget
  openInNewTabLink?: string; // Optional URL to open in a new tab when the user clicks a button in the widget header
  version?: number;
  availableVersions?: number[];
  latestVersion?: number;
  createdBy?: string; // Username of whoever published this widget (custom widgets only)
}

export const widgetRegistry: Record<string, WidgetDefinition> = {};
let registryVersion = 0;
let isRegistryLoading = true;
let initialLoadStarted = false;
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
  if (isRegistryLoading && initialLoadStarted) return;
  initialLoadStarted = true;
  isRegistryLoading = true;
  listeners.forEach(l => l());

  try {
    const res = await fetch('/api/widgets/custom');
    if (!res.ok) return;
    const data = await res.json();
    
    const versionsByWidget: Record<string, number[]> = {};
    const latestVersionByWidget: Record<string, number> = {};
    data.widgets.forEach((w: any) => {
      if (!versionsByWidget[w.id]) versionsByWidget[w.id] = [];
      if (w.version) versionsByWidget[w.id].push(w.version);
      if (w.version && (!latestVersionByWidget[w.id] || w.version > latestVersionByWidget[w.id])) {
        latestVersionByWidget[w.id] = w.version;
      }
    });
    
    const seenIds = new Set<string>();

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

        const baseDef = {
          id: w.id,
          version: w.version,
          availableVersions: versionsByWidget[w.id]?.sort((a, b) => b - a) || [],
          latestVersion: latestVersionByWidget[w.id] || w.version,
          name: w.name,
          description: w.description,
          category: w.category,
          domain: w.domain,
          defaultW: w.default_w || 6,
          defaultH: w.default_h || 6,
          component: Component,
          configurationMode: w.configuration_mode || 'none' as const,
          configSchema: w.config_schema ? JSON.parse(w.config_schema) : undefined,
          defaultProps: (() => {
            const props: Record<string, any> = {};
            if (w.data_source) {
              props.dataSource = w.data_source;
              props.dataSourceType = w.data_source_type || 'none';
            }
            if (w.config_schema) {
              try {
                const schema = JSON.parse(w.config_schema);
                schema.forEach((field: any) => {
                  if (field.key && field.defaultValue !== undefined && field.defaultValue !== '') {
                    props[field.key] = field.type === 'number' ? Number(field.defaultValue) : field.defaultValue;
                  }
                });
              } catch (e) { }
            }
            return Object.keys(props).length > 0 ? props : undefined;
          })(),
          isCertified: w.is_certified === 1,
          isExecutable: w.is_executable === 1,
          snapshot: w.snapshot || undefined,
          openInNewTabLink: w.open_in_new_tab_link || undefined,
          createdBy: w.created_by || undefined,
          accessControl: { mockHasAccess: true }
        };

        // Always register the versioned ID
        registerWidget({ ...baseDef, id: `${w.id}@${w.version}` });

        // If it's the first time we see this widget ID, it's the latest version
        // so we also register it under the base ID
        if (!seenIds.has(w.id)) {
          seenIds.add(w.id);
          registerWidget(baseDef);
        }
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

export const getAvailableWidgets = () => Object.values(widgetRegistry).filter(w => !w.id.includes('@'));

export const getWidgetCategories = () => {
  const categories = new Set<string>();
  Object.values(widgetRegistry)
    .filter(w => !w.id.includes('@'))
    .forEach(w => {
      categories.add(w.category || 'Uncategorized');
    });
  return Array.from(categories).sort();
};

export const getWidgetDomains = () => {
  const domains = new Set<string>();
  Object.values(widgetRegistry)
    .filter(w => !w.id.includes('@'))
    .forEach(w => {
      if (w.domain) domains.add(w.domain);
    });
  return Array.from(domains).sort();
};

export const getWidgetsByCategory = (category: string) => {
  return Object.values(widgetRegistry)
    .filter(w => !w.id.includes('@') && (w.category || 'Uncategorized') === category);
};
