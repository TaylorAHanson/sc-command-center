import React, { useEffect, useRef, useState } from 'react';
import { Bot, Check, MessageSquarePlus, PanelRightClose, ChevronDown, Pin } from 'lucide-react';
import type { AgentChat } from '../hooks/useAgentChat';
import { AgentConversation } from './AgentConversation';
import { ConversationHistory } from './ConversationHistory';
import { useDashboardStore, DEFAULT_AGENT_PIN } from '../store/dashboardStore';
import { DEFAULT_AGENT_NAME, pinnedAgentOf, tabLabel, type CanvasBackground } from '../store/appSpec';

export const AgentPanel: React.FC<{
    chat: AgentChat;
    onCollapse: () => void;
    backdrop?: CanvasBackground | null;
    /** Draw the header in the dark color, as the page header beside it is. */
    dark?: boolean;
}> = ({ chat, onCollapse, backdrop, dark = false }) => {
    const quiet = dark ? 'text-white/70 hover:text-white hover:bg-white/10' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100';
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
            {/* As tall as the page header beside it (h-14), so the two read as one
                line: anything that varies goes below, never in here. */}
            <div className={`h-14 px-3 border-b shrink-0 flex items-center gap-1 ${dark ? 'bg-brand-navy border-white/10' : 'bg-white border-gray-200'}`}>
                    <div className="relative flex-1 min-w-0 mr-1">
                        <Bot className={`w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none ${dark ? 'text-white/80' : 'text-brand-navy'}`} />
                        <select
                            value={selectedProfileId}
                            onChange={e => setSelectedProfileId(e.target.value)}
                            onFocus={loadProfilesOnce}
                            onMouseDown={loadProfilesOnce}
                            disabled={isLoading}
                            aria-label="Active agent"
                            title={`The agent answering here. It can see ${widgetCount} widget${widgetCount === 1 ? '' : 's'} on this tab.`}
                            className={`w-full truncate appearance-none rounded-md border pl-8 pr-8 py-1.5 text-sm font-semibold cursor-pointer transition-colors focus:outline-none focus:ring-2 disabled:opacity-50 ${dark
                                ? 'border-white/20 bg-white/10 hover:bg-white/15 text-white focus:ring-white/40 [&>option]:text-gray-900'
                                : 'border-brand-blue/40 bg-brand-blue/5 hover:bg-brand-blue/10 text-brand-navy focus:ring-brand-blue/40'}`}
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
                        <ChevronDown className={`w-4 h-4 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none ${dark ? 'text-white/80' : 'text-brand-blue'}`} />
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
                                    : dark
                                        ? 'border-white/20 text-white/70 hover:text-white hover:bg-white/10'
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
                <ConversationHistory chat={chat} disabled={isLoading} buttonClassName={quiet} />
                <button
                    onClick={clear}
                    className={`p-1.5 rounded-md transition-colors ${quiet}`}
                    title="New conversation (this one is saved in history)"
                >
                    <MessageSquarePlus className="w-4 h-4" />
                </button>
                <button
                    onClick={onCollapse}
                    className={`p-1.5 rounded-md transition-colors ${quiet}`}
                    title={`Collapse ${DEFAULT_AGENT_NAME}`}
                >
                    <PanelRightClose className="w-4 h-4" />
                </button>
            </div>

            <AgentConversation
                chat={chat}
                placeholder="Ask about your dashboard…"
                backdrop={backdrop}
                footnote={`Sees ${widgetCount} widget${widgetCount === 1 ? '' : 's'} on this tab.`}
                notice={pinnedAgentUnavailable ? (
                    { warn: true, text: 'This view is pinned to an agent you can’t open, so it stays on the one above.' }
                ) : pinnedButPrivate ? (
                    { warn: true, text: `This agent is private, so others on this view still get the ${DEFAULT_AGENT_NAME}.` }
                ) : pinnedAgentId && !isPinnedHere ? (
                    { warn: false, text: `${nameOf(pinnedAgentId)} is pinned to ${pinnedWhere}.` }
                ) : pinnedAgentId && multiTab ? (
                    { warn: false, text: `Pinned to ${pinnedWhere}.` }
                ) : null}
            />
        </div>
    );
};
