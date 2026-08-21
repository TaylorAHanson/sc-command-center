import { useCallback, useState } from 'react';

// A file the user attached, as a composer and transcript see it. Parsing runs
// server-side after the bytes land, so `status` moves parsing -> ready|failed.
export interface Attachment {
    id: string;
    filename: string;
    kind: string;
    status: 'parsing' | 'ready' | 'failed' | string;
    size_bytes: number;
    summary?: string;
    error?: string;
    warnings?: string[];
}

const UPLOAD_POLL_MS = 900;
const UPLOAD_TIMEOUT_MS = 180_000;

export interface ChatUploads {
    attachments: Attachment[];
    setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>;
    /** Upload each file and wait for the server to finish reading it. */
    attachFiles: (files: FileList | File[]) => Promise<Attachment[]>;
    /** The same path for bytes that were never a file on disk — a screenshot. */
    attachBlob: (blob: Blob, filename: string) => Promise<Attachment | null>;
    removeAttachment: (id: string) => Promise<void>;
    isUploading: boolean;
    uploadError: string | null;
    setUploadError: (message: string | null) => void;
    clearUploadError: () => void;
}

/**
 * Attaching files to a conversation: store the bytes, then poll until they have
 * been read.
 *
 * Parsing is a background task server-side (a 25 MB workbook is far too slow to
 * hold a request open), so a chip appears the moment the bytes land and fills in
 * its summary afterwards. Both the assistant drawer and Widget Studio need
 * exactly this, which is why it isn't inside either of them.
 *
 * `conversationId` is read at upload time rather than captured, because the
 * drawer mints one lazily and a file attached before the first turn must still
 * end up on the right conversation.
 */
export function useChatUploads(options: {
    conversationId: () => string;
    /** False where files can't be stored — the Agent Studio draft chat. */
    enabled?: boolean;
    /** Ran before the first byte goes out, for callers that lazily set up state. */
    beforeUpload?: () => void;
}): ChatUploads {
    const { conversationId, enabled = true, beforeUpload } = options;
    const [attachments, setAttachments] = useState<Attachment[]>([]);
    const [uploadError, setUploadError] = useState<string | null>(null);
    const [isUploading, setIsUploading] = useState(false);

    const attachFiles = useCallback(async (files: FileList | File[]): Promise<Attachment[]> => {
        const list = Array.from(files || []);
        if (!list.length || !enabled) return [];
        beforeUpload?.();
        setUploadError(null);
        setIsUploading(true);
        const landed: Attachment[] = [];
        try {
            for (const file of list) {
                const form = new FormData();
                form.append('file', file);
                form.append('conversation_id', conversationId());

                const uploaded = await (async (): Promise<Attachment | null> => {
                    try {
                        const r = await fetch('/api/agent/uploads', { method: 'POST', body: form });
                        const payload = await r.json().catch(() => ({}));
                        if (!r.ok) {
                            setUploadError(payload?.detail || `Could not upload ${file.name}.`);
                            return null;
                        }
                        return payload as Attachment;
                    } catch {
                        setUploadError(`Could not upload ${file.name}.`);
                        return null;
                    }
                })();
                if (!uploaded) continue;
                setAttachments(prev => [...prev.filter(a => a.id !== uploaded.id), uploaded]);

                let latest = uploaded;
                const startedAt = Date.now();
                while (latest.status === 'parsing' && Date.now() - startedAt < UPLOAD_TIMEOUT_MS) {
                    await new Promise(resolve => setTimeout(resolve, UPLOAD_POLL_MS));
                    try {
                        const poll = await fetch(`/api/agent/uploads/${encodeURIComponent(latest.id)}`);
                        if (!poll.ok) break;
                        latest = await poll.json() as Attachment;
                    } catch {
                        break;
                    }
                    const settled = latest;
                    setAttachments(prev => prev.map(a => (a.id === settled.id ? settled : a)));
                }
                if (latest.status === 'failed' && latest.error) setUploadError(latest.error);
                landed.push(latest);
            }
        } finally {
            setIsUploading(false);
        }
        return landed;
    }, [enabled, beforeUpload, conversationId]);

    const attachBlob = useCallback(async (blob: Blob, filename: string): Promise<Attachment | null> => {
        const file = new File([blob], filename, { type: blob.type || 'image/png' });
        return (await attachFiles([file]))[0] || null;
    }, [attachFiles]);

    const removeAttachment = useCallback(async (id: string) => {
        setAttachments(prev => prev.filter(a => a.id !== id));
        try {
            await fetch(`/api/agent/uploads/${encodeURIComponent(id)}`, { method: 'DELETE' });
        } catch {
            // The chip is already gone; a failed delete only leaves a stray row.
        }
    }, []);

    const clearUploadError = useCallback(() => setUploadError(null), []);

    return {
        attachments, setAttachments, attachFiles, attachBlob, removeAttachment,
        isUploading, uploadError, setUploadError, clearUploadError,
    };
}
