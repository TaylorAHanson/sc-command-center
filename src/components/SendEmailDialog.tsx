import React, { useEffect, useId, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, CheckCircle2, Loader2, Mail, Paperclip, X } from 'lucide-react';
import type { EmailOutcome, EmailRequest } from '../appApi';
import { findCapability, useCapabilities } from '../capabilities';
import {
    EMAIL_UNAVAILABLE, logAndSend, previewEmail, recipientsText,
    type EmailPayload, type EmailPreview, type ExecuteAction,
} from '../email';
import { appLink, linkTab } from '../store/appRoute';
import { tabLabel } from '../store/appSpec';
import { useDashboardStore } from '../store/dashboardStore';
import { useDialog } from './sharing/useDialog';

export interface SendEmailDialogProps {
    /** What the widget asked for, already through `normalizeEmailRequest`. */
    request: EmailRequest;
    /** The widget's own, so the Send lands in the action log under its name. */
    executeAction: ExecuteAction;
    onClose: (outcome: EmailOutcome) => void;
}

type Phase =
    | { kind: 'editing' }
    | { kind: 'sending' }
    | { kind: 'done'; status: 'sent' | 'logged'; recipients: string[] };

const PREVIEW_DELAY_MS = 350;

const domainOf = (address: string | null) => (address && address.includes('@') ? address.split('@').pop() : '') || '';

/**
 * The platform's Send dialog behind `props.app.sendEmail`. The widget supplies
 * the subject, message and table; the person decides who it goes to and sees the
 * email exactly as the server renders it before anything is sent. The preview is
 * the server's HTML in a sandboxed frame, so it runs nothing and reads nothing.
 */
export const SendEmailDialog: React.FC<SendEmailDialogProps> = ({ request, executeAction, onClose }) => {
    const { activeApp, activeAppTab } = useDashboardStore();
    const capability = findCapability(useCapabilities(), 'email');
    const [to, setTo] = useState(() => recipientsText(request.to));
    const [subject, setSubject] = useState(request.subject || '');
    const [preview, setPreview] = useState<EmailPreview | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);
    const [phase, setPhase] = useState<Phase>({ kind: 'editing' });
    const [error, setError] = useState<string | null>(null);
    const titleId = useId();
    const toId = useId();
    const subjectId = useId();

    const view = useMemo(() => {
        if (!activeApp) return { name: '', link: '' };
        const index = activeAppTab ? activeApp.spec.tabs.findIndex(t => t.id === activeAppTab.id) : -1;
        const tabName = activeAppTab && activeApp.spec.tabs.length > 1 ? tabLabel(activeApp, activeAppTab, Math.max(index, 0)) : '';
        return {
            name: tabName && tabName !== activeApp.name ? `${activeApp.name} – ${tabName}` : activeApp.name,
            link: appLink(activeApp, linkTab(activeApp, activeAppTab)),
        };
    }, [activeApp, activeAppTab]);

    const payload = useMemo<EmailPayload>(() => ({
        to,
        subject,
        message: request.message || '',
        table: request.table || null,
        attach_csv: !!request.attachCsv,
        view_name: view.name,
        view_link: view.link,
    }), [to, subject, request, view]);

    useEffect(() => {
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            void previewEmail(payload, controller.signal).then(result => {
                if (controller.signal.aborted) return;
                if ('error' in result) {
                    setPreviewError(result.error);
                } else {
                    setPreview(result);
                    setPreviewError(null);
                }
            });
        }, PREVIEW_DELAY_MS);
        return () => { controller.abort(); window.clearTimeout(timer); };
    }, [payload]);

    const sending = phase.kind === 'sending';
    const close = () => {
        if (sending) return;
        onClose(phase.kind === 'done'
            ? { sent: true, status: phase.status, recipients: phase.recipients }
            : { sent: false, status: preview && !preview.available ? 'unavailable' : 'cancelled', recipients: [] });
    };
    const { ref, onKeyDown } = useDialog<HTMLDivElement>(close, sending);

    // The preview's answer is fresher than the capability, which is cached for a minute.
    const unavailable = preview ? !preview.available : capability ? !capability.available : false;
    const canSend = phase.kind === 'editing' && !!preview && preview.available && !preview.problem;

    const send = async () => {
        setError(null);
        setPhase({ kind: 'sending' });
        const result = await logAndSend(executeAction, payload);
        if (result.ok) {
            setPhase({ kind: 'done', status: result.status, recipients: result.recipients });
        } else {
            setPhase({ kind: 'editing' });
            setError(result.error);
        }
    };

    const scope = preview
        ? `Up to ${preview.max_recipients} ${preview.max_recipients === 1 ? 'person' : 'people'}`
          + (preview.allowed_domains.length
              ? ` at ${preview.allowed_domains.join(', ')}`
              : domainOf(preview.reply_to) ? ` at ${domainOf(preview.reply_to)}` : '')
          + '. Separate addresses with commas.'
        : 'Separate addresses with commas.';

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            // Portalled, but still inside the widget's React tree: keep its handlers out of this.
            onClick={e => e.stopPropagation()}
            onMouseDown={e => { e.stopPropagation(); if (e.target === e.currentTarget) close(); }}
        >
            <div
                ref={ref}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-busy={sending}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-150 focus:outline-none"
            >
                <div className="flex items-start gap-3 px-6 pt-5 pb-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-brand-blue" aria-hidden="true">
                        <Mail size={17} />
                    </span>
                    <div className="min-w-0 flex-1">
                        <h2 id={titleId} className="text-base font-bold text-gray-900">Send by email</h2>
                        <p className="truncate text-sm text-gray-600">
                            {preview?.from_address ? `From ${preview.from_address}. ` : ''}
                            Replies come to you{preview?.reply_to ? ` (${preview.reply_to})` : ''}.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={close}
                        disabled={sending}
                        aria-label="Close"
                        className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
                    >
                        <X size={18} />
                    </button>
                </div>

                {phase.kind === 'done' ? (
                    <div className="flex items-start gap-3 px-6 py-6 text-sm text-gray-700" role="status">
                        <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-emerald-600" />
                        {phase.status === 'logged' ? (
                            <p>Written to the server log instead of sent: this is a local run without Amazon SES. Nothing left the app.</p>
                        ) : (
                            <p>Sent to {phase.recipients.join(', ')}.</p>
                        )}
                    </div>
                ) : (
                    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 pb-3">
                        {unavailable && (
                            <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                                <p className="font-semibold">{EMAIL_UNAVAILABLE}</p>
                                <p className="mt-0.5 text-xs">
                                    {capability?.next_step || 'An administrator can set it up under Admin Panel → Settings.'}
                                </p>
                            </div>
                        )}
                        {preview?.mode === 'log' && !unavailable && (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                                Local run: Send writes the email to the server log instead of sending it.
                            </p>
                        )}

                        <div>
                            <label htmlFor={toId} className="block text-xs font-semibold uppercase tracking-wide text-gray-500">To</label>
                            <textarea
                                id={toId}
                                data-autofocus
                                rows={2}
                                value={to}
                                onChange={e => setTo(e.target.value)}
                                disabled={sending}
                                placeholder="name@example.com, other@example.com"
                                className="mt-1 w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-brand-blue focus:outline-none focus:ring-1 focus:ring-brand-blue disabled:bg-gray-50"
                            />
                            <p className="mt-0.5 text-xs text-gray-500">{scope}</p>
                        </div>

                        <div>
                            <label htmlFor={subjectId} className="block text-xs font-semibold uppercase tracking-wide text-gray-500">Subject</label>
                            <input
                                id={subjectId}
                                type="text"
                                value={subject}
                                maxLength={200}
                                onChange={e => setSubject(e.target.value)}
                                disabled={sending}
                                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-brand-blue focus:outline-none focus:ring-1 focus:ring-brand-blue disabled:bg-gray-50"
                            />
                        </div>

                        <div>
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Preview</span>
                                {preview?.attachment && (
                                    <span className="flex items-center gap-1 text-xs text-gray-600">
                                        <Paperclip size={12} aria-hidden="true" />
                                        {preview.attachment.filename} · {preview.attachment.rows.toLocaleString()} rows
                                    </span>
                                )}
                            </div>
                            {preview?.html ? (
                                <iframe
                                    title="Email preview"
                                    sandbox=""
                                    referrerPolicy="no-referrer"
                                    srcDoc={preview.html}
                                    className="mt-1 h-72 w-full rounded-lg border border-gray-200 bg-white"
                                />
                            ) : (
                                <div className="mt-1 flex h-24 items-center justify-center gap-2 rounded-lg border border-dashed border-gray-200 text-sm text-gray-500">
                                    {previewError
                                        ? <span className="text-red-600">Couldn’t prepare the preview: {previewError}</span>
                                        : <><Loader2 size={14} className="animate-spin" /> Preparing the preview…</>}
                                </div>
                            )}
                        </div>

                        {preview?.available && preview.problem && (
                            <p role="alert" className="flex items-start gap-1.5 text-sm text-red-600">
                                <AlertCircle size={15} className="mt-0.5 shrink-0" /> {preview.problem}
                            </p>
                        )}
                        {error && (
                            <p role="alert" className="flex items-start gap-1.5 text-sm text-red-600">
                                <AlertCircle size={15} className="mt-0.5 shrink-0" /> {error}
                            </p>
                        )}
                    </div>
                )}

                <div className="flex items-center gap-3 rounded-b-xl border-t border-gray-100 bg-gray-50 px-6 py-3">
                    {phase.kind !== 'done' && preview && preview.available && preview.sent_today !== null && (
                        <span className="text-xs text-gray-500">
                            {preview.sent_today} of {preview.daily_limit} emails sent in the last 24 hours
                        </span>
                    )}
                    {phase.kind === 'done' ? (
                        <button
                            type="button"
                            onClick={close}
                            className="ml-auto rounded-lg bg-brand-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-navy"
                        >
                            Done
                        </button>
                    ) : (
                        <>
                            <button
                                type="button"
                                onClick={close}
                                disabled={sending}
                                className="ml-auto rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={send}
                                disabled={!canSend}
                                title={unavailable ? EMAIL_UNAVAILABLE : preview?.problem || undefined}
                                className="flex items-center gap-1.5 rounded-lg bg-brand-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {sending && <Loader2 size={14} className="animate-spin" />}
                                {sending ? 'Sending…' : 'Send'}
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>,
        document.body,
    );
};

export default SendEmailDialog;
