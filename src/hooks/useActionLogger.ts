import { useState, useCallback } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { logAction } from '../api';

interface UseActionLoggerProps {
    widgetId: string;
    widgetName: string;
}

export const useActionLogger = ({ widgetId, widgetName }: UseActionLoggerProps) => {
    const [isConfirming, setIsConfirming] = useState(false);
    const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
    const { tabs, activeTabId, viewingTemplate } = useDashboardStore();

    const getDashboardContext = useCallback(() => {
        // Find the current active tab
        const activeTab = viewingTemplate ? null : tabs.find(t => t.id === activeTabId);

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
    }, [tabs, activeTabId, viewingTemplate]);

    const initiateAction = useCallback((action: () => void) => {
        setPendingAction(() => action);
        setIsConfirming(true);
    }, []);

    const confirmAction = useCallback(async (explanation: string) => {
        if (pendingAction) {
            // Log the action first (or in parallel)
            const context = getDashboardContext();

            logAction({
                widget_id: widgetId,
                widget_name: widgetName,
                explanation,
                context
            });

            // Execute the action
            pendingAction();
        }
        setIsConfirming(false);
        setPendingAction(null);
    }, [pendingAction, widgetId, widgetName, getDashboardContext]);

    const cancelAction = useCallback(() => {
        setIsConfirming(false);
        setPendingAction(null);
    }, []);

    return {
        isConfirming,
        initiateAction,
        confirmAction,
        cancelAction
    };
};
