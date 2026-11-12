import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowDown, ArrowUp, Check, Loader2, Plus, X } from 'lucide-react';
import clsx from 'clsx';
import { searchViews, type ViewRow } from '../../discover';
import { addPick, MAX_COMBINED, movePick } from '../../discoverPage';
import { requestJson } from '../../sharing';
import { useDialog } from '../sharing/useDialog';
import { ViewSearchBox } from './ViewSearchBox';

const NAME_LIMIT = 120;
const FOUND_LIMIT = 24;

const compose = (name: string, sourceIds: string[], standalone: boolean) =>
    requestJson<{ id: string; tabs: number }>('/api/apps/compose', {
        method: 'POST',
        body: JSON.stringify({ name, source_ids: sourceIds, presentation: standalone ? 'standalone' : 'workspace' }),
    });

const Byline: React.FC<{ row: ViewRow }> = ({ row }) => {
    const parts = [row.owner, row.domain].filter(Boolean);
    return parts.length ? <div className="truncate text-xs text-gray-500">{parts.join(' · ')}</div> : null;
};

/**
 * Combine views: a new view with a tab for each view picked, copied as the
 * caller sees it (POST /api/apps/compose). Views are found with the same search
 * as Discover, because no list of every view is ever loaded. The views picked
 * are copied, not moved, so their links keep working.
 */
export const ComposeDialog: React.FC<{ initial?: ViewRow[]; onClose: () => void }> = ({ initial = [], onClose }) => {
    const titleId = useId();
    const [name, setName] = useState('');
    const [picked, setPicked] = useState<ViewRow[]>(initial.slice(0, MAX_COMBINED));
    const [text, setText] = useState('');
    const [found, setFound] = useState<{ q: string; rows: ViewRow[]; more: boolean } | null>(null);
    const [searching, setSearching] = useState(false);
    const [standalone, setStandalone] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const pending = useRef<AbortController | null>(null);
    const { ref, onKeyDown } = useDialog<HTMLDivElement>(onClose, saving);

    const full = picked.length >= MAX_COMBINED;
    const add = (row: ViewRow) => setPicked(p => addPick(p, row));

    const search = (value: string) => {
        pending.current?.abort();
        const q = value.trim();
        if (!q) {
            setFound(null);
            setSearching(false);
            return;
        }
        const ctrl = new AbortController();
        pending.current = ctrl;
        setSearching(true);
        searchViews({ q, scope: 'all', sort: 'relevance', limit: FOUND_LIMIT }, { signal: ctrl.signal })
            .then(res => setFound({ q, rows: res.results, more: !!res.next_cursor }))
            .catch(e => { if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e)); })
            .finally(() => { if (pending.current === ctrl) setSearching(false); });
    };

    const create = () => {
        const trimmed = name.trim();
        if (!trimmed || picked.length === 0 || saving) return;
        setSaving(true);
        setError(null);
        compose(trimmed, picked.map(r => r.id), standalone)
            .then(res => {
                onClose();
                window.location.hash = `#/app/${encodeURIComponent(res.id)}`;
            })
            .catch(e => {
                setSaving(false);
                setError(e instanceof Error ? e.message : String(e));
            });
    };

    const pickedIds = picked.map(r => r.id);

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
            onMouseDown={e => { if (e.target === e.currentTarget && !saving) onClose(); }}
        >
            <div
                ref={ref}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-2xl focus:outline-none"
            >
                <div className="flex items-start gap-3 px-6 pb-3 pt-5">
                    <div className="min-w-0 flex-1">
                        <h2 id={titleId} className="text-lg font-semibold text-gray-900">Combine views</h2>
                        <p className="mt-0.5 text-sm text-gray-500">
                            A new view with a tab for each view you pick (a view with several tabs brings them all), copied as you see it now. The views you pick stay as they are.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={saving}
                        aria-label="Close"
                        className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-2">
                    <label className="block">
                        <span className="text-sm font-medium text-gray-700">Name</span>
                        <input
                            data-autofocus
                            value={name}
                            maxLength={NAME_LIMIT}
                            onChange={e => setName(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); create(); } }}
                            placeholder="e.g. Supply chain overview"
                            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20"
                        />
                    </label>

                    <section aria-label="Views to combine">
                        <div className="flex items-baseline justify-between">
                            <h3 className="text-sm font-medium text-gray-700">Tabs, in order</h3>
                            <span className={clsx('text-xs', full ? 'font-medium text-amber-700' : 'text-gray-400')}>
                                {picked.length} picked · at most {MAX_COMBINED} tabs in all
                            </span>
                        </div>
                        {picked.length === 0 ? (
                            <p className="mt-1 rounded-lg border border-dashed border-gray-300 px-3 py-4 text-center text-sm text-gray-500">
                                Search below and add the views to combine.
                            </p>
                        ) : (
                            <ol className="mt-1 divide-y divide-gray-100 rounded-lg border border-gray-200">
                                {picked.map((row, i) => (
                                    <li key={row.id} className="flex items-center gap-2 px-3 py-2">
                                        <span className="w-5 shrink-0 text-right text-xs tabular-nums text-gray-400">{i + 1}</span>
                                        <div className="min-w-0 flex-1">
                                            <div className="truncate text-sm font-medium text-gray-900">{row.name}</div>
                                            <Byline row={row} />
                                        </div>
                                        <button type="button" aria-label={`Move ${row.name} up`} disabled={i === 0} onClick={() => setPicked(p => movePick(p, row.id, -1))} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-30">
                                            <ArrowUp size={14} />
                                        </button>
                                        <button type="button" aria-label={`Move ${row.name} down`} disabled={i === picked.length - 1} onClick={() => setPicked(p => movePick(p, row.id, 1))} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-30">
                                            <ArrowDown size={14} />
                                        </button>
                                        <button type="button" aria-label={`Remove ${row.name}`} onClick={() => setPicked(p => p.filter(r => r.id !== row.id))} className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600">
                                            <X size={14} />
                                        </button>
                                    </li>
                                ))}
                            </ol>
                        )}
                    </section>

                    <section aria-label="Add views">
                        <h3 className="mb-1 text-sm font-medium text-gray-700">Add views</h3>
                        <ViewSearchBox
                            label="Find views to add"
                            placeholder="Search views you can open"
                            value={text}
                            onChange={setText}
                            onSubmit={search}
                            onPick={row => { add(row); setText(''); }}
                            exclude={pickedIds}
                        />
                        {searching && <div className="flex justify-center py-3 text-gray-400"><Loader2 className="h-4 w-4 animate-spin" aria-label="Searching" /></div>}
                        {!searching && found && (
                            found.rows.length === 0 ? (
                                <p className="py-3 text-center text-sm text-gray-500">No views match “{found.q}”.</p>
                            ) : (
                                <ul className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-200">
                                    {found.rows.map(row => {
                                        const added = pickedIds.includes(row.id);
                                        return (
                                            <li key={row.id} className="flex items-center gap-3 px-3 py-2">
                                                <div className="min-w-0 flex-1">
                                                    <div className="truncate text-sm text-gray-900">{row.name}</div>
                                                    <Byline row={row} />
                                                </div>
                                                <button
                                                    type="button"
                                                    disabled={added || full}
                                                    onClick={() => add(row)}
                                                    className="flex shrink-0 items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-default disabled:border-transparent disabled:text-gray-400"
                                                >
                                                    {added ? <><Check size={12} /> Added</> : <><Plus size={12} /> Add</>}
                                                </button>
                                            </li>
                                        );
                                    })}
                                    {found.more && (
                                        <li className="px-3 py-2 text-xs text-gray-500">Showing the best {FOUND_LIMIT} matches. Add words to find others.</li>
                                    )}
                                </ul>
                            )
                        )}
                    </section>

                    <fieldset>
                        <legend className="text-sm font-medium text-gray-700">Opens</legend>
                        <div className="mt-1 flex gap-4 text-sm text-gray-700">
                            {([[false, 'In the workspace'], [true, 'On its own page']] as const).map(([value, label]) => (
                                <label key={label} className="flex cursor-pointer items-center gap-2">
                                    <input
                                        type="radio"
                                        name={`${titleId}-opens`}
                                        checked={standalone === value}
                                        onChange={() => setStandalone(value)}
                                        className="h-3.5 w-3.5 border-gray-300 text-brand-blue focus:ring-brand-blue/30"
                                    />
                                    {label}
                                </label>
                            ))}
                        </div>
                    </fieldset>
                </div>

                {error && <p className="mx-6 mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{error}</p>}
                <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-6 py-4">
                    <span className="mr-auto text-xs text-gray-500">It starts as a draft only you can see.</span>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={saving}
                        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={create}
                        disabled={saving || !name.trim() || picked.length === 0}
                        className="flex items-center gap-1.5 rounded-lg bg-brand-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                        Create view
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
};
