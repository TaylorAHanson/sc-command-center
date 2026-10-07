import React from 'react';
import { Filter } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import { BAR_SURFACE, barSurface } from '../store/appSpec';

/**
 * The view's own filters. Each sets the dashboard variable its key names, the
 * same variables widgets set for one another, so a widget written to follow a
 * variable follows the filter bar too. Choosing a filter changes nothing that is
 * saved, so anyone who can see the view can use it.
 */
export const FilterBar: React.FC = () => {
  const { activeApp, variables, setVariable } = useDashboardStore();
  const filters = activeApp?.spec.filters;
  if (!filters?.length) return null;
  const surface = barSurface(activeApp);

  return (
    <div
      className={`border-b px-4 py-2 flex flex-wrap items-center gap-x-5 gap-y-2 shrink-0 ${BAR_SURFACE[surface]}`}
      role="group"
      aria-label="Filters"
    >
      <Filter className={`w-4 h-4 ${surface === 'dark' ? 'text-white/60' : 'text-gray-400'}`} aria-hidden />
      {filters.map(filter => {
        const current = variables[filter.key] == null ? '' : String(variables[filter.key]);
        return (
          <label key={filter.key} className={`flex items-center gap-2 text-sm ${surface === 'dark' ? 'text-white/80' : 'text-gray-600'}`}>
            <span className="font-medium">{filter.label}</span>
            <select
              value={current}
              onChange={e => setVariable(filter.key, e.target.value)}
              className="px-2 py-1 text-sm border border-gray-300 rounded-md bg-white text-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
            >
              <option value="">All</option>
              {filter.options.map(option => <option key={option} value={option}>{option}</option>)}
              {/* A widget may have set this variable to something the filter doesn't list. */}
              {current && !filter.options.includes(current) && <option value={current}>{current}</option>}
            </select>
          </label>
        );
      })}
    </div>
  );
};
