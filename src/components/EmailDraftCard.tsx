import React, { useMemo, useState } from 'react';
import { CheckCircle2, Mail, Paperclip, Table2 } from 'lucide-react';
import type { EmailOutcome } from '../appApi';
import { requestFromDraft, type AgentEmailDraft } from '../email';
import { SendEmailDialog } from './SendEmailDialog';

/**
 * An email an agent drafted with its email tool, waiting for the person. The
 * agent can't send; the button opens the same Send dialog a widget's
 * `props.app.sendEmail` opens, where the person edits the recipients, sees the
 * email exactly as it will arrive and presses Send themselves.
 *
 * `sent` comes from the server once a send went (it is saved on the chat turn),
 * so a reopened chat shows what already went instead of offering it again.
 */
export const EmailDraftCard: React.FC<{
    draft: AgentEmailDraft;
    sent?: { status: 'sent' | 'logged'; recipients: string[] };
    conversationId?: string;
    glass?: boolean;
}> = ({ draft, sent, conversationId, glass = false }) => {
    const [open, setOpen] = useState(false);
    const [outcome, setOutcome] = useState<EmailOutcome | null>(
        sent ? { sent: true, status: sent.status, recipients: sent.recipients } : null,
    );
    const request = useMemo(() => requestFromDraft(draft), [draft]);
    const tableCount = request.tables?.length || 0;
    const fileCount = request.attachments.length;
    const went = !!outcome?.sent;

    const close = (result: EmailOutcome) => {
        setOpen(false);
        // A cancel leaves an earlier send standing.
        if (result.sent || !outcome?.sent) setOutcome(result);
    };

    const box = glass ? 'border-white/15 bg-white/5 text-slate-100' : 'border-gray-200 bg-white text-gray-800';
    const quiet = glass ? 'text-white/60' : 'text-gray-500';

    return (
        <div className={`mt-2 rounded-lg border px-3 py-2 not-prose ${box}`}>
            <div className="flex items-start gap-2">
                <Mail className={`mt-0.5 h-4 w-4 shrink-0 ${glass ? 'text-white/70' : 'text-brand-blue'}`} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{request.subject || 'Untitled email'}</p>
                    <p className={`truncate text-xs ${quiet}`}>
                        {draft.to?.length ? `To ${draft.to.join(', ')}` : 'No recipients yet'}
                    </p>
                    {(tableCount > 0 || fileCount > 0) && (
                        <p className={`mt-0.5 flex items-center gap-2 text-xs ${quiet}`}>
                            {tableCount > 0 && (
                                <span className="flex items-center gap-1">
                                    <Table2 className="h-3 w-3" aria-hidden="true" />
                                    {tableCount} table{tableCount === 1 ? '' : 's'}
                                </span>
                            )}
                            {fileCount > 0 && (
                                <span className="flex items-center gap-1">
                                    <Paperclip className="h-3 w-3" aria-hidden="true" />
                                    {fileCount} file{fileCount === 1 ? '' : 's'}
                                </span>
                            )}
                        </p>
                    )}
                </div>
            </div>
            <div className="mt-2 flex items-center gap-2">
                {went ? (
                    <span className={`flex items-center gap-1 text-xs ${glass ? 'text-emerald-300' : 'text-emerald-700'}`} role="status">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        {outcome?.status === 'logged'
                            ? 'Written to the server log (local run)'
                            : `Sent to ${outcome?.recipients.join(', ') || 'its recipients'}`}
                    </span>
                ) : (
                    <span className={`text-xs ${quiet}`}>Not sent. Nothing goes until you press Send.</span>
                )}
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    className={`ml-auto rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${went
                        ? (glass ? 'border border-white/20 text-white/80 hover:bg-white/10' : 'border border-gray-300 text-gray-700 hover:bg-gray-50')
                        : 'bg-brand-blue text-white hover:bg-brand-navy'}`}
                >
                    {went ? 'Send again…' : 'Review and send…'}
                </button>
            </div>
            {open && (
                <SendEmailDialog
                    request={request}
                    draft={{ id: draft.id, conversationId }}
                    onClose={close}
                />
            )}
        </div>
    );
};

export default EmailDraftCard;
