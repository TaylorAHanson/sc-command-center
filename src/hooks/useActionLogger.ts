import { useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { logAction } from '../api';
import type { ActionRunContext } from '../contexts/ActionContext';

interface UseActionLoggerProps {
    widgetId: string;
    widgetName: string;
}

/**
 * A correlation id for one action. `crypto.randomUUID` needs a secure context,
 * which a deployment always has and a bare-IP dev server may not, so fall back
 * rather than throw — a missing id costs traceability, never the action.
 */
const newRequestId = (): string => {
    try {
        return crypto.randomUUID();
    } catch {
        return `cc-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    }
};

export const useActionLogger = ({ widgetId, widgetName }: UseActionLoggerProps) => {
    const { activeApp, activeAppTab } = useDashboardStore();

    const getDashboardContext = useCallback(() => {
        if (!activeApp || !activeAppTab) return { error: "No active tab found" };

        // `tabId` / `tabName` have always held the view's id and name, and every
        // action_logs row written so far says so; they keep that meaning (now the
        // app's) so the audit trail reads the same before and after apps. The tab
        // within the app is recorded alongside.
        return {
            tabId: activeApp.id,
            tabName: activeApp.name,
            appTabId: activeAppTab.id,
            appTabName: activeAppTab.name,
            widgets: activeAppTab.widgets.map(w => ({
                id: w.i,
                type: w.type,
                props: w.props
            }))
        };
    }, [activeApp, activeAppTab]);

    const runAction = useCallback(async (name: string, action: (ctx: ActionRunContext) => void) => {
        const context = getDashboardContext();
        // Minted here so the same id reaches the audit row and the widget: the
        // log entry and the work it records are only joinable afterwards if
        // both carry it.
        const requestId = newRequestId();

        const logged = await logAction({
            widget_id: widgetId,
            widget_name: widgetName,
            action_name: name,
            explanation: '',
            context,
            request_id: requestId
        });

        if (!logged) {
            window.alert(
                'Could not record this action in the audit log, so it was not run. Try again or contact an administrator.'
            );
            return;
        }

        action({ requestId });
    }, [widgetId, widgetName, getDashboardContext]);

    return { runAction };
};
