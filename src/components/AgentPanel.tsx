import React, { useEffect } from 'react';
import { Bot, MessageSquarePlus, PanelRightClose, ChevronDown, Pin } from 'lucide-react';
import type { AgentChat } from '../hooks/useAgentChat';
import { AgentConversation } from './AgentConversation';
import { ConversationHistory } from './ConversationHistory';
import { useDashboardStore, DEFAULT_AGENT_PIN } from '../store/dashboardStore';
import { pinnedAgentOf } from '../store/appSpec';

const DEFAULT_AGENT_NAME = 'EDH Agent';

export const AgentPanel: React.FC<{
    chat: AgentChat;
    onCollapse: () => void;
    /** What the built-in agent is called here; an app shown on its own may rename it. */
    defaultAgentName?: string;
}> = ({ chat, onCollapse, defaultAgentName = DEFAULT_AGENT_NAME }) => {
    const {
        isLoading, clear, widgetCount,
        availableProfiles, selectedProfileId, setSelectedProfileId, loadProfilesOnce,
        pinnedAgentUnavailable,
    } = chat;

    // The pin belongs to the app, so it is read and written through the
    // dashboard store rather than the chat — the same save path as renaming or
    // locking an app, which is also what decides who is allowed to do it.
    const { activeApp, activeAppTab, setPinnedAgent, canEditApp, standalone } = useDashboardStore();
    const pinnedAgentId = pinnedAgentOf(activeApp, activeAppTab);
    // What the pin would be if the user set it now. Pinning the built-in agent is
    // a real choice, so an empty picker maps to the explicit default marker.
    const wouldPin = selectedProfileId || DEFAULT_AGENT_PIN;
    const isPinnedHere = pinnedAgentId === wouldPin;
    // Pinning is an edit to the app, and an app shown on its own is edited in the workspace.
    const canPin = !standalone && canEditApp(activeApp);

    const nameOf = (id: string): string =>
        (id === DEFAULT_AGENT_PIN || !id)
            ? defaultAgentName
            : (availableProfiles.find(p => p.id === id)?.name || 'an agent you cannot open');

    // A picker showing a value that isn't in its list renders blank, which reads
    // as "no agent" when the truth is "an agent that is gone".
    const selectionMissing = Boolean(
        selectedProfileId
        && availableProfiles.length > 0
        && !availableProfiles.some(p => p.id === selectedProfileId),
    );

    // Pinning a personal agent to a view other people open leaves them with the
    // default agent and no explanation, so say so at the moment it happens.
    const selectedProfile = availableProfiles.find(p => p.id === selectedProfileId);
    const pinnedButPrivate = Boolean(
        isPinnedHere && activeApp?.is_global && selectedProfile?.visibility === 'personal',
    );

    const togglePin = () => {
        if (!activeApp) return;
        setPinnedAgent(activeApp.id, activeAppTab?.id ?? null, isPinnedHere ? null : wouldPin);
    };

    // Populate the profile picker as soon as the drawer opens, so the saved
    // agents are present the first time the user opens the dropdown (a native
    // <select> shows its current options immediately; loading on click would
    // only fill them after a reopen). Guarded to run once per session.
    useEffect(() => {
        loadProfilesOnce();
    }, [loadProfilesOnce]);

    return (
        <div className="flex flex-col h-full bg-white">
            {/* Header — the agent title doubles as the profile picker (Agent
                Studio profiles), on its own line so it isn't cramped at narrow
                widths. Loaded lazily/throttled to avoid a UC scan on every mount. */}
            <div className="px-4 py-2.5 border-b border-gray-200 shrink-0">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                        <div className="p-1.5 bg-brand-navy/10 rounded-md shrink-0">
                            <Bot className="w-4 h-4 text-brand-navy" />
                        </div>
                        <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-blue">
                            Active Agent:
                        </span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                        <ConversationHistory chat={chat} disabled={isLoading} />
                        <button
                            onClick={clear}
                            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                            title="New conversation (this one is saved in history)"
                        >
                            <MessageSquarePlus className="w-4 h-4" />
                        </button>
                        <button
                            onClick={onCollapse}
                            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                            title={`Collapse ${defaultAgentName}`}
                        >
                            <PanelRightClose className="w-4 h-4" />
                        </button>
                    </div>
                </div>
                <div className="flex items-center gap-1.5 mt-2">
                    <div className="relative flex-1 min-w-0">
                        <select
                            value={selectedProfileId}
                            onChange={e => setSelectedProfileId(e.target.value)}
                            onFocus={loadProfilesOnce}
                            onMouseDown={loadProfilesOnce}
                            disabled={isLoading}
                            title="Run the drawer as a saved Agent Studio profile"
                            className="w-full truncate appearance-none rounded-md border border-brand-blue/40 bg-brand-blue/5 hover:bg-brand-blue/10 pl-2.5 pr-8 py-1.5 text-sm font-semibold text-brand-navy cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-brand-blue/40 disabled:opacity-50"
                        >
                            <option value="">{defaultAgentName} (default)</option>
                            {availableProfiles.map(p => {
                                const provenance = p.owned_by_me
                                    ? (p.location_label ? ` · ${p.location_label}` : '')
                                    : ` · shared${p.author ? ` by ${p.author}` : ''}`;
                                return (
                                    <option key={p.id} value={p.id}>
                                        {p.name}{provenance}
                                    </option>
                                );
                            })}
                            {selectionMissing && (
                                <option value={selectedProfileId}>Agent unavailable</option>
                            )}
                        </select>
                        <ChevronDown className="w-4 h-4 text-brand-blue absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                    {canPin && (
                        <button
                            onClick={togglePin}
                            aria-pressed={isPinnedHere}
                            aria-label={isPinnedHere
                                ? `Unpin ${nameOf(wouldPin)} from ${activeApp?.name}`
                                : `Pin ${nameOf(wouldPin)} to ${activeApp?.name}`}
                            title={isPinnedHere
                                ? `Pinned to "${activeApp?.name}" — click to unpin`
                                : `Open "${activeApp?.name}" with ${nameOf(wouldPin)}`}
                            className={`shrink-0 p-1.5 rounded-md border transition-colors ${isPinnedHere
                                ? 'border-brand-blue/40 bg-brand-blue text-white hover:bg-brand-blue/90'
                                : 'border-gray-200 text-gray-400 hover:text-brand-blue hover:border-brand-blue/40 hover:bg-brand-blue/5'}`}
                        >
                            <Pin className={`w-4 h-4 ${isPinnedHere ? 'fill-current' : ''}`} />
                        </button>
                    )}
                </div>
                {pinnedAgentUnavailable ? (
                    <div className="text-[10px] text-amber-600 mt-1.5 pl-0.5">
                        This view is pinned to an agent you can't open, so it stays on the one above.
                    </div>
                ) : pinnedButPrivate ? (
                    <div className="text-[10px] text-amber-600 mt-1.5 pl-0.5">
                        This agent is private, so others on this view still get the {defaultAgentName}.
                    </div>
                ) : pinnedAgentId && !isPinnedHere ? (
                    <div className="text-[10px] text-gray-400 mt-1.5 pl-0.5">
                        {nameOf(pinnedAgentId)} is pinned to this view
                    </div>
                ) : null}
                <div className="text-[10px] text-gray-400 mt-1.5 pl-0.5">
                    {widgetCount} widget{widgetCount === 1 ? '' : 's'} in context
                </div>
            </div>

            <AgentConversation chat={chat} placeholder="Ask about your dashboard…" />
        </div>
    );
};
