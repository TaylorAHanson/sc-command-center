// Admin Panel → Action Logs: what the tab asks the server for, and how it keeps
// its place. The searching, filtering, sorting and paging all happen on the
// server (GET /api/actions/search, choices from GET /api/actions/facets); this
// module only turns the tab's state into those requests.
//
// Pure and import-free, so tests/action_logs.test.ts loads it under Node.

export interface ActionLog {
    id: number;
    widget_id: string;
    widget_name: string;
    action_name: string | null;
    username: string | null;
    request_id: string | null;
    domain: string | null;
    user_explanation: string;
    dashboard_context: string;
    timestamp: string;
}

export interface ActionLogPage {
    rows: ActionLog[];
    total: number;
    limit: number;
    offset: number;
    sort: SortKey;
    dir: SortDir;
}

export interface FacetValue {
    value: string;
    label: string;
    count: number;
}

export interface ActionLogFacets {
    widgets: FacetValue[];
    actions: FacetValue[];
    users: FacetValue[];
    domains: FacetValue[];
}

// The server's whitelist (server/services/action_log_query.py SORTS), in the
// order the columns are shown.
export const SORT_KEYS = ['timestamp', 'widget_name', 'action_name', 'username', 'domain', 'id'] as const;
export type SortKey = typeof SORT_KEYS[number];
export type SortDir = 'asc' | 'desc';

export const PAGE_SIZES = [25, 50, 100, 200] as const;

export interface LogQuery {
    q: string;
    widgetId: string;
    actionName: string;
    username: string;
    domain: string;
    /** `YYYY-MM-DD` from a date input, in the reader's own time zone; '' for open. */
    from: string;
    to: string;
    sort: SortKey;
    dir: SortDir;
    page: number;
    pageSize: number;
}

export const DEFAULT_QUERY: LogQuery = {
    q: '', widgetId: '', actionName: '', username: '', domain: '', from: '', to: '',
    sort: 'timestamp', dir: 'desc', page: 0, pageSize: 50,
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Local midnight of a `YYYY-MM-DD`, or null for anything else. */
const localMidnight = (day: string): Date | null => {
    if (!DAY.test(day)) return null;
    const [y, m, d] = day.split('-').map(Number);
    const at = new Date(y, m - 1, d);
    return Number.isNaN(at.getTime()) || at.getDate() !== d ? null : at;
};

/**
 * The date inputs as the server's `since` (inclusive) and `until` (exclusive).
 * Both days are the reader's local days, and `to` includes the whole of its day,
 * so "from the 1st to the 1st" is that one day.
 */
export const dateRange = (from: string, to: string): { since?: string; until?: string } => {
    const start = localMidnight(from);
    const end = localMidnight(to);
    const out: { since?: string; until?: string } = {};
    if (start) out.since = start.toISOString();
    if (end) {
        const next = new Date(end.getFullYear(), end.getMonth(), end.getDate() + 1);
        out.until = next.toISOString();
    }
    return out;
};

/** True when `from` falls after `to`, which the server would refuse. */
export const rangeIsBackwards = (from: string, to: string): boolean => {
    const start = localMidnight(from);
    const end = localMidnight(to);
    return !!start && !!end && start.getTime() > end.getTime();
};

export const searchUrl = (query: LogQuery): string => {
    const params = new URLSearchParams();
    const q = query.q.trim();
    if (q) params.set('q', q);
    if (query.widgetId) params.set('widget_id', query.widgetId);
    if (query.actionName) params.set('action_name', query.actionName);
    if (query.username) params.set('username', query.username);
    if (query.domain) params.set('domain', query.domain);
    const { since, until } = dateRange(query.from, query.to);
    if (since) params.set('since', since);
    if (until) params.set('until', until);
    params.set('sort', query.sort);
    params.set('dir', query.dir);
    params.set('limit', String(query.pageSize));
    params.set('offset', String(query.page * query.pageSize));
    return `/api/actions/search?${params.toString()}`;
};

/** Whether anything narrows the log, which decides what an empty page says. */
export const isFiltered = (query: LogQuery): boolean =>
    !!(query.q.trim() || query.widgetId || query.actionName || query.username || query.domain || query.from || query.to);

/**
 * A header click: the same column flips direction, a new one starts where
 * people expect it to (newest first for time and id, A to Z for text).
 */
export const nextSort = (current: { sort: SortKey; dir: SortDir }, key: SortKey): { sort: SortKey; dir: SortDir } => {
    if (current.sort === key) return { sort: key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
    return { sort: key, dir: key === 'timestamp' || key === 'id' ? 'desc' : 'asc' };
};

export interface PageInfo {
    first: number;
    last: number;
    pages: number;
    hasPrev: boolean;
    hasNext: boolean;
}

/** "Showing first–last of total" and what the paging buttons may do (rows 1-based). */
export const pageInfo = (total: number, page: number, pageSize: number, shown: number): PageInfo => {
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const first = shown ? page * pageSize + 1 : 0;
    return {
        first,
        last: shown ? first + shown - 1 : 0,
        pages,
        hasPrev: page > 0,
        hasNext: page + 1 < pages,
    };
};

/**
 * The tab's saved state (sessionStorage), checked field by field: an old or
 * hand-edited entry must not become a request the server refuses.
 */
export const readSavedQuery = (raw: string | null): LogQuery => {
    if (!raw) return DEFAULT_QUERY;
    let data: unknown;
    try {
        data = JSON.parse(raw);
    } catch {
        return DEFAULT_QUERY;
    }
    if (!data || typeof data !== 'object') return DEFAULT_QUERY;
    const d = data as Record<string, unknown>;
    const text = (v: unknown, max = 200) => (typeof v === 'string' ? v.slice(0, max) : '');
    const day = (v: unknown) => (typeof v === 'string' && localMidnight(v) ? v : '');
    const sort = SORT_KEYS.includes(d.sort as SortKey) ? (d.sort as SortKey) : DEFAULT_QUERY.sort;
    const dir: SortDir = d.dir === 'asc' || d.dir === 'desc' ? d.dir : DEFAULT_QUERY.dir;
    const pageSize = (PAGE_SIZES as readonly number[]).includes(d.pageSize as number)
        ? (d.pageSize as number) : DEFAULT_QUERY.pageSize;
    const page = Number.isInteger(d.page) && (d.page as number) >= 0 ? (d.page as number) : 0;
    return {
        q: text(d.q), widgetId: text(d.widgetId, 500), actionName: text(d.actionName, 500),
        username: text(d.username, 500), domain: text(d.domain, 500), from: day(d.from), to: day(d.to),
        sort, dir, page, pageSize,
    };
};
