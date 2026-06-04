import { useMemo } from 'react';
import { useDashboardStore } from '../store/dashboardStore';
import { widgetRegistry } from '../widgetRegistry';

/**
 * The "emitted" snapshot of everything happening on the active view.
 *
 * This is the extended evolution of the per-widget Emitter/Receiver mechanism
 * (dashboard variables): instead of only sharing the handful of variables a
 * widget author opts into, we broadcast the full picture of what the user is
 * currently looking at — every widget's title, description, and configuration —
 * plus the user's identity and roles. It feeds the AI assistant so it always
 * has grounded context about the user's screen.
 */
export interface EmittedWidgetContext {
    id: string;
    title: string;
    description: string;
    domain?: string;
    category?: string;
    /** The widget's live configuration (its props), minus internal bookkeeping keys. */
    configuration: Record<string, any>;
}

export interface EmittedUserContext {
    email: string;
    isAdmin: boolean;
    /** Map of domain -> permission level (viewer/editor/admin). */
    roles: Record<string, string>;
}

export interface DashboardContext {
    user: EmittedUserContext;
    view: { id: string; name: string } | null;
    widgets: EmittedWidgetContext[];
    /** Explicit dashboard variables set by Emitter widgets. */
    variables: Record<string, any>;
}

// Internal prop keys we don't want to leak into the emitted configuration.
const INTERNAL_PROP_KEYS = new Set(['_version']);

const sanitizeConfiguration = (props?: Record<string, any>): Record<string, any> => {
    if (!props) return {};
    const clean: Record<string, any> = {};
    Object.entries(props).forEach(([k, v]) => {
        if (!INTERNAL_PROP_KEYS.has(k)) clean[k] = v;
    });
    return clean;
};

/**
 * Assemble the live emitted context for the active view. Memoized against the
 * inputs so consumers (e.g. the agent panel) can depend on it directly.
 */
export const useDashboardContext = (): DashboardContext => {
    const { tabs, activeTabId, username, isAdmin, domainPermissions, variables } = useDashboardStore();

    const activeTab = useMemo(
        () => tabs.find(t => t.id === activeTabId) || null,
        [tabs, activeTabId]
    );

    return useMemo<DashboardContext>(() => {
        const widgets: EmittedWidgetContext[] = (activeTab?.widgets || []).map(w => {
            const versionKey = w.props?._version ? `${w.type}@${w.props._version}` : w.type;
            const def = widgetRegistry[versionKey] || widgetRegistry[w.type];
            return {
                id: w.i,
                title: def?.name || w.type,
                description: def?.description || '',
                domain: def?.domain,
                category: def?.category,
                configuration: sanitizeConfiguration(w.props),
            };
        });

        return {
            user: {
                email: username,
                isAdmin,
                roles: domainPermissions || {},
            },
            view: activeTab ? { id: activeTab.id, name: activeTab.name } : null,
            widgets,
            variables: variables || {},
        };
    }, [activeTab, username, isAdmin, domainPermissions, variables]);
};

/**
 * Render the emitted context into a compact, human-readable preamble that is
 * prepended (invisibly) to the user's message before it is sent to the agent.
 * Keeping it as plain structured text lets the agent reason over it without any
 * changes to its API contract.
 */
export const buildContextPreamble = (ctx: DashboardContext): string => {
    const lines: string[] = [];
    lines.push('[DASHBOARD CONTEXT — for your awareness, not shown to the user]');

    lines.push(
        `User: ${ctx.user.email} | Admin: ${ctx.user.isAdmin ? 'yes' : 'no'} | ` +
        `Roles: ${Object.keys(ctx.user.roles).length ? JSON.stringify(ctx.user.roles) : 'none'}`
    );

    if (ctx.view) {
        lines.push(`Active view: "${ctx.view.name}"`);
    }

    if (ctx.widgets.length) {
        lines.push(`Widgets currently on screen (${ctx.widgets.length}):`);
        ctx.widgets.forEach((w, i) => {
            const cfg = Object.keys(w.configuration).length
                ? ` | config: ${JSON.stringify(w.configuration)}`
                : '';
            const desc = w.description ? ` — ${w.description}` : '';
            lines.push(`  ${i + 1}. ${w.title}${desc}${cfg}`);
        });
    } else {
        lines.push('Widgets currently on screen: none');
    }

    if (Object.keys(ctx.variables).length) {
        lines.push(`Shared dashboard variables: ${JSON.stringify(ctx.variables)}`);
    }

    lines.push('[END DASHBOARD CONTEXT]');
    return lines.join('\n');
};
