import { useCallback, useEffect, useRef, useState } from 'react';
import { useDashboardContext, buildContextPreamble, type DashboardContext } from './useDashboardContext';

export interface ToolCall {
    tool_name: string;
    status?: string;
}

export interface AgentProfile {
    id: string;
    name: string;
    description?: string;
    location_label?: string;
    author?: string;
    owned_by_me?: boolean;
}

// A file the user attached, as the composer and transcript see it. Parsing runs
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

export interface MessageAttachment {
    id: string;
    filename: string;
    kind: string;
}

// A turn as the server stores it: the same shape as AgentMessage, but `role`
// arrives as a plain string and every field is optional.
interface StoredMessage {
    role: string;
    content?: string;
    reasoning?: string;
    tool_calls?: ToolCall[];
    attachments?: MessageAttachment[];
    isError?: boolean;
    finalized?: boolean;
}

export interface ConversationSummary {
    id: string;
    title: string;
    profile_id: string;
    updated_at?: string | null;
    message_count: number;
}

export interface AgentMessage {
    role: 'user' | 'assistant';
    content: string;
    reasoning?: string;
    tool_calls?: ToolCall[];
    attachments?: MessageAttachment[];
    trace_id?: string;
    isError?: boolean;
    // True once the agent has emitted its authoritative answer. Until then any
    // streamed `content` is intermediate scaffolding shown as live "thinking".
    finalized?: boolean;
}

// An UNSAVED draft profile to run a turn as (Agent Studio "Try it"). When the
// hook is given an `inlineProfile` getter, each turn forwards this instead of a
// saved `profile_ref`, and the profile picker / dashboard context are skipped.
export interface InlineProfileSpec {
    name?: string;
    prompt?: string;
    tools?: string[];
    skills?: { name: string; content: string }[];
    python_tools?: { name: string; description?: string; code: string }[];
    model?: string;
}

export interface UseAgentChatOptions {
    // When provided, the hook runs in "draft" mode: it forwards the latest
    // inline profile (read fresh at send time) rather than a saved profile_ref,
    // and omits dashboard context. Used by the Agent Studio "Try it" tab.
    inlineProfile?: () => InlineProfileSpec;
    // Opening greeting shown in a fresh transcript.
    greeting?: string;
}

// Generic greeting used when no specific Agent Studio profile is active. The
// active agent's name is shown in the picker, so the default doesn't claim to be
// any particular agent.
const DEFAULT_GREETING = "Hi! I can see the widgets on your current view and your role context. How can I help?";

// When a profile is selected, greet as that agent (using its description as a
// short tagline when available).
const greetingFor = (name?: string, description?: string): string => {
    if (!name) return DEFAULT_GREETING;
    const desc = (description || '').trim();
    return desc ? `Hi! I'm ${name} — ${desc} How can I help?` : `Hi! I'm ${name}. How can I help?`;
};

const GREETING: AgentMessage = {
    role: 'assistant',
    content: DEFAULT_GREETING,
};

// Which conversation the user was last in. The transcript itself lives in the
// database (so it survives a reload, and so uploaded files have an owner); this
// only remembers where to reopen, since "most recently updated" is not always the
// one they were reading.
const CONVERSATION_KEY = 'sccc-agent-conversation';

const newConversationId = (): string =>
    'conv-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-6);

const rememberConversation = (id: string) => {
    try { localStorage.setItem(CONVERSATION_KEY, id); } catch { /* private browsing */ }
};

// Files still being parsed are polled until the server settles them. Parsing a
// large workbook takes seconds, so this needs room without hanging forever.
const UPLOAD_POLL_MS = 900;
const UPLOAD_TIMEOUT_MS = 180_000;

/**
 * Owns the EDH Agent conversation. Lives above the panel component so the chat
 * (messages, session, in-flight request) survives the panel being collapsed or
 * re-mounted. Also centralizes context injection, error handling, cancellation,
 * and telemetry.
 */
export const useAgentChat = (options: UseAgentChatOptions = {}) => {
    // Keep the latest options in a ref so send() reads the freshest inline draft
    // without being re-created (and without churning the callback's deps).
    const optionsRef = useRef(options);
    optionsRef.current = options;
    const isDraftMode = !!options.inlineProfile;

    const [messages, setMessages] = useState<AgentMessage[]>(
        () => [{ role: 'assistant', content: options.greeting || DEFAULT_GREETING }],
    );
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId] = useState(() => 'sccc-' + Math.random().toString(36).substring(2, 10));

    // Draft mode ("Try it" in Agent Studio) is for authoring, so it neither
    // persists nor accepts files: those belong to a real conversation.
    const persists = !isDraftMode;
    const [conversationId, setConversationId] = useState<string>(() => newConversationId());
    const [conversations, setConversations] = useState<ConversationSummary[]>([]);
    const [attachments, setAttachments] = useState<Attachment[]>([]);
    const [uploadError, setUploadError] = useState<string | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isRestoring, setIsRestoring] = useState(persists);

    // Set the moment the user does something of their own — sends a turn, attaches
    // a file, picks a conversation. Restoring the last conversation is a
    // round trip away, and the user is free to start typing during it; if they do,
    // whatever they started wins and the restore is abandoned.
    //
    // Engaging also claims the conversation as the one to reopen. The id minted at
    // mount is otherwise never remembered, so a user who attached a file or sent a
    // turn while the restore was still in flight came back after a reload to the
    // conversation the restore had *declined* to open, not the one they had been
    // working in.
    const engagedRef = useRef(false);
    const engage = useCallback(() => {
        engagedRef.current = true;
        rememberConversation(conversationIdRef.current);
    }, []);

    // Attachment ids already shown on an earlier turn, so a file the user sent
    // three questions ago doesn't re-chip onto every later message. The agent can
    // still query every file on the conversation — this is only presentation.
    const sentAttachmentsRef = useRef<Set<string>>(new Set());

    // The ref, not the state, is what uploads and turns are addressed to, so it
    // has to move in the same tick as the change. Syncing it from an effect left
    // it a commit behind: a file attached in that window was posted against the
    // conversation being navigated away from, so it belonged to a chat the user
    // was no longer in and its chip never appeared.
    const conversationIdRef = useRef(conversationId);
    const adoptConversation = useCallback((id: string) => {
        // Seeding the ref from state is what the compiler objects to, not the write
        // itself: this runs from an event handler, and the whole point is that the
        // ref lead the re-render rather than trail it.
        // eslint-disable-next-line react-hooks/immutability
        conversationIdRef.current = id;
        setConversationId(id);
        rememberConversation(id);
    }, []);

    // Agent profiles authored in the Agent Studio. Selecting one runs the EDH
    // drawer as that profile (its prompt, skills, tools, model) via the
    // consolidated runtime. Empty selection = the default unified agent.
    const [availableProfiles, setAvailableProfiles] = useState<AgentProfile[]>([]);
    const [selectedProfileId, setSelectedProfileId] = useState<string>('');

    const abortRef = useRef<AbortController | null>(null);

    // Mirror the transcript in a ref so send() can build conversation_history
    // from the messages PRIOR to this turn without re-creating the callback.
    const messagesRef = useRef<AgentMessage[]>(messages);
    useEffect(() => { messagesRef.current = messages; }, [messages]);

    // Which agent the current transcript belongs to. Switching agents starts a
    // new conversation rather than stashing this one in memory: conversations are
    // durable now, so the previous chat is a click away in the history list
    // instead of being lost on the next reload.
    const prevProfileIdRef = useRef<string>(selectedProfileId);

    // Keep the latest emitted context in a ref so send() always reads fresh
    // values without needing to be re-created on every dashboard change.
    const dashboardContext = useDashboardContext();
    const ctxRef = useRef<DashboardContext>(dashboardContext);
    useEffect(() => { ctxRef.current = dashboardContext; }, [dashboardContext]);

    // Bumped by every local edit to the list (rename, delete). A fetch that was
    // already in flight when the user edited would otherwise land afterwards and
    // put the old title back on screen for a moment.
    const listEditRef = useRef(0);

    const refreshConversations = useCallback(async (): Promise<ConversationSummary[]> => {
        if (!persists) return [];
        const editsAtStart = listEditRef.current;
        try {
            const r = await fetch('/api/conversations?limit=50');
            if (!r.ok) return [];
            const d = await r.json();
            const list: ConversationSummary[] = d.conversations || [];
            if (listEditRef.current === editsAtStart) setConversations(list);
            return list;
        } catch {
            // The list is a convenience; a failure here must not disturb the chat.
            return [];
        }
    }, [persists]);

    // Adopt a conversation: its transcript, its files, and the agent it was held
    // with. `prevProfileIdRef` is set alongside `selectedProfileId` so the
    // agent-switch effect below sees no switch and leaves the restored chat alone.
    const openConversation = useCallback(async (id: string, opts?: { yieldToUser?: boolean }): Promise<boolean> => {
        if (!opts?.yieldToUser) engagedRef.current = true;
        try {
            const r = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
            if (!r.ok) return false;
            const d = await r.json();
            // The restore lost a race with the user: they are mid-conversation, so
            // report success and leave their transcript alone.
            if (opts?.yieldToUser && engagedRef.current) return true;
            const stored: StoredMessage[] = d.messages || [];
            const restored: AgentMessage[] = stored.map(m => ({
                role: m.role === 'user' ? 'user' : 'assistant',
                content: m.content || '',
                reasoning: m.reasoning,
                tool_calls: m.tool_calls,
                attachments: m.attachments,
                isError: m.isError,
                finalized: m.finalized,
            }));
            abortRef.current?.abort();
            const profileId = d.conversation?.profile_id || '';
            prevProfileIdRef.current = profileId;
            setSelectedProfileId(profileId);
            adoptConversation(id);
            setMessages(restored.length ? restored : [{ role: 'assistant', content: DEFAULT_GREETING }]);
            setAttachments(d.attachments || []);
            setUploadError(null);
            sentAttachmentsRef.current = new Set(
                stored.flatMap(m => (m.attachments || []).map(a => a.id)),
            );
            return true;
        } catch {
            return false;
        }
    }, [adoptConversation]);

    const startConversation = useCallback((greeting?: string) => {
        engagedRef.current = true;
        abortRef.current?.abort();
        adoptConversation(newConversationId());
        setMessages([{ role: 'assistant', content: greeting || optionsRef.current.greeting || DEFAULT_GREETING }]);
        setAttachments([]);
        setUploadError(null);
        sentAttachmentsRef.current = new Set();
    }, [adoptConversation]);

    // On mount, reopen where the user left off. Falls back to their most recent
    // conversation when the remembered one is gone (deleted, or pruned).
    //
    // Both requests go out together: reading the list and only then the
    // conversation doubles the delay before the transcript appears, and against a
    // remote database that delay is seconds rather than milliseconds. Deliberately
    // no cancellation flag — this runs once per mount (`restoredRef`), so a flag
    // set by StrictMode's throwaway cleanup would abandon the only attempt and
    // leave the drawer permanently showing the greeting.
    const restoredRef = useRef(false);
    useEffect(() => {
        if (!persists || restoredRef.current) return;
        restoredRef.current = true;
        (async () => {
            try {
                let remembered = '';
                try { remembered = localStorage.getItem(CONVERSATION_KEY) || ''; } catch { /* private browsing */ }
                const [list, opened] = await Promise.all([
                    refreshConversations(),
                    remembered ? openConversation(remembered, { yieldToUser: true }) : Promise.resolve(false),
                ]);
                if (opened) return;
                const recent = list[0];
                if (recent) await openConversation(recent.id, { yieldToUser: true });
            } finally {
                setIsRestoring(false);
            }
        })();
    }, [persists, openConversation, refreshConversations]);

    // React to (a) the selected agent changing and (b) the profile list loading
    // in after mount. Switching agents starts a fresh conversation. When the agent
    // is unchanged we only refresh the opening greeting while the chat is still
    // fresh, so we never clobber an in-progress conversation.
    useEffect(() => {
        // Draft mode ("Try it") has no profile picker — the inline draft IS the
        // agent — so skip the picker's transcript switching. We DO keep the
        // opening greeting in sync with the latest options.greeting (e.g. when the
        // user loads a saved agent), but only while the transcript is still fresh
        // (just the greeting bubble) so we never clobber an in-progress chat.
        if (isDraftMode) {
            const g = optionsRef.current.greeting || DEFAULT_GREETING;
            setMessages(prev => {
                if (prev.length !== 1 || prev[0].role !== 'assistant') return prev;
                return prev[0].content === g ? prev : [{ role: 'assistant', content: g }];
            });
            return;
        }
        const active = availableProfiles.find(p => p.id === selectedProfileId);
        const greetingText = greetingFor(active?.name, active?.description);
        const prevId = prevProfileIdRef.current;

        if (prevId === selectedProfileId) {
            setMessages(prev => {
                if (prev.length !== 1 || prev[0].role !== 'assistant') return prev;
                return prev[0].content === greetingText ? prev : [{ role: 'assistant', content: greetingText }];
            });
            return;
        }

        // Agent switched: the outgoing conversation is already saved server-side,
        // so open a new one for the incoming agent instead of splicing transcripts.
        prevProfileIdRef.current = selectedProfileId;
        startConversation(greetingText);
    }, [selectedProfileId, availableProfiles, isDraftMode, options.greeting, startConversation]);

    // Agent Studio profile discovery is LAZY: listing them triggers a UC scan
    // (or a pinned-location lookup) server-side, so we don't pay it on every
    // drawer mount for every user. The picker calls loadProfilesOnce() the first
    // time the user interacts with it.
    // Throttled (not single-latch): refresh at most once per window so opening
    // the drawer re-checks for newly saved profiles, but we never hammer the
    // (UC-scanning) endpoint. Errors reset the clock so the next interaction retries.
    const lastProfileLoadRef = useRef(0);
    const PROFILE_REFRESH_MS = 30_000;
    const loadProfilesOnce = useCallback(async () => {
        const now = Date.now();
        if (now - lastProfileLoadRef.current < PROFILE_REFRESH_MS) return;
        lastProfileLoadRef.current = now;
        try {
            const r = await fetch('/api/agent/studio/profiles');
            if (r.ok) {
                const d = await r.json();
                setAvailableProfiles(d.profiles || []);
            } else {
                lastProfileLoadRef.current = 0; // allow a retry on next interaction
            }
        } catch {
            lastProfileLoadRef.current = 0; // allow a retry on next interaction
        }
    }, []);

    // Upload files, then poll each one until the server has parsed it. Parsing is
    // a background task server-side (a 25 MB workbook is far too slow to hold a
    // request open), so the chip appears immediately and fills in its summary.
    const attachFiles = useCallback(async (files: FileList | File[]) => {
        const list = Array.from(files || []);
        if (!list.length || !persists) return;
        engage();
        setUploadError(null);
        setIsUploading(true);
        try {
            for (const file of list) {
                const form = new FormData();
                form.append('file', file);
                form.append('conversation_id', conversationIdRef.current);

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
            }
        } finally {
            setIsUploading(false);
        }
    }, [persists, engage]);

    const removeAttachment = useCallback(async (id: string) => {
        setAttachments(prev => prev.filter(a => a.id !== id));
        try {
            await fetch(`/api/agent/uploads/${encodeURIComponent(id)}`, { method: 'DELETE' });
        } catch {
            // The chip is already gone; a failed delete only leaves a stray row.
        }
    }, []);

    const send = useCallback(async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed || isLoading) return;
        engage();

        const draftProfile = optionsRef.current.inlineProfile?.();
        const ctx = ctxRef.current;
        // The agent's `user_prompt` carries the dashboard context, kept out of the
        // user-visible query and the agent's stored conversation history. In draft
        // mode ("Try it") there is no dashboard, so we send no context.
        const userPrompt = draftProfile ? '' : buildContextPreamble(ctx);

        // A persisted conversation gets its history from the database, so the
        // client only builds a transcript for draft mode ("Try it"). `role` is sent
        // alongside the legacy `type` because "agent" is not a role any runtime
        // recognizes — reading it as one is what used to drop prior answers.
        const nowIso = new Date().toISOString();
        const conversationHistory = persists ? undefined : messagesRef.current
            .filter(m => (m.role === 'user' || m.role === 'assistant') && (m.content || '').trim())
            .slice(-20)
            .map((m, i) => ({
                id: `edh-${i}`,
                role: m.role,
                type: m.role === 'user' ? 'user' : 'agent',
                content: m.content,
                timestamp: nowIso,
            }));

        // Files not yet shown on a message ride with this turn. Anything still
        // parsing is left for a later turn rather than silently ignored.
        const readyAttachments = attachments.filter(
            a => a.status === 'ready' && !sentAttachmentsRef.current.has(a.id),
        );
        readyAttachments.forEach(a => sentAttachmentsRef.current.add(a.id));

        setInput('');
        setMessages(prev => [
            ...prev,
            {
                role: 'user',
                content: trimmed,
                attachments: readyAttachments.map(a => ({ id: a.id, filename: a.filename, kind: a.kind })),
            },
            { role: 'assistant', content: '', tool_calls: [] },
        ]);
        setIsLoading(true);

        const controller = new AbortController();
        abortRef.current = controller;

        // Mutate just the trailing assistant message (the in-flight turn).
        const updateLast = (mutate: (m: AgentMessage) => void) => setMessages(prev => {
            const next = [...prev];
            const i = next.length - 1;
            if (next[i]?.role !== 'assistant') return prev;
            const last = { ...next[i] };
            mutate(last);
            next[i] = last;
            return next;
        });

        const sleep = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
            const t = setTimeout(resolve, ms);
            signal.addEventListener('abort', () => { clearTimeout(t); resolve(); }, { once: true });
        });

        // Drains an async Genie turn after the agent halted with a pending_poll handle. Each poll
        // is a short request, so no single request is ever held open past the platform's ~5-min
        // cap — this is what makes long Genie answers reliable instead of timing out.
        const drainGeniePoll = async (handle: any, signal: AbortSignal) => {
            const startedAt = Date.now();
            // Each poll is its own short request, so the TOTAL window is NOT bound by the
            // platform's ~5-min per-request cap — only by how long the user will wait.
            const TIMEOUT_MS = 900_000; // 15 min
            const INTERVAL_MS = 3000;
            // Genie's terminal status lags well past when the answer is ready, so also complete
            // once a non-empty answer has stopped changing for several polls (~15s).
            const STABLE_POLLS_TO_COMPLETE = 5;
            let lastAnswer = '';
            let stableCount = 0;

            const finish = async (text: string, deepLink?: string) => {
                const link = deepLink ? `\n\n[Open in Databricks Genie ↗](${deepLink})` : '';
                const full = (text || '_Genie returned no answer._') + link;
                updateLast(m => { m.content = full; });
                try {
                    await fetch('/api/agent/genie/resume', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId, answer: full }),
                    });
                } catch { /* best-effort */ }
            };

            while (!signal.aborted) {
                if (Date.now() - startedAt > TIMEOUT_MS) {
                    updateLast(m => { m.content = 'Genie did not respond in time. Please try again or narrow the question.'; m.isError = true; });
                    return;
                }
                let res: any;
                try {
                    const r = await fetch('/api/agent/genie/poll', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        signal,
                        body: JSON.stringify({
                            conversation_id: handle.conversation_id,
                            response_id: handle.response_id,
                            space_id: handle.space_id || '',
                            question: handle.question || '',
                        }),
                    });
                    res = await r.json();
                } catch (e: any) {
                    if (signal.aborted) return;
                    updateLast(m => { m.content = 'Sorry, I lost the connection while waiting on Genie.'; m.isError = true; });
                    return;
                }
                if (signal.aborted) return;

                if (res.status === 'complete') {
                    await finish(res.answer, res.deep_link);
                    return;
                }
                if (res.status === 'failed') {
                    updateLast(m => { m.content = `Genie could not answer: ${res.error || 'unknown error'}`; m.isError = true; });
                    return;
                }
                // Still running: show the live feed — the real partial answer if Genie has one,
                // else the progress narration (steps + SQL). REPLACE each poll (non-additive).
                const display: string = res.answer || '';
                if (display) updateLast(m => { m.content = display; });
                // Early completion keys on the REAL answer only (res.final), never the narration,
                // so we never settle the turn on progress text. Genie's COMPLETED status lags.
                const finalAns: string = res.final || '';
                if (finalAns && finalAns === lastAnswer) {
                    stableCount += 1;
                    if (stableCount >= STABLE_POLLS_TO_COMPLETE) {
                        await finish(finalAns, res.deep_link);
                        return;
                    }
                } else {
                    lastAnswer = finalAns;
                    stableCount = 0;
                }
                await sleep(res.attempt_after_ms || INTERVAL_MS, signal);
            }
        };

        // Set when the agent halts on an async tool and hands us a poll handle.
        let pendingPoll: any = null;

        try {
            const response = await fetch('/api/agent/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: controller.signal,
                // Context rides in `user_prompt` (a dedicated agent field) instead of
                // the query, so it never pollutes the user-visible message or the
                // agent's stored conversation history.
                body: JSON.stringify({
                    session_id: sessionId,
                    query: trimmed,
                    user_prompt: userPrompt,
                    // Draft mode forwards the unsaved profile inline; otherwise we
                    // reference the selected saved profile (if any).
                    inline_profile: draftProfile || undefined,
                    profile_ref: draftProfile ? undefined : (selectedProfileId || undefined),
                    conversation_history: conversationHistory,
                    // Sending an id is what makes the turn durable; "Try it" omits it.
                    conversation_id: persists ? conversationIdRef.current : undefined,
                    attachment_ids: readyAttachments.length ? readyAttachments.map(a => a.id) : undefined,
                }),
            });

            if (!response.ok || !response.body) throw new Error(`Agent responded ${response.status}`);

            // The server may write to a different conversation than the one asked
            // for (an id that turned out to belong to someone else); follow it.
            const written = response.headers.get('X-Conversation-Id');
            if (written && written !== conversationIdRef.current) adoptConversation(written);

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.substring(6);
                    if (dataStr === '[DONE]') continue;
                    let data: any;
                    try { data = JSON.parse(dataStr); } catch { continue; }

                    if (data.type === 'pending_poll') {
                        // The agent started Genie and halted; remember the handle and drive the
                        // poll loop once this (short) stream closes.
                        pendingPoll = data;
                        continue;
                    }

                    setMessages(prev => {
                        const next = [...prev];
                        const i = next.length - 1;
                        const last = { ...next[i] };
                        if (last.role !== 'assistant') return prev;
                        switch (data.type) {
                            case 'chunk':
                                last.content += data.content;
                                break;
                            case 'reasoning':
                                last.reasoning = (last.reasoning || '') + data.content;
                                break;
                            case 'reclassify': {
                                // Prose the agent abandoned to call a tool: take it back out of
                                // the answer and file it under thinking. A turn can do this
                                // several times over, so the runs are kept apart.
                                const moved: string = data.content;
                                if (last.content.endsWith(moved)) last.content = last.content.slice(0, -moved.length);
                                const prior = last.reasoning || '';
                                last.reasoning = prior ? `${prior.replace(/\s+$/, '')}\n\n${moved}` : moved;
                                break;
                            }
                            case 'final':
                                last.content = data.content;
                                last.finalized = true;
                                break;
                            case 'tool_calls':
                                last.tool_calls = data.content;
                                if (last.content && !last.content.endsWith('\n\n')) last.content += '\n\n';
                                break;
                            case 'trace_id':
                                last.trace_id = data.content;
                                break;
                            case 'error':
                                last.content = `The agent hit an error: ${data.content}`;
                                last.isError = true;
                                break;
                            default:
                                return prev;
                        }
                        next[i] = last;
                        return next;
                    });
                }
            }

            // The agent halted on an async Genie call: drain it via short poll requests so the
            // answer streams in reliably instead of timing out a single long-held request.
            if (pendingPoll && !controller.signal.aborted) {
                await drainGeniePoll(pendingPoll, controller.signal);
            }
        } catch (err: any) {
            if (err?.name === 'AbortError') {
                setMessages(prev => {
                    const next = [...prev];
                    const last = { ...next[next.length - 1] };
                    if (last.role === 'assistant') {
                        last.content = (last.content || '').trim() + (last.content ? '\n\n_Stopped._' : '_Stopped._');
                        next[next.length - 1] = last;
                    }
                    return next;
                });
            } else {
                setMessages(prev => {
                    const next = [...prev];
                    next[next.length - 1] = {
                        role: 'assistant',
                        content: 'Sorry, I had trouble reaching the agent service.',
                        isError: true,
                    };
                    return next;
                });
            }
        } finally {
            setIsLoading(false);
            abortRef.current = null;
            // The list orders by activity and titles itself from the first
            // question, so it is stale the moment a turn lands.
            refreshConversations();
        }
    }, [isLoading, sessionId, selectedProfileId, persists, attachments, refreshConversations, adoptConversation, engage]);

    const stop = useCallback(() => {
        abortRef.current?.abort();
    }, []);

    // "New chat". The outgoing conversation is already saved, so this starts a
    // fresh one rather than throwing anything away — which is also why draft mode,
    // where nothing is saved, simply resets the transcript.
    const clear = useCallback(async () => {
        if (!persists) {
            abortRef.current?.abort();
            setMessages([{ ...GREETING, content: optionsRef.current.greeting || DEFAULT_GREETING }]);
            return;
        }
        const active = availableProfiles.find(p => p.id === selectedProfileId);
        startConversation(greetingFor(active?.name, active?.description));
        refreshConversations();
    }, [persists, availableProfiles, selectedProfileId, startConversation, refreshConversations]);

    // Both of these show the change straight away and then re-read the list. The
    // re-read is not belt-and-braces: opening the dropdown kicks off a list fetch,
    // and against a remote database that fetch can still be in flight when the
    // rename lands — arriving late with the old title and undoing it on screen.
    const renameConversation = useCallback(async (id: string, title: string) => {
        const clean = title.trim();
        if (!clean) return;
        listEditRef.current += 1;
        setConversations(prev => prev.map(c => (c.id === id ? { ...c, title: clean } : c)));
        try {
            await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: clean }),
            });
        } finally {
            refreshConversations();
        }
    }, [refreshConversations]);

    const deleteConversation = useCallback(async (id: string) => {
        listEditRef.current += 1;
        setConversations(prev => prev.filter(c => c.id !== id));
        try {
            await fetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
        } catch {
            refreshConversations();
            return;
        }
        refreshConversations();
        // Deleting the conversation on screen leaves nothing to show, so open a
        // fresh one; deleting any other only changes the list.
        if (id === conversationIdRef.current) {
            const active = availableProfiles.find(p => p.id === selectedProfileId);
            startConversation(greetingFor(active?.name, active?.description));
        }
    }, [availableProfiles, selectedProfileId, startConversation, refreshConversations]);

    return {
        messages,
        input,
        setInput,
        isLoading,
        send,
        stop,
        clear,
        widgetCount: dashboardContext.widgets.length,
        // Agent profiles
        availableProfiles,
        selectedProfileId,
        setSelectedProfileId,
        loadProfilesOnce,
        // Conversations (empty/no-ops in draft mode, where nothing is persisted)
        persists,
        isRestoring,
        conversationId,
        conversations,
        refreshConversations,
        openConversation,
        renameConversation,
        deleteConversation,
        // Attachments
        attachments,
        attachFiles,
        removeAttachment,
        isUploading,
        uploadError,
        clearUploadError: () => setUploadError(null),
    };
};

export type AgentChat = ReturnType<typeof useAgentChat>;
