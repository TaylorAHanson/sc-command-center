import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, CircleX, Loader2, Users, User } from 'lucide-react';
import clsx from 'clsx';
import type { PrincipalVerdict } from '../principals';

/**
 * Typeahead for the name a role mapping grants to: a Databricks group, or one
 * user's username. Suggestions come from SCIM (`GET /api/roles/principals`), and
 * whatever is in the field is checked as you type (`/api/roles/principals/check`).
 *
 * Unlike `ModelSelect`, free text is not the point here. A mapping is compared
 * with a user's groups *exactly*, so a name that isn't a real group — or is one
 * spelled with different capitals — saves fine and then grants nothing to anyone.
 * The check reports that before the save, and `onVerdict` lets the form refuse
 * it. The server makes the same check on save; this is so the admin finds out
 * while typing rather than from an error.
 *
 * Two interaction details are borrowed from `ModelSelect` for the same reasons:
 * options commit on mousedown (a click would arrive after the list had closed),
 * and Enter never escapes to the surrounding form. The field is controlled by the
 * parent throughout — there is no separate "typed" state to reconcile on blur,
 * because every keystroke is a candidate name to be checked.
 *
 * Gate saving with `principalAllowsSave(verdict, value)` from `principals.ts`,
 * which also refuses a verdict that describes earlier text.
 */

interface Suggestions {
    groups: string[];
    users: string[];
    available: boolean;
    error?: string;
}

interface PrincipalSelectProps {
    value: string;
    onChange: (next: string) => void;
    onVerdict?: (verdict: PrincipalVerdict) => void;
    placeholder?: string;
    ariaLabel?: string;
    compact?: boolean;
    autoFocus?: boolean;
}

const DEBOUNCE_MS = 250;

export const PrincipalSelect: React.FC<PrincipalSelectProps> = ({
    value, onChange, onVerdict, placeholder = 'Search Databricks groups and users…', ariaLabel = 'Group or user', compact, autoFocus,
}) => {
    const [open, setOpen] = useState(false);
    const [suggestions, setSuggestions] = useState<Suggestions | null>(null);
    const [searching, setSearching] = useState(false);
    // The last answer from the server. What is shown is derived from it and the
    // current text, so a verdict about what was typed a moment ago is never shown
    // (or reported) as a verdict about what is there now.
    const [checked, setChecked] = useState<PrincipalVerdict | null>(null);
    // Arrow-key highlight, remembered against the list it was made in so a new
    // set of suggestions starts unhighlighted.
    const [arrowed, setArrowed] = useState<{ rows: unknown; index: number } | null>(null);
    const wrapRef = useRef<HTMLDivElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    // Responses can land out of order when someone types quickly; only the newest
    // request may write its answer.
    const searchRun = useRef(0);
    const checkRun = useRef(0);
    const onVerdictRef = useRef(onVerdict);
    useEffect(() => { onVerdictRef.current = onVerdict; });

    const trimmed = value.trim();
    const verdict: PrincipalVerdict = !trimmed
        ? { status: 'empty', name: '' }
        : checked && checked.name === trimmed ? checked : { status: 'checking', name: trimmed };

    // Suggestions follow the text in the field.
    useEffect(() => {
        if (!open) return;
        const run = ++searchRun.current;
        const timer = window.setTimeout(async () => {
            setSearching(true);
            try {
                const res = await fetch(`/api/roles/principals?q=${encodeURIComponent(value.trim())}`);
                const data = await res.json().catch(() => ({}));
                if (run !== searchRun.current) return;
                if (!res.ok) {
                    setSuggestions({ groups: [], users: [], available: false, error: data?.detail || `HTTP ${res.status}` });
                } else {
                    setSuggestions({
                        groups: Array.isArray(data.groups) ? data.groups : [],
                        users: Array.isArray(data.users) ? data.users : [],
                        available: data.available !== false,
                        error: data.error,
                    });
                }
            } catch (e) {
                if (run === searchRun.current) setSuggestions({ groups: [], users: [], available: false, error: e instanceof Error ? e.message : String(e) });
            } finally {
                if (run === searchRun.current) setSearching(false);
            }
        }, DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [value, open]);

    // Every committed value is checked, so the form always knows whether what it
    // would save is real.
    useEffect(() => {
        const name = value.trim();
        const run = ++checkRun.current;
        if (!name) return;
        const settle = (next: PrincipalVerdict) => {
            if (run !== checkRun.current) return;
            setChecked(next);
            onVerdictRef.current?.(next);
        };
        const timer = window.setTimeout(async () => {
            try {
                const res = await fetch(`/api/roles/principals/check?name=${encodeURIComponent(name)}`);
                const data = await res.json().catch(() => ({}));
                if (!res.ok) settle({ status: 'unverified', name, detail: data?.detail || 'Could not check this name against Databricks.' });
                else settle({ status: data.status, name, detail: data.detail, suggestion: data.suggestion });
            } catch {
                settle({ status: 'unverified', name, detail: 'Could not check this name against Databricks.' });
            }
        }, DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [value]);

    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, [open]);

    const rows = useMemo(() => [
        ...(suggestions?.groups || []).map(name => ({ name, kind: 'group' as const })),
        ...(suggestions?.users || []).map(name => ({ name, kind: 'user' as const })),
    ], [suggestions]);

    const highlight = arrowed && arrowed.rows === rows ? arrowed.index : -1;
    const setHighlight = (index: number) => setArrowed({ rows, index });
    useEffect(() => {
        listRef.current?.querySelector('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' });
    }, [highlight]);

    const commit = (next: string) => {
        setOpen(false);
        onChange(next);
    };

    const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!open) { setOpen(true); return; }
            const next = e.key === 'ArrowDown' ? highlight + 1 : highlight - 1;
            setHighlight(Math.max(0, Math.min(rows.length - 1, next)));
        } else if (e.key === 'Enter') {
            // Swallowed: this sits inside the mapping forms, and an Enter that
            // escaped would submit a half-typed name.
            e.preventDefault();
            e.stopPropagation();
            if (open && highlight >= 0 && highlight < rows.length) commit(rows[highlight].name);
            else setOpen(false);
        } else if (e.key === 'Escape') {
            if (open) e.stopPropagation();
            setOpen(false);
        }
    };

    return (
        <div ref={wrapRef} className="relative">
            <input
                role="combobox"
                aria-expanded={open}
                aria-label={ariaLabel}
                autoComplete="off"
                spellCheck={false}
                autoFocus={autoFocus}
                value={value}
                placeholder={placeholder}
                onChange={(e) => { onChange(e.target.value); setOpen(true); }}
                onFocus={() => setOpen(true)}
                onClick={() => setOpen(true)}
                onKeyDown={onKeyDown}
                className={clsx(
                    'w-full bg-white border rounded-md font-mono focus:outline-none focus:ring-1',
                    compact ? 'px-2 py-1 text-sm' : 'px-3 py-2 text-sm',
                    verdict.status === 'unknown' || verdict.status === 'mismatch'
                        ? 'border-red-300 focus:ring-red-400 focus:border-red-400'
                        : 'border-gray-300 focus:ring-qualcomm-blue focus:border-qualcomm-blue',
                )}
            />

            {open && (
                <div ref={listRef} role="listbox" className="absolute z-30 mt-1 max-h-64 w-full min-w-[16rem] overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                    {suggestions && !suggestions.available && (
                        <div className="px-3 py-2 text-xs text-amber-700">
                            Couldn't search Databricks{suggestions.error ? `: ${suggestions.error}` : ''}. You can still type a name.
                        </div>
                    )}
                    {suggestions?.available && rows.length === 0 && !searching && (
                        <div className="px-3 py-2 text-xs text-gray-500">No groups or users match.</div>
                    )}
                    {searching && rows.length === 0 && (
                        <div className="px-3 py-2 text-xs text-gray-500">Searching…</div>
                    )}
                    {rows.map((row, idx) => (
                        <button
                            key={`${row.kind}:${row.name}`}
                            type="button"
                            role="option"
                            aria-selected={row.name === value}
                            data-highlighted={idx === highlight}
                            onMouseEnter={() => setHighlight(idx)}
                            onMouseDown={(e) => { e.preventDefault(); commit(row.name); }}
                            className={clsx(
                                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-gray-900',
                                idx === highlight && 'bg-gray-100',
                            )}
                        >
                            {row.kind === 'group'
                                ? <Users size={13} className="shrink-0 text-gray-400" />
                                : <User size={13} className="shrink-0 text-gray-400" />}
                            <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{row.name}</span>
                            <span className="text-[11px] text-gray-400">{row.kind}</span>
                        </button>
                    ))}
                </div>
            )}

            <PrincipalVerdictLine verdict={verdict} onUse={commit} />
        </div>
    );
};

const PrincipalVerdictLine: React.FC<{ verdict: PrincipalVerdict; onUse: (name: string) => void }> = ({ verdict, onUse }) => {
    const base = 'mt-1 flex items-start gap-1 text-[11px]';
    switch (verdict.status) {
        case 'empty':
            return null;
        case 'checking':
            return <p className={clsx(base, 'text-gray-400')}><Loader2 size={12} className="mt-0.5 animate-spin" /> Checking…</p>;
        case 'group':
        case 'user':
            return <p className={clsx(base, 'text-green-700')}><Check size={12} className="mt-0.5" /> {verdict.status === 'group' ? 'Databricks group' : 'Databricks user'}</p>;
        case 'unverified':
            return <p className={clsx(base, 'text-amber-700')}><AlertTriangle size={12} className="mt-0.5 shrink-0" /> {verdict.detail || 'Could not be checked; it will be saved as typed.'}</p>;
        case 'mismatch':
            return (
                <p className={clsx(base, 'text-red-600')}>
                    <CircleX size={12} className="mt-0.5 shrink-0" />
                    <span>
                        {verdict.detail}{' '}
                        {verdict.suggestion && (
                            <button type="button" onClick={() => onUse(verdict.suggestion!)} className="font-medium underline">
                                Use '{verdict.suggestion}'
                            </button>
                        )}
                    </span>
                </p>
            );
        default:
            return <p className={clsx(base, 'text-red-600')}><CircleX size={12} className="mt-0.5 shrink-0" /> {verdict.detail}</p>;
    }
};
