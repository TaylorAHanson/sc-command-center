import React from 'react';
import { ArrowRight, FileText, LayoutGrid } from 'lucide-react';
import clsx from 'clsx';
import type { WidgetProps } from '../widgetRegistry';

const SAMPLE_TABS = ['Overview', 'Details', 'Team'];

/**
 * The built-in "Tab links" widget: a tile, or a line, for each of the view's
 * tabs. It only ever calls `props.app.goToTab`, so it reads no data and needs no
 * permission beyond seeing the view.
 *
 * Targets are kept by tab id, so renaming a tab keeps its link; a target whose
 * tab was deleted simply stops showing.
 */
export const TabLinksWidget: React.FC<WidgetProps> = ({ data, app }) => {
  const heading = typeof data?.heading === 'string' ? data.heading.trim() : '';
  const list = data?.style === 'list';
  const picked: string[] = Array.isArray(data?.tabs) ? data.tabs.filter((t: unknown) => typeof t === 'string') : [];

  const targets = app
    ? (picked.length
        ? picked.map(id => app.tabs.find(t => t.id === id)).filter((t): t is NonNullable<typeof t> => !!t)
        : app.tabs.filter(t => t.id !== app.activeTabId))
    : SAMPLE_TABS.map((name, i) => ({ id: `sample-${i}`, name, layout: 'canvas' as const }));

  if (!targets.length) {
    return (
      <div className="h-full w-full flex items-center justify-center text-center text-sm text-gray-400 px-4">
        {picked.length
          ? 'The tabs these links went to have been deleted. Pick others in this card’s settings.'
          : 'Add another tab to this view and a link to it appears here.'}
      </div>
    );
  }

  return (
    <nav aria-label={heading || 'Tab links'} className="h-full w-full flex flex-col gap-3">
      {heading && <h3 className="text-base font-semibold text-brand-navy">{heading}</h3>}
      <div className={clsx(list ? 'flex flex-col divide-y divide-gray-100' : 'grid gap-3 grid-cols-[repeat(auto-fill,minmax(10rem,1fr))]')}>
        {targets.map(tab => {
          const Icon = tab.layout === 'page' ? FileText : LayoutGrid;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => app?.goToTab(tab.id)}
              disabled={!app}
              className={clsx(
                'group flex items-center gap-3 text-left text-brand-navy transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue/40',
                list
                  ? 'py-2.5 px-1 hover:text-brand-blue'
                  : 'p-4 rounded-lg border border-gray-200 bg-white hover:border-brand-blue hover:bg-brand-blue/5',
              )}
            >
              <span className={clsx('shrink-0 flex items-center justify-center rounded-md bg-brand-blue/10 text-brand-blue', list ? 'w-7 h-7' : 'w-9 h-9')}>
                <Icon className="w-4 h-4" />
              </span>
              <span className="flex-1 min-w-0 truncate text-sm font-medium">{tab.name}</span>
              <ArrowRight className="w-4 h-4 shrink-0 text-gray-300 group-hover:text-brand-blue transition-colors" />
            </button>
          );
        })}
      </div>
    </nav>
  );
};
