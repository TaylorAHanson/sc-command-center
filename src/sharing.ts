/**
 * Direct sharing (MANAGE / USE per user, group or Everyone) and the draft /
 * published vocabulary shared by views, widgets and agents.
 *
 * Access is decided on the server (`services/access.py`); nothing here grants or
 * withholds anything. The client only reads and replaces an object's list.
 */

export type ObjectType = 'app' | 'widget' | 'agent';
export type Level = 'MANAGE' | 'USE';
export type PrincipalType = 'user' | 'group' | 'all';
export type PublishState = 'draft_only' | 'published' | 'published_with_draft';
export type AccessSummary = 'private' | 'shared' | 'everyone';

export interface AclEntry {
    principal: string;
    principal_type: PrincipalType;
    level: Level;
    granted_by?: string | null;
    granted_at?: string | null;
}

export interface Acl {
    object_type: ObjectType;
    object_id: string;
    my_level: Level;
    owner: string | null;
    entries: AclEntry[];
}

export interface PrincipalSuggestion {
    principal: string;
    principal_type: PrincipalType;
    /** One of the caller's own groups (or the caller). */
    mine: boolean;
}

export interface PreflightItem {
    object_type: 'widget' | 'agent';
    object_id: string;
    name: string;
    reason: 'never_published' | 'unpublished_changes' | 'uncertified';
    can_publish: boolean;
}

export interface Preflight {
    items: PreflightItem[];
    /** Readable reasons the publish will be refused. */
    blocking: string[];
}

/** What a publish call is told to publish alongside the object itself. */
export interface PublishInclude {
    object_type: PreflightItem['object_type'];
    object_id: string;
}

export interface Me {
    username: string;
    is_admin: boolean;
    groups: string[];
}

export const EVERYONE = '*';
export const EVERYONE_LABEL = 'Everyone in this app';

export const LEVEL_LABELS: Record<Level, string> = {
    MANAGE: 'Can manage',
    USE: 'Can use',
};

export const STATE_LABELS: Record<PublishState, string> = {
    draft_only: 'Not published yet',
    published: 'Published',
    published_with_draft: 'Unpublished changes',
};

export const OBJECT_LABELS: Record<ObjectType, string> = {
    app: 'view',
    widget: 'widget',
    agent: 'agent',
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A service principal is addressed by its application id. */
export const isServicePrincipal = (principal: string): boolean => UUID.test(principal.trim());

/**
 * The type a typed name most likely is, by the same rule the access migration
 * uses: an email or an application id is a user, `*` is Everyone, anything else
 * a group (groups are matched by their exact SCIM display name).
 */
export const inferPrincipalType = (principal: string): PrincipalType => {
    const p = principal.trim();
    if (p === EVERYONE) return 'all';
    return p.includes('@') || isServicePrincipal(p) ? 'user' : 'group';
};

/** Users match ignoring case on the server (`same_person`), so the client does too. */
export const samePrincipal = (a?: string | null, b?: string | null): boolean =>
    Boolean(a && b && a.trim().toLowerCase() === b.trim().toLowerCase());

export const principalLabel = (principal: string): string =>
    principal === EVERYONE ? EVERYONE_LABEL : principal;

export const initials = (principal: string): string => {
    if (isServicePrincipal(principal)) return 'SP';
    const parts = principal.split('@')[0].split(/[\s._-]+/).filter(Boolean);
    if (!parts.length) return '?';
    const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2);
    return letters.toUpperCase();
};

/**
 * Lock / people / globe. A single grant to a user is the owner on their own; a
 * single grant to a group already reaches other people.
 */
export const accessSummary = (entries: AclEntry[]): AccessSummary => {
    if (entries.some(e => e.principal === EVERYONE)) return 'everyone';
    if (entries.length > 1 || entries.some(e => e.principal_type === 'group')) return 'shared';
    return 'private';
};

/** The same summary from the counts `GET /api/sharing/content` sends. */
export const accessSummaryFromCount = (entries: number, everyone: boolean): AccessSummary =>
    everyone ? 'everyone' : entries > 1 ? 'shared' : 'private';

const detailOf = (data: unknown): string | null => {
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    // FastAPI's validation errors are a list of {msg, loc}.
    if (Array.isArray(detail)) {
        const msgs = detail.map(d => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : String(d)));
        return msgs.join('; ') || null;
    }
    return detail == null ? null : JSON.stringify(detail);
};

/** fetch + JSON that throws an Error carrying the server's `detail` on non-2xx. */
export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
    const headers = init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers;
    const res = await fetch(url, { ...init, headers });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(detailOf(data) || `${res.statusText || 'Request failed'} (HTTP ${res.status})`);
    return data as T;
}

const aclUrl = (type: ObjectType, id: string) =>
    `/api/sharing/${encodeURIComponent(type)}/${encodeURIComponent(id)}`;

export const fetchAcl = (type: ObjectType, id: string): Promise<Acl> => requestJson<Acl>(aclUrl(type, id));

export const saveAcl = (type: ObjectType, id: string, entries: AclEntry[]): Promise<Acl> =>
    requestJson<Acl>(aclUrl(type, id), {
        method: 'PUT',
        body: JSON.stringify({
            entries: entries.map(({ principal, principal_type, level }) => ({ principal, principal_type, level })),
        }),
    });

export const searchPrincipals = async (q: string): Promise<PrincipalSuggestion[]> => {
    const data = await requestJson<{ principals?: PrincipalSuggestion[] }>(
        `/api/sharing/principals?q=${encodeURIComponent(q)}`,
    );
    return Array.isArray(data?.principals) ? data.principals : [];
};

// Identity doesn't change within a page load, and every share dialog asks.
let mePromise: Promise<Me> | null = null;

export const fetchMe = (): Promise<Me> => {
    if (!mePromise) {
        mePromise = requestJson<Partial<Me>>('/api/roles/my-permissions')
            .then(d => ({ username: d.username || '', is_admin: Boolean(d.is_admin), groups: d.groups || [] }))
            .catch(e => { mePromise = null; throw e; });
    }
    return mePromise;
};
