import React, { useCallback, useMemo, useRef, useState } from 'react';
import type { AppApi, EmailOutcome, EmailRequest, EmailTable } from './appApi';
import type { ActionRunContext } from './contexts/ActionContext';

/**
 * Email from widgets (`props.app.sendEmail`): the request helpers behind the
 * Send dialog, and the hook that binds `sendEmail` to one widget so its Send is
 * logged through that widget's `executeAction`. The rules (who may be emailed,
 * how many, what the email looks like) are the server's; see
 * `server/services/email_service.py`.
 */

export const EMAIL_UNAVAILABLE = 'Email isn’t set up in this app yet.';

/** What `executeAction` is: logs the action, then runs the callback, or alerts and doesn't. */
export type ExecuteAction = (actionName: string, callback: (ctx: ActionRunContext) => void) => unknown;

export interface EmailPayload {
    to: string;
    subject: string;
    message: string;
    table: EmailTable | null;
    attach_csv: boolean;
    view_name: string;
    view_link: string;
    request_id?: string;
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
    attachment: { filename: string; rows: number; bytes: number } | null;
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

/** What the widget asked for, reduced to the shapes the dialog holds. */
export const normalizeEmailRequest = (request: unknown): EmailRequest => {
    const r = (request && typeof request === 'object' ? request : {}) as Record<string, unknown>;
    const to = Array.isArray(r.to) ? r.to.filter(x => typeof x === 'string') as string[]
        : typeof r.to === 'string' ? r.to : undefined;
    const table = r.table && typeof r.table === 'object' && Array.isArray((r.table as EmailTable).rows)
        ? r.table as EmailTable : undefined;
    return {
        subject: typeof r.subject === 'string' ? r.subject : '',
        message: typeof r.message === 'string' ? r.message : '',
        to,
        table,
        attachCsv: r.attachCsv === true,
    };
};

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
    const [request, setRequest] = useState<EmailRequest | null>(null);
    const settle = useRef<((outcome: EmailOutcome) => void) | null>(null);

    const open = useCallback((asked: EmailRequest) => new Promise<EmailOutcome>(resolve => {
        settle.current?.(CANCELLED);
        settle.current = resolve;
        setRequest(normalizeEmailRequest(asked));
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
