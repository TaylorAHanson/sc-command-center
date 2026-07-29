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

/**
 * Which deployment served this bundle: 'local' | 'dev' | 'stage' | 'prod'.
 * Comes from the backend (not a build-time constant) because the same built
 * assets get promoted across environments. Empty string when unknown.
 */
export const getAppEnvironment = async (): Promise<string> => {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) return '';
        const data = await response.json();
        return typeof data?.environment === 'string' ? data.environment.trim().toLowerCase() : '';
    } catch {
        return '';
    }
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
}

export const logAction = async (payload: ActionLogPayload) => {
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
        }
    } catch (error) {
        console.error('Error logging action:', error);
    }
};
