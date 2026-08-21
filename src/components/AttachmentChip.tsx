import React from 'react';
import { X, FileSpreadsheet, FileText, Image as ImageIcon, FileJson, Loader2 } from 'lucide-react';
import type { Attachment } from '../hooks/useChatUploads';

const KIND_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
    table: FileSpreadsheet,
    document: FileText,
    image: ImageIcon,
    data: FileJson,
};

const FileIcon: React.FC<{ kind: string; className?: string }> = ({ kind, className }) => {
    const Icon = KIND_ICONS[kind] || FileText;
    return <Icon className={className} />;
};

const humanSize = (bytes: number): string => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * A file waiting to be sent.
 *
 * Parsing happens server-side, so the chip shows progress and then what the
 * agent will actually be able to see (row and column counts, page counts) — a
 * file that failed says so instead of quietly doing nothing when the question is
 * asked.
 */
export const AttachmentChip: React.FC<{
    file: Attachment;
    onRemove: (id: string) => void;
    variant?: 'light' | 'dark';
}> = ({ file, onRemove, variant = 'light' }) => {
    const failed = file.status === 'failed';
    const parsing = file.status === 'parsing';
    const dark = variant === 'dark';
    const shell = failed
        ? (dark ? 'border-rose-900/60 bg-rose-950/40 text-rose-300' : 'border-rose-200 bg-rose-50 text-rose-700')
        : (dark ? 'border-slate-600 bg-slate-800 text-slate-300' : 'border-gray-200 bg-gray-50 text-gray-600');
    const accent = dark ? 'text-indigo-400' : 'text-qualcomm-blue';
    return (
        <div
            className={`group flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] max-w-full ${shell}`}
            title={failed ? file.error : [file.filename, file.summary, humanSize(file.size_bytes)].filter(Boolean).join(' · ')}
        >
            {parsing
                ? <Loader2 className={`w-3.5 h-3.5 shrink-0 animate-spin ${accent}`} />
                : <FileIcon kind={file.kind} className={`w-3.5 h-3.5 shrink-0 ${accent}`} />}
            <span className="truncate max-w-[11rem] font-medium">{file.filename}</span>
            <span className={`shrink-0 ${dark ? 'text-slate-500' : 'text-gray-400'}`}>
                {parsing ? 'reading…' : failed ? 'unreadable' : file.summary || humanSize(file.size_bytes)}
            </span>
            <button
                type="button"
                onClick={() => onRemove(file.id)}
                className={`ml-0.5 p-0.5 rounded shrink-0 ${
                    dark ? 'text-slate-500 hover:text-rose-400 hover:bg-slate-700' : 'text-gray-400 hover:text-rose-600 hover:bg-rose-50'
                }`}
                title="Remove file"
            >
                <X className="w-3 h-3" />
            </button>
        </div>
    );
};

/**
 * The files that went with a message, in the message.
 *
 * Read-only on purpose: the turn has been sent, so there is nothing to remove.
 * It exists to answer "which file was that answer about?" three questions later,
 * which is why it sits inside the user's own bubble in both chats.
 */
export const SentAttachments: React.FC<{
    files: { id: string; filename: string; kind: string }[];
}> = ({ files }) => {
    if (!files.length) return null;
    return (
        <div className="flex flex-wrap gap-1 mb-1.5">
            {files.map(file => (
                <span
                    key={file.id}
                    className="inline-flex items-center gap-1 rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-medium"
                    title={file.filename}
                >
                    <FileIcon kind={file.kind} className="w-3 h-3" />
                    <span className="truncate max-w-[10rem]">{file.filename}</span>
                </span>
            ))}
        </div>
    );
};

export default AttachmentChip;
