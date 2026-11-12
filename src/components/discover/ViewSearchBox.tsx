import React, { useEffect, useId, useState } from 'react';
import { Loader2, Search, ShieldCheck, X } from 'lucide-react';
import clsx from 'clsx';
import { suggestViews, type ViewRow } from '../../discover';

const SUGGEST_DELAY_MS = 120;

/**
 * A search box over views. Typing suggests up to eight (the server's word-prefix
 * match, which answers in every search mode); Enter runs the full search.
 * Discover's header and Combine views both use it, so finding a view works the
 * same everywhere and nothing lists every view to pick from.
 *
 * A suggestion commits on mousedown, not click: pressing down blurs the input,
 * whose handler closes the list, so a click handler would never run.
 */
export const ViewSearchBox: React.FC<{
    value: string;
    onChange: (text: string) => void;
    /** Enter with no suggestion highlighted, and clearing the box (with ''). */
    onSubmit: (text: string) => void;
    /** A suggestion chosen with the mouse, or highlighted and Enter. */
    onPick: (row: ViewRow) => void;
    label: string;
    placeholder?: string;
    autoFocus?: boolean;
    /** Suggestions to leave out, such as views already picked. */
    exclude?: string[];
    size?: 'lg' | 'md';
    className?: string;
}> = ({ value, onChange, onSubmit, onPick, label, placeholder, autoFocus, exclude, size = 'md', className }) => {
    const listId = useId();
    const [open, setOpen] = useState(false);
    const [found, setFound] = useState<{ q: string; rows: ViewRow[] } | null>(null);
    // Kept with the text it was chosen for, so new suggestions start unhighlighted.
    const [active, setActive] = useState<{ q: string; index: number }>({ q: '', index: -1 });
    const q = value.trim();

    useEffect(() => {
        if (!open || !q) return;
        const ctrl = new AbortController();
        const timer = window.setTimeout(() => {
            suggestViews(q, { signal: ctrl.signal })
                .then(res => setFound({ q, rows: res.results }))
                .catch(() => { if (!ctrl.signal.aborted) setFound({ q, rows: [] }); });
        }, SUGGEST_DELAY_MS);
        return () => { window.clearTimeout(timer); ctrl.abort(); };
    }, [q, open]);

    const rows = open && q && found?.q === q ? found.rows.filter(r => !exclude?.includes(r.id)) : [];
    const waiting = open && !!q && found?.q !== q;
    const index = active.q === q ? Math.min(active.index, rows.length - 1) : -1;
    const shown = open && !!q && (rows.length > 0 || !waiting);

    const pick = (row: ViewRow) => {
        setOpen(false);
        onPick(row);
    };
    const submit = (text: string) => {
        setOpen(false);
        onSubmit(text);
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
            const step = e.key === 'ArrowDown' ? 1 : -1;
            setActive({ q, index: Math.max(-1, Math.min(rows.length - 1, index + step)) });
        } else if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            if (index >= 0 && rows[index]) pick(rows[index]);
            // The input's own value: a keystroke can arrive before the render carrying the last one.
            else submit(e.currentTarget.value);
        } else if (e.key === 'Escape') {
            if (shown) {
                e.stopPropagation();
                setOpen(false);
            } else if (value) {
                e.stopPropagation();
                onChange('');
            }
        }
    };

    const big = size === 'lg';
    return (
        <div className={clsx('relative', className)}>
            <Search className={clsx('pointer-events-none absolute top-1/2 -translate-y-1/2 text-gray-400', big ? 'left-4 h-5 w-5' : 'left-3 h-4 w-4')} aria-hidden="true" />
            <input
                type="search"
                role="combobox"
                aria-label={label}
                aria-expanded={shown}
                aria-controls={listId}
                aria-autocomplete="list"
                aria-activedescendant={index >= 0 ? `${listId}-${index}` : undefined}
                autoFocus={autoFocus}
                value={value}
                placeholder={placeholder}
                onChange={e => { onChange(e.target.value); setOpen(true); }}
                onFocus={() => setOpen(true)}
                onBlur={() => setOpen(false)}
                onKeyDown={onKeyDown}
                className={clsx(
                    'w-full rounded-xl border border-gray-300 bg-white text-gray-900 placeholder:text-gray-400 shadow-sm',
                    'focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20 [&::-webkit-search-cancel-button]:hidden',
                    big ? 'py-3 pl-12 pr-12 text-base' : 'py-2 pl-9 pr-9 text-sm',
                )}
            />
            {waiting && <Loader2 className={clsx('absolute top-1/2 -translate-y-1/2 animate-spin text-gray-400', big ? 'right-12 h-4 w-4' : 'right-9 h-3.5 w-3.5')} aria-hidden="true" />}
            {value && (
                <button
                    type="button"
                    aria-label="Clear search"
                    onMouseDown={e => { e.preventDefault(); onChange(''); onSubmit(''); }}
                    className={clsx('absolute top-1/2 -translate-y-1/2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700', big ? 'right-3' : 'right-2')}
                >
                    <X className={big ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
                </button>
            )}
            {shown && (
                <div className="absolute left-0 right-0 top-full z-40 mt-1 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
                    <ul id={listId} role="listbox" aria-label={`Views matching ${q}`} className="max-h-80 overflow-y-auto py-1">
                        {rows.map((row, i) => (
                            <li
                                key={row.id}
                                id={`${listId}-${i}`}
                                role="option"
                                aria-selected={i === index}
                                onMouseDown={e => { e.preventDefault(); pick(row); }}
                                onMouseEnter={() => setActive({ q, index: i })}
                                className={clsx('flex cursor-pointer items-center gap-3 px-4 py-2', i === index ? 'bg-brand-blue/10' : 'hover:bg-gray-50')}
                            >
                                <div className="min-w-0 flex-1">
                                    <div className="truncate text-sm font-medium text-gray-900">{row.name}</div>
                                    <div className="truncate text-xs text-gray-500">{[row.owner, row.domain].filter(Boolean).join(' · ')}</div>
                                </div>
                                {row.certified && <ShieldCheck className="h-4 w-4 shrink-0 text-green-600" aria-label="Certified" />}
                            </li>
                        ))}
                        {rows.length === 0 && <li className="px-4 py-2 text-sm text-gray-500">No quick matches. Search to look further.</li>}
                    </ul>
                    <button
                        type="button"
                        onMouseDown={e => { e.preventDefault(); submit(value); }}
                        className="flex w-full items-center gap-2 border-t border-gray-100 px-4 py-2 text-left text-sm text-brand-blue hover:bg-gray-50"
                    >
                        <Search className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="truncate">Search for “{q}”</span>
                        <span className="ml-auto text-xs text-gray-400">Enter</span>
                    </button>
                </div>
            )}
        </div>
    );
};
