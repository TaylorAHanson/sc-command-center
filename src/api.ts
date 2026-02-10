const API_BASE = 'http://localhost:8000/api';

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
