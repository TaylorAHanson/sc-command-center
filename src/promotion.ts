/**
 * Widget promotion between the dev / test / prod environments, shared by Admin
 * Panel → Widget Promotion and Widget Studio's promotion panel.
 *
 * Version numbers are per env. `POST /api/promotion/transfer` copies the source
 * row into the target as the target's next number, so Dev v7 may well arrive as
 * Test v3 — never compare or display a version without the env it belongs to.
 */

export type Env = 'dev' | 'test' | 'prod';

export const ENVS: readonly Env[] = ['dev', 'test', 'prod'];

export const ENV_LABELS: Record<Env, string> = { dev: 'Dev', test: 'Test', prod: 'Prod' };

/** Head version number per env; absent means the widget isn't in that env. */
export type EnvHeads = Partial<Record<Env, number>>;

export interface PromotionResult {
    ok: boolean;
    message: string;
}

/** One non-deprecated version, as `/api/widgets/history` describes it (no code). */
export interface PromotionVersion {
    version: number;
    name: string;
    created_by: string | null;
    timestamp: string | null;
    is_certified: boolean;
    domain: string | null;
    lines: number;
    chars: number;
}

export interface EnvPromotion {
    /** Newest first, deprecated versions excluded. Empty when `error` is set. */
    versions: PromotionVersion[];
    /** The highest non-deprecated version, which is what the env serves. */
    head: PromotionVersion | null;
    /** Set when this env couldn't be read — the lists are then unknown, not empty. */
    error: string | null;
}

export type WidgetPromotion = Record<Env, EnvPromotion>;

/**
 * The client's copy of `require_domain_editor`, which the transfer applies in the
 * target env: a global admin, or editor/admin on the widget's domain.
 */
export const canPromote = (
    isAdmin: boolean,
    domainPermissions: Record<string, string>,
    domain?: string | null,
): boolean => {
    if (isAdmin) return true;
    const level = domainPermissions[domain || 'General'];
    return level === 'editor' || level === 'admin';
};

/**
 * Which env the admin screen copies `version` from: the first of dev, test, prod
 * whose head is at least that number. The transfer looks the row up by exact
 * version in the source, so this only finds it when that env holds the number.
 */
export const sourceEnvFor = (version: number, heads: EnvHeads): Env => {
    for (const env of ENVS) {
        const head = heads[env];
        if (head !== undefined && head >= version) return env;
    }
    return 'dev';
};

/**
 * Postgres timestamps arrive without a zone and are UTC; parsed as they are,
 * every version looks hours older or newer than it is.
 */
export const parseServerTime = (ts?: string | null): Date | null => {
    if (!ts) return null;
    const date = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(ts) ? ts : `${ts}Z`);
    return Number.isNaN(date.getTime()) ? null : date;
};

const failureText = async (res: Response): Promise<string> => {
    try {
        const data = await res.json();
        const reason = data?.detail ?? data?.message;
        if (typeof reason === 'string' && reason) return reason;
        // FastAPI validation errors put a list of problems in `detail`.
        if (reason) return JSON.stringify(reason);
    } catch { /* non-JSON body */ }
    return `${res.statusText || 'Request failed'} (HTTP ${res.status})`;
};

const postPromotion = async (path: string, body: object, fallback: string): Promise<PromotionResult> => {
    try {
        const res = await fetch(`/api/promotion/${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) return { ok: false, message: await failureText(res) };
        const data = await res.json().catch(() => ({}));
        return { ok: true, message: typeof data?.message === 'string' && data.message ? data.message : fallback };
    } catch (error) {
        console.error(`Error calling /api/promotion/${path}:`, error);
        return { ok: false, message: `Could not reach the server: ${error instanceof Error ? error.message : String(error)}` };
    }
};

/**
 * Copy `version` of the widget from `sourceEnv` into `targetEnv`, or with
 * `isRollback` deprecate every `targetEnv` version above `version` so it becomes
 * the head. A rollback still reads `version` from `sourceEnv` first (for the
 * domain check), so that row must exist there.
 */
export const transferWidget = (params: {
    widgetId: string;
    version: number;
    sourceEnv: Env;
    targetEnv: Env;
    isRollback?: boolean;
}): Promise<PromotionResult> =>
    postPromotion('transfer', {
        widget_id: params.widgetId,
        version: params.version,
        source_env: params.sourceEnv,
        target_env: params.targetEnv,
        is_rollback: !!params.isRollback,
    }, params.isRollback
        ? `Rolled back to ${ENV_LABELS[params.targetEnv]} v${params.version}.`
        : `Copied to ${ENV_LABELS[params.targetEnv]}.`);

/** Certify a prod version; certification only exists in prod. */
export const certifyWidget = (widgetId: string, version: number): Promise<PromotionResult> =>
    postPromotion('certify', { widget_id: widgetId, version }, `Certified Prod v${version}.`);

const loadEnv = async (widgetId: string, env: Env): Promise<EnvPromotion> => {
    try {
        const res = await fetch(`/api/widgets/history?widget_id=${encodeURIComponent(widgetId)}&env=${env}`);
        if (!res.ok) return { versions: [], head: null, error: await failureText(res) };
        const data = await res.json();
        const versions: PromotionVersion[] = (Array.isArray(data?.history) ? data.history : [])
            .map((h: Record<string, unknown>) => ({
                version: Number(h.version),
                name: String(h.name ?? ''),
                created_by: (h.created_by as string | null) ?? null,
                timestamp: (h.timestamp as string | null) ?? null,
                // Stored as 0/1 integers.
                is_certified: !!h.is_certified,
                domain: (h.domain as string | null) ?? null,
                lines: Number(h.lines ?? 0),
                chars: Number(h.chars ?? 0),
            }))
            .sort((a: PromotionVersion, b: PromotionVersion) => b.version - a.version);
        return { versions, head: versions[0] ?? null, error: null };
    } catch (error) {
        console.error(`Error loading ${env} history for widget ${widgetId}:`, error);
        return { versions: [], head: null, error: error instanceof Error ? error.message : String(error) };
    }
};

/**
 * Every env's versions and head for one widget, read in parallel. Never throws:
 * an env that fails carries `error` so the caller can offer a retry rather than
 * show "not in this env", which would be a lie.
 */
export const loadWidgetPromotion = async (widgetId: string): Promise<WidgetPromotion> => {
    const [dev, test, prod] = await Promise.all(ENVS.map(env => loadEnv(widgetId, env)));
    return { dev, test, prod };
};
