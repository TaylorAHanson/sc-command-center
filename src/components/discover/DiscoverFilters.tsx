import React, { useId, useState } from 'react';
import clsx from 'clsx';
import type { DiscoverRoute, SearchResponse } from '../../discover';
import { facetOptions, hasFilters, toggled, type FacetOption } from '../../discoverPage';

const FACET_PREVIEW = 6;

const Group: React.FC<{ title: string; hint?: string; children: React.ReactNode }> = ({ title, hint, children }) => (
    <fieldset className="border-t border-gray-100 pt-3 first:border-t-0 first:pt-0">
        <legend className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{title}</legend>
        {hint && <p className="mt-0.5 text-xs text-gray-400">{hint}</p>}
        <div className="mt-1.5 space-y-0.5">{children}</div>
    </fieldset>
);

const FacetGroup: React.FC<{
    title: string;
    noun: string;
    options: FacetOption[] | null;
    onToggle: (value: string) => void;
}> = ({ title, noun, options, onToggle }) => {
    const [all, setAll] = useState(false);
    if (options === null) {
        return (
            <Group title={title}>
                {[0, 1, 2].map(i => <div key={i} className="h-4 animate-pulse rounded bg-gray-100" />)}
            </Group>
        );
    }
    const shown = all ? options : options.filter((o, i) => i < FACET_PREVIEW || o.selected);
    return (
        <Group title={title}>
            {options.length === 0 && <p className="text-sm text-gray-400">No {noun} on these views.</p>}
            {shown.map(o => (
                <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm text-gray-700 hover:bg-gray-50">
                    <input
                        type="checkbox"
                        checked={o.selected}
                        onChange={() => onToggle(o.value)}
                        className="h-3.5 w-3.5 rounded border-gray-300 text-brand-blue focus:ring-brand-blue/30"
                    />
                    <span className="flex-1 truncate" title={o.label}>{o.label}</span>
                    {o.count !== null && <span className="text-xs tabular-nums text-gray-400">{o.count.toLocaleString()}</span>}
                </label>
            ))}
            {options.length > shown.length && (
                <button type="button" onClick={() => setAll(true)} className="px-1 text-xs font-medium text-brand-blue hover:underline">
                    Show {options.length - shown.length} more
                </button>
            )}
        </Group>
    );
};

function Choice<T extends string | boolean>({ title, hint, value, options, onPick }: {
    title: string;
    hint?: string;
    value: T | undefined;
    options: { value: T | undefined; label: string }[];
    onPick: (value: T | undefined) => void;
}) {
    const name = useId();
    return (
        <Group title={title} hint={hint}>
            {options.map(o => (
                <label key={String(o.value)} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm text-gray-700 hover:bg-gray-50">
                    <input
                        type="radio"
                        name={name}
                        checked={value === o.value}
                        onChange={() => onPick(o.value)}
                        className="h-3.5 w-3.5 border-gray-300 text-brand-blue focus:ring-brand-blue/30"
                    />
                    <span className="flex-1">{o.label}</span>
                </label>
            ))}
        </Group>
    );
}

/**
 * The filters beside search results. Domain and owner list the server's counts
 * for the current search (each leaves out its own filter, so ticking a second
 * domain still shows the others' counts).
 */
export const DiscoverFilters: React.FC<{
    route: DiscoverRoute;
    /** Undefined while the first page is loading. */
    facets: SearchResponse['facets'] | undefined;
    /** Only people who manage views can narrow by status. */
    offersStatus: boolean;
    /** For anyone else, a status filter also narrows to the views they manage. */
    isAdmin: boolean;
    onChange: (patch: Partial<DiscoverRoute>) => void;
    onClear: () => void;
    className?: string;
}> = ({ route, facets, offersStatus, isAdmin, onChange, onClear, className }) => (
    <div className={clsx('space-y-3', className)}>
        <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Filters</h2>
            {hasFilters(route) && (
                <button type="button" onClick={onClear} className="text-xs font-medium text-brand-blue hover:underline">Clear all</button>
            )}
        </div>
        <FacetGroup
            title="Domain"
            noun="domains"
            options={facets ? facetOptions(facets.domain, route.domain) : null}
            onToggle={v => onChange({ domain: toggled(route.domain, v) })}
        />
        <FacetGroup
            title="Owner"
            noun="owners"
            options={facets ? facetOptions(facets.owner, route.owner) : null}
            onToggle={v => onChange({ owner: toggled(route.owner, v) })}
        />
        <Choice
            title="Certified"
            value={route.certified}
            options={[{ value: undefined, label: 'Any' }, { value: true, label: 'Certified' }, { value: false, label: 'Not certified' }]}
            onPick={certified => onChange({ certified })}
        />
        <Choice
            title="Opens"
            value={route.standalone}
            options={[{ value: undefined, label: 'Anywhere' }, { value: false, label: 'In the workspace' }, { value: true, label: 'On its own page' }]}
            onPick={standalone => onChange({ standalone })}
        />
        <Choice
            title="Last opened"
            hint="By anyone."
            value={route.opened}
            options={[{ value: undefined, label: 'Any time' }, { value: 'never', label: 'Never opened' }, { value: '90d', label: 'Not in 90 days' }]}
            onPick={opened => onChange({ opened })}
        />
        {offersStatus && (
            <Choice
                title="Status"
                hint={isAdmin ? undefined : 'Narrows to views you manage.'}
                value={route.status}
                options={[{ value: undefined, label: 'Any' }, { value: 'draft', label: 'Unpublished changes' }, { value: 'published', label: 'No unpublished changes' }]}
                onPick={status => onChange({ status })}
            />
        )}
    </div>
);
