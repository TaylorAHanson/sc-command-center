import React, { useRef, useEffect, useState, createContext, useContext } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components, ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertCircle, Paperclip, X, Loader2 } from 'lucide-react';
import type { AgentChat, AgentMessage } from '../hooks/useAgentChat';
import { AttachmentChip, SentAttachments } from './AttachmentChip';
import { ThinkingDisclosure } from './ThinkingDisclosure';
import { SendStopButton } from './SendStopButton';
import { VegaChart, CHART_FENCE_MODES } from './VegaChart';
import { ChatImage } from './ChatImage';
import { backgroundStyle, canvasTone, type CanvasBackground } from '../store/appSpec';

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

// Whether the message is still streaming reaches the `pre` override through
// context rather than a closure: the overrides must keep one identity across the
// re-render every chunk causes, or each chunk would remount any chart already drawn.
const StreamingContext = createContext(false);

// Fenced blocks tagged as a chart are drawn; every other `pre` renders exactly as
// react-markdown's default would. v10 no longer tells `code` whether it is inline,
// so the fence is recognized from the parent `pre`, whose only child is the `code`.
const MarkdownPre: React.FC<React.ComponentProps<'pre'> & ExtraProps> = ({ node, children, ...rest }) => {
    const streaming = useContext(StreamingContext);
    const block = <pre {...rest}>{children}</pre>;
    const code = node?.children[0];
    if (code?.type !== 'element' || code.tagName !== 'code') return block;
    const classes = code.properties.className;
    const lang = Array.isArray(classes)
        ? classes.map(String).find(c => c.startsWith('language-'))?.slice('language-'.length)
        : undefined;
    const mode = lang ? CHART_FENCE_MODES.get(lang.toLowerCase()) : undefined;
    if (!mode) return block;
    const source = code.children.map(c => (c.type === 'text' ? c.value : '')).join('');
    return <VegaChart source={source} mode={mode} streaming={streaming} fallback={block} />;
};

const MARKDOWN_COMPONENTS: Components = { pre: MarkdownPre, img: ChatImage };

type ConversationChat = Pick<AgentChat, 'messages' | 'input' | 'setInput' | 'isLoading' | 'send' | 'stop'>
    & Partial<Pick<AgentChat, 'attachments' | 'attachFiles' | 'removeAttachment' | 'isUploading' | 'uploadError' | 'clearUploadError' | 'persists' | 'isRestoring'>>;

/**
 * The shared EDH Agent transcript + composer. Used by both the Command Center
 * drawer (AgentPanel) and the Agent Studio "Try it" tab so they render and
 * stream identically — including reasoning disclosures, tool pills, live
 * "Thinking…" progress, and (via the hook) async Genie poll draining.
 */
export const AgentConversation: React.FC<{
    chat: ConversationChat;
    placeholder?: string;
    /** Drawn behind the messages, as a view's background is behind its cards. */
    backdrop?: CanvasBackground | null;
    /** A line kept at the top of the messages. */
    notice?: { text: string; warn: boolean } | null;
    /** Said first in the small print under the composer. */
    footnote?: string;
}> = ({
    chat,
    placeholder = 'Ask about your dashboard…',
    backdrop,
    notice,
    footnote,
}) => {
    const tone = canvasTone(backdrop);
    // Text drawn straight on the backdrop; anything in a white box keeps its gray.
    const loose = tone === 'dark' ? 'text-white/70' : tone === 'image' ? 'w-fit px-1.5 rounded bg-white/90 text-gray-600' : 'text-gray-400';
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
            className={`flex flex-col h-full min-h-0 relative ${backdrop ? '' : 'bg-white'}`}
            style={backgroundStyle(backdrop)}
            data-chat-backdrop
            onDragOver={e => { if (canAttach) { e.preventDefault(); setIsDragging(true); } }}
            onDragLeave={e => {
                // Only clear when the pointer actually leaves the panel, not when it
                // crosses between children.
                if (e.currentTarget === e.target) setIsDragging(false);
            }}
            onDrop={handleDrop}
        >
            {isDragging && canAttach && (
                <div className="absolute inset-2 z-20 pointer-events-none rounded-lg border-2 border-dashed border-brand-blue bg-brand-blue/5 flex items-center justify-center">
                    <span className="text-sm font-medium text-brand-navy">Drop files to attach</span>
                </div>
            )}
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {notice && (
                    <div
                        role="status"
                        className={`sticky top-0 z-10 rounded-md border px-2.5 py-1.5 text-[11px] leading-snug shadow-sm ${
                            notice.warn ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-white border-gray-200 text-gray-600'
                        }`}
                    >
                        {notice.text}
                    </div>
                )}
                {/* Reopening the last conversation is a round trip, and without this
                    the greeting sits there looking like a new chat until it lands. */}
                {chat.isRestoring && (
                    <div className={`mx-auto flex items-center justify-center gap-2 py-1 text-xs ${loose}`}>
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Reopening your last conversation…
                    </div>
                )}
                {messages.map((msg: AgentMessage, idx: number) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[90%] min-w-0 break-words [overflow-wrap:anywhere] rounded-lg px-3 py-2 text-sm ${
                                msg.role === 'user'
                                    ? 'bg-brand-blue text-white'
                                    : msg.isError
                                        ? 'bg-rose-50 border border-rose-200 text-rose-700'
                                        : `${backdrop ? 'bg-white' : 'bg-gray-50'} border border-gray-200 text-gray-800`
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
                                            <StreamingContext.Provider value={working}>
                                                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{stripAgentMarkers(msg.content)}</ReactMarkdown>
                                            </StreamingContext.Provider>
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
            <form onSubmit={handleSubmit} className={`p-3 shrink-0 ${backdrop ? '' : 'border-t border-gray-200'}`}>
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
                                className={`p-2 rounded-md transition-colors shrink-0 disabled:opacity-40 ${
                                    tone === 'dark' ? 'text-white/70 hover:text-white hover:bg-white/10'
                                        : tone === 'image' ? 'bg-white/90 text-gray-500 hover:text-brand-blue'
                                            : 'text-gray-400 hover:text-brand-blue hover:bg-gray-100'
                                }`}
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
                        className="flex-1 resize-none rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-brand-blue focus:border-brand-blue max-h-32"
                    />
                    <SendStopButton
                        running={isLoading}
                        canSend={!!input.trim()}
                        onStop={stop}
                        stopTitle="Stop the agent"
                        className="p-2 rounded-md shrink-0 h-9 w-9"
                    />
                </div>
                {/* Stated at the point of use rather than buried in the user guide:
                    the two things someone needs to know before typing are that the
                    answer is generated and may be wrong, and that what they type is
                    kept. Both are also in the User Guide and app_guide.md. */}
                <p className={`mt-1.5 px-0.5 text-[10px] leading-tight ${loose}`}>
                    {footnote && <>{footnote} </>}
                    Responses are AI-generated and can be wrong — check anything you plan to act on.
                    Conversations are saved to your history and may be retained by your administrator.
                </p>
            </form>
        </div>
    );
};

export default AgentConversation;
