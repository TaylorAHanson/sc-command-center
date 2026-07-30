import React, { useEffect, useRef, useState } from 'react';
import { History, Pencil, Trash2, Check, X } from 'lucide-react';
import type { AgentChat } from '../hooks/useAgentChat';

const relativeTime = (iso?: string | null): string => {
    if (!iso) return '';
    // Timestamps come from Postgres without a zone; they are UTC, so say so before
    // parsing or every conversation looks hours old.
    const stamp = new Date(/[Z+]/.test(iso) ? iso : `${iso}Z`).getTime();
    if (Number.isNaN(stamp)) return '';
    const seconds = Math.max(0, (Date.now() - stamp) / 1000);
    if (seconds < 90) return 'just now';
    const minutes = seconds / 60;
    if (minutes < 60) return `${Math.round(minutes)}m ago`;
    const hours = minutes / 60;
    if (hours < 24) return `${Math.round(hours)}h ago`;
    const days = hours / 24;
    return days < 7 ? `${Math.round(days)}d ago` : new Date(stamp).toLocaleDateString();
};

type HistoryChat = Pick<AgentChat,
    'conversationId' | 'conversations' | 'refreshConversations' | 'openConversation' |
    'renameConversation' | 'deleteConversation'>;

/**
 * Past conversations for the assistant drawer. The list is read on open rather
 * than kept live, since it only changes when a turn completes or the user acts
 * here.
 */
export const ConversationHistory: React.FC<{ chat: HistoryChat; disabled?: boolean }> = ({ chat, disabled }) => {
    const { conversationId, conversations, refreshConversations, openConversation, renameConversation, deleteConversation } = chat;
    const [open, setOpen] = useState(false);
    const [editing, setEditing] = useState<string | null>(null);
    const [draftTitle, setDraftTitle] = useState('');
    const wrapperRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        refreshConversations();
        const onClickAway = (e: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
                setOpen(false);
                setEditing(null);
            }
        };
        const onEscape = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); setEditing(null); } };
        document.addEventListener('mousedown', onClickAway);
        document.addEventListener('keydown', onEscape);
        return () => {
            document.removeEventListener('mousedown', onClickAway);
            document.removeEventListener('keydown', onEscape);
        };
    }, [open, refreshConversations]);

    const commitRename = async (id: string) => {
        const title = draftTitle.trim();
        setEditing(null);
        if (title) await renameConversation(id, title);
    };

    return (
        <div className="relative" ref={wrapperRef}>
            <button
                type="button"
                onClick={() => setOpen(v => !v)}
                disabled={disabled}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-40"
                title="Past conversations"
            >
                <History className="w-4 h-4" />
            </button>
            {open && (
                <div className="absolute right-0 top-full mt-1 z-30 w-80 max-h-96 overflow-y-auto rounded-md border border-gray-200 bg-white shadow-lg py-1">
                    {conversations.length === 0 ? (
                        <p className="px-3 py-3 text-xs text-gray-400">
                            No past conversations yet. They are saved automatically once you ask something.
                        </p>
                    ) : conversations.map(conversation => {
                        const isCurrent = conversation.id === conversationId;
                        if (editing === conversation.id) {
                            return (
                                <div key={conversation.id} className="flex items-center gap-1 px-2 py-1.5">
                                    <input
                                        autoFocus
                                        value={draftTitle}
                                        onChange={e => setDraftTitle(e.target.value)}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter') { e.preventDefault(); commitRename(conversation.id); }
                                            if (e.key === 'Escape') { e.preventDefault(); setEditing(null); }
                                        }}
                                        className="flex-1 min-w-0 rounded border border-qualcomm-blue px-1.5 py-1 text-xs focus:outline-none"
                                    />
                                    <button type="button" onClick={() => commitRename(conversation.id)} className="p-1 text-emerald-600 hover:bg-emerald-50 rounded" title="Save">
                                        <Check className="w-3.5 h-3.5" />
                                    </button>
                                    <button type="button" onClick={() => setEditing(null)} className="p-1 text-gray-400 hover:bg-gray-100 rounded" title="Cancel">
                                        <X className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            );
                        }
                        return (
                            <div
                                key={conversation.id}
                                className={`group flex items-center gap-1 px-2 py-1.5 text-left ${isCurrent ? 'bg-qualcomm-blue/5' : 'hover:bg-gray-50'}`}
                            >
                                <button
                                    type="button"
                                    onClick={async () => { setOpen(false); await openConversation(conversation.id); }}
                                    className="flex-1 min-w-0 text-left"
                                >
                                    <span className={`block truncate text-xs ${isCurrent ? 'font-semibold text-qualcomm-navy' : 'text-gray-700'}`}>
                                        {conversation.title}
                                    </span>
                                    <span className="block text-[10px] text-gray-400">
                                        {relativeTime(conversation.updated_at)}
                                        {conversation.message_count ? ` · ${conversation.message_count} messages` : ''}
                                    </span>
                                </button>
                                <button
                                    type="button"
                                    onClick={() => { setEditing(conversation.id); setDraftTitle(conversation.title); }}
                                    className="p-1 text-gray-300 hover:text-gray-600 hover:bg-gray-100 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                                    title="Rename"
                                >
                                    <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => deleteConversation(conversation.id)}
                                    className="p-1 text-gray-300 hover:text-rose-600 hover:bg-rose-50 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                                    title="Delete conversation"
                                >
                                    <Trash2 className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default ConversationHistory;
