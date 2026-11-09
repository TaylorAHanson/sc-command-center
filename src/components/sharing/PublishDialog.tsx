import React, { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, Bot, CheckCircle2, LayoutGrid, Loader2, Upload, X } from 'lucide-react';
import type { Preflight, PreflightItem, PublishInclude } from '../../sharing';
import { useDialog } from './useDialog';

export interface PublishDialogProps {
    /** The name of what is being published; shown as "Publish ‘<title>’". */
    title: string;
    loadPreflight: () => Promise<Preflight>;
    /** Publish, with the items ticked here. Throw to keep the dialog open with the message. */
    onConfirm: (include: PublishInclude[]) => Promise<void>;
    /** Called on Cancel, Escape, and after `onConfirm` resolves. */
    onClose: () => void;
}

type Load = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; preflight: Preflight };

const REASONS: { reason: PreflightItem['reason']; label: string; hint: string }[] = [
    { reason: 'never_published', label: 'Not published yet', hint: 'People see a placeholder for these until they’re published.' },
    { reason: 'unpublished_changes', label: 'Has unpublished changes', hint: 'People keep seeing the last published version of these.' },
    { reason: 'uncertified', label: 'Not certified', hint: 'Someone who manages each one must certify it.' },
];

const keyOf = (item: Pick<PreflightItem, 'object_type' | 'object_id'>) => `${item.object_type}:${item.object_id}`;
const selectable = (item: PreflightItem) => item.can_publish && item.reason !== 'uncertified';

/**
 * Publishing a view, after checking what it uses: widgets and agents that were
 * never published or have newer drafts can go out in the same publish, when the
 * caller manages them.
 */
export const PublishDialog: React.FC<PublishDialogProps> = ({ title, loadPreflight, onConfirm, onClose }) => {
    // Captured once: callers pass an inline arrow, and a fresh one each render
    // would otherwise reload the preflight on every parent render.
    const [load] = useState(() => loadPreflight);
    const [nonce, setNonce] = useState(0);
    const [state, setState] = useState<Load>({ kind: 'loading' });
    // Unticked rather than ticked, so a refreshed preflight starts with everything on.
    const [unticked, setUnticked] = useState<Set<string>>(() => new Set());
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const titleId = useId();
    const { ref, onKeyDown } = useDialog<HTMLDivElement>(onClose, busy);

    useEffect(() => {
        let cancelled = false;
        load()
            .then(preflight => {
                if (cancelled) return;
                setState({ kind: 'ready', preflight: { items: preflight?.items || [], blocking: preflight?.blocking || [] } });
            })
            .catch(e => { if (!cancelled) setState({ kind: 'error', message: e?.message || String(e) }); });
        return () => { cancelled = true; };
    }, [load, nonce]);

    const preflight = state.kind === 'ready' ? state.preflight : null;
    const items = preflight?.items || [];
    const blocking = preflight?.blocking || [];
    const include: PublishInclude[] = [];
    const seen = new Set<string>();
    for (const item of items) {
        const key = keyOf(item);
        if (!selectable(item) || unticked.has(key) || seen.has(key)) continue;
        seen.add(key);
        include.push({ object_type: item.object_type, object_id: item.object_id });
    }

    const toggle = (item: PreflightItem) => setUnticked(prev => {
        const next = new Set(prev);
        const key = keyOf(item);
        if (next.has(key)) next.delete(key); else next.add(key);
        return next;
    });

    const confirm = async () => {
        setBusy(true);
        setError(null);
        try {
            await onConfirm(include);
            onClose();
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
            setBusy(false);
        }
    };

    const canPublish = state.kind === 'ready' && blocking.length === 0 && !busy;

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}
        >
            <div
                ref={ref}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-busy={state.kind === 'loading' || busy}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="flex max-h-[85vh] w-full max-w-md flex-col rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-150 focus:outline-none"
            >
                <div className="flex items-start gap-3 px-6 pt-5 pb-2">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-brand-blue" aria-hidden="true">
                        <Upload size={17} />
                    </span>
                    <div className="min-w-0 flex-1">
                        <h2 id={titleId} className="truncate text-base font-bold text-gray-900" title={title}>Publish ‘{title}’</h2>
                        <p className="text-sm text-gray-600">Everyone it’s shared with will see this version.</p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={busy}
                        aria-label="Close"
                        className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
                    {state.kind === 'loading' && (
                        <div className="flex items-center gap-2 py-6 text-sm text-gray-500">
                            <Loader2 size={16} className="animate-spin" /> Checking what it uses…
                        </div>
                    )}

                    {state.kind === 'error' && (
                        <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                            <AlertCircle size={16} className="mt-0.5 shrink-0" />
                            <span className="flex-1">Couldn’t check before publishing: {state.message}</span>
                            <button
                                type="button"
                                onClick={() => { setState({ kind: 'loading' }); setNonce(n => n + 1); }}
                                className="font-medium underline"
                            >
                                Retry
                            </button>
                        </div>
                    )}

                    {preflight && blocking.length > 0 && (
                        <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                            <div className="flex items-center gap-1.5 font-semibold">
                                <AlertCircle size={15} className="shrink-0" /> It can’t be published yet
                            </div>
                            <ul className="mt-1 list-disc space-y-0.5 pl-6 text-xs">
                                {blocking.map(reason => <li key={reason}>{reason}</li>)}
                            </ul>
                        </div>
                    )}

                    {preflight && items.length === 0 && blocking.length === 0 && (
                        <p className="flex items-center gap-2 py-2 text-sm text-gray-600">
                            <CheckCircle2 size={16} className="shrink-0 text-emerald-600" />
                            Everything it uses is already published.
                        </p>
                    )}

                    {REASONS.map(({ reason, label, hint }) => {
                        const group = items.filter(i => i.reason === reason);
                        if (!group.length) return null;
                        return (
                            <section key={reason} className="mb-3 last:mb-0" aria-label={label}>
                                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</h3>
                                <p className="mb-1 text-xs text-gray-400">{hint}</p>
                                <ul className="space-y-0.5">
                                    {group.map(item => {
                                        const key = keyOf(item);
                                        const Icon = item.object_type === 'agent' ? Bot : LayoutGrid;
                                        const tickable = selectable(item);
                                        const row = (
                                            <>
                                                <Icon size={14} aria-hidden="true" className="shrink-0 text-gray-400" />
                                                <span className="min-w-0 flex-1 truncate text-sm text-gray-800" title={item.name}>{item.name}</span>
                                                <span className="shrink-0 text-[11px] text-gray-400">{item.object_type === 'agent' ? 'Agent' : 'Widget'}</span>
                                            </>
                                        );
                                        return (
                                            <li key={`${key}:${reason}`}>
                                                {tickable ? (
                                                    <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 hover:bg-gray-50">
                                                        <input
                                                            type="checkbox"
                                                            checked={!unticked.has(key)}
                                                            onChange={() => toggle(item)}
                                                            disabled={busy}
                                                            className="h-4 w-4 shrink-0 rounded border-gray-300 accent-brand-blue"
                                                        />
                                                        {row}
                                                    </label>
                                                ) : (
                                                    <div className="px-1.5 py-1">
                                                        <div className="flex items-center gap-2 pl-6">{row}</div>
                                                        {!item.can_publish && (
                                                            <p className="pl-12 text-[11px] text-amber-700">Ask its owner to publish it</p>
                                                        )}
                                                    </div>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            </section>
                        );
                    })}

                    {error && (
                        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-red-600">
                            <AlertCircle size={13} className="mt-px shrink-0" />
                            {error}
                        </p>
                    )}
                </div>

                <div className="flex items-center gap-3 rounded-b-xl border-t border-gray-100 bg-gray-50 px-6 py-3">
                    {include.length > 0 && (
                        <span className="text-xs text-gray-500">
                            Also publishes {include.length === 1 ? '1 item' : `${include.length} items`}
                        </span>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={busy}
                        className="ml-auto rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={confirm}
                        disabled={!canPublish}
                        className="flex items-center gap-1.5 rounded-lg bg-brand-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {busy && <Loader2 size={14} className="animate-spin" />}
                        {busy ? 'Publishing…' : 'Publish'}
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
};

export default PublishDialog;
