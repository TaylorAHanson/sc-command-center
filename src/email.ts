import React, { useCallback, useMemo, useRef, useState } from 'react';
import type { AppApi, EmailAttachment, EmailOutcome, EmailRequest, EmailTable } from './appApi';
import type { ActionRunContext } from './contexts/ActionContext';

/**
 * Email from widgets (`props.app.sendEmail`) and from agents' drafts: the
 * request helpers behind the Send dialog, and the hook that binds `sendEmail`
 * to one widget so its Send is logged through that widget's `executeAction`.
 * The rules (who may be emailed, how many, what HTML and files survive) are the
 * server's; see `server/services/email_service.py` and `email_content.py`.
 */

export const EMAIL_UNAVAILABLE = 'Email isn’t set up in this app yet.';

/** What `executeAction` is: logs the action, then runs the callback, or alerts and doesn't. */
export type ExecuteAction = (actionName: string, callback: (ctx: ActionRunContext) => void) => unknown;

/** An attachment as it travels: text as `content`, anything else as base64 or a data: URL in `data`. */
export interface SentAttachment {
    filename: string;
    content?: string;
    data?: string;
}

/** What the dialog holds: the widget's or agent's request, files already read into strings. */
export interface PreparedEmail extends Omit<EmailRequest, 'attachments'> {
    attachments: SentAttachment[];
}

export interface EmailPayload {
    to: string;
    subject: string;
    message: string;
    html: string;
    tables: EmailTable[];
    attach_csv: boolean;
    attachments: SentAttachment[];
    view_name: string;
    view_link: string;
    request_id?: string;
    /** Who opened the dialog, for the log. */
    via?: 'widget' | 'assistant';
    /** An agent's draft: where it came from, so a send that goes is noted on that chat. */
    conversation_id?: string;
    draft_id?: string;
}

/** A draft from an agent's email tool, as it arrives on the chat turn. */
export interface AgentEmailDraft {
    id: string;
    to?: string[];
    subject?: string;
    message?: string;
    html?: string;
    tables?: EmailTable[];
    attach_csv?: boolean;
    attachments?: SentAttachment[];
}

export interface EmailPreview {
    available: boolean;
    /** `ses`, or `log` for a local run that writes the email to the server log. */
    mode: 'ses' | 'log' | null;
    /** What would stop Send, as a sentence; null when it would go. */
    problem: string | null;
    reason: string | null;
    recipients: string[];
    from_address: string | null;
    reply_to: string | null;
    subject: string;
    html: string;
    /** Files listed under the email; images shown in its body are not among them. */
    attachments: { filename: string; content_type: string; rows: number | null; bytes: number }[];
    /** What was left out of the HTML, such as images from other sites. */
    notes: string[];
    max_recipients: number;
    allowed_domains: string[];
    daily_limit: number;
    sent_today: number | null;
}

export type SendResult =
    | { ok: true; status: 'sent' | 'logged'; recipients: string[] }
    | { ok: false; error: string };

const CANCELLED: EmailOutcome = { sent: false, status: 'cancelled', recipients: [] };

const detailOf = async (res: Response): Promise<string> => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string' && body.detail) return body.detail;
    } catch {
        // Not JSON; fall through to the status line.
    }
    return `${res.statusText || 'Request failed'} (HTTP ${res.status})`;
};

const asTable = (value: unknown): EmailTable | undefined =>
    value && typeof value === 'object' && Array.isArray((value as EmailTable).rows) ? value as EmailTable : undefined;

/** What the widget asked for, reduced to the shapes the dialog holds. Files are kept as given. */
export const normalizeEmailRequest = (request: unknown): EmailRequest => {
    const r = (request && typeof request === 'object' ? request : {}) as Record<string, unknown>;
    const to = Array.isArray(r.to) ? r.to.filter(x => typeof x === 'string') as string[]
        : typeof r.to === 'string' ? r.to : undefined;
    const tables = Array.isArray(r.tables) ? r.tables.map(asTable).filter((t): t is EmailTable => !!t) : undefined;
    const attachments = Array.isArray(r.attachments)
        ? r.attachments.filter((a): a is EmailAttachment => !!a && typeof a === 'object'
            && typeof (a as EmailAttachment).filename === 'string')
        : undefined;
    return {
        subject: typeof r.subject === 'string' ? r.subject : '',
        message: typeof r.message === 'string' ? r.message : '',
        html: typeof r.html === 'string' ? r.html : '',
        to,
        table: asTable(r.table),
        tables,
        attachCsv: r.attachCsv === true,
        attachments,
    };
};

const bytesToBase64 = (bytes: Uint8Array): string => {
    let binary = '';
    // In chunks: a spread of a few megabytes overflows the call stack.
    for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
};

/** One attachment with its data read into a string, or null when there is nothing to read. */
export const readAttachment = async (file: EmailAttachment): Promise<SentAttachment | null> => {
    const { filename, content, data } = file;
    if (typeof content === 'string' && data === undefined) return { filename, content };
    if (typeof data === 'string') return { filename, data };
    if (data instanceof Uint8Array) return { filename, data: bytesToBase64(data) };
    if (data instanceof ArrayBuffer) return { filename, data: bytesToBase64(new Uint8Array(data)) };
    if (typeof Blob !== 'undefined' && data instanceof Blob) {
        return { filename, data: bytesToBase64(new Uint8Array(await data.arrayBuffer())) };
    }
    return typeof content === 'string' ? { filename, content } : null;
};

/** The request as the dialog holds it: normalized, every file read. */
export const prepareEmailRequest = async (request: unknown): Promise<PreparedEmail> => {
    const normalized = normalizeEmailRequest(request);
    const read = await Promise.all((normalized.attachments || []).map(file => readAttachment(file).catch(() => null)));
    return { ...normalized, attachments: read.filter((a): a is SentAttachment => !!a) };
};

/** An agent's draft as the dialog holds it. */
export const requestFromDraft = (draft: AgentEmailDraft): PreparedEmail => ({
    subject: draft.subject || '',
    message: draft.message || '',
    html: draft.html || '',
    to: draft.to || [],
    tables: Array.isArray(draft.tables) ? draft.tables.map(asTable).filter((t): t is EmailTable => !!t) : [],
    attachCsv: draft.attach_csv === true,
    attachments: Array.isArray(draft.attachments) ? draft.attachments : [],
});

/** Every table in the request, `table` first. */
export const tablesOf = (request: EmailRequest): EmailTable[] =>
    [...(request.table ? [request.table] : []), ...(request.tables || [])];

export const recipientsText = (to: EmailRequest['to']): string =>
    Array.isArray(to) ? to.join(', ') : (to || '');

export const previewEmail = async (payload: EmailPayload, signal?: AbortSignal): Promise<EmailPreview | { error: string }> => {
    try {
        const res = await fetch('/api/email/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal,
        });
        if (!res.ok) return { error: await detailOf(res) };
        return await res.json() as EmailPreview;
    } catch (e) {
        if (signal?.aborted) return { error: '' };
        console.warn('Email preview failed:', e);
        return { error: e instanceof Error ? e.message : String(e) };
    }
};

export const postEmail = async (payload: EmailPayload): Promise<SendResult> => {
    try {
        const res = await fetch('/api/email/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) return { ok: false, error: await detailOf(res) };
        const body = await res.json();
        return { ok: true, status: body?.status === 'logged' ? 'logged' : 'sent', recipients: body?.recipients || [] };
    } catch (e) {
        console.warn('Sending email failed:', e);
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
};

/**
 * Send through the widget's `executeAction`, so the action log row is written
 * first and its id travels with the email. When the log can't be written,
 * `executeAction` alerts and never calls back, and nothing is sent.
 */
export const logAndSend = (executeAction: ExecuteAction, payload: EmailPayload): Promise<SendResult> =>
    new Promise(resolve => {
        let ran = false;
        const notLogged = () => {
            if (!ran) resolve({ ok: false, error: 'Not sent: the action log couldn’t record it.' });
        };
        let started: unknown;
        try {
            started = executeAction('Send email', ({ requestId }) => {
                ran = true;
                void postEmail({ ...payload, request_id: requestId }).then(resolve);
            });
        } catch (e) {
            resolve({ ok: false, error: e instanceof Error ? e.message : String(e) });
            return;
        }
        if (started && typeof (started as PromiseLike<unknown>).then === 'function') {
            (started as PromiseLike<unknown>).then(notLogged, notLogged);
        } else {
            notLogged();
        }
    });

/** The `app` prop among an injector's children (in practice, its one widget). */
export const appOfChildren = (children: React.ReactNode): AppApi | undefined => {
    let found: AppApi | undefined;
    React.Children.forEach(children, child => {
        if (!found && React.isValidElement(child)) found = (child.props as { app?: AppApi }).app;
    });
    return found;
};

/**
 * `app` with `sendEmail` bound to this widget: calling it holds the request
 * for the Send dialog and returns a promise the dialog settles on close. A
 * second call while the dialog is open replaces the first, which resolves as
 * cancelled. Without an action log (`canLog` false) `app` comes back unchanged,
 * and its own `sendEmail` opens nothing.
 */
export const useWidgetEmail = (app: AppApi | undefined, canLog: boolean) => {
    const [request, setRequest] = useState<PreparedEmail | null>(null);
    const settle = useRef<((outcome: EmailOutcome) => void) | null>(null);

    const open = useCallback((asked: EmailRequest) => new Promise<EmailOutcome>(resolve => {
        settle.current?.(CANCELLED);
        settle.current = resolve;
        // Files are read before the dialog opens, so a Blob is already a string by then.
        void prepareEmailRequest(asked).then(prepared => {
            if (settle.current === resolve) setRequest(prepared);
        });
    }), []);

    const close = useCallback((outcome: EmailOutcome) => {
        settle.current?.(outcome);
        settle.current = null;
        setRequest(null);
    }, []);

    const bound = useMemo(
        () => (app && canLog ? { ...app, sendEmail: open } : app),
        [app, canLog, open],
    );

    return { app: bound, request, close };
};
