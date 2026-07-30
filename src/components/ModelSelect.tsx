import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Loader2 } from 'lucide-react';
import clsx from 'clsx';

/**
 * Typeahead picker for a model, backed by the workspace's chat-capable serving
 * endpoints (`GET /api/settings/models`).
 *
 * Free text still commits. A workspace can hold endpoints the listing misses, the
 * listing itself can fail, and the value was a plain text field before this
 * component existed — so the list assists rather than constrains, and anything
 * typed that isn't on it gets a warning rather than a block.
 */

export interface ModelOption {
    /** The value to store — the AI Gateway alias for foundation models. */
    name: string;
    /** Underlying serving endpoint name, shown as the secondary line. */
    endpoint: string;
    route: 'gateway' | 'serving';
    task?: string;
    ready?: boolean | null;
    foundation?: boolean;
}

// One fetch per page load, shared by every mounted picker: the Admin Settings page
// alone renders three of these, and the list changes about as often as the
// workspace gains a model.
let cachedModels: ModelOption[] | null = null;
let inFlight: Promise<ModelOption[]> | null = null;

const fetchModels = (force = false): Promise<ModelOption[]> => {
    if (cachedModels && !force) return Promise.resolve(cachedModels);
    if (inFlight && !force) return inFlight;
    inFlight = fetch(`/api/settings/models${force ? '?refresh=true' : ''}`)
        .then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data?.detail || `${res.statusText} (HTTP ${res.status})`);
            const models: ModelOption[] = Array.isArray(data?.models) ? data.models : [];
            cachedModels = models;
            return models;
        })
        .finally(() => { inFlight = null; });
    return inFlight;
};

interface ModelSelectProps {
    value: string;
    onChange: (next: string) => void;
    variant?: 'light' | 'dark';
    placeholder?: string;
    /** Rendered as the first option; picking it commits an empty value. */
    blankLabel?: string;
    ariaLabel?: string;
    className?: string;
}

export const ModelSelect: React.FC<ModelSelectProps> = ({
    value, onChange, variant = 'light', placeholder = 'Search models…', blankLabel, ariaLabel = 'Model', className,
}) => {
    const [models, setModels] = useState<ModelOption[]>(cachedModels || []);
    const [loading, setLoading] = useState(!cachedModels);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    // null means "showing the committed value"; a string means the user is typing.
    const [query, setQuery] = useState<string | null>(null);
    // Mirrored in a ref because blur is dispatched synchronously: `setQuery(null)`
    // has not applied yet when the blur handler runs, so reading the state there
    // sees the text the user typed and writes it over the option just chosen.
    const queryRef = useRef<string | null>(null);
    const setTyped = (next: string | null) => { queryRef.current = next; setQuery(next); };
    // Arrow-key selection, remembered against the query it was made under so that
    // typing another letter drops it and the highlight goes back to the best match.
    const [arrowed, setArrowed] = useState<{ query: string | null; index: number } | null>(null);
    const wrapRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);

    const load = useCallback((force = false) => {
        setLoading(true);
        fetchModels(force)
            .then((items) => { setModels(items); setLoadError(null); })
            .catch((e) => setLoadError(e?.message || String(e)))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => { if (!cachedModels) load(); }, [load]);

    useEffect(() => {
        if (!open) return;
        // Closing only. What happens to half-typed text on the way out is the
        // input's blur handler's job, and having both decide meant whichever ran
        // first won.
        const onDown = (e: MouseEvent) => {
            if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [open]);

    const options = useMemo(() => {
        const q = (query || '').trim().toLowerCase();
        if (!q) return models;
        return models.filter(m => `${m.name} ${m.endpoint}`.toLowerCase().includes(q));
    }, [models, query]);

    // +1 row for the blank option, which lives at index 0 when offered.
    const rows = blankLabel ? [null, ...options] : options;

    // Typing highlights the best match, so Enter completes to a real model rather
    // than storing the fragment that was typed. Nothing typed, or nothing matched,
    // means no highlight, and then Enter commits the text as it stands.
    //
    // Two exceptions keep a fully typed name from being rewritten: text that is
    // already a model's name highlights that model rather than whichever match
    // sorts first, and text that is a serving endpoint's own name highlights
    // nothing, so Enter stores the endpoint instead of the AI Gateway alias whose
    // row it matched.
    const firstModelRow = blankLabel ? 1 : 0;
    const bestMatch = useMemo(() => {
        const q = (query || '').trim().toLowerCase();
        if (!q || !options.length) return -1;
        const named = options.findIndex(m => m.name.toLowerCase() === q);
        if (named >= 0) return named + firstModelRow;
        if (options.some(m => m.endpoint.toLowerCase() === q)) return -1;
        return firstModelRow;
    }, [query, options, firstModelRow]);
    const highlight = arrowed && arrowed.query === query ? arrowed.index : bestMatch;

    useEffect(() => {
        listRef.current?.querySelector('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' });
    }, [highlight, open]);

    // Focus stays in the field: blurring made the page feel like it had reset, and
    // it is what let the stale-query blur handler undo the choice.
    const commit = (next: string) => {
        setTyped(null);
        setArrowed(null);
        setOpen(false);
        onChange(next);
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!open) { setOpen(true); return; }
            const next = e.key === 'ArrowDown' ? highlight + 1 : highlight - 1;
            setArrowed({ query, index: Math.max(0, Math.min(rows.length - 1, next)) });
        } else if (e.key === 'Enter') {
            // Always swallow Enter: this control sits on pages that also hold forms
            // and page-level key handlers, and an escaping Enter submits or
            // navigates, which reads as the whole screen resetting.
            e.preventDefault();
            e.stopPropagation();
            // Nothing highlighted means nothing matched what was typed (or nothing
            // was typed), so commit the text as-is: a custom endpoint name doesn't
            // need the list's blessing.
            if (open && highlight >= 0 && highlight < rows.length) {
                const row = rows[highlight];
                commit(row ? row.name : '');
            } else {
                commit((query ?? value).trim());
            }
        } else if (e.key === 'Escape') {
            if (open) { e.stopPropagation(); }
            setOpen(false);
            setTyped(null);
        }
    };

    const dark = variant === 'dark';
    const known = models.some(m => m.name === value || m.endpoint === value);
    const shown = query ?? value;

    return (
        <div ref={wrapRef} className={clsx('relative', className)}>
            <div className="relative">
                <input
                    ref={inputRef}
                    role="combobox"
                    aria-expanded={open}
                    aria-label={ariaLabel}
                    autoComplete="off"
                    value={shown}
                    placeholder={placeholder}
                    onChange={(e) => { setTyped(e.target.value); setOpen(true); }}
                    onFocus={() => setOpen(true)}
                    // Focus survives a commit, so a second click on the field fires
                    // no focus event — without this the list would not reopen.
                    onClick={() => setOpen(true)}
                    onBlur={() => {
                        // Options cancel their own mousedown and commit clears the
                        // ref, so text still pending here was typed and then
                        // abandoned — keep it, since a custom endpoint name never
                        // appears in the list.
                        if (queryRef.current !== null) { onChange(queryRef.current.trim()); setTyped(null); }
                        setOpen(false);
                    }}
                    onKeyDown={onKeyDown}
                    className={clsx(
                        'w-full rounded-md border pl-3 pr-9 py-2 text-sm font-mono focus:outline-none',
                        dark
                            ? 'bg-slate-900 border-slate-700 text-slate-100 placeholder-slate-500 focus:border-blue-500'
                            : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400 focus:border-qualcomm-blue',
                    )}
                />
                <button
                    type="button"
                    tabIndex={-1}
                    aria-label="Show models"
                    onClick={() => { setOpen(o => !o); inputRef.current?.focus(); }}
                    className={clsx('absolute right-2 top-1/2 -translate-y-1/2', dark ? 'text-slate-400' : 'text-gray-400')}
                >
                    {loading ? <Loader2 size={15} className="animate-spin" /> : <ChevronDown size={15} />}
                </button>
            </div>

            {open && (
                <div
                    ref={listRef}
                    role="listbox"
                    className={clsx(
                        'absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-md border shadow-lg',
                        dark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
                    )}
                >
                    {loadError && (
                        <div className={clsx('px-3 py-2 text-xs', dark ? 'text-amber-300' : 'text-amber-700')}>
                            Could not list models: {loadError}
                            <button type="button" onClick={() => load(true)} className="ml-2 underline">Retry</button>
                            <div className={clsx('mt-1', dark ? 'text-slate-400' : 'text-gray-500')}>
                                You can still type an endpoint name.
                            </div>
                        </div>
                    )}
                    {/* On `options`, not `rows`: where a blank row is offered it would
                        otherwise stand in for the list and hide both messages. */}
                    {!loadError && options.length === 0 && (
                        <div className={clsx('px-3 py-2 text-xs', dark ? 'text-slate-400' : 'text-gray-500')}>
                            {loading ? 'Loading models…' : 'No matching models. Press Enter to use what you typed.'}
                        </div>
                    )}
                    {rows.map((row, idx) => {
                        const selected = row ? row.name === value : !value;
                        return (
                            <button
                                key={row ? row.name : '__blank__'}
                                type="button"
                                role="option"
                                aria-selected={selected}
                                data-highlighted={idx === highlight}
                                onMouseEnter={() => setArrowed({ query, index: idx })}
                                // Commit on mousedown, not click: pressing down
                                // blurs the input, whose handler keeps the typed
                                // filter text and closes the list — so by the time
                                // a click would fire, this option is already gone
                                // and the typed text has won. preventDefault also
                                // stops the focus change itself.
                                onMouseDown={(e) => { e.preventDefault(); commit(row ? row.name : ''); }}
                                className={clsx(
                                    'flex w-full items-center gap-2 px-3 py-2 text-left text-sm',
                                    idx === highlight && (dark ? 'bg-slate-800' : 'bg-gray-100'),
                                    dark ? 'text-slate-100' : 'text-gray-900',
                                )}
                            >
                                <Check size={13} className={clsx(selected ? 'opacity-100' : 'opacity-0', dark ? 'text-blue-400' : 'text-qualcomm-blue')} />
                                {row ? (
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate font-mono text-[13px]">{row.name}</span>
                                        {/* slate-400, not 500: at 11px on this panel
                                            slate-500 measures 3.75:1, under AA. */}
                                        <span className={clsx('block truncate text-[11px]', dark ? 'text-slate-400' : 'text-gray-500')}>
                                            {row.route === 'gateway' ? `AI Gateway · endpoint ${row.endpoint}` : 'Serving endpoint'}
                                            {row.ready === false ? ' · not ready' : ''}
                                        </span>
                                    </span>
                                ) : (
                                    <span className={clsx('flex-1 text-[13px]', dark ? 'text-slate-300' : 'text-gray-700')}>{blankLabel}</span>
                                )}
                            </button>
                        );
                    })}
                </div>
            )}

            {!open && value && !known && !loading && !loadError && (
                <p className={clsx('mt-1 flex items-start gap-1 text-[11px]', dark ? 'text-amber-300' : 'text-amber-700')}>
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    Not in this workspace's model list. It will be used exactly as typed.
                </p>
            )}
        </div>
    );
};
