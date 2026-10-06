import React, { useState } from 'react';
import { LayoutGrid, Pencil, Replace, Settings, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';
import { widgetRegistry, useWidgetRegistry } from '../widgetRegistry';
import { useActionLogger } from '../hooks/useActionLogger';
import { ActionProvider, ExecuteActionPropInjector } from '../contexts/ActionContext';
import { useWorkspaceTools } from '../contexts/WorkspaceTools';
import type { App, AppTab } from '../store/appSpec';

const WIDGET_DRAG = 'application/widget-type';

/**
 * A page tab: its one widget drawn edge to edge, with no card around it. The
 * widget brings its own background and layout; Command Center adds only a small
 * toolbar for whoever may change the tab, and only inside Command Center.
 */
export const PageTab: React.FC<{ app: App; tab: AppTab; readOnly: boolean }> = ({ app, tab, readOnly }) => {
  const { addWidget, removeWidget, updateWidget, openConfigModal, setTabLayout, activeDomain, username, variables, setVariable, canEditDomain } = useDashboardStore();
  const { loading } = useWidgetRegistry();
  const tools = useWorkspaceTools();
  const [dropping, setDropping] = useState(false);

  const widget = tab.widgets[0];
  const versioned = widget?.props?._version ? `${widget.type}@${widget.props._version}` : widget?.type;
  const found = widget ? (widgetRegistry[versioned!] || widgetRegistry[widget.type]) : undefined;
  const def = found && !(activeDomain && found.domain && found.domain !== activeDomain) ? found : undefined;
  const editable = !readOnly && !!tools;

  const { runAction } = useActionLogger({ widgetId: widget?.i || tab.id, widgetName: def?.name || 'Page' });
  const data = React.useMemo(
    () => ({ ...widget?.props, username, variables, setVariable }),
    [widget?.props, username, variables, setVariable],
  );

  const place = (type: string) => {
    const next = widgetRegistry[type];
    if (!next) return;
    if (widget && !window.confirm(`Replace “${def?.name || widget.type}” on this page with “${next.name}”?`)) return;
    const config: Record<string, unknown> = { ...(next.defaultProps || {}) };
    next.configSchema?.forEach(f => { if (f.defaultValue !== undefined) config[f.key] = f.defaultValue; });
    if (next.configurationMode === 'config_required') openConfigModal(type, c => addWidget(app.id, tab.id, type, undefined, c));
    else addWidget(app.id, tab.id, type, undefined, config);
  };

  const dropProps = editable ? {
    onDragOver: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes(WIDGET_DRAG)) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'copy';
      if (!dropping) setDropping(true);
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropping(false);
    },
    onDrop: (e: React.DragEvent) => {
      setDropping(false);
      const type = e.dataTransfer.getData(WIDGET_DRAG);
      if (!type) return;
      e.preventDefault();
      e.stopPropagation();
      place(type);
    },
  } : {};

  const configurable = def && (def.configurationMode === 'config_required' || def.configurationMode === 'config_allowed');
  const button = 'flex items-center gap-1.5 px-2 py-1 rounded text-xs text-gray-600 hover:text-brand-blue hover:bg-gray-100';

  return (
    <div className="relative h-full w-full overflow-auto" data-page-tab={tab.id} {...dropProps}>
      {editable && (
        <div className="absolute top-2 right-2 z-20 flex items-center gap-0.5 p-0.5 bg-white/95 border border-gray-200 rounded-md shadow-sm opacity-70 hover:opacity-100 focus-within:opacity-100 transition-opacity">
          <button type="button" className={button} onClick={tools!.openLibrary} title="Open the widget library and drag a widget onto this page">
            <Replace className="w-3.5 h-3.5" />
            <span>{widget ? 'Change widget' : 'Choose a widget'}</span>
          </button>
          {def && canEditDomain(def.domain) && (
            <button type="button" className={button} onClick={() => tools!.editWidget(widget!.type)} title="Edit this page's widget in Widget Studio">
              <Pencil className="w-3.5 h-3.5" />
              <span>Edit in Widget Studio</span>
            </button>
          )}
          {configurable && (
            <button
              type="button"
              className={button}
              onClick={() => openConfigModal(widget!.type, c => updateWidget(app.id, tab.id, widget!.i, { props: c }), widget!.props)}
              title="Configure this page's widget"
            >
              <Settings className="w-3.5 h-3.5" />
            </button>
          )}
          {widget && (
            <button type="button" className={clsx(button, 'hover:text-red-600')} onClick={() => removeWidget(app.id, tab.id, widget.i)} title="Take the widget off this page">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
          <button type="button" className={button} onClick={() => setTabLayout(app.id, tab.id, 'canvas')} title="Make this tab a canvas of cards">
            <LayoutGrid className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {def ? (
        <ActionProvider value={runAction}>
          <React.Suspense fallback={<div className="h-full w-full flex items-center justify-center text-xs text-gray-400">Loading page…</div>}>
            <ExecuteActionPropInjector>
              <def.component id={widget!.i} data={data} key={widget!.i} />
            </ExecuteActionPropInjector>
          </React.Suspense>
        </ActionProvider>
      ) : (
        <div className="h-full w-full flex items-center justify-center text-center text-gray-400">
          {widget && loading ? (
            <span className="text-xs">Loading page…</span>
          ) : (
            <div>
              <p className="text-lg mb-2">{widget ? 'This page’s widget isn’t available' : 'An empty page'}</p>
              <p className="text-sm">
                {editable
                  ? 'Drag a widget here from the library. It fills the whole tab.'
                  : widget ? 'It may have been deleted, or belong to another domain.' : 'Nothing has been placed on this page yet.'}
              </p>
            </div>
          )}
        </div>
      )}

      {dropping && (
        <div className="pointer-events-none absolute inset-0 z-10 border-2 border-dashed border-brand-blue bg-brand-blue/5 flex items-center justify-center">
          <span className="px-3 py-1.5 rounded bg-white text-sm text-brand-navy shadow-sm">{widget ? 'Drop to replace this page’s widget' : 'Drop to fill this page'}</span>
        </div>
      )}
    </div>
  );
};
