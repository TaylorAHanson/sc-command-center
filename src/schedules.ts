/**
 * Scheduling from widgets (`props.app.schedule`) and the My schedules page: the
 * `/api/schedules` contract as types, the requests behind the dialog and the
 * page, and the pure helpers both draw with. When a schedule next runs, and what
 * it may do when it does, are the server's to decide; nothing here works out a
 * run time, so DST and month ends are never computed twice.
 *
 * No React and no runtime imports, and `window` only inside the functions that
 * read the address, so `tests/schedules.test.ts` loads this under Node.
 */

export type ScheduleKind = 'email_report' | 'run_statement';
export type SendWhen = 'always' | 'has_rows' | 'no_rows';
export type Frequency = 'hourly' | 'daily' | 'weekly' | 'monthly';
export type ScheduleStatus = 'active' | 'paused' | 'needs_reconnect';
export type RunStatus = 'ok' | 'skipped' | 'failed' | 'needs_reconnect';
export type RunTrigger = 'schedule' | 'manual' | 'recovery';

/**
 * `days`: weekly, ISO weekdays 1 (Monday) to 7 (Sunday); monthly, days of the
 * month 1 to 31, which the server moves to a shorter month's last day; ignored
 * for hourly and daily. Hourly uses only the minutes of `time`. `tz` is IANA.
 */
export interface Recurrence {
    freq: Frequency;
    days: number[];
    time: string;
    tz: string;
}

export interface ScheduleRun {
    id: string;
    schedule_id: string;
    trigger: RunTrigger;
    started_at: string | null;
    finished_at: string | null;
    /** `skipped`: the send-when rule said not to send. */
    status: RunStatus;
    rows: number | null;
    emailed: number | boolean | null;
    error: string | null;
}

export interface Schedule {
    id: string;
    owner: string;
    kind: ScheduleKind;
    name: string;
    sql: string;
    source_app_id: string | null;
    source_widget_instance: string | null;
    source_widget_id: string | null;
    view_name: string | null;
    view_link: string | null;
    recipients: string[];
    subject: string;
    message: string;
    send_when: SendWhen;
    attach_csv: boolean;
    recurrence: Recurrence;
    next_run_at: string | null;
    last_run: ScheduleRun | null;
    status: ScheduleStatus;
    paused_reason: null | 'owner' | 'failures';
    failure_count: number;
    created_at: string;
    updated_at: string;
}

/** `GET /api/oauth/status`. `needs_reconnect` means a connection existed and stopped working. */
export interface ConnectionStatus {
    connected: boolean;
    connected_at: string | null;
    expires_at: string | null;
    needs_reconnect: boolean;
    reason: string | null;
}

/** Where a schedule came from, captured when the dialog opens. */
export interface ScheduleSource {
    source_app_id: string | null;
    source_widget_instance: string | null;
    source_widget_id: string | null;
    view_name: string | null;
    view_link: string | null;
}

/** What `props.app.schedule` accepts. Everything but `sql` is a starting value the person can change. */
export interface ScheduleRequest {
    name?: string;
    subject?: string;
    /** Markdown, rendered and escaped by the server like `sendEmail`'s. */
    message?: string;
    /** The statement the widget runs for what it shows. The schedule keeps this text. */
    sql: string;
    kind?: ScheduleKind;
    sendWhen?: SendWhen;
    attachCsv?: boolean;
    recipients?: string | string[];
    recurrence?: Partial<Recurrence>;
}

export interface ScheduleOutcome {
    /** True once the person saved it, whether or not it can run yet. */
    scheduled: boolean;
    id?: string;
    status?: string;
}

/** What the dialog edits. */
export interface ScheduleForm {
    name: string;
    kind: ScheduleKind;
    recipients: string[];
    subject: string;
    message: string;
    sendWhen: SendWhen;
    attachCsv: boolean;
    recurrence: Recurrence;
}

export const SCHEDULING_UNAVAILABLE = 'Scheduling isn’t set up in this app yet.';

export const FREQUENCIES: { id: Frequency; label: string }[] = [
    { id: 'hourly', label: 'Hourly' },
    { id: 'daily', label: 'Daily' },
    { id: 'weekly', label: 'Weekly' },
    { id: 'monthly', label: 'Monthly' },
];

export const SEND_WHEN: { id: SendWhen; label: string }[] = [
    { id: 'always', label: 'Every time' },
    { id: 'has_rows', label: 'Only when the query returns rows' },
    { id: 'no_rows', label: 'Only when the query returns no rows' },
];

/** ISO weekday order: index 0 is day 1, Monday. */
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export const DEFAULT_TIME = '08:00';
export const MAX_NAME_LENGTH = 200;

const KINDS: readonly ScheduleKind[] = ['email_report', 'run_statement'];
const SEND_WHEN_IDS: readonly string[] = SEND_WHEN.map(s => s.id);
const FREQUENCY_IDS: readonly string[] = FREQUENCIES.map(f => f.id);
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

// ------------------------------------------------------------------ dates

/** A timestamp from the server as a Date. One without a zone is UTC, as Postgres writes it. */
export const parseUtc = (iso: string | null | undefined): Date | null => {
    if (!iso) return null;
    const zoned = /(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso.replace(' ', 'T')}Z`;
    const date = new Date(zoned);
    return Number.isNaN(date.getTime()) ? null : date;
};

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** "in 3 hours", "5 minutes ago", "just now". */
export const relativeTime = (iso: string | null | undefined, now: number | Date = Date.now()): string => {
    const date = parseUtc(iso);
    if (!date) return '';
    const ms = date.getTime() - Number(now);
    const span = Math.abs(ms);
    if (span < MINUTE) return 'just now';
    const text = span < HOUR ? plural(Math.round(span / MINUTE), 'minute')
        : span < DAY ? plural(Math.round(span / HOUR), 'hour')
            : plural(Math.round(span / DAY), 'day');
    return ms > 0 ? `in ${text}` : `${text} ago`;
};

/** A server timestamp in the reader's own zone and locale, e.g. "Nov 13, 2026, 8:00 AM". */
export const formatWhen = (iso: string | null | undefined): string => {
    const date = parseUtc(iso);
    return date ? date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
};

/** "expires in 6 days", or "expired". Null when there is no expiry to count down to. */
export const expiresIn = (expiresAt: string | null | undefined, now: number | Date = Date.now()): string | null => {
    const date = parseUtc(expiresAt);
    if (!date) return null;
    const ms = date.getTime() - Number(now);
    if (ms <= 0) return 'expired';
    if (ms < HOUR) return 'expires in less than an hour';
    if (ms < DAY) return `expires in ${plural(Math.round(ms / HOUR), 'hour')}`;
    return `expires in ${plural(Math.round(ms / DAY), 'day')}`;
};

/** Whether a connection ends within `days`, lapsed ones included. */
export const expiresWithin = (expiresAt: string | null | undefined, days: number, now: number | Date = Date.now()): boolean => {
    const date = parseUtc(expiresAt);
    return !!date && date.getTime() - Number(now) <= days * DAY;
};

// ------------------------------------------------------------ recurrence

export const ordinal = (n: number): string => {
    const tens = n % 100;
    if (tens >= 11 && tens <= 13) return `${n}th`;
    return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] || 'th'}`;
};

/** "a", "a and b", "a, b and c". */
export const listJoin = (items: string[]): string =>
    items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;

const cleanDays = (days: unknown, max: number): number[] =>
    Array.isArray(days)
        ? [...new Set(days.map(Number).filter(d => Number.isInteger(d) && d >= 1 && d <= max))].sort((a, b) => a - b)
        : [];

const minutesOf = (time: string): string => (TIME_RE.test(time) ? time.slice(3) : '00');

/**
 * The schedule in words: "Every weekday at 08:00 (America/Los_Angeles)",
 * "Hourly at :15", "Monthly on the 1st and 15th at 09:00 (UTC)". The zone is
 * left off hourly, whose minute reads the same almost everywhere.
 */
export const describeRecurrence = (r: Recurrence): string => {
    const zone = r.tz ? ` (${r.tz})` : '';
    const at = `at ${r.time}${zone}`;
    switch (r.freq) {
        case 'hourly':
            return `Hourly at :${minutesOf(r.time)}`;
        case 'daily':
            return `Every day ${at}`;
        case 'weekly': {
            const days = cleanDays(r.days, 7);
            if (!days.length) return `Weekly, no day chosen, ${at}`;
            if (days.length === 7) return `Every day ${at}`;
            if (days.join() === '1,2,3,4,5') return `Every weekday ${at}`;
            return `Every ${listJoin(days.map(d => WEEKDAYS[d - 1]))} ${at}`;
        }
        case 'monthly': {
            const days = cleanDays(r.days, 31);
            if (!days.length) return `Monthly, no day chosen, ${at}`;
            return `Monthly on the ${listJoin(days.map(ordinal))} ${at}`;
        }
        default:
            return '';
    }
};

/** A sentence saying what's wrong with a recurrence, or null when it can be saved. */
export const recurrenceProblem = (r: Recurrence): string | null => {
    if (r.freq === 'weekly' && !cleanDays(r.days, 7).length) return 'Choose at least one day of the week.';
    if (r.freq === 'monthly' && !cleanDays(r.days, 31).length) return 'Choose at least one day of the month.';
    if (!TIME_RE.test(r.time)) return 'Choose a time.';
    if (!r.tz) return 'Choose a time zone.';
    return null;
};

export const isTimeZone = (tz: unknown): tz is string => {
    if (typeof tz !== 'string' || !tz) return false;
    try {
        new Intl.DateTimeFormat('en-US', { timeZone: tz });
        return true;
    } catch {
        return false;
    }
};

const cleanTime = (value: unknown): string | null => {
    if (typeof value !== 'string') return null;
    const m = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
    if (!m) return null;
    const time = `${m[1].padStart(2, '0')}:${m[2]}`;
    return TIME_RE.test(time) ? time : null;
};

/** What a widget asked for, made into a recurrence the dialog can show. `tz` fills a missing or unknown zone. */
export const normalizeRecurrence = (value: unknown, tz: string): Recurrence => {
    const r = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
    const freq = (FREQUENCY_IDS.includes(r.freq as string) ? r.freq : 'daily') as Frequency;
    const time = cleanTime(r.time) || DEFAULT_TIME;
    const days = freq === 'weekly' ? cleanDays(r.days, 7) : freq === 'monthly' ? cleanDays(r.days, 31) : [];
    return {
        freq,
        days: (freq === 'weekly' || freq === 'monthly') && !days.length ? [1] : days,
        time,
        tz: isTimeZone(r.tz) ? r.tz : tz,
    };
};

/** Switching frequency keeps the time and zone, and starts the day list over where the meaning changes. */
export const withFrequency = (r: Recurrence, freq: Frequency): Recurrence => {
    if (freq === r.freq) return r;
    const days = freq === 'weekly' || freq === 'monthly' ? [1] : [];
    return { ...r, freq, days };
};

// ------------------------------------------------------------ the request

/** Addresses from text or a list: split on commas, semicolons and spaces, blanks dropped, repeats (any case) once. */
export const parseRecipients = (value: unknown): string[] => {
    const parts = (Array.isArray(value) ? value : [value])
        .filter((v): v is string => typeof v === 'string')
        .flatMap(v => v.split(/[\s,;]+/));
    const seen = new Set<string>();
    const out: string[] = [];
    for (const part of parts) {
        const address = part.trim();
        const key = address.toLowerCase();
        if (!address || seen.has(key)) continue;
        seen.add(key);
        out.push(address);
    }
    return out;
};

/** Only a hint for the person typing: the server decides what it will send to. */
export const looksLikeEmail = (value: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);

export interface NormalizedScheduleRequest {
    name: string;
    subject: string;
    message: string;
    sql: string;
    kind: ScheduleKind;
    /** The widget asked for a statement run but isn't executable, so it was made a report. */
    statementRefused: boolean;
    sendWhen: SendWhen;
    attachCsv: boolean;
    /** Null when the widget named nobody, so the dialog starts with the person themselves. */
    recipients: string[] | null;
    recurrence: Recurrence;
}

const text = (value: unknown, max = 10_000): string => (typeof value === 'string' ? value.trim().slice(0, max) : '');

/**
 * What a widget passed to `schedule`, reduced to what the dialog holds. A
 * statement run is offered only from an executable widget, whose runs are
 * recorded in the action log; anywhere else the request becomes a report.
 */
export const normalizeScheduleRequest = (
    request: unknown,
    { tz, executable }: { tz: string; executable: boolean },
): NormalizedScheduleRequest => {
    const r = (request && typeof request === 'object' ? request : {}) as Record<string, unknown>;
    const asked = KINDS.includes(r.kind as ScheduleKind) ? r.kind as ScheduleKind : 'email_report';
    const kind: ScheduleKind = asked === 'run_statement' && !executable ? 'email_report' : asked;
    const recipients = r.recipients === undefined || r.recipients === null ? null : parseRecipients(r.recipients);
    return {
        name: text(r.name, MAX_NAME_LENGTH),
        subject: text(r.subject, 200),
        message: typeof r.message === 'string' ? r.message.slice(0, 10_000) : '',
        sql: typeof r.sql === 'string' ? r.sql.trim() : '',
        kind,
        statementRefused: asked !== kind,
        sendWhen: (SEND_WHEN_IDS.includes(r.sendWhen as string) ? r.sendWhen : 'always') as SendWhen,
        attachCsv: r.attachCsv === true,
        recipients,
        recurrence: normalizeRecurrence(r.recurrence, tz),
    };
};

/** A sentence saying what stops the form saving, or null. The server checks everything again. */
export const formProblem = (form: ScheduleForm, sql: string): string | null => {
    if (!form.name.trim()) return 'Give the schedule a name.';
    if (!sql.trim()) return 'There’s no query to run: the widget didn’t pass one.';
    if (form.kind === 'email_report' && !form.recipients.length) return 'Add at least one recipient.';
    return recurrenceProblem(form.recurrence);
};

/** The body of `POST /api/schedules`. A statement run emails nobody, so its email fields go empty. */
export const createPayload = (form: ScheduleForm, sql: string, source: ScheduleSource) => ({
    ...patchPayload(form),
    kind: form.kind,
    sql,
    ...source,
});

/** The body of `PATCH /api/schedules/{id}`: the fields the dialog edits, never owner, kind or the query. */
export const patchPayload = (form: ScheduleForm) => {
    const report = form.kind === 'email_report';
    return {
        name: form.name.trim(),
        recipients: report ? form.recipients : [],
        subject: report ? form.subject.trim() : '',
        message: report ? form.message : '',
        send_when: report ? form.sendWhen : 'always' as SendWhen,
        attach_csv: report && form.attachCsv,
        recurrence: form.recurrence,
    };
};

export type CreatePayload = ReturnType<typeof createPayload>;
export type PatchPayload = ReturnType<typeof patchPayload>;

export const formOf = (s: Schedule): ScheduleForm => ({
    name: s.name || '',
    kind: s.kind,
    recipients: [...(s.recipients || [])],
    subject: s.subject || '',
    message: s.message || '',
    sendWhen: s.send_when || 'always',
    attachCsv: !!s.attach_csv,
    recurrence: { ...s.recurrence, days: [...(s.recurrence?.days || [])] },
});

// --------------------------------------------------------------- labels

export const statusLabel = (s: Pick<Schedule, 'status' | 'paused_reason'>): string => {
    if (s.status === 'needs_reconnect') return 'Needs reconnect';
    if (s.status === 'paused') return s.paused_reason === 'failures' ? 'Paused after failures' : 'Paused';
    return 'Active';
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
    ok: 'Succeeded',
    skipped: 'Skipped',
    failed: 'Failed',
    needs_reconnect: 'Needs reconnect',
};

export const TRIGGER_LABELS: Record<RunTrigger, string> = {
    schedule: 'On schedule',
    manual: 'Run now',
    recovery: 'Missed run',
};

export const KIND_LABELS: Record<ScheduleKind, string> = {
    email_report: 'Email report',
    run_statement: 'Statement',
};

// --------------------------------------------------------- the connection

/**
 * What a sign-in that didn't finish means to the person, keyed by the vault's
 * `oauth_error` reasons (`services/token_vault.py`). Anything else reads as a
 * plain failure rather than a code.
 */
export const OAUTH_ERRORS: Record<string, string> = {
    not_set_up: 'Scheduling isn’t set up in this app yet.',
    denied: 'You cancelled the Databricks sign-in, so nothing was connected.',
    idp_error: 'Databricks couldn’t finish the sign-in. Try connecting again.',
    invalid_state: 'That sign-in had expired or was started in another tab. Connect again from here.',
    exchange_failed: 'Databricks didn’t accept the sign-in. Try again; if it keeps failing, ask an administrator to check the app connection.',
    identity_mismatch: 'You signed in to Databricks as a different user. Sign in as yourself and connect again.',
    no_refresh_token: 'Databricks didn’t grant lasting access, so schedules couldn’t run as you. Ask an administrator to check the app connection’s scopes.',
    storage_failed: 'The app couldn’t save your connection. Try again in a moment.',
    not_signed_in: 'The app couldn’t tell who you are. Reload the page and connect again.',
    invalid_id_token: 'The app couldn’t verify who signed in. Try connecting again.',
    no_id_token: 'Databricks didn’t say who signed in. Ask an administrator to check the app connection includes signing in.',
};

export const oauthErrorMessage = (reason: string): string =>
    OAUTH_ERRORS[reason] || 'Your account wasn’t connected. Try again.';

/** Why a connection stopped working, from `GET /api/oauth/status`'s `reason`. */
export const RECONNECT_REASONS: Record<string, string> = {
    expired: 'Your connection expired.',
    revoked: 'Your connection was revoked or replaced.',
    undecryptable: 'This app can no longer read your connection because its key changed.',
};

export type OAuthOutcome = { connected: true } | { connected: false; reason: string; message: string };

const OUTCOME_KEYS = ['oauth', 'oauth_error'];

const paramName = (part: string): string => {
    const name = part.split('=')[0].replace(/\+/g, ' ');
    try {
        return decodeURIComponent(name);
    } catch {
        return name;
    }
};

/** What a return from `/api/oauth/connect` says happened; null for an address that isn't one. */
export const readOAuthOutcome = (search: string): OAuthOutcome | null => {
    const params = new URLSearchParams(search);
    const error = params.get('oauth_error');
    if (error !== null) return { connected: false, reason: error, message: oauthErrorMessage(error) };
    return params.get('oauth') === 'connected' ? { connected: true } : null;
};

/** `search` without the outcome, every other param kept as it was written. */
export const withoutOAuthOutcome = (search: string): string => {
    const kept = search.replace(/^\?/, '').split('&').filter(part => part && !OUTCOME_KEYS.includes(paramName(part)));
    return kept.length ? `?${kept.join('&')}` : '';
};

const MAX_RETURN_TO = 2048;

const printable = (value: string): string => value.replace(/[^\x21-\x5b\x5d-\x7e]/gu, ch => {
    try {
        return encodeURIComponent(ch);
    } catch {
        return '';
    }
});

/**
 * The `return_to` for a connect: this page's path, query (less any earlier
 * outcome) and hash, as the vault accepts them: one leading `/`, printable
 * ASCII, no backslash, at most 2,048 characters. Too long, the query goes first,
 * since the hash is what names the page.
 */
export const returnPath = (pathname: string, search = '', hash = ''): string => {
    const path = pathname.startsWith('/') && !pathname.startsWith('//') ? pathname : '/';
    for (const candidate of [path + withoutOAuthOutcome(search) + hash, path + hash, path]) {
        const out = printable(candidate);
        if (out.length <= MAX_RETURN_TO && out.startsWith('/') && !out.startsWith('//')) return out;
    }
    return '/';
};

/** A top-level navigation: the vault's sign-in comes back to `returnTo` with the outcome. */
export const connectUrl = (returnTo: string): string => `/api/oauth/connect?return_to=${encodeURIComponent(returnTo)}`;

export const currentReturnPath = (): string =>
    returnPath(window.location.pathname, window.location.search, window.location.hash);

let heldOutcome: OAuthOutcome | null = null;

/**
 * Called once at startup, before anything reads the address: keeps the outcome
 * of a connect for whoever shows it, and takes it out of the address so a
 * reload or a copied link doesn't announce it again.
 */
export const takeOAuthOutcome = (): void => {
    try {
        const outcome = readOAuthOutcome(window.location.search);
        if (!outcome) return;
        heldOutcome = outcome;
        const { pathname, search, hash } = window.location;
        window.history.replaceState(window.history.state, '', pathname + withoutOAuthOutcome(search) + hash);
    } catch {
        /* file: or test */
    }
};

export const pendingOAuthOutcome = (): OAuthOutcome | null => heldOutcome;

export const clearOAuthOutcome = (): void => {
    heldOutcome = null;
};

/**
 * Why the app-wide banner should show, or null. Only schedules that should be
 * running count: one waiting for a reconnect, or an active one whose connection
 * ends within a week.
 */
export const bannerReason = (
    connection: ConnectionStatus | null,
    schedules: Pick<Schedule, 'status'>[],
    now: number | Date = Date.now(),
): 'reconnect' | 'expiring' | null => {
    const running = schedules.filter(s => s.status === 'active' || s.status === 'needs_reconnect');
    if (!running.length) return null;
    if (running.some(s => s.status === 'needs_reconnect') || connection?.needs_reconnect) return 'reconnect';
    if (connection?.connected && expiresWithin(connection.expires_at, 7, now)) return 'expiring';
    return null;
};

// ------------------------------------------------------------- requests

export type Result<T> = { ok: true; data: T } | { ok: false; status: number; error: string };

const detailOf = async (res: Response): Promise<string> => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string' && body.detail) return body.detail;
    } catch {
        // Not JSON; fall through to the status line.
    }
    return `${res.statusText || 'Request failed'} (HTTP ${res.status})`;
};

const call = async <T>(path: string, init?: RequestInit): Promise<Result<T>> => {
    try {
        const res = await fetch(path, init);
        if (!res.ok) return { ok: false, status: res.status, error: await detailOf(res) };
        return { ok: true, data: await res.json() as T };
    } catch (e) {
        console.warn(`${init?.method || 'GET'} ${path} failed:`, e);
        return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
    }
};

const send = <T>(method: string, path: string, body?: unknown) => call<T>(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
});

const item = (id: string) => `/api/schedules/${encodeURIComponent(String(id))}`;

const isSchedule = (value: unknown): value is Schedule =>
    !!value && typeof value === 'object' && 'id' in value && 'recurrence' in value;

/** The schedule in a response, bare or as `{ schedule }`; anything else is an error, since a row drawn from it would break the page. */
const scheduleOf = (result: Result<unknown>): Result<Schedule> => {
    if (!result.ok) return result;
    const data = result.data as { schedule?: unknown } | null;
    const found = isSchedule(data) ? data : isSchedule(data?.schedule) ? data.schedule : null;
    return found ? { ok: true, data: found } : { ok: false, status: 0, error: 'The server’s answer didn’t include the schedule. Refresh to see it.' };
};

export const listSchedules = async (all = false): Promise<Result<{ schedules: Schedule[]; can_see_all: boolean }>> => {
    const result = await call<{ schedules?: unknown; can_see_all?: unknown }>(`/api/schedules${all ? '?all=true' : ''}`);
    if (!result.ok) return result;
    const schedules = Array.isArray(result.data?.schedules) ? result.data.schedules.filter(isSchedule) : [];
    return { ok: true, data: { schedules, can_see_all: result.data?.can_see_all === true } };
};

export const createSchedule = async (payload: CreatePayload): Promise<Result<{ schedule: Schedule; connection: ConnectionStatus | null }>> => {
    const result = await send<{ connection?: ConnectionStatus | null }>('POST', '/api/schedules', payload);
    const schedule = scheduleOf(result);
    if (!schedule.ok) return schedule;
    return { ok: true, data: { schedule: schedule.data, connection: (result.ok && result.data?.connection) || null } };
};

export const updateSchedule = async (id: string, patch: PatchPayload) => scheduleOf(await send('PATCH', item(id), patch));

export const deleteSchedule = (id: string) => send<{ deleted: boolean }>('DELETE', item(id));

export const pauseSchedule = async (id: string) => scheduleOf(await send('POST', `${item(id)}/pause`));

export const resumeSchedule = async (id: string) => scheduleOf(await send('POST', `${item(id)}/resume`));

/** Queues a run for the scheduler's next tick, within about 30 seconds. */
export const runScheduleNow = async (id: string) => scheduleOf(await send('POST', `${item(id)}/run`));

export const listRuns = (id: string, limit = 20) => call<{ runs: ScheduleRun[] }>(`${item(id)}/runs?limit=${limit}`);

export const fetchConnection = () => call<ConnectionStatus>('/api/oauth/status');

export const disconnectAccount = () => send<{ disconnected: boolean }>('POST', '/api/oauth/disconnect');
