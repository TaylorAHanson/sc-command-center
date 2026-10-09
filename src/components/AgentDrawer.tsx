import React, { useEffect, useState } from 'react';
import { Bot } from 'lucide-react';
import clsx from 'clsx';
import { AgentPanel } from './AgentPanel';
import { assistantLabel, type AgentChat } from '../hooks/useAgentChat';
import type { CanvasBackground } from '../store/appSpec';

/**
 * The assistant: a resizable panel down the right-hand side when open, a
 * floating launcher when not. The chat is held by the page, so a conversation
 * survives collapsing the panel.
 */
export const AgentDrawer: React.FC<{
  chat: AgentChat;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** The view's background, drawn behind the messages. */
  backdrop?: CanvasBackground | null;
  /** The page header beside the drawer is the dark color, so its header is too. */
  dark?: boolean;
  /** Outline the assistant, for the welcome panel pointing at it. */
  spotlight?: boolean;
}> = ({ chat, isOpen, onOpenChange, backdrop, dark, spotlight }) => {
  const label = assistantLabel(chat);
  const [width, setWidth] = useState(400);
  const [isResizing, setIsResizing] = useState(false);

  // Drag-to-resize the assistant panel. Width is the distance from the right
  // edge of the viewport to the cursor, clamped to a sensible range.
  useEffect(() => {
    if (!isResizing) return;
    const MIN = 320;
    const MAX = 900;
    const onMove = (e: MouseEvent) => {
      const next = window.innerWidth - e.clientX;
      setWidth(Math.min(MAX, Math.max(MIN, next)));
    };
    const onUp = () => setIsResizing(false);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isResizing]);

  if (isOpen) {
    return (
      <div
        className="relative border-l border-gray-200 bg-white flex flex-col shrink-0"
        style={{ width }}
      >
        {/* Drag handle to resize the panel */}
        <div
          onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); }}
          className={clsx(
            'absolute left-0 top-0 h-full w-1.5 -translate-x-1/2 cursor-col-resize z-10 group',
            'hover:bg-brand-blue/30 transition-colors',
            isResizing && 'bg-brand-blue/40'
          )}
          title="Drag to resize"
        >
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-10 w-1 rounded-full bg-gray-300 group-hover:bg-brand-blue transition-colors" />
        </div>
        <AgentPanel chat={chat} onCollapse={() => onOpenChange(false)} backdrop={backdrop} dark={dark} />
        {/* Over the panel rather than on it: an inset ring on the container is
            painted beneath the panel's own background. */}
        {spotlight && <div className="pointer-events-none absolute inset-0 z-20 ring-4 ring-inset ring-brand-blue/70 animate-pulse" />}
      </div>
    );
  }

  return (
    <button
      onClick={() => onOpenChange(true)}
      className={clsx(
        'fixed bottom-6 right-6 z-40 flex items-center gap-2 pl-4 pr-5 py-3 bg-brand-navy text-white rounded-full shadow-lg shadow-brand-navy/40 hover:bg-brand-blue hover:shadow-xl transition-all group',
        spotlight && 'ring-4 ring-brand-blue/60 ring-offset-2 animate-pulse',
      )}
      title={`Open ${label}`}
    >
      {chat.isLoading && (
        <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
        </span>
      )}
      <Bot className="w-5 h-5 relative" />
      <span className="text-sm font-semibold relative">{label}</span>
    </button>
  );
};
