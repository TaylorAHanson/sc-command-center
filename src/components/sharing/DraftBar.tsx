import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { History, Loader2, Undo2, Upload } from 'lucide-react';
import clsx from 'clsx';
import { ConfirmModal } from '../ConfirmModal';
import { STATE_LABELS, type PublishState } from '../../sharing';

export type DraftMode = 'draft' | 'published';

export interface DraftBarProps {
    /** Undefined for people who can only use the object; the bar then renders nothing. */
    state?: PublishState;
    mode: DraftMode;
    onModeChange: (mode: DraftMode) => void;
    onPublish: () => void;
    onDiscard?: () => void | Promise<void>;
    onHistory?: () => void;
    busy?: boolean;
    variant?: 'light' | 'dark';
    /** Off when the state is shown elsewhere, e.g. beside a title. */
    showState?: boolean;
    /** Rendered just before Publish, so Publish stays the last, primary button. */
    children?: React.ReactNode;
    className?: string;
}

const PILL: Record<PublishState, { light: string; dark: string; dot: string; hint: string }> = {
    published_with_draft: {
        light: 'bg-amber-50 text-amber-800 border-amber-200',
        dark: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        dot: 'bg-amber-400',
        hint: 'You have changes that people it’s shared with don’t see yet. Publish to show them.',
    },
    published: {
        light: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        dark: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
        dot: 'bg-emerald-500',
        hint: 'People it’s shared with see exactly this.',
    },
    draft_only: {
        light: 'bg-slate-100 text-slate-600 border-slate-200',
        dark: 'bg-slate-700/60 text-slate-300 border-slate-600',
        dot: 'bg-slate-400',
        hint: 'Only people who can manage it see it. Publish to show it to everyone it’s shared with.',
    },
};

/** Where the draft stands, as a small chip with an explanation on hover. */
export const StatePill: React.FC<{ state?: PublishState; variant?: 'light' | 'dark'; className?: string }> = ({
    state, variant = 'light', className,
}) => {
    if (!state) return null;
    const pill = PILL[state];
    return (
        <span
            title={pill.hint}
            className={clsx(
                'flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium shrink-0',
                variant === 'dark' ? pill.dark : pill.light,
                className,
            )}
        >
            <span className={clsx('h-1.5 w-1.5 rounded-full', pill.dot)} aria-hidden="true" />
            {STATE_LABELS[state]}
        </span>
    );
};

/**
 * Draft / Published, where the draft stands, and Publish, for the people who
 * manage a view, widget or agent. Sized for a header bar.
 *
 * Each control appears only when it can do something: the toggle when the draft
 * and the published version differ (or to get back from Published), Publish when
 * there is something to publish. A bar that always showed all of them spent most
 * of a header saying the same thing three ways.
 */
export const DraftBar: React.FC<DraftBarProps> = ({
    state, mode, onModeChange, onPublish, onDiscard, onHistory, busy = false, variant = 'light',
    showState = true, children, className,
}) => {
    const [confirmDiscard, setConfirmDiscard] = useState(false);
    if (!state) return null;

    const dark = variant === 'dark';
    const hasDraftChanges = state === 'published_with_draft';
    const showToggle = hasDraftChanges || mode === 'published';
    const canPublish = state !== 'published';

    const segment = (value: DraftMode, label: string, title: string) => {
        const selected = mode === value;
        return (
            <button
                type="button"
                role="radio"
                aria-checked={selected}
                title={title}
                onClick={() => { if (!selected) onModeChange(value); }}
                className={clsx(
                    'px-2.5 py-1 text-xs font-medium rounded transition-colors',
                    selected
                        ? (dark ? 'bg-slate-600 text-white shadow-sm' : 'bg-white text-gray-900 shadow-sm')
                        : (dark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-800'),
                )}
            >
                {label}
            </button>
        );
    };

    const quiet = clsx(
        'flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
        dark ? 'text-slate-300 hover:bg-slate-700 hover:text-white' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
    );

    return (
        <div className={clsx('flex items-center gap-2', className)}>
            {showState && <StatePill state={state} variant={variant} />}

            {showToggle && (
                <div
                    role="radiogroup"
                    aria-label="Version shown"
                    className={clsx('flex items-center gap-0.5 rounded-md p-0.5', dark ? 'bg-slate-800 border border-slate-700' : 'bg-gray-100')}
                >
                    {segment('draft', 'Draft', 'Your working copy, with the changes. Only people who can manage it see this.')}
                    {segment('published', 'Published', 'What people it’s shared with see now')}
                </div>
            )}

            {onHistory && (
                <button type="button" onClick={onHistory} className={quiet} title="Published versions">
                    <History size={13} aria-hidden="true" />
                    History
                </button>
            )}

            {onDiscard && hasDraftChanges && (
                <button
                    type="button"
                    onClick={() => setConfirmDiscard(true)}
                    disabled={busy}
                    className={quiet}
                    title="Throw away the draft and go back to the published version"
                >
                    <Undo2 size={13} aria-hidden="true" />
                    Discard draft
                </button>
            )}

            {children}

            {canPublish && (
                <button
                    type="button"
                    onClick={onPublish}
                    disabled={busy}
                    title={state === 'draft_only'
                        ? 'Make this visible to everyone it’s shared with'
                        : 'Replace what people see with your draft'}
                    className="flex items-center gap-1.5 rounded-md bg-brand-blue px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-brand-blue"
                >
                    {busy ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Upload size={13} aria-hidden="true" />}
                    Publish
                </button>
            )}

            {confirmDiscard && createPortal(
                <ConfirmModal
                    title="Discard draft?"
                    message="Your unpublished changes will be deleted. The published version stays as it is."
                    confirmLabel="Discard draft"
                    variant="danger"
                    onCancel={() => setConfirmDiscard(false)}
                    onConfirm={() => { setConfirmDiscard(false); void onDiscard?.(); }}
                />,
                document.body,
            )}
        </div>
    );
};

export default DraftBar;
