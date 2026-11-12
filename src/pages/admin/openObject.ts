import type { WorkspaceTools } from '../../contexts/WorkspaceTools';
import type { ObjectType } from '../../sharing';

const AGENT_STUDIO = '#/agent-studio/';

/** The agent an `#/agent-studio/<id>` address asks Agent Studio to open, if any. */
export const agentIdFromHash = (hash: string): string | null => {
    if (!hash.startsWith(AGENT_STUDIO)) return null;
    try {
        return decodeURIComponent(hash.slice(AGENT_STUDIO.length)).trim() || null;
    } catch {
        return null;
    }
};

/** What the button that opens an object says: a view is looked at, the others are edited in a studio. */
export const OPEN_LABEL: Record<ObjectType, string> = { app: 'Open', widget: 'Edit', agent: 'Edit' };

/**
 * Open a view, widget or agent where people normally work on it: a view by its
 * link, a widget in Widget Studio, an agent in Agent Studio. Returns false when
 * this screen can't (Widget Studio needs the workspace's tools).
 */
export const openObject = (type: ObjectType, id: string, tools: WorkspaceTools | null): boolean => {
    if (type === 'widget') {
        if (!tools) return false;
        tools.editWidget(id);
        return true;
    }
    window.location.hash = type === 'app'
        ? `#/app/${encodeURIComponent(id)}`
        : `${AGENT_STUDIO}${encodeURIComponent(id)}`;
    return true;
};
