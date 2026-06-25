import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Send, Trash2, PanelRightClose, ChevronRight, ChevronDown, Square, AlertCircle } from 'lucide-react';
import type { AgentChat, AgentMessage } from '../hooks/useAgentChat';

const ThinkingDisclosure: React.FC<{ text: string; label: string; defaultOpen: boolean }> = ({ text, label, defaultOpen }) => {
    const [openOverride, setOpenOverride] = useState<boolean | null>(null);
    const open = openOverride === null ? defaultOpen : openOverride;
    const trimmed = text.replace(/\n{3,}/g, '\n\n').trim();
    return (
        <div className="mb-2">
            <button
                type="button"
                onClick={() => setOpenOverride(!open)}
                className="flex items-center gap-1.5 text-[11px] font-medium text-gray-400 hover:text-gray-600 transition-colors"
            >
                <ChevronRight className={`w-3 h-3 transition-transform duration-150 ${open ? 'rotate-90' : ''}`} />
                <span>{label}</span>
            </button>
            {open && (
                <div className="mt-1.5 max-h-64 overflow-y-auto rounded-md bg-gray-50 border border-gray-100 px-3 py-2 text-[12px] text-gray-500 whitespace-pre-wrap leading-relaxed">
                    {trimmed}
                </div>
            )}
        </div>
    );
};

const TypingDots: React.FC = () => (
    <div className="flex items-center space-x-1.5 h-5 px-1">
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" />
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
    </div>
);

// The agent wraps embedded result tables in HTML comment markers
// (e.g. <!-- begin-embedded:query_b94a8c --> ... <!-- end-embedded:query_b94a8c -->).
// We render with react-markdown (no raw HTML), so those markers would otherwise
// show up as literal text. Strip all HTML comments before display; collapse the
// blank lines they leave behind.
const stripAgentMarkers = (text: string): string =>
    text
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/\n{3,}/g, '\n\n')
        .trim();

export const AgentPanel: React.FC<{ chat: AgentChat; onCollapse: () => void }> = ({ chat, onCollapse }) => {
    const {
        messages, input, setInput, isLoading, send, stop, clear, widgetCount,
        availableProfiles, selectedProfileId, setSelectedProfileId, loadProfilesOnce,
    } = chat;
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    // Populate the profile picker as soon as the drawer opens, so the saved
    // agents are present the first time the user opens the dropdown (a native
    // <select> shows its current options immediately; loading on click would
    // only fill them after a reopen). Guarded to run once per session.
    useEffect(() => {
        loadProfilesOnce();
    }, [loadProfilesOnce]);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        send(input);
    };

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

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {messages.map((msg: AgentMessage, idx: number) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
                                msg.role === 'user'
                                    ? 'bg-qualcomm-blue text-white'
                                    : msg.isError
                                        ? 'bg-rose-50 border border-rose-200 text-rose-700'
                                        : 'bg-gray-50 border border-gray-200 text-gray-800'
                            }`}
                        >
                            {msg.role === 'user' ? (
                                <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                            ) : (() => {
                                // While the agent is still working on the last turn, any streamed
                                // `content` is intermediate scaffolding (e.g. "Running SQL…"),
                                // not the answer. Show it as live progress under "Thinking…" and
                                // keep the dots going until the authoritative answer arrives.
                                const working = isLoading && idx === messages.length - 1 && !msg.finalized && !msg.isError;
                                const thinkingText = working
                                    ? [msg.reasoning, msg.content].filter(Boolean).join('\n\n')
                                    : (msg.reasoning || '');
                                return (
                                <>
                                    {thinkingText && (
                                        <ThinkingDisclosure
                                            text={thinkingText}
                                            label={working ? 'Thinking…' : 'Thoughts'}
                                            defaultOpen={working}
                                        />
                                    )}
                                    <div className="prose prose-sm max-w-none leading-relaxed">
                                        {working ? (
                                            <TypingDots />
                                        ) : msg.isError ? (
                                            <div className="flex items-start gap-1.5">
                                                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                                                <span>{msg.content}</span>
                                            </div>
                                        ) : msg.content ? (
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{stripAgentMarkers(msg.content)}</ReactMarkdown>
                                        ) : (
                                            <TypingDots />
                                        )}
                                    </div>
                                    {msg.tool_calls && msg.tool_calls.length > 0 && (
                                        <div className="mt-2 pt-2 border-t border-gray-100">
                                            <p className="text-[10px] font-semibold text-gray-400 mb-1">TOOLS USED</p>
                                            <div className="flex flex-wrap gap-1">
                                                {msg.tool_calls.map((tc, tIdx) => (
                                                    <span key={tIdx} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500">
                                                        {tc.tool_name}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </>
                                );
                            })()}
                        </div>
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <form onSubmit={handleSubmit} className="border-t border-gray-200 p-3 shrink-0">
                <div className="flex items-end gap-2">
                    <textarea
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                send(input);
                            }
                        }}
                        rows={1}
                        placeholder="Ask about your dashboard…"
                        className="flex-1 resize-none rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-qualcomm-blue max-h-32"
                    />
                    {isLoading ? (
                        <button
                            type="button"
                            onClick={stop}
                            className="p-2 bg-rose-500 text-white rounded-md hover:bg-rose-600 transition-colors shrink-0"
                            title="Stop generating"
                        >
                            <Square className="w-4 h-4" />
                        </button>
                    ) : (
                        <button
                            type="submit"
                            disabled={!input.trim()}
                            className="p-2 bg-qualcomm-blue text-white rounded-md hover:bg-qualcomm-navy transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                            title="Send"
                        >
                            <Send className="w-4 h-4" />
                        </button>
                    )}
                </div>
            </form>
        </div>
    );
};
