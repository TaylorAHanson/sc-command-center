import { useState, useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { logAction } from '../api';
import type { ActionRunContext } from '../contexts/ActionContext';

interface UseActionLoggerProps {
    widgetId: string;
    widgetName: string;
}

/**
 * A correlation id for one approval. `crypto.randomUUID` needs a secure context,
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
    const [isConfirming, setIsConfirming] = useState(false);
    const [actionName, setActionName] = useState('');
    const [pendingAction, setPendingAction] = useState<((ctx: ActionRunContext) => void) | null>(null);
    const { tabs, activeTabId } = useDashboardStore();

    const getDashboardContext = useCallback(() => {
        // Find the current active tab
        const activeTab = tabs.find(t => t.id === activeTabId);

        if (!activeTab) return { error: "No active tab found" };

        return {
            tabId: activeTab.id,
            tabName: activeTab.name,
            widgets: activeTab.widgets.map(w => ({
                id: w.i,
                type: w.type,
                props: w.props
            }))
        };
    }, [tabs, activeTabId]);

    const initiateAction = useCallback((name: string, action: (ctx: ActionRunContext) => void) => {
        setActionName(name);
        setPendingAction(() => action);
        setIsConfirming(true);
    }, []);

    const confirmAction = useCallback(async (explanation: string) => {
        if (!pendingAction) {
            return;
        }

        const context = getDashboardContext();
        // Minted here so the same id reaches the audit row and the widget: the
        // approval and the work it authorised are only joinable afterwards if
        // both carry it.
        const requestId = newRequestId();

        const logged = await logAction({
            widget_id: widgetId,
            widget_name: widgetName,
            action_name: actionName,
            explanation,
            context,
            request_id: requestId
        });

        if (!logged) {
            window.alert(
                'Could not record this action in the audit log, so it was not run. Try again or contact an administrator.'
            );
            return;
        }

        pendingAction({ requestId });
        setIsConfirming(false);
        setPendingAction(null);
        setActionName('');
    }, [pendingAction, widgetId, widgetName, actionName, getDashboardContext]);

    const cancelAction = useCallback(() => {
        setIsConfirming(false);
        setPendingAction(null);
    }, []);

    return {
        isConfirming,
        actionName,
        initiateAction,
        confirmAction,
        cancelAction
    };
};
