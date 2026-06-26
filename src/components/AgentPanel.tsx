import React, { useEffect } from 'react';
import { Bot, Trash2, PanelRightClose, ChevronDown } from 'lucide-react';
import type { AgentChat } from '../hooks/useAgentChat';
import { AgentConversation } from './AgentConversation';

export const AgentPanel: React.FC<{ chat: AgentChat; onCollapse: () => void }> = ({ chat, onCollapse }) => {
    const {
        isLoading, clear, widgetCount,
        availableProfiles, selectedProfileId, setSelectedProfileId, loadProfilesOnce,
    } = chat;

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
                        <div className="p-1.5 bg-qualcomm-navy/10 rounded-md shrink-0">
                            <Bot className="w-4 h-4 text-qualcomm-navy" />
                        </div>
                        <span className="text-[11px] font-semibold uppercase tracking-wide text-qualcomm-blue">
                            Active Agent:
                        </span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                        <button
                            onClick={clear}
                            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                            title="Clear conversation"
                        >
                            <Trash2 className="w-4 h-4" />
                        </button>
                        <button
                            onClick={onCollapse}
                            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                            title="Collapse EDH Agent"
                        >
                            <PanelRightClose className="w-4 h-4" />
                        </button>
                    </div>
                </div>
                <div className="relative mt-2">
                    <select
                        value={selectedProfileId}
                        onChange={e => setSelectedProfileId(e.target.value)}
                        onFocus={loadProfilesOnce}
                        onMouseDown={loadProfilesOnce}
                        disabled={isLoading}
                        title="Run the drawer as a saved Agent Studio profile"
                        className="w-full truncate appearance-none rounded-md border border-qualcomm-blue/40 bg-qualcomm-blue/5 hover:bg-qualcomm-blue/10 pl-2.5 pr-8 py-1.5 text-sm font-semibold text-qualcomm-navy cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-qualcomm-blue/40 disabled:opacity-50"
                    >
                        <option value="">EDH Agent (default)</option>
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
                    </select>
                    <ChevronDown className="w-4 h-4 text-qualcomm-blue absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
                <div className="text-[10px] text-gray-400 mt-1.5 pl-0.5">
                    {widgetCount} widget{widgetCount === 1 ? '' : 's'} in context
                </div>
            </div>

            <AgentConversation chat={chat} placeholder="Ask about your dashboard…" />
        </div>
    );
};
