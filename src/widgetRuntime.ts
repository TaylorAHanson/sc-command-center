/**
 * What a widget did when it ran in Widget Studio's preview.
 *
 * The browser is the only place widget code ever runs, so it is the only place
 * that can see a query come back 400, a `.map` of undefined inside an async
 * effect, or a panel that loaded zero rows. Before this the agent was told about
 * compile errors and render crashes and nothing else: a widget that rendered its
 * own "Query failed" message counted as a success, and the user had to notice,
 * read the error, and paste it back.
 *
 * The preview's compiled widget is handed this recorder's `fetch` and `console`
 * in place of the globals (see the `new Function` call in WidgetStudio), so what
 * it records is the widget's own traffic and logging — not the studio's, which
 * shares the page. Uncaught errors come from window events and are kept only
 * when their stack runs through the evaluated widget code.
 */

export type RuntimeEntry = {
    kind: 'request' | 'console' | 'exception' | 'note';
    level: 'error' | 'warn' | 'info';
    text: string;
    /**
     * Whether changing the widget's code is the likely fix. A 400 from a query the
     * widget composed is; a 403 (the user's grants), a 5xx (the server), a network
     * failure, or the configured data source failing verbatim (the Configuration
     * tab) is not — auto-fixing those would send the agent rewriting working code.
     */
    fixable: boolean;
    count: number;
};

/** When a run counts as finished: quiet for `quietMs`, and never before `minMs` or after `maxMs`. */
export const SETTLE = { quietMs: 1000, minMs: 1500, maxMs: 10000 };

const MAX_ENTRIES = 40;
const MAX_TEXT = 400;
const SQL_CHARS = 240;

const squash = (text: string, limit: number) => {
    const flat = text.replace(/\s+/g, ' ').trim();
    return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
};

const requestUrl = (input: RequestInfo | URL): string =>
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;

/** The statement in a JSON request body, if the widget sent one. */
const sqlFromBody = (body: unknown): string | null => {
    if (typeof body !== 'string') return null;
    try {
        const parsed = JSON.parse(body);
        const sql = parsed?.sql ?? parsed?.query ?? parsed?.statement;
        return typeof sql === 'string' ? sql : null;
    } catch {
        return null;
    }
};

const describe = (value: unknown): string => {
    if (value instanceof Error) return `${value.name}: ${value.message}`;
    if (typeof value === 'string') return value;
    try {
        return JSON.stringify(value);
    } catch {
        return String(value);
    }
};

// A logged message that names a programming error. Widgets routinely log the
// failure they are about to show ("Failed to load", err), which is evidence but
// not a code bug; a TypeError they caught and logged is.
const CODE_BUG = /\b(TypeError|ReferenceError|SyntaxError|RangeError)\b|is not a function|is not defined|Cannot read propert|undefined is not/;

// Evaluated code shows up in stacks as `eval at …` / `<anonymous>:12:5` in
// Chromium and `… > Function:12:5` in Firefox. A bare `<anonymous>` is not
// enough: Chromium writes it for every built-in frame (`at Array.map
// (<anonymous>)`), so the studio's own errors carry it too.
const fromWidget = (error: unknown): boolean => {
    const stack = error instanceof Error ? error.stack || '' : '';
    return /\beval at\b|<anonymous>:\d+:\d+|> Function:\d/.test(stack);
};

const normalizeSql = (sql: string) => sql.replace(/\s+/g, ' ').trim().replace(/;$/, '').toLowerCase();

export class RuntimeRecorder {
    entries: RuntimeEntry[] = [];
    readonly fetch: typeof fetch;
    readonly console: Console;

    private inFlight = 0;
    private startedAt = Date.now();
    private lastActivity = Date.now();
    private listening = false;
    private disposed = false;
    private readonly listeners = new Set<() => void>();
    private readonly realFetch = window.fetch.bind(window);
    private readonly configuredSql: () => string;

    /** `configuredSql` is read when a request fails, so it follows edits to the data source. */
    constructor(configuredSql: () => string) {
        this.configuredSql = configuredSql;
        this.fetch = this.recordingFetch.bind(this) as typeof fetch;

        const base = window.console;
        const shadow = Object.create(base) as Console;
        shadow.error = (...args: unknown[]) => {
            base.error(...args);
            const text = args.map(describe).join(' ');
            this.add({ kind: 'console', level: 'error', text: `console.error: ${squash(text, MAX_TEXT)}`, fixable: CODE_BUG.test(text) });
        };
        shadow.warn = (...args: unknown[]) => {
            base.warn(...args);
            this.add({ kind: 'console', level: 'warn', text: `console.warn: ${squash(args.map(describe).join(' '), MAX_TEXT)}`, fixable: false });
        };
        this.console = shadow;
    }

    /** The widget has mounted: start the settle clock and listen for uncaught errors. */
    start() {
        this.startedAt = Date.now();
        this.lastActivity = Date.now();
        if (!this.listening) {
            window.addEventListener('error', this.onError);
            window.addEventListener('unhandledrejection', this.onRejection);
            this.listening = true;
        }
    }

    /** The widget unmounted; the next mount is a fresh run. In-flight counts are kept. */
    reset() {
        this.entries = [];
        this.stopListening();
        this.emit();
    }

    dispose() {
        this.disposed = true;
        this.stopListening();
        this.listeners.clear();
    }

    subscribe(listener: () => void): () => void {
        this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    }

    /** Calls `done` once the run has settled. Returns a cancel function. */
    onSettled(done: () => void): () => void {
        const timer = window.setInterval(() => {
            if (this.disposed) {
                window.clearInterval(timer);
                return;
            }
            const now = Date.now();
            const ran = now - this.startedAt;
            const quiet = this.inFlight === 0 && now - this.lastActivity >= SETTLE.quietMs;
            if ((ran >= SETTLE.minMs && quiet) || ran >= SETTLE.maxMs) {
                window.clearInterval(timer);
                if (this.inFlight > 0) {
                    this.add({
                        kind: 'note', level: 'warn', fixable: false,
                        text: `${this.inFlight} request(s) were still running ${Math.round(SETTLE.maxMs / 1000)}s after the widget mounted`,
                    });
                }
                done();
            }
        }, 200);
        return () => window.clearInterval(timer);
    }

    private stopListening() {
        if (!this.listening) return;
        window.removeEventListener('error', this.onError);
        window.removeEventListener('unhandledrejection', this.onRejection);
        this.listening = false;
    }

    private emit() {
        this.listeners.forEach(listener => listener());
    }

    private add(entry: Omit<RuntimeEntry, 'count'>) {
        if (this.disposed) return;
        this.lastActivity = Date.now();
        const last = this.entries[this.entries.length - 1];
        if (last && last.text === entry.text) {
            last.count += 1;
        } else {
            // The oldest go first: a widget that polls fills the log with routine
            // results, and the entry that matters is the one that just happened.
            this.entries = [...this.entries, { ...entry, count: 1 }].slice(-MAX_ENTRIES);
        }
        this.emit();
    }

    private onError = (event: ErrorEvent) => {
        if (!fromWidget(event.error)) return;
        this.add({ kind: 'exception', level: 'error', text: `Uncaught ${squash(describe(event.error ?? event.message), MAX_TEXT)}`, fixable: true });
    };

    private onRejection = (event: PromiseRejectionEvent) => {
        if (!fromWidget(event.reason)) return;
        this.add({ kind: 'exception', level: 'error', text: `Unhandled promise rejection: ${squash(describe(event.reason), MAX_TEXT)}`, fixable: true });
    };

    private async recordingFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
        const url = requestUrl(input);
        const path = url.startsWith(window.location.origin) ? url.slice(window.location.origin.length) : url;
        const ours = path.startsWith('/api/');
        const label = ours ? path.split('?')[0] : squash(url, 120);
        const sql = sqlFromBody(init?.body);
        const query = sql ? ` for \`${squash(sql, SQL_CHARS)}\`` : '';

        this.inFlight += 1;
        this.lastActivity = Date.now();
        let response: Response;
        try {
            response = await this.realFetch(input, init);
        } catch (err) {
            this.inFlight -= 1;
            // A widget cancelling its own request on unmount is not a failure.
            if (!(err instanceof DOMException && err.name === 'AbortError')) {
                this.add({
                    kind: 'request', level: 'error', fixable: false,
                    text: `${label}${query} did not complete: ${squash(describe(err), 200)}${ours ? '' : ' (for an external API this is usually CORS or the network)'}`,
                });
            }
            throw err;
        }

        if (!ours) {
            this.inFlight -= 1;
            if (!response.ok) {
                this.add({ kind: 'request', level: 'error', fixable: false, text: `${label} returned HTTP ${response.status}` });
            }
            return response;
        }

        // Read a copy in the background, so the widget gets its response as soon as
        // it would have and its own read of the body is untouched.
        void this.recordResponse(response.clone(), label, sql, query).finally(() => {
            this.inFlight -= 1;
            this.lastActivity = Date.now();
        });
        return response;
    }

    private async recordResponse(response: Response, label: string, sql: string | null, query: string) {
        let payload: unknown = null;
        try {
            payload = await response.json();
        } catch {
            // Not JSON; the status alone has to do.
        }
        const body = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;

        if (!response.ok) {
            const status = response.status;
            const detail = typeof body.detail === 'string' ? body.detail : response.statusText;
            const configured = this.configuredSql();
            const isConfigured = !!sql && !!configured.trim() && normalizeSql(sql) === normalizeSql(configured);
            const permission = status === 401 || status === 403;
            let text = `${label} returned HTTP ${status}${query}: ${squash(detail || '', 300)}`;
            if (isConfigured) text += ' — this is the configured data source run as written, so the fix belongs on the Configuration tab';
            else if (permission) text += ' — a permission problem for this user, not something code can fix';
            this.add({
                kind: 'request', level: 'error', text,
                fixable: status >= 400 && status < 500 && !permission && status !== 429 && !isConfigured,
            });
            return;
        }

        if (typeof body.row_count === 'number') {
            const rows = body.row_count;
            this.add({
                kind: 'request', level: rows === 0 ? 'warn' : 'info', fixable: false,
                text: `${label} returned ${rows} row${rows === 1 ? '' : 's'}${query}`,
            });
        }
    }
}

/** One entry as the agent and the Problems panel read it. */
export const formatRuntimeEntry = (entry: RuntimeEntry): string =>
    entry.count > 1 ? `${entry.text} (×${entry.count})` : entry.text;
