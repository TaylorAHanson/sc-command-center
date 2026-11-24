import React, { useEffect, useMemo, useState } from 'react';
import {
    Loader2, ChevronDown, ChevronRight, ChevronLeft, ChevronsLeft, ChevronsRight, Search, ArrowLeft,
    ArrowUp, ArrowDown, ArrowUpDown, RefreshCw, X,
} from 'lucide-react';
import clsx from 'clsx';
import {
    DEFAULT_QUERY, PAGE_SIZES, isFiltered, nextSort, pageInfo, rangeIsBackwards, readSavedQuery, searchUrl,
    type ActionLogFacets, type ActionLogPage, type FacetValue, type LogQuery, type SortKey,
} from '../actionLogs';
import { formatServerTime } from './admin/time';

interface ActionLogsProps {
    onNavigate?: (page: string | null) => void;
}

// Per tab, so switching Admin Panel tabs and back, or reloading, keeps the
// search, filters, sort and page someone was reading.
const SAVED_KEY = 'cc:action-logs:query';
const SEARCH_DEBOUNCE_MS = 300;
const NO_FACETS: ActionLogFacets = { widgets: [], actions: [], users: [], domains: [] };

const loadSaved = (): LogQuery => {
    try {
        return readSavedQuery(window.sessionStorage.getItem(SAVED_KEY));
    } catch {
        return DEFAULT_QUERY;
    }
};

const LOAD_FAILED = 'Couldn’t load the action logs. Reload the page to try again.';

class LoadError extends Error {
    readonly status: number;
    constructor(message: string, status: number) {
        super(message);
        this.status = status;
    }
}

const getJson = async <T,>(url: string): Promise<T> => {
    const res = await fetch(url);
    const data = await res.json().catch(() => null);
    if (!res.ok) {
        // A refusal or a failed load must not read as "No logs found": an empty
        // log and one you aren't allowed to see are different answers.
        const detail = data && typeof data.detail === 'string' ? data.detail : '';
        const message = res.status === 403
            ? 'Only administrators can read the action logs.'
            : res.status === 400 && detail ? detail : LOAD_FAILED;
        throw new LoadError(message, res.status);
    }
    return data as T;
};

const messageOf = (e: unknown) => (e instanceof Error && e.message ? e.message : LOAD_FAILED);

const prettyContext = (raw: string): string => {
    try {
        return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
        return raw;
    }
};

const selectClass = 'rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:border-brand-blue max-w-[14rem]';

// The columns, in order; `sort` names the server's sort key where there is one.
const COLUMNS: { label: string; sort?: SortKey; className?: string }[] = [
    { label: 'Timestamp', sort: 'timestamp' },
    { label: 'Widget', sort: 'widget_name' },
    { label: 'Action', sort: 'action_name' },
    { label: 'User', sort: 'username' },
    { label: 'Domain', sort: 'domain' },
    { label: 'User Explanation' },
    { label: 'Action ID', sort: 'id', className: 'w-24' },
];

/** A filter's dropdown. A saved choice the log no longer has is still shown, so it can be cleared. */
const FacetSelect: React.FC<{
    label: string;
    anyLabel: string;
    value: string;
    options: FacetValue[];
    onChange: (value: string) => void;
}> = ({ label, anyLabel, value, options, onChange }) => {
    const known = !value || options.some(o => o.value === value);
    return (
        <select aria-label={label} value={value} onChange={e => onChange(e.target.value)} className={selectClass}>
            <option value="">{anyLabel}</option>
            {!known && <option value={value}>{value}</option>}
            {options.map(o => (
                <option key={o.value} value={o.value}>{o.label} ({o.count.toLocaleString()})</option>
            ))}
        </select>
    );
};

export const ActionLogs: React.FC<ActionLogsProps> = ({ onNavigate }) => {
    const [query, setQuery] = useState<LogQuery>(loadSaved);
    const [searchDraft, setSearchDraft] = useState(() => query.q);
    const [tick, setTick] = useState(0);
    const [result, setResult] = useState<{ key: string; page: ActionLogPage | null; error: string | null; status: number } | null>(null);
    const [facets, setFacets] = useState<ActionLogFacets>(NO_FACETS);
    const [expandedRow, setExpandedRow] = useState<number | null>(null);

    const backwards = rangeIsBackwards(query.from, query.to);
    const url = useMemo(() => searchUrl(query), [query]);
    const resultKey = `${url}#${tick}`;
    // Derived, not set in the effect: the shown page carries the request it answered.
    const loading = !backwards && result?.key !== resultKey;

    // Typing waits for a pause before it asks the server, and a new search starts on page one.
    useEffect(() => {
        if (searchDraft.trim() === query.q.trim()) return;
        const timer = window.setTimeout(() => {
            setQuery(prev => ({ ...prev, q: searchDraft, page: 0 }));
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [searchDraft, query.q]);

    useEffect(() => {
        try {
            window.sessionStorage.setItem(SAVED_KEY, JSON.stringify(query));
        } catch {
            // Storage full or off: the tab still works, it just won't remember.
        }
    }, [query]);

    useEffect(() => {
        if (backwards) return;
        let cancelled = false;
        getJson<ActionLogPage>(url)
            .then(page => {
                if (cancelled) return;
                // Rows were deleted or the filter narrowed under a later page:
                // go to the last page that has any rather than showing an empty one.
                if (page.rows.length === 0 && page.total > 0 && page.offset > 0) {
                    setQuery(prev => ({ ...prev, page: Math.max(0, Math.ceil(page.total / prev.pageSize) - 1) }));
                    return;
                }
                setResult({ key: resultKey, page, error: null, status: 200 });
            })
            // Keep the rows already shown: an empty table would read as "no actions".
            .catch(e => {
                if (cancelled) return;
                setResult(prev => ({
                    key: resultKey,
                    page: prev?.page ?? null,
                    error: messageOf(e),
                    status: e instanceof LoadError ? e.status : 0,
                }));
            });
        return () => { cancelled = true; };
    }, [url, resultKey, backwards]);

    // The filters' choices come from the whole log, not from the page on screen.
    useEffect(() => {
        let cancelled = false;
        getJson<ActionLogFacets>('/api/actions/facets')
            .then(data => { if (!cancelled) setFacets({ ...NO_FACETS, ...data }); })
            .catch(e => console.error('Failed to fetch action log filters', e));
        return () => { cancelled = true; };
    }, [tick]);

    /** A filter or sort change; anything but paging goes back to page one. */
    const update = (change: Partial<LogQuery>) =>
        setQuery(prev => ({ ...prev, page: 0, ...change }));

    const clearAll = () => {
        setSearchDraft('');
        setQuery(prev => ({ ...DEFAULT_QUERY, sort: prev.sort, dir: prev.dir, pageSize: prev.pageSize }));
    };

    const toggleRow = (id: number) => setExpandedRow(prev => (prev === id ? null : id));

    const page = result?.page ?? null;
    const rows = page?.rows ?? [];
    const total = page?.total ?? 0;
    const info = pageInfo(total, query.page, query.pageSize, rows.length);
    const filtered = isFiltered(query);
    const refused = result?.status === 403;
    const firstLoad = loading && !page;

    return (
        <div className="p-6 h-full flex flex-col">
            <div className="flex justify-between items-center mb-4 gap-4">
                <div className="flex items-center gap-4">
                    {onNavigate && (
                        <button
                            onClick={() => onNavigate(null)}
                            className="p-2 hover:bg-gray-200 rounded-full transition-colors"
                            title="Back to Dashboard"
                        >
                            <ArrowLeft className="w-5 h-5 text-gray-600" />
                        </button>
                    )}
                    <h1 className="text-2xl font-bold text-brand-navy">Action Logs (Telemetry)</h1>
                </div>
                <div className="flex items-center gap-2">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                        <input
                            type="text"
                            placeholder="Search logs..."
                            aria-label="Search logs"
                            value={searchDraft}
                            maxLength={200}
                            onChange={(e) => setSearchDraft(e.target.value)}
                            className="pl-10 pr-8 py-2 w-72 border border-gray-300 rounded-md focus:ring-brand-blue focus:border-brand-blue text-sm"
                        />
                        {searchDraft && (
                            <button
                                type="button"
                                aria-label="Clear search"
                                onClick={() => { setSearchDraft(''); update({ q: '' }); }}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                    <button
                        onClick={() => setTick(t => t + 1)}
                        className="p-2 text-gray-400 hover:text-brand-blue transition-colors rounded-lg hover:bg-gray-50"
                        title="Refresh"
                    >
                        <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {!refused && (
                <div className="flex flex-wrap items-center gap-3 mb-4">
                    <FacetSelect label="Widget" anyLabel="Any widget" value={query.widgetId} options={facets.widgets}
                        onChange={v => update({ widgetId: v })} />
                    <FacetSelect label="Action" anyLabel="Any action" value={query.actionName} options={facets.actions}
                        onChange={v => update({ actionName: v })} />
                    <FacetSelect label="User" anyLabel="Anyone" value={query.username} options={facets.users}
                        onChange={v => update({ username: v })} />
                    <FacetSelect label="Domain" anyLabel="Any domain" value={query.domain} options={facets.domains}
                        onChange={v => update({ domain: v })} />
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                        <input type="date" aria-label="From" value={query.from} max={query.to || undefined}
                            onChange={e => update({ from: e.target.value })} className={selectClass} />
                        <span>to</span>
                        <input type="date" aria-label="To" value={query.to} min={query.from || undefined}
                            onChange={e => update({ to: e.target.value })} className={selectClass} />
                    </div>
                    {filtered && (
                        <button type="button" onClick={clearAll} className="text-xs text-gray-500 underline hover:text-gray-800">
                            Clear all filters
                        </button>
                    )}
                </div>
            )}

            {backwards && (
                <div className="mb-4 text-sm text-amber-700" role="alert">
                    The start of the date range is after its end.
                </div>
            )}

            {firstLoad ? (
                <div className="flex-1 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 animate-spin text-brand-blue" />
                </div>
            ) : refused || (result?.error && !page) ? (
                <div className="flex-1 flex items-center justify-center text-sm text-gray-600" role="alert">
                    {result?.error}
                </div>
            ) : (
                <>
                    {result?.error && (
                        <div className="mb-3 text-sm text-red-600" role="alert">{result.error}</div>
                    )}
                    <div className={clsx(
                        'flex-1 overflow-auto bg-white rounded-lg shadow border border-gray-200 transition-opacity',
                        loading && 'opacity-60',
                    )} aria-busy={loading}>
                        <table className="w-full text-sm text-left text-gray-500">
                            <thead className="text-xs text-gray-700 uppercase bg-gray-50 border-b border-gray-200 sticky top-0">
                                <tr>
                                    <th className="px-6 py-3 w-10"></th>
                                    {COLUMNS.map(col => {
                                        const active = col.sort && query.sort === col.sort;
                                        const ariaSort = active ? (query.dir === 'asc' ? 'ascending' : 'descending') : undefined;
                                        return (
                                            <th key={col.label} className={clsx('px-6 py-3', col.className)} aria-sort={ariaSort}>
                                                {col.sort ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => update(nextSort(query, col.sort as SortKey))}
                                                        className={clsx(
                                                            'inline-flex items-center gap-1 uppercase hover:text-brand-blue',
                                                            active && 'text-brand-blue',
                                                        )}
                                                        title={`Sort by ${col.label.toLowerCase()}`}
                                                    >
                                                        {col.label}
                                                        {active ? (
                                                            query.dir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />
                                                        ) : (
                                                            <ArrowUpDown className="w-3 h-3 text-gray-300" />
                                                        )}
                                                    </button>
                                                ) : col.label}
                                            </th>
                                        );
                                    })}
                                </tr>
                            </thead>
                            <tbody>
                                {rows.length === 0 ? (
                                    <tr>
                                        <td colSpan={8} className="px-6 py-10 text-center text-gray-500">
                                            {filtered ? (
                                                <>
                                                    No actions match these filters.{' '}
                                                    <button type="button" onClick={clearAll} className="underline hover:text-gray-800">
                                                        Clear all filters
                                                    </button>
                                                </>
                                            ) : 'No actions have been logged yet.'}
                                        </td>
                                    </tr>
                                ) : (
                                    rows.map((log) => (
                                        <React.Fragment key={log.id}>
                                            <tr
                                                className={`border-b hover:bg-gray-50 cursor-pointer ${expandedRow === log.id ? 'bg-blue-50' : ''}`}
                                                onClick={() => toggleRow(log.id)}
                                            >
                                                <td className="px-6 py-4">
                                                    {expandedRow === log.id ? (
                                                        <ChevronDown className="w-4 h-4" />
                                                    ) : (
                                                        <ChevronRight className="w-4 h-4" />
                                                    )}
                                                </td>
                                                <td className="px-6 py-4 font-mono text-xs whitespace-nowrap">
                                                    {formatServerTime(log.timestamp)}
                                                </td>
                                                <td className="px-6 py-4 font-medium text-gray-900">
                                                    {log.widget_name}
                                                </td>
                                                <td className="px-6 py-4 italic text-gray-600">
                                                    {log.action_name || <span className="text-gray-400">—</span>}
                                                </td>
                                                <td className="px-6 py-4 text-gray-700">
                                                    {/* Actions logged before the acting user was recorded have no
                                                        name to show, and inventing one would be worse than a blank. */}
                                                    {log.username || <span className="text-gray-400">—</span>}
                                                </td>
                                                <td className="px-6 py-4">
                                                    {log.domain ? (
                                                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                                                            {log.domain}
                                                        </span>
                                                    ) : (
                                                        <span className="text-gray-400 text-xs">—</span>
                                                    )}
                                                </td>
                                                <td className="px-6 py-4">
                                                    {log.user_explanation}
                                                </td>
                                                <td className="px-6 py-4 font-mono text-xs text-gray-400">
                                                    #{log.id}
                                                </td>
                                            </tr>
                                            {expandedRow === log.id && (
                                                <tr className="bg-gray-50">
                                                    <td colSpan={8} className="px-6 py-4 border-b">
                                                        <div className="space-y-2">
                                                            {/* The handle that joins this approval to the statement it
                                                                authorised in Databricks' own query history. */}
                                                            <h4 className="text-xs font-semibold uppercase text-gray-500">Request ID</h4>
                                                            <p className="font-mono text-xs text-gray-700">
                                                                {log.request_id || <span className="text-gray-400">Not recorded</span>}
                                                            </p>
                                                            <h4 className="text-xs font-semibold uppercase text-gray-500">Dashboard Context</h4>
                                                            <pre className="bg-gray-900 text-gray-100 p-4 rounded-md text-xs font-mono overflow-auto max-h-96">
                                                                {prettyContext(log.dashboard_context)}
                                                            </pre>
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-3 pt-3 text-sm text-gray-600">
                        <div className="flex items-center gap-2">
                            {loading && <Loader2 className="w-4 h-4 animate-spin text-brand-blue" />}
                            {total > 0
                                ? `Showing ${info.first.toLocaleString()}–${info.last.toLocaleString()} of ${total.toLocaleString()}`
                                : 'No actions'}
                        </div>
                        <div className="flex items-center gap-3">
                            <label className="flex items-center gap-2">
                                Rows per page
                                <select
                                    value={query.pageSize}
                                    onChange={e => update({ pageSize: Number(e.target.value) })}
                                    className={selectClass}
                                >
                                    {PAGE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
                                </select>
                            </label>
                            <div className="flex items-center gap-1">
                                <PageButton label="First page" disabled={!info.hasPrev || loading}
                                    onClick={() => setQuery(prev => ({ ...prev, page: 0 }))}><ChevronsLeft className="w-4 h-4" /></PageButton>
                                <PageButton label="Previous page" disabled={!info.hasPrev || loading}
                                    onClick={() => setQuery(prev => ({ ...prev, page: Math.max(0, prev.page - 1) }))}><ChevronLeft className="w-4 h-4" /></PageButton>
                                <span className="px-2 whitespace-nowrap">
                                    Page {(query.page + 1).toLocaleString()} of {info.pages.toLocaleString()}
                                </span>
                                <PageButton label="Next page" disabled={!info.hasNext || loading}
                                    onClick={() => setQuery(prev => ({ ...prev, page: prev.page + 1 }))}><ChevronRight className="w-4 h-4" /></PageButton>
                                <PageButton label="Last page" disabled={!info.hasNext || loading}
                                    onClick={() => setQuery(prev => ({ ...prev, page: info.pages - 1 }))}><ChevronsRight className="w-4 h-4" /></PageButton>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

const PageButton: React.FC<{ label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }> = ({
    label, disabled, onClick, children,
}) => (
    <button
        type="button"
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onClick}
        className="p-1.5 rounded-md border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
    >
        {children}
    </button>
);
