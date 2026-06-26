import React, { useRef, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, Square, AlertCircle, ChevronRight } from 'lucide-react';
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

type ConversationChat = Pick<AgentChat, 'messages' | 'input' | 'setInput' | 'isLoading' | 'send' | 'stop'>;

/**
 * The shared EDH Agent transcript + composer. Used by both the Command Center
 * drawer (AgentPanel) and the Agent Studio "Try it" tab so they render and
 * stream identically — including reasoning disclosures, tool pills, live
 * "Thinking…" progress, and (via the hook) async Genie poll draining.
 */
export const AgentConversation: React.FC<{ chat: ConversationChat; placeholder?: string }> = ({
    chat,
    placeholder = 'Ask about your dashboard…',
}) => {
    const { messages, input, setInput, isLoading, send, stop } = chat;
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        send(input);
    };

    return (
        <div className="flex flex-col h-full min-h-0 bg-white">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {messages.map((msg: AgentMessage, idx: number) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[90%] min-w-0 break-words [overflow-wrap:anywhere] rounded-lg px-3 py-2 text-sm ${
                                msg.role === 'user'
                                    ? 'bg-qualcomm-blue text-white'
                                    : msg.isError
                                        ? 'bg-rose-50 border border-rose-200 text-rose-700'
                                        : 'bg-gray-50 border border-gray-200 text-gray-800'
                            }`}
                        >
                            {msg.role === 'user' ? (
                                <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere] leading-relaxed">{msg.content}</p>
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
                                    <div className="prose prose-sm max-w-none leading-relaxed break-words [overflow-wrap:anywhere] [&_code]:[overflow-wrap:anywhere] [&_code]:break-words [&_pre]:whitespace-pre-wrap [&_pre]:break-words [&_pre]:overflow-x-auto [&_table]:block [&_table]:overflow-x-auto">
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
                        placeholder={placeholder}
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

export default AgentConversation;
