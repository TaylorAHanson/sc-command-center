import React, { useEffect, useId, useImperativeHandle, useRef, useState } from 'react';
import { Globe, Info, Loader2, User, Users } from 'lucide-react';
import clsx from 'clsx';
import {
    EVERYONE, EVERYONE_LABEL, inferPrincipalType, principalLabel, samePrincipal, searchPrincipals,
    type PrincipalSuggestion, type PrincipalType,
} from '../../sharing';

export interface PickedPrincipal {
    principal: string;
    principal_type: PrincipalType;
}

export interface PrincipalPickerHandle {
    /** Submit what Enter would: the highlighted suggestion, else the typed text. False if empty. */
    submit: () => boolean;
    focus: () => void;
}

export interface PrincipalPickerProps {
    value: string;
    onChange: (text: string) => void;
    onSubmit: (picked: PickedPrincipal) => void;
    placeholder?: string;
    autoFocus?: boolean;
    /** Principals not to suggest, e.g. those already on the list. */
    exclude?: string[];
    /** Offer Everyone (`*`) when the server suggests it. */
    allowEveryone?: boolean;
    disabled?: boolean;
    ariaLabel?: string;
    className?: string;
    ref?: React.Ref<PrincipalPickerHandle>;
}

const DEBOUNCE_MS = 150;
const CACHE_MS = 30_000;
// Suggestions come from `known_principals`, which only grows as people visit, so a
// short cache spares a request per keystroke-back without hiding anyone for long.
const cache = new Map<string, { at: number; items: PrincipalSuggestion[] }>();

const cached = (q: string): PrincipalSuggestion[] | null => {
    const hit = cache.get(q);
    return hit && Date.now() - hit.at < CACHE_MS ? hit.items : null;
};

const labelOf = (item: PrincipalSuggestion) => principalLabel(item.principal).toLowerCase();

const IconFor: React.FC<{ type: PrincipalType }> = ({ type }) => {
    const Icon = type === 'all' ? Globe : type === 'group' ? Users : User;
    return <Icon size={14} aria-hidden="true" className="shrink-0 text-gray-400" />;
};

/**
 * Typeahead over the principals this app has seen. A deployed App can't list
 * workspace users or groups, so free text is always allowed: anyone who has never
 * opened the app can still be named exactly.
 */
export const PrincipalPicker: React.FC<PrincipalPickerProps> = ({
    value, onChange, onSubmit, placeholder = 'Add people or groups', autoFocus, exclude, allowEveryone = false,
    disabled, ariaLabel = 'Person or group', className, ref,
}) => {
    const [open, setOpen] = useState(false);
    const [results, setResults] = useState<{ q: string; items: PrincipalSuggestion[]; error?: string } | null>(null);
    // Arrow-key choice and Escape both belong to the text they were made under, so
    // typing another letter returns the highlight to the best match.
    const [arrowed, setArrowed] = useState<{ q: string; index: number } | null>(null);
    const [dismissedFor, setDismissedFor] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const listId = useId();
    const hintId = useId();

    const q = value.trim();
    const ql = q.toLowerCase();

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        const hit = cached(q);
        const timer = window.setTimeout(() => {
            if (hit) { setResults({ q, items: hit }); return; }
            searchPrincipals(q)
                .then(items => {
                    cache.set(q, { at: Date.now(), items });
                    if (!cancelled) setResults({ q, items });
                })
                .catch(e => { if (!cancelled) setResults({ q, items: [], error: e?.message || String(e) }); });
        }, hit ? 0 : DEBOUNCE_MS);
        return () => { cancelled = true; window.clearTimeout(timer); };
    }, [q, open]);

    const settled = results?.q === q;
    const searching = open && !settled;
    const shown = (results?.items || []).filter(item => {
        if (item.principal === EVERYONE && !allowEveryone) return false;
        if (exclude?.some(p => samePrincipal(p, item.principal))) return false;
        // While the next answer is on its way, narrow the last one instead of flashing empty.
        return settled || !ql || labelOf(item).includes(ql) || item.principal.toLowerCase().includes(ql);
    });

    // Typing highlights a suggestion that completes what was typed, so Enter (and
    // Add) finishes a name instead of granting the fragment. Escape drops it, and
    // then the text is used exactly as typed.
    const bestMatch = (() => {
        if (!ql || dismissedFor === q) return -1;
        const exact = shown.findIndex(i => samePrincipal(i.principal, q) || labelOf(i) === ql);
        if (exact >= 0) return exact;
        return shown.findIndex(i => labelOf(i).startsWith(ql) || i.principal.toLowerCase().startsWith(ql));
    })();
    const highlight = arrowed && arrowed.q === q && arrowed.index < shown.length ? arrowed.index : bestMatch;
    const listOpen = open && !disabled && (shown.length > 0 || Boolean(results?.error && settled));
    const unknown = Boolean(q) && settled && highlight < 0
        && !shown.some(i => samePrincipal(i.principal, q)) && q !== EVERYONE;

    useEffect(() => {
        if (highlight >= 0) listRef.current?.querySelector('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' });
    }, [highlight, listOpen]);

    const pick = (item: PrincipalSuggestion) => {
        setArrowed(null);
        setOpen(false);
        onSubmit({ principal: item.principal, principal_type: item.principal_type });
    };

    const submit = (): boolean => {
        if (highlight >= 0 && shown[highlight]) { pick(shown[highlight]); return true; }
        if (!q) return false;
        setOpen(false);
        onSubmit({ principal: q, principal_type: inferPrincipalType(q) });
        return true;
    };

    useImperativeHandle(ref, () => ({ submit, focus: () => inputRef.current?.focus() }));

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!open) { setOpen(true); return; }
            if (!shown.length) return;
            const next = e.key === 'ArrowDown' ? highlight + 1 : highlight - 1;
            setArrowed({ q, index: Math.max(0, Math.min(shown.length - 1, next)) });
            setDismissedFor(null);
        } else if (e.key === 'Enter') {
            // Swallowed always: this sits in dialogs and pages with their own Enter handling.
            e.preventDefault();
            e.stopPropagation();
            submit();
        } else if (e.key === 'Escape' && listOpen) {
            // Stop here so the dialog around us stays open; a second Escape closes it.
            e.stopPropagation();
            setOpen(false);
            setArrowed(null);
            setDismissedFor(q);
        }
    };

    const active = listOpen && highlight >= 0 ? `${listId}-${highlight}` : undefined;

    return (
        <div className={clsx('relative', className)}>
            <div className="relative">
                <input
                    ref={inputRef}
                    type="text"
                    role="combobox"
                    aria-label={ariaLabel}
                    aria-expanded={listOpen}
                    aria-controls={listId}
                    aria-autocomplete="list"
                    aria-activedescendant={active}
                    aria-describedby={unknown ? hintId : undefined}
                    autoComplete="off"
                    spellCheck={false}
                    autoFocus={autoFocus}
                    data-autofocus={autoFocus ? true : undefined}
                    disabled={disabled}
                    value={value}
                    placeholder={placeholder}
                    onChange={e => { onChange(e.target.value); setOpen(true); setDismissedFor(null); }}
                    onFocus={() => setOpen(true)}
                    onClick={() => setOpen(true)}
                    onBlur={() => setOpen(false)}
                    onKeyDown={onKeyDown}
                    className="w-full rounded-lg border border-gray-300 bg-white pl-3 pr-8 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/20 disabled:bg-gray-50 disabled:text-gray-400"
                />
                {searching && (
                    <Loader2 size={14} aria-hidden="true" className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-gray-400" />
                )}
            </div>

            {listOpen && (
                <div
                    ref={listRef}
                    id={listId}
                    role="listbox"
                    aria-label="Suggestions"
                    className="absolute z-30 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
                >
                    {results?.error && settled && (
                        <div className="px-3 py-2 text-xs text-amber-700">
                            Couldn’t search: {results.error}. You can still type a name.
                        </div>
                    )}
                    {shown.map((item, idx) => (
                        <div
                            key={item.principal}
                            id={`${listId}-${idx}`}
                            role="option"
                            aria-selected={idx === highlight}
                            data-highlighted={idx === highlight}
                            onMouseEnter={() => setArrowed({ q, index: idx })}
                            // Commit on mousedown: pressing down blurs the input, which
                            // closes the list before a click would ever fire.
                            onMouseDown={e => { e.preventDefault(); pick(item); }}
                            className={clsx(
                                'flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm text-gray-900',
                                idx === highlight && 'bg-gray-100',
                            )}
                        >
                            <IconFor type={item.principal_type} />
                            <span className="min-w-0 flex-1 truncate">
                                {item.principal === EVERYONE ? EVERYONE_LABEL : item.principal}
                            </span>
                            {item.mine && item.principal_type === 'group' && (
                                <span className="shrink-0 rounded bg-brand-blue/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-navy">
                                    Your group
                                </span>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {unknown && !disabled && (
                <p id={hintId} className="mt-1 flex items-start gap-1 text-[11px] leading-snug text-amber-700">
                    <Info size={12} aria-hidden="true" className="mt-px shrink-0" />
                    Not seen in this app yet — must match the Databricks user or group name exactly.
                </p>
            )}
        </div>
    );
};

export default PrincipalPicker;
