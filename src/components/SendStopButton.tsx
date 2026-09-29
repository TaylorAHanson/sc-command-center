import React from 'react';
import { Send, Square } from 'lucide-react';

/**
 * The composer's one button: Send while idle, Stop while the agent is working.
 *
 * Two things keep a keystroke from stopping a turn nobody meant to stop:
 *
 * - **It never takes focus.** A click focuses a button in most browsers, and the
 *   Send button then *becomes* Stop — React reuses the element, so the focus
 *   survives the swap and the next Enter or Space stops the agent. Pressing down
 *   is swallowed instead, which leaves the caret in the message box.
 * - **The two states are different elements** (`key`), so even a focus that got
 *   there by Tab is dropped when Send turns into Stop rather than carried across.
 *
 * Enter in the message box is the caller's to handle, and while a turn runs it
 * must do nothing: it neither sends nor stops.
 */
export const SendStopButton: React.FC<{
    running: boolean;
    canSend: boolean;
    onStop: () => void;
    /** Omit to make Send a submit button for the surrounding form. */
    onSend?: () => void;
    variant?: 'light' | 'dark';
    stopping?: boolean;
    stopTitle?: string;
    className?: string;
}> = ({ running, canSend, onStop, onSend, variant = 'light', stopping = false, stopTitle = 'Stop', className = '' }) => {
    const keepFocus = (e: React.MouseEvent) => e.preventDefault();
    const tone = variant === 'dark'
        ? { send: 'bg-indigo-600 hover:bg-indigo-500 text-white', stop: 'bg-rose-600 hover:bg-rose-500 text-white' }
        : { send: 'bg-brand-blue hover:bg-brand-navy text-white', stop: 'bg-rose-500 hover:bg-rose-600 text-white' };

    if (running) {
        return (
            <button
                key="stop"
                type="button"
                tabIndex={-1}
                onMouseDown={keepFocus}
                onClick={onStop}
                disabled={stopping}
                title={stopping ? 'Stopping…' : stopTitle}
                aria-label={stopTitle}
                className={`flex items-center justify-center transition-colors disabled:opacity-60 ${tone.stop} ${className}`}
            >
                <Square size={14} fill="currentColor" />
            </button>
        );
    }
    return (
        <button
            key="send"
            type={onSend ? 'button' : 'submit'}
            onMouseDown={keepFocus}
            onClick={onSend}
            disabled={!canSend}
            title="Send"
            aria-label="Send"
            className={`flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${tone.send} ${className}`}
        >
            <Send size={16} />
        </button>
    );
};

export default SendStopButton;
