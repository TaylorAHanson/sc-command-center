import React from 'react';
import { useScript } from './hooks/useScript';

// Define types broadly since we only need component matching
export interface WidgetProps {
  id: string;
  data?: any;
  executeAction?: (actionName: string, callback: () => void) => void;
  variables?: Record<string, any>;
  setVariable?: (key: string, value: any) => void;
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
  helpText?: string; // Optional help text for the widget
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

const announce = () => {
  registryVersion++;
  listeners.forEach(l => l());
};

export const registerWidget = (def: WidgetDefinition) => {
  widgetRegistry[def.id] = def;
  announce();
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

/** Compiled components, keyed `id@version`, built the first time one renders. */
const compiled = new Map<string, React.ComponentType<WidgetProps>>();

/**
 * Babel Standalone arrives as a deferred CDN script, so it can be a moment behind
 * the app. Anything that compiles waits for it.
 *
 * This used to be a bare `if (!window.Babel) return`, which meant a slow CDN — the
 * normal case behind a corporate proxy — produced an empty widget library with
 * nothing in the console to say why.
 */
const babelReady = (timeoutMs = 30000): Promise<any> => new Promise((resolve, reject) => {
  // @ts-ignore
  if (window.Babel) return resolve(window.Babel);
  const started = Date.now();
  const tick = window.setInterval(() => {
    // @ts-ignore
    if (window.Babel) {
      window.clearInterval(tick);
      // @ts-ignore
      resolve(window.Babel);
    } else if (Date.now() - started > timeoutMs) {
      window.clearInterval(tick);
      reject(new Error('The widget compiler (Babel) did not load. Check your network.'));
    }
  }, 50);
});

/** Turn a widget's TSX into a component. Costs tens of milliseconds — the reason
 *  none of this happens until something actually renders. */
const build = (key: string, tsx: string, Babel: any): React.ComponentType<WidgetProps> => {
  // Two-pass transform. Pass 1 (react + typescript presets) strips TS types
  // and *type-only* imports (e.g. `import { WidgetProps }`) and compiles JSX.
  // Pass 2 converts any remaining runtime ES module `import`/`export` to
  // CommonJS. This ordering matters: Babel runs plugins before presets, so
  // doing the module transform in the same pass would rewrite the WidgetProps
  // type import into a real require() before the TS preset could elide it.
  // Without pass 2, a widget with a runtime import (like `import React, {
  // useState } from 'react'`) keeps the `import` and throws "Cannot use import
  // statement outside a module" inside new Function().
  const stripped = Babel.transform(tsx, {
    filename: `${key}.tsx`,
    presets: ['react', 'typescript'],
  }).code;
  const transpiled = Babel.transform(stripped, {
    filename: `${key}.js`,
    plugins: ['transform-modules-commonjs'],
  }).code;

  // Minimal CommonJS sandbox. `require` resolves to the injected React, to
  // runtime globals loaded via the useScript() hook (e.g. window.Highcharts),
  // or throws a clear error — so a widget that imports something unavailable
  // fails on its own rather than taking down the whole registry load.
  const executableCode = `
    var module = { exports: {} };
    var exports = module.exports;
    var require = function (name) {
      if (name === 'react') return React;
      if (name === 'react-dom') return (typeof window !== 'undefined' ? window.ReactDOM : undefined);
      if (typeof window !== 'undefined') {
        var g = window[name] || window[name.charAt(0).toUpperCase() + name.slice(1)];
        if (g) return g;
      }
      throw new Error("Module '" + name + "' is not available in this sandbox. Use the useScript() hook for external libraries.");
    };
    ${transpiled}
    return (module.exports && module.exports.default) ? module.exports.default : module.exports;
  `;
  // eslint-disable-next-line no-new-func
  const createComponent = new (Function as any)('React', 'useScript', executableCode);
  return createComponent(React, useScript);
};

const notice = (text: string, tone: string) =>
  React.createElement('div', { className: `flex items-center justify-center h-full w-full p-4 text-xs text-center ${tone}` }, text);

/**
 * A widget's component, compiled the first time it is put on screen.
 *
 * Startup used to compile every row the library returned — every version of every
 * widget — in one synchronous pass. Thirty widgets with a few dozen saves each is
 * a main thread blocked for fifteen seconds, which is where Chrome starts asking
 * whether you'd like to leave. A dashboard shows a handful of widgets, so that is
 * how many compiles a page load should cost.
 *
 * The wrapper is a real component rather than a getter so that fetching an older
 * version's source can be part of the same path: nothing else has to know whether
 * the code was already in hand.
 */
const lazyWidget = (key: string, source: () => Promise<string>): React.ComponentType<WidgetProps> => {
  const Lazy: React.FC<WidgetProps> = (props) => {
    const [Component, setComponent] = React.useState<React.ComponentType<WidgetProps> | undefined>(
      () => compiled.get(key)
    );
    const [failure, setFailure] = React.useState<string | null>(null);

    React.useEffect(() => {
      if (Component) return;
      let alive = true;
      (async () => {
        try {
          const Babel = await babelReady();
          const tsx = await source();
          if (!tsx) throw new Error('This version has no code stored.');
          const built = compiled.get(key) || build(key, tsx, Babel);
          compiled.set(key, built);
          if (alive) setComponent(() => built);
        } catch (err) {
          console.error(`Failed to load widget ${key}:`, err);
          if (alive) setFailure((err as Error)?.message || String(err));
        }
      })();
      return () => { alive = false; };
    }, [Component]);

    if (failure) return notice(failure, 'text-rose-500');
    if (!Component) return notice('Loading…', 'text-gray-400 animate-pulse');
    return React.createElement(Component, props);
  };
  Lazy.displayName = `Widget(${key})`;
  return Lazy;
};

/** One older version's source, fetched only if somebody pins that version. */
const fetchVersionSource = async (id: string, version: number): Promise<string> => {
  const res = await fetch(`/api/widgets/version?widget_id=${encodeURIComponent(id)}&version=${version}`);
  if (!res.ok) throw new Error(`Version ${version} of this widget could not be loaded.`);
  const data = await res.json();
  return data.widget?.tsx_code || data.tsx_code || '';
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
        const key = `${w.id}@${w.version}`;
        // The server sends the source of the current version and nothing else, so
        // an older version resolves its own when it is rendered.
        const source = w.tsx_code
          ? async () => w.tsx_code as string
          : () => fetchVersionSource(w.id, w.version);
        const Component = lazyWidget(key, source);

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
          helpText: w.help_text || undefined,
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
        widgetRegistry[key] = { ...baseDef, id: key };

        // The current version is also the widget under its plain id. The server
        // says which that is; older payloads relied on newest-first ordering.
        const isLatest = w.is_latest === undefined ? !seenIds.has(w.id) : !!w.is_latest;
        if (isLatest && !seenIds.has(w.id)) {
          seenIds.add(w.id);
          widgetRegistry[w.id] = baseDef;
        }
      } catch (err) {
        console.error(`Failed to load widget ${w.id}:`, err);
      }
    });
    // One notification for the whole library rather than one per row: each of
    // these re-renders every subscribed component.
    announce();
  } catch (err) {
    console.error("Failed to load widgets:", err);
  } finally {
    isRegistryLoading = false;
    listeners.forEach(l => l());
  }
};

/**
 * Thumbnails for the library, fetched the first time it is opened.
 *
 * They are base64 PNGs — by far the largest thing a widget stores — and the only
 * place they appear is the library tray, so a session that never opens it never
 * pays for them.
 */
let snapshotsLoaded = false;
export const loadWidgetSnapshots = async () => {
  if (snapshotsLoaded) return;
  snapshotsLoaded = true;
  try {
    const res = await fetch('/api/widgets/custom/snapshots');
    if (!res.ok) return;
    const { snapshots } = await res.json();
    let found = false;
    Object.entries(snapshots || {}).forEach(([id, snapshot]) => {
      const def = widgetRegistry[id];
      if (def && typeof snapshot === 'string') {
        def.snapshot = snapshot;
        found = true;
      }
    });
    if (found) announce();
  } catch (err) {
    console.error('Failed to load widget thumbnails:', err);
    snapshotsLoaded = false;
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
