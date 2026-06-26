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

export interface AgentMessage {
    role: 'user' | 'assistant';
    content: string;
    reasoning?: string;
    tool_calls?: ToolCall[];
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

    // Per-agent transcript store: switching the active agent stashes the
    // outgoing agent's chat and restores the incoming agent's (or a fresh
    // greeting), so each agent keeps its own conversation rather than bleeding
    // one agent's history into another. ``prevProfileIdRef`` tracks which agent
    // the current ``messages`` belong to.
    const historyRef = useRef<Record<string, AgentMessage[]>>({});
    const prevProfileIdRef = useRef<string>(selectedProfileId);

    // Keep the latest emitted context in a ref so send() always reads fresh
    // values without needing to be re-created on every dashboard change.
    const dashboardContext = useDashboardContext();
    const ctxRef = useRef<DashboardContext>(dashboardContext);
    useEffect(() => { ctxRef.current = dashboardContext; }, [dashboardContext]);

    // React to (a) the selected agent changing and (b) the profile list loading
    // in after mount. On an actual agent switch we stash the outgoing chat and
    // restore the incoming agent's chat (or greet fresh). When the agent is
    // unchanged we only refresh the opening greeting while the chat is still
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

        // Agent switched: save the outgoing agent's transcript so it's there when
        // the user comes back, then load the incoming agent's transcript (or a
        // fresh greeting if it has none yet).
        historyRef.current[prevId] = messagesRef.current;
        const restored = historyRef.current[selectedProfileId];
        setMessages(restored && restored.length ? restored : [{ role: 'assistant', content: greetingText }]);
        prevProfileIdRef.current = selectedProfileId;
    }, [selectedProfileId, availableProfiles, isDraftMode, options.greeting]);

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

    const send = useCallback(async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed || isLoading) return;

        const draftProfile = optionsRef.current.inlineProfile?.();
        const ctx = ctxRef.current;
        // The agent's `user_prompt` carries the dashboard context, kept out of the
        // user-visible query and the agent's stored conversation history. In draft
        // mode ("Try it") there is no dashboard, so we send no context.
        const userPrompt = draftProfile ? '' : buildContextPreamble(ctx);

        // Build prior-turn history (the runtime is stateless, so we own the
        // transcript). Shape each entry as the runtime's ChatMessage and keep
        // only the last ~20 user/assistant turns with content to bound payload.
        const nowIso = new Date().toISOString();
        const conversationHistory = messagesRef.current
            .filter(m => (m.role === 'user' || m.role === 'assistant') && (m.content || '').trim())
            .slice(-20)
            .map((m, i) => ({
                id: `edh-${i}`,
                type: m.role === 'user' ? 'user' : 'agent',
                content: m.content,
                timestamp: nowIso,
            }));

        setInput('');
        setMessages(prev => [
            ...prev,
            { role: 'user', content: trimmed },
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
                }),
            });

            if (!response.ok || !response.body) throw new Error(`Agent responded ${response.status}`);

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
                                const moved: string = data.content;
                                if (last.content.endsWith(moved)) last.content = last.content.slice(0, -moved.length);
                                last.reasoning = (last.reasoning || '') + moved;
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
        }
    }, [isLoading, sessionId, selectedProfileId]);

    const stop = useCallback(() => {
        abortRef.current?.abort();
    }, []);

    const clear = useCallback(async () => {
        abortRef.current?.abort();
        try {
            await fetch('/api/agent/clear_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });
        } catch {
            // best-effort
        }
        // Drop the stashed transcript for this agent so switching away and back
        // doesn't resurrect the cleared conversation.
        delete historyRef.current[selectedProfileId];
        setMessages([{ ...GREETING, content: 'Chat cleared. How can I help?' }]);
    }, [sessionId, selectedProfileId]);

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
    };
};

export type AgentChat = ReturnType<typeof useAgentChat>;
