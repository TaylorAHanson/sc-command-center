import React, { useEffect, useRef, useState } from 'react';
import { Bot, Check, MessageSquarePlus, PanelRightClose, ChevronDown, Pin } from 'lucide-react';
import type { AgentChat } from '../hooks/useAgentChat';
import { AgentConversation } from './AgentConversation';
import { ConversationHistory } from './ConversationHistory';
import { useDashboardStore, DEFAULT_AGENT_PIN } from '../store/dashboardStore';
import { DEFAULT_AGENT_NAME, pinnedAgentOf, tabLabel } from '../store/appSpec';

export const AgentPanel: React.FC<{
    chat: AgentChat;
    onCollapse: () => void;
}> = ({ chat, onCollapse }) => {
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
            ? DEFAULT_AGENT_NAME
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

    // With one tab there is one place to pin: whichever pin is in force (a view
    // built from others may carry it on its tab). With several, the menu chooses.
    const multiTab = (activeApp?.spec.tabs.length ?? 0) > 1;
    const tabPin = activeAppTab?.pinned_agent_id || '';
    const appPin = activeApp?.pinned_agent_id || '';
    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!menuOpen) return;
        const close = (e: MouseEvent) => {
            if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
        };
        document.addEventListener('mousedown', close);
        return () => document.removeEventListener('mousedown', close);
    }, [menuOpen]);

    const pinTo = (onTab: boolean, pinned: boolean) => {
        if (!activeApp) return;
        setPinnedAgent(activeApp.id, onTab ? activeAppTab?.id ?? null : null, pinned ? null : wouldPin);
    };
    const togglePin = () => {
        if (multiTab) setMenuOpen(open => !open);
        else pinTo(Boolean(tabPin), isPinnedHere);
    };
    const tabName = activeApp && activeAppTab
        ? tabLabel(activeApp, activeAppTab, activeApp.spec.tabs.indexOf(activeAppTab))
        : '';
    const pinnedWhere = multiTab && tabPin ? 'this tab' : 'this view';

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
                            title={`Collapse ${DEFAULT_AGENT_NAME}`}
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
                            <option value="">{DEFAULT_AGENT_NAME} (default)</option>
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
                        <div className="relative shrink-0" ref={menuRef}>
                            <button
                                onClick={togglePin}
                                aria-pressed={isPinnedHere}
                                aria-haspopup={multiTab ? 'menu' : undefined}
                                aria-expanded={multiTab ? menuOpen : undefined}
                                aria-label={multiTab
                                    ? `Pin ${nameOf(wouldPin)} to this tab or to ${activeApp?.name}`
                                    : isPinnedHere
                                        ? `Unpin ${nameOf(wouldPin)} from ${activeApp?.name}`
                                        : `Pin ${nameOf(wouldPin)} to ${activeApp?.name}`}
                                title={multiTab
                                    ? `Open this tab or every tab of "${activeApp?.name}" with ${nameOf(wouldPin)}`
                                    : isPinnedHere
                                        ? `Pinned to "${activeApp?.name}" — click to unpin`
                                        : `Open "${activeApp?.name}" with ${nameOf(wouldPin)}`}
                                className={`p-1.5 rounded-md border transition-colors ${isPinnedHere
                                    ? 'border-brand-blue/40 bg-brand-blue text-white hover:bg-brand-blue/90'
                                    : 'border-gray-200 text-gray-400 hover:text-brand-blue hover:border-brand-blue/40 hover:bg-brand-blue/5'}`}
                            >
                                <Pin className={`w-4 h-4 ${isPinnedHere ? 'fill-current' : ''}`} />
                            </button>
                            {multiTab && menuOpen && (
                                <div role="menu" className="absolute right-0 top-full mt-1 z-50 w-64 rounded-md border border-gray-200 bg-white shadow-lg py-1">
                                    <div className="px-3 py-1.5 text-[11px] text-gray-500">Open with {nameOf(wouldPin)}:</div>
                                    {([
                                        [true, `This tab (${tabName})`, tabPin === wouldPin],
                                        [false, `Every tab of ${activeApp?.name}`, appPin === wouldPin],
                                    ] as const).map(([onTab, label, pinned]) => (
                                        <button
                                            key={String(onTab)}
                                            role="menuitemcheckbox"
                                            aria-checked={pinned}
                                            onClick={() => { pinTo(onTab, pinned); setMenuOpen(false); }}
                                            className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left text-gray-700 hover:bg-gray-50"
                                        >
                                            <Check className={`w-4 h-4 shrink-0 ${pinned ? 'text-brand-blue' : 'invisible'}`} />
                                            <span className="truncate">{label}</span>
                                        </button>
                                    ))}
                                    {tabPin && (
                                        <div className="px-3 pt-1 pb-1.5 text-[11px] text-gray-400">
                                            This tab’s own pin wins over the view’s.
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>
                {pinnedAgentUnavailable ? (
                    <div className="text-[10px] text-amber-600 mt-1.5 pl-0.5">
                        This view is pinned to an agent you can't open, so it stays on the one above.
                    </div>
                ) : pinnedButPrivate ? (
                    <div className="text-[10px] text-amber-600 mt-1.5 pl-0.5">
                        This agent is private, so others on this view still get the {DEFAULT_AGENT_NAME}.
                    </div>
                ) : pinnedAgentId && !isPinnedHere ? (
                    <div className="text-[10px] text-gray-400 mt-1.5 pl-0.5">
                        {nameOf(pinnedAgentId)} is pinned to {pinnedWhere}
                    </div>
                ) : pinnedAgentId && multiTab ? (
                    <div className="text-[10px] text-gray-400 mt-1.5 pl-0.5">
                        Pinned to {pinnedWhere}
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
