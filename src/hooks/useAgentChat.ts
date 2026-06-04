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
