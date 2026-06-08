import { useCallback, useEffect, useRef, useState } from 'react';
import { useDashboardContext, buildContextPreamble, type DashboardContext } from './useDashboardContext';

export interface ToolCall {
    tool_name: string;
    status?: string;
}

export interface AgentMessage {
    role: 'user' | 'assistant';
    content: string;
    reasoning?: string;
    tool_calls?: ToolCall[];
    trace_id?: string;
    isError?: boolean;
}

const GREETING: AgentMessage = {
    role: 'assistant',
    content: "Hi! I'm the EDH Agent. I can see the widgets on your current view and your role context. How can I help?",
};

/**
 * Owns the EDH Agent conversation. Lives above the panel component so the chat
 * (messages, session, in-flight request) survives the panel being collapsed or
 * re-mounted. Also centralizes context injection, error handling, cancellation,
 * and telemetry.
 */
export const useAgentChat = () => {
    const [messages, setMessages] = useState<AgentMessage[]>([GREETING]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId] = useState(() => 'sccc-' + Math.random().toString(36).substring(2, 10));

    const abortRef = useRef<AbortController | null>(null);

    // Keep the latest emitted context in a ref so send() always reads fresh
    // values without needing to be re-created on every dashboard change.
    const dashboardContext = useDashboardContext();
    const ctxRef = useRef<DashboardContext>(dashboardContext);
    useEffect(() => { ctxRef.current = dashboardContext; }, [dashboardContext]);

    const send = useCallback(async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed || isLoading) return;

        const ctx = ctxRef.current;
        const preamble = buildContextPreamble(ctx);

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
            const TIMEOUT_MS = 270_000;
            const INTERVAL_MS = 3000;
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
                    const answer = res.answer || '_Genie returned no answer._';
                    const link = res.deep_link ? `\n\n[Open in Databricks Genie ↗](${res.deep_link})` : '';
                    const full = answer + link;
                    updateLast(m => { m.content = full; });
                    // Record the answer in the agent's server-side history so follow-ups have context.
                    try {
                        await fetch('/api/agent/genie/resume', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ session_id: sessionId, answer: full }),
                        });
                    } catch { /* best-effort */ }
                    return;
                }
                if (res.status === 'failed') {
                    updateLast(m => { m.content = `Genie could not answer: ${res.error || 'unknown error'}`; m.isError = true; });
                    return;
                }
                // Still running: render Genie's partial answer live (REPLACE — it can change
                // non-additively). Empty partial falls back to the typing indicator.
                const partial: string = res.answer || '';
                if (partial) updateLast(m => { m.content = partial; });
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
                body: JSON.stringify({ session_id: sessionId, query: trimmed, user_prompt: preamble }),
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
    }, [isLoading, sessionId]);

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
        setMessages([{ ...GREETING, content: 'Chat cleared. How can I help?' }]);
    }, [sessionId]);

    return {
        messages,
        input,
        setInput,
        isLoading,
        send,
        stop,
        clear,
        widgetCount: dashboardContext.widgets.length,
    };
};

export type AgentChat = ReturnType<typeof useAgentChat>;
