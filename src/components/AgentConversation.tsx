import React, { useRef, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, Square, AlertCircle, Paperclip, X, Loader2 } from 'lucide-react';
import type { AgentChat, AgentMessage } from '../hooks/useAgentChat';
import { AttachmentChip, SentAttachments } from './AttachmentChip';
import { ThinkingDisclosure } from './ThinkingDisclosure';

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

type ConversationChat = Pick<AgentChat, 'messages' | 'input' | 'setInput' | 'isLoading' | 'send' | 'stop'>
    & Partial<Pick<AgentChat, 'attachments' | 'attachFiles' | 'removeAttachment' | 'isUploading' | 'uploadError' | 'clearUploadError' | 'persists' | 'isRestoring'>>;

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
    const {
        messages, input, setInput, isLoading, send, stop,
        attachments = [], attachFiles, removeAttachment, isUploading, uploadError, clearUploadError,
    } = chat;
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [isDragging, setIsDragging] = useState(false);
    // Files can only be attached where they can be stored, which rules out the
    // Agent Studio draft chat.
    const canAttach = !!attachFiles && chat.persists !== false;

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        send(input);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        if (!canAttach) return;
        const dropped = e.dataTransfer?.files;
        if (dropped?.length) attachFiles!(dropped);
    };

    return (
        <div
            className="flex flex-col h-full min-h-0 bg-white relative"
            onDragOver={e => { if (canAttach) { e.preventDefault(); setIsDragging(true); } }}
            onDragLeave={e => {
                // Only clear when the pointer actually leaves the panel, not when it
                // crosses between children.
                if (e.currentTarget === e.target) setIsDragging(false);
            }}
            onDrop={handleDrop}
        >
            {isDragging && canAttach && (
                <div className="absolute inset-2 z-20 pointer-events-none rounded-lg border-2 border-dashed border-qualcomm-blue bg-qualcomm-blue/5 flex items-center justify-center">
                    <span className="text-sm font-medium text-qualcomm-navy">Drop files to attach</span>
                </div>
            )}
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {/* Reopening the last conversation is a round trip, and without this
                    the greeting sits there looking like a new chat until it lands. */}
                {chat.isRestoring && (
                    <div className="flex items-center justify-center gap-2 py-1 text-xs text-gray-400">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Reopening your last conversation…
                    </div>
                )}
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
                                <>
                                    <SentAttachments files={msg.attachments || []} />
                                    <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere] leading-relaxed">{msg.content}</p>
                                </>
                            ) : (() => {
                                // The answer streams into the answer, so what is on screen is what
                                // the agent is actually saying. The disclosure holds thinking only:
                                // reasoning tokens, and prose the agent abandoned to call a tool
                                // (the server reclassifies that as it happens). Showing streamed
                                // content here as well meant reading the same text twice — greyed
                                // out while it arrived, then again as the answer.
                                const working = isLoading && idx === messages.length - 1 && !msg.finalized && !msg.isError;
                                const thinkingText = msg.reasoning || '';
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
                                        {msg.isError ? (
                                            <div className="flex items-start gap-1.5">
                                                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                                                <span>{msg.content}</span>
                                            </div>
                                        ) : msg.content ? (
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{stripAgentMarkers(msg.content)}</ReactMarkdown>
                                        ) : (
                                            // Nothing said yet, or the agent just handed its prose
                                            // over to the thinking box and is running a tool.
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
                {uploadError && (
                    <div className="mb-2 flex items-start gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700">
                        <AlertCircle className="w-3.5 h-3.5 mt-px shrink-0" />
                        <span className="flex-1">{uploadError}</span>
                        <button type="button" onClick={clearUploadError} className="p-0.5 hover:text-rose-900" title="Dismiss">
                            <X className="w-3 h-3" />
                        </button>
                    </div>
                )}
                {attachments.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                        {attachments.map(file => (
                            <AttachmentChip key={file.id} file={file} onRemove={removeAttachment!} />
                        ))}
                    </div>
                )}
                <div className="flex items-end gap-2">
                    {canAttach && (
                        <>
                            <input
                                ref={fileInputRef}
                                type="file"
                                multiple
                                className="hidden"
                                accept=".csv,.tsv,.xlsx,.xlsm,.json,.ndjson,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
                                onChange={e => {
                                    if (e.target.files?.length) attachFiles!(e.target.files);
                                    // Reset so re-picking the same file still fires a change.
                                    e.target.value = '';
                                }}
                            />
                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isUploading}
                                className="p-2 text-gray-400 hover:text-qualcomm-blue hover:bg-gray-100 rounded-md transition-colors shrink-0 disabled:opacity-40"
                                title="Attach a spreadsheet, document, or image"
                            >
                                {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Paperclip className="w-4 h-4" />}
                            </button>
                        </>
                    )}
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
