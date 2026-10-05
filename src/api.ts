const API_BASE = '/api';

export const logWidgetRun = async (widgetId: string) => {
    try {
        const response = await fetch(`${API_BASE}/widgets/${widgetId}/run`, {
            method: 'POST',
        });
        if (!response.ok) {
            console.error('Failed to log widget run');
        }
    } catch (error) {
        console.error('Error logging widget run:', error);
    }
};

let healthRequest: Promise<Record<string, unknown>> | null = null;

/** `/api/health`, read once per page load. */
const getHealth = (): Promise<Record<string, unknown>> => {
    healthRequest ??= fetch(`${API_BASE}/health`)
        .then(response => (response.ok ? response.json() : {}))
        .catch(() => ({}));
    return healthRequest;
};

/**
 * Which deployment served this bundle: 'local' | 'dev' | 'stage' | 'prod'.
 * Comes from the backend (not a build-time constant) because the same built
 * assets get promoted across environments. Empty string when unknown.
 */
export const getAppEnvironment = async (): Promise<string> => {
    const { environment } = await getHealth();
    return typeof environment === 'string' ? environment.trim().toLowerCase() : '';
};

/**
 * The badge for this environment ('Dev', 'Stage', 'Local'), or '' for prod.
 * The tab title is the only cue that tells someone with dev, stage and prod
 * open side by side which window they are typing into, so everything except
 * prod gets badged. An unknown environment stays unbadged rather than guessing.
 */
export const getEnvironmentBadge = async (): Promise<string> => {
    const env = (await getAppEnvironment()) || (import.meta.env.DEV ? 'local' : '');
    if (!env || env === 'prod' || env === 'production') return '';
    return `${env.charAt(0).toUpperCase()}${env.slice(1)}`;
};

/** The deployment's brand name (`APP_BRAND`), or '' when none is set. */
export const getAppBrand = async (): Promise<string> => {
    const { brand } = await getHealth();
    return typeof brand === 'string' && /^[a-z][a-z0-9]*$/.test(brand) ? brand : '';
};

export const getPopularityScores = async (): Promise<Record<string, number>> => {
    try {
        const response = await fetch(`${API_BASE}/widgets/popularity`);
        if (!response.ok) {
            throw new Error('Failed to fetch popularity scores');
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching popularity scores:', error);
        return {};
    }
};

export interface ActionLogPayload {
    widget_id: string;
    widget_name: string;
    action_name: string;
    explanation: string;
    context: any;
    /**
     * Correlation handle for this approval, also handed to the widget's callback
     * so it can tag the statement it runs. It is what lets an auditor get from
     * "who approved this and why" to the row Databricks recorded for the work.
     */
    request_id?: string;
}

export const logAction = async (payload: ActionLogPayload): Promise<boolean> => {
    try {
        const response = await fetch(`${API_BASE}/actions/log`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            console.error('Failed to log action');
            const err = await response.text();
            console.error(err);
            return false;
        }
        return true;
    } catch (error) {
        console.error('Error logging action:', error);
        return false;
    }
};
