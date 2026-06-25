import React, { useState, useEffect, useRef } from 'react';
import {
    Bot, Send, Save, RefreshCw, Trash2, Plus, Settings, FileText, Sparkles,
    ListChecks, AlertTriangle, Wrench, ChevronDown, FolderOpen, Rocket, X, Play,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type ChatMessage = { role: 'user' | 'assistant' | 'system'; content: string };

// A single turn in the "Try it" draft-agent conversation.
type TryMessage = { role: 'user' | 'assistant'; content: string; toolCalls?: string[] };

interface SkillDraft {
    slug?: string;
    name: string;
    description: string;
    content: string;
}

interface ToolInfo {
    id: string;            // canonical server-qualified id ("<server>/<tool>")
    name: string;          // bare tool name (display)
    description: string;
    server?: string;
    server_label?: string;
}

interface ProfileSummary {
    id: string;
    store: string;
    name: string;
    description: string;
    model: string;
    tools: string[];
    location_label: string;
    writable: boolean;
    author?: string;
    owned_by_me?: boolean;
}

interface StudioLocation {
    store: string;
    base_path: string;
    label: string;
    is_personal: boolean;
}

interface ReviewReport {
    suggested_tools?: { name: string; why: string }[];
    missing?: string[];
    ambiguities?: string[];
    schema_checks?: { query: string; columns?: string[]; ok?: boolean }[];
}

const API = '/api/agent/studio';
const DEFAULT_PROMPT = '# New Agent\n\nDescribe how this agent should behave, what data it can access, and the tone it should use.';

type RightTab = 'prompt' | 'skills' | 'review' | 'settings' | 'tryit';

export const AgentStudio: React.FC = () => {
    const [messages, setMessages] = useState<ChatMessage[]>([
        { role: 'assistant', content: "Welcome to the Agent Studio. Describe the agent you want to build — what should it do, and what data should it reach?" },
    ]);
    const [prompt, setPrompt] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [isSaving, setIsSaving] = useState(false);

    const [rightTab, setRightTab] = useState<RightTab>('prompt');

    // Profile under edit
    const [profileId, setProfileId] = useState<string | null>(null);
    // Version token from the last load/save, echoed back on save so the server
    // can reject a clobbering write if someone else edited in between.
    const [loadedUpdatedAt, setLoadedUpdatedAt] = useState<string>('');
    const [name, setName] = useState('New Agent');
    const [description, setDescription] = useState('');
    const [model, setModel] = useState('');
    const [selectedTools, setSelectedTools] = useState<string[]>([]);
    const [agentPrompt, setAgentPrompt] = useState(DEFAULT_PROMPT);
    const [skills, setSkills] = useState<SkillDraft[]>([]);
    const [activeSkillIdx, setActiveSkillIdx] = useState<number | null>(null);
    const [review, setReview] = useState<ReviewReport | null>(null);

    // Try-it: a multi-turn chat that runs the current (unsaved) draft against the
    // consolidated runtime, so authoring feels like a normal agent conversation.
    const [tryMessages, setTryMessages] = useState<TryMessage[]>([]);
    const [tryInput, setTryInput] = useState('');
    const [tryRunning, setTryRunning] = useState(false);
    const tryEndRef = useRef<HTMLDivElement>(null);

    // Target location for new profiles
    const [store, setStore] = useState<string>('workspace');
    const [basePath, setBasePath] = useState<string>('');

    // Catalog data
    const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
    const [locations, setLocations] = useState<StudioLocation[]>([]);
    const [tools, setTools] = useState<ToolInfo[]>([]);
    const [toolsLoading, setToolsLoading] = useState(false);
    const [showProfileMenu, setShowProfileMenu] = useState(false);

    // Promotion
    const [showPromote, setShowPromote] = useState(false);
    const [promoteTargets, setPromoteTargets] = useState<StudioLocation[]>([]);
    const [promoteTarget, setPromoteTarget] = useState<string>('');
    const [isPromoting, setIsPromoting] = useState(false);

    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        refreshProfiles();
        refreshLocations();
        refreshTools();
    }, []);

    useEffect(() => {
        const t = setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
        return () => clearTimeout(t);
    }, [messages, isGenerating]);

    useEffect(() => {
        tryEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [tryMessages]);

    const refreshProfiles = async () => {
        try {
            const r = await fetch(`${API}/profiles`);
            const d = await r.json();
            if (r.ok) setProfiles(d.profiles || []);
        } catch (e) { console.error('list profiles failed', e); }
    };

    const refreshLocations = async () => {
        try {
            const r = await fetch(`${API}/locations`);
            const d = await r.json();
            if (r.ok) {
                setLocations(d.locations || []);
                const personal = (d.locations || []).find((l: StudioLocation) => l.is_personal);
                if (personal && !basePath) {
                    setStore(personal.store);
                    setBasePath(personal.base_path);
                }
            }
        } catch (e) { console.error('list locations failed', e); }
    };

    const refreshTools = async () => {
        setToolsLoading(true);
        try {
            const r = await fetch(`${API}/tools`);
            const d = await r.json();
            if (r.ok) setTools(d.tools || []);
        } catch (e) {
            console.error('list tools failed', e);
        } finally {
            setToolsLoading(false);
        }
    };

    const resetToNew = () => {
        setProfileId(null);
        setLoadedUpdatedAt('');
        setName('New Agent');
        setDescription('');
        setModel('');
        setSelectedTools([]);
        setAgentPrompt(DEFAULT_PROMPT);
        setSkills([]);
        setActiveSkillIdx(null);
        setReview(null);
        setMessages([{ role: 'assistant', content: 'Starting a fresh agent. Describe what you want it to do.' }]);
        setRightTab('prompt');
    };

    const loadProfile = async (id: string) => {
        setShowProfileMenu(false);
        try {
            const r = await fetch(`${API}/profiles/${encodeURIComponent(id)}`);
            const d = await r.json();
            if (!r.ok) { alert(d.detail || 'Failed to load profile'); return; }
            setProfileId(d.id);
            setLoadedUpdatedAt(d.updated_at || '');
            setName(d.name || '');
            setDescription(d.description || '');
            setModel(d.model || '');
            setSelectedTools(d.tools || []);
            setAgentPrompt(d.prompt || DEFAULT_PROMPT);
            setSkills((d.skills || []).map((s: any) => ({ slug: s.slug, name: s.name, description: s.description, content: s.content })));
            setStore(d.store);
            setActiveSkillIdx(null);
            setReview(null);
            setMessages([{ role: 'assistant', content: `Loaded "${d.name}". Tell me what you'd like to change, or edit directly on the right.` }]);
            setRightTab('prompt');
        } catch (e) {
            alert(`Error loading profile: ${e}`);
        }
    };

    const applyDraft = (draft: any) => {
        if (!draft) return;
        if (draft.name) setName(draft.name);
        if (typeof draft.description === 'string') setDescription(draft.description);
        if (typeof draft.model === 'string' && draft.model) setModel(draft.model);
        if (Array.isArray(draft.tools)) setSelectedTools(draft.tools);
        if (typeof draft.prompt === 'string' && draft.prompt) setAgentPrompt(draft.prompt);
        if (Array.isArray(draft.skills)) {
            setSkills(draft.skills.map((s: any) => ({ name: s.name, description: s.description || '', content: s.content || '' })));
        }
        if (draft.review) setReview(draft.review as ReviewReport);
    };

    const handleGenerate = async () => {
        if (!prompt.trim()) return;
        const history = messages.filter(m => m.role !== 'system');
        const baseMessages = [...messages, { role: 'user' as const, content: prompt }];
        setMessages(baseMessages);
        setPrompt('');
        setIsGenerating(true);

        // Stream the authoring run as SSE: prose arrives as `chunk` events and we
        // render it live; a single `final` event carries the parsed draft.
        let assistantText = '';
        const renderAssistant = () => setMessages([...baseMessages, { role: 'assistant' as const, content: assistantText }]);
        try {
            const resp = await fetch(`${API}/generate/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt,
                    history,
                    current_prompt: agentPrompt,
                    current_skills: skills,
                    confirm_schema: true,
                }),
            });
            if (!resp.ok || !resp.body) {
                let detail = resp.statusText;
                try { detail = (await resp.json()).detail || detail; } catch { /* non-JSON */ }
                setMessages([...baseMessages, { role: 'system', content: `Server Error: ${detail}` }]);
                setIsGenerating(false);
                return;
            }
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const frames = buffer.split('\n\n');
                buffer = frames.pop() || '';
                for (const frame of frames) {
                    const line = frame.split('\n').find(l => l.startsWith('data:'));
                    if (!line) continue;
                    const payload = line.slice('data:'.length).trim();
                    if (payload === '[DONE]') continue;
                    let evt: any;
                    try { evt = JSON.parse(payload); } catch { continue; }
                    if (evt.type === 'chunk') {
                        assistantText += evt.content || '';
                        renderAssistant();
                    } else if (evt.type === 'final') {
                        applyDraft(evt.draft);
                        if (evt.draft?.review) setRightTab('review');
                        assistantText = evt.explanation || assistantText || 'Draft updated.';
                        renderAssistant();
                    } else if (evt.type === 'error') {
                        setMessages([...baseMessages, { role: 'system', content: `Generation Error: ${evt.content}` }]);
                    }
                }
            }
        } catch (e) {
            setMessages([...baseMessages, { role: 'system', content: `Network Error: ${e}` }]);
        } finally {
            setIsGenerating(false);
        }
    };

    const handleSave = async () => {
        if (!name.trim()) { alert('Please provide an agent name.'); setRightTab('settings'); return; }
        if (!profileId && store === 'volume' && !basePath) {
            alert('Please choose a save location.'); setRightTab('settings'); return;
        }
        setIsSaving(true);
        try {
            const r = await fetch(`${API}/profiles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name, prompt: agentPrompt, description, model,
                    tools: selectedTools, skills,
                    store, base_path: basePath || null,
                    profile_id: profileId,
                    expected_updated_at: loadedUpdatedAt || null,
                }),
            });
            const d = await r.json();
            if (r.status === 409) {
                alert(d.detail || 'This profile was changed elsewhere. Reload before saving.');
                return;
            }
            if (!r.ok) { alert(`Save failed: ${d.detail || r.statusText}`); return; }
            setProfileId(d.id);
            setLoadedUpdatedAt(d.updated_at || '');
            await refreshProfiles();
            alert(`Saved "${d.name}".`);
        } catch (e) {
            alert(`Error: ${e}`);
        } finally {
            setIsSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!profileId) return;
        if (!confirm(`Delete "${name}"? This removes the AGENT.md and its skills.`)) return;
        try {
            const r = await fetch(`${API}/profiles/${encodeURIComponent(profileId)}`, { method: 'DELETE' });
            if (!r.ok) { const d = await r.json(); alert(`Delete failed: ${d.detail || r.statusText}`); return; }
            await refreshProfiles();
            resetToNew();
        } catch (e) {
            alert(`Error: ${e}`);
        }
    };

    const openPromote = async () => {
        if (!profileId) { alert('Save the profile before promoting it.'); return; }
        setShowPromote(true);
        try {
            const r = await fetch(`${API}/promotion/targets`);
            const d = await r.json();
            if (r.ok) {
                const targets: StudioLocation[] = (d.targets || []).map((t: any) => ({
                    store: t.store, base_path: t.base_path, label: t.label, is_personal: false,
                }));
                setPromoteTargets(targets);
                if (targets.length && !promoteTarget) {
                    setPromoteTarget(`${targets[0].store}|${targets[0].base_path}`);
                }
            }
        } catch (e) { console.error('promotion targets failed', e); }
    };

    const handlePromote = async () => {
        if (!profileId || !promoteTarget) return;
        const [tStore, ...rest] = promoteTarget.split('|');
        const tBase = rest.join('|');
        setIsPromoting(true);
        try {
            const r = await fetch(`${API}/promote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile_id: profileId, target_store: tStore, target_base_path: tBase }),
            });
            const d = await r.json();
            if (!r.ok) { alert(`Promotion failed: ${d.detail || r.statusText}`); return; }
            await refreshProfiles();
            setShowPromote(false);
            alert(`Promoted "${name}" to ${tBase}.`);
        } catch (e) {
            alert(`Error: ${e}`);
        } finally {
            setIsPromoting(false);
        }
    };

    // Selection is keyed on the canonical server-qualified id. We also treat a
    // legacy bare-name entry as selected (older profiles stored just the name).
    const toolIsSelected = (t: ToolInfo) => selectedTools.includes(t.id) || selectedTools.includes(t.name);

    const toggleTool = (t: ToolInfo) => {
        setSelectedTools(prev =>
            (prev.includes(t.id) || prev.includes(t.name))
                ? prev.filter(x => x !== t.id && x !== t.name)
                : [...prev, t.id]
        );
    };

    // Run the current draft (unsaved) against the consolidated runtime via the
    // agent proxy. The runtime applies the inline profile with the same
    // governance as a saved one (tool intersection + model allowlist).
    const runTryIt = async () => {
        const q = tryInput.trim();
        if (!q || tryRunning) return;

        // Prior turns become conversation_history so the draft agent is multi-turn
        // (the runtime is stateless; the client owns the transcript).
        const nowIso = new Date().toISOString();
        const priorHistory = tryMessages
            .filter(m => m.content.trim())
            .slice(-20)
            .map((m, i) => ({
                id: `try-${i}`,
                type: m.role === 'user' ? 'user' : 'agent',
                content: m.content,
                timestamp: nowIso,
            }));

        setTryInput('');
        setTryMessages(prev => [
            ...prev,
            { role: 'user', content: q },
            { role: 'assistant', content: '', toolCalls: [] },
        ]);
        setTryRunning(true);

        // Mutate just the trailing assistant message (the in-flight turn).
        const updateLast = (mutate: (m: TryMessage) => void) => setTryMessages(prev => {
            const next = [...prev];
            const i = next.length - 1;
            if (next[i]?.role !== 'assistant') return prev;
            const last = { ...next[i] };
            mutate(last);
            next[i] = last;
            return next;
        });

        try {
            const resp = await fetch('/api/agent/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: q,
                    inline_profile: {
                        name: name || 'Draft',
                        prompt: agentPrompt,
                        tools: selectedTools,
                        skills: skills.map(s => ({ name: s.name, content: s.content })),
                        model,
                    },
                    conversation_history: priorHistory,
                }),
            });
            if (!resp.ok || !resp.body) {
                updateLast(m => { m.content = `Error: runtime returned ${resp.status}.`; });
                return;
            }
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const frames = buffer.split('\n\n');
                buffer = frames.pop() || '';
                for (const frame of frames) {
                    const line = frame.split('\n').find(l => l.startsWith('data:'));
                    if (!line) continue;
                    const payload = line.slice('data:'.length).trim();
                    if (payload === '[DONE]') continue;
                    try {
                        const evt = JSON.parse(payload);
                        if (evt.type === 'final') updateLast(m => { m.content = evt.content || ''; });
                        else if (evt.type === 'chunk') updateLast(m => { m.content += (evt.content || ''); });
                        else if (evt.type === 'tool_calls' && Array.isArray(evt.content)) {
                            updateLast(m => { m.toolCalls = evt.content.map((c: any) => `${c.tool_name} · ${c.status}`); });
                        } else if (evt.type === 'error') {
                            updateLast(m => { m.content = `Error: ${evt.content}`; });
                        }
                    } catch { /* ignore non-JSON keepalives */ }
                }
            }
        } catch (e) {
            updateLast(m => { m.content = `Network error: ${e}`; });
        } finally {
            setTryRunning(false);
        }
    };

    const addSkill = () => {
        const next = [...skills, { name: 'New Skill', description: '', content: '# New Skill\n\nStep-by-step instructions for the agent.' }];
        setSkills(next);
        setActiveSkillIdx(next.length - 1);
        setRightTab('skills');
    };

    const updateSkill = (idx: number, patch: Partial<SkillDraft>) => {
        setSkills(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
    };

    const removeSkill = (idx: number) => {
        setSkills(prev => prev.filter((_, i) => i !== idx));
        setActiveSkillIdx(null);
    };

    const tabBtn = (id: RightTab, label: string, Icon: any) => (
        <button
            className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${rightTab === id ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
            onClick={() => setRightTab(id)}
        >
            <Icon size={14} /> {label}
        </button>
    );

    return (
        <div className="flex h-full w-full bg-slate-900 text-slate-100 overflow-hidden font-sans">
            {/* LEFT: chat */}
            <div className="w-1/3 flex flex-col border-r border-slate-700 bg-slate-800">
                <div className="p-4 border-b border-slate-700 bg-slate-900 flex justify-between items-center h-14">
                    <div className="flex items-center gap-2 text-indigo-400 font-semibold tracking-wide">
                        <Bot size={18} />
                        <span>Agent Studio</span>
                    </div>
                    <button
                        onClick={resetToNew}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-md transition-colors font-medium">
                        <Plus size={14} /> New
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((m, i) => (
                        <div key={i} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className={`max-w-[85%] rounded-lg p-3 text-sm shadow-sm ${m.role === 'user' ? 'bg-indigo-600 text-white rounded-br-none' :
                                m.role === 'system' ? 'bg-slate-700/50 text-slate-300 border border-slate-600/50 rounded-bl-none' :
                                    'bg-slate-700 text-slate-200 rounded-bl-none border border-slate-600'}`}>
                                <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-li:my-0">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                                </div>
                            </div>
                        </div>
                    ))}
                    {isGenerating && (
                        <div className="flex items-start">
                            <div className="bg-slate-700 text-slate-400 rounded-lg p-3 rounded-bl-none text-sm border border-slate-600 flex items-center gap-2">
                                <RefreshCw size={14} className="animate-spin" /> Designing agent...
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                <div className="p-4 border-t border-slate-700 bg-slate-800/50">
                    <div className="flex border border-slate-600 rounded-md bg-slate-900 focus-within:border-indigo-500 ring-1 focus-within:ring-indigo-500 overflow-hidden transition-all shadow-inner items-end">
                        <textarea
                            className="flex-1 bg-transparent border-none px-4 py-3 text-sm focus:outline-none text-slate-200 placeholder-slate-500 resize-none min-h-[44px] max-h-32 overflow-hidden"
                            placeholder="Build an agent that answers supply-chain questions from the orders table..."
                            value={prompt}
                            onChange={e => { setPrompt(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${e.target.scrollHeight}px`; }}
                            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleGenerate(); e.currentTarget.style.height = 'auto'; } }}
                            rows={1}
                        />
                        <button
                            onClick={handleGenerate}
                            disabled={isGenerating || !prompt}
                            className="px-4 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition-colors flex items-center justify-center self-stretch">
                            <Send size={16} />
                        </button>
                    </div>
                </div>
            </div>

            {/* RIGHT: workspace */}
            <div className="w-2/3 flex flex-col bg-slate-900">
                <div className="flex border-b border-slate-800 bg-slate-900/50 px-4 pt-2 gap-2 h-14 items-end justify-between">
                    <div className="flex gap-2 items-end">
                        {tabBtn('prompt', 'Prompt', FileText)}
                        {tabBtn('skills', `Skills${skills.length ? ` (${skills.length})` : ''}`, Sparkles)}
                        {tabBtn('tryit', 'Try it', Play)}
                        {tabBtn('review', 'Review', ListChecks)}
                        {tabBtn('settings', 'Settings', Settings)}
                    </div>
                    <div className="flex items-center gap-2 pb-2">
                        <div className="relative">
                            <button
                                onClick={() => setShowProfileMenu(s => !s)}
                                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-md transition-colors font-medium">
                                <FolderOpen size={14} /> Open <ChevronDown size={14} />
                            </button>
                            {showProfileMenu && (
                                <div className="absolute right-0 mt-1 w-72 max-h-80 overflow-y-auto bg-slate-800 border border-slate-600 rounded-md shadow-xl z-20">
                                    {profiles.length === 0 ? (
                                        <div className="px-3 py-2 text-sm text-slate-400 italic">No saved profiles yet.</div>
                                    ) : profiles.map(p => (
                                        <button key={p.id} onClick={() => loadProfile(p.id)}
                                            className="w-full text-left px-3 py-2 hover:bg-slate-700 border-b border-slate-700/50 last:border-0">
                                            <div className="text-sm text-slate-200 font-medium truncate flex items-center gap-1.5">
                                                <span className="truncate">{p.name}</span>
                                                {!p.owned_by_me && (
                                                    <span title={p.author ? `Shared by ${p.author}` : 'Shared profile'}
                                                        className="shrink-0 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                                        Shared
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-xs text-slate-500 truncate">
                                                {p.location_label}
                                                {!p.owned_by_me && p.author ? ` · by ${p.author}` : ''}
                                                {' · '}{p.description || 'No description'}
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        {profileId && (
                            <button onClick={openPromote} title="Promote to a shared / prod location"
                                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-slate-700 hover:bg-emerald-600 rounded-md transition-colors font-medium">
                                <Rocket size={14} /> Promote
                            </button>
                        )}
                        {profileId && (
                            <button onClick={handleDelete}
                                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-slate-700 hover:bg-rose-600 rounded-md transition-colors font-medium">
                                <Trash2 size={14} />
                            </button>
                        )}
                        <button
                            onClick={handleSave}
                            disabled={isSaving}
                            className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors font-medium ${isSaving ? 'bg-indigo-400 cursor-not-allowed text-indigo-100' : 'bg-indigo-600 hover:bg-indigo-500 text-white'}`}>
                            {isSaving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                            {isSaving ? 'Saving...' : (profileId ? 'Update' : 'Save')}
                        </button>
                    </div>
                </div>

                <div className="flex-1 relative overflow-hidden">
                    {rightTab === 'prompt' && (
                        <div className="absolute inset-0 flex flex-col bg-[#1e1e1e] p-4">
                            <div className="text-xs text-slate-500 mb-2 font-mono">AGENT.md — system prompt (markdown)</div>
                            <textarea
                                className="w-full h-full bg-transparent text-slate-300 font-mono text-sm resize-none focus:outline-none"
                                value={agentPrompt}
                                onChange={e => setAgentPrompt(e.target.value)}
                                spellCheck={false}
                            />
                        </div>
                    )}

                    {rightTab === 'skills' && (
                        <div className="absolute inset-0 flex">
                            <div className="w-1/3 border-r border-slate-800 flex flex-col">
                                <div className="p-3 border-b border-slate-800 flex items-center justify-between">
                                    <span className="text-sm font-medium text-slate-300">Skills</span>
                                    <button onClick={addSkill} className="flex items-center gap-1 px-2 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs">
                                        <Plus size={12} /> Add
                                    </button>
                                </div>
                                <div className="flex-1 overflow-y-auto">
                                    {skills.length === 0 ? (
                                        <div className="p-4 text-xs text-slate-500 italic">No skills. Each skill is a single markdown file the agent can load.</div>
                                    ) : skills.map((s, i) => (
                                        <button key={i} onClick={() => setActiveSkillIdx(i)}
                                            className={`w-full text-left px-3 py-2 border-b border-slate-800/60 ${activeSkillIdx === i ? 'bg-slate-800' : 'hover:bg-slate-800/50'}`}>
                                            <div className="text-sm text-slate-200 truncate">{s.name || 'Untitled'}</div>
                                            <div className="text-xs text-slate-500 truncate">{s.description || 'No description'}</div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col bg-[#1e1e1e]">
                                {activeSkillIdx === null || !skills[activeSkillIdx] ? (
                                    <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">Select or add a skill to edit.</div>
                                ) : (
                                    <div className="flex-1 flex flex-col p-4 gap-3">
                                        <div className="flex gap-3">
                                            <input
                                                value={skills[activeSkillIdx].name}
                                                onChange={e => updateSkill(activeSkillIdx, { name: e.target.value })}
                                                placeholder="Skill name"
                                                className="flex-1 bg-slate-900 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                            />
                                            <button onClick={() => removeSkill(activeSkillIdx)}
                                                className="px-2 py-1.5 text-slate-400 hover:text-rose-500 hover:bg-rose-500/10 rounded">
                                                <Trash2 size={16} />
                                            </button>
                                        </div>
                                        <input
                                            value={skills[activeSkillIdx].description}
                                            onChange={e => updateSkill(activeSkillIdx, { description: e.target.value })}
                                            placeholder="One-line description"
                                            className="bg-slate-900 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                        <textarea
                                            value={skills[activeSkillIdx].content}
                                            onChange={e => updateSkill(activeSkillIdx, { content: e.target.value })}
                                            spellCheck={false}
                                            className="flex-1 bg-transparent text-slate-300 font-mono text-sm resize-none focus:outline-none border border-slate-800 rounded p-3"
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {rightTab === 'review' && (
                        <div className="absolute inset-0 overflow-y-auto p-6">
                            {!review ? (
                                <div className="text-sm text-slate-500 italic">No review yet. Ask the assistant to design or refine the agent and it will report suggested tools, gaps, and schema checks here.</div>
                            ) : (
                                <div className="max-w-3xl space-y-6">
                                    <ReviewSection title="Suggested tools" icon={Wrench} empty="No tool suggestions.">
                                        {(review.suggested_tools || []).map((t, i) => (
                                            <li key={i} className="text-sm text-slate-300"><span className="font-mono text-indigo-300">{t.name}</span> — {t.why}</li>
                                        ))}
                                    </ReviewSection>
                                    <ReviewSection title="Missing capabilities" icon={AlertTriangle} empty="Nothing missing — all requested capabilities map to available tools.">
                                        {(review.missing || []).map((m, i) => (
                                            <li key={i} className="text-sm text-amber-300">{m}</li>
                                        ))}
                                    </ReviewSection>
                                    <ReviewSection title="Open questions" icon={ListChecks} empty="No open questions.">
                                        {(review.ambiguities || []).map((a, i) => (
                                            <li key={i} className="text-sm text-slate-300">{a}</li>
                                        ))}
                                    </ReviewSection>
                                    <ReviewSection title="Schema checks" icon={FileText} empty="No schema checks were run.">
                                        {(review.schema_checks || []).map((c, i) => (
                                            <li key={i} className="text-sm text-slate-300">
                                                <span className={c.ok === false ? 'text-rose-400' : 'text-emerald-400'}>{c.ok === false ? 'FAILED' : 'OK'}</span>
                                                <span className="font-mono text-slate-400 ml-2">{c.query}</span>
                                                {c.columns && c.columns.length > 0 && (
                                                    <div className="text-xs text-slate-500 ml-6">columns: {c.columns.join(', ')}</div>
                                                )}
                                            </li>
                                        ))}
                                    </ReviewSection>
                                </div>
                            )}
                        </div>
                    )}

                    {rightTab === 'settings' && (
                        <div className="absolute inset-0 overflow-y-auto p-8">
                            <div className="max-w-3xl space-y-6">
                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1.5">Agent Name</label>
                                    <input value={name} onChange={e => setName(e.target.value)}
                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1.5">Description</label>
                                    <textarea value={description} onChange={e => setDescription(e.target.value)}
                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-none h-20" />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-slate-300 mb-1.5">Model (serving endpoint)</label>
                                    <input value={model} onChange={e => setModel(e.target.value)} placeholder="e.g. databricks-claude-sonnet-4-6"
                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500" />
                                    <p className="text-xs text-slate-500 mt-1">Leave blank to use the runtime default.</p>
                                </div>

                                {!profileId && (
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Save Location</label>
                                        <select
                                            value={`${store}|${basePath}`}
                                            onChange={e => { const [s, ...rest] = e.target.value.split('|'); setStore(s); setBasePath(rest.join('|')); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500">
                                            {locations.map(l => (
                                                <option key={`${l.store}|${l.base_path}`} value={`${l.store}|${l.base_path}`}>
                                                    {l.label}{l.is_personal ? ' (private)' : ''}
                                                </option>
                                            ))}
                                        </select>
                                        <p className="text-xs text-slate-500 mt-1">Shared locations are UC Volumes; visibility follows Unity Catalog grants.</p>
                                    </div>
                                )}

                                <div>
                                    <div className="flex items-center justify-between mb-1.5">
                                        <label className="block text-sm font-medium text-slate-300">Tools (AI Gateway MCP)</label>
                                        <button onClick={refreshTools} className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                                            <RefreshCw size={12} className={toolsLoading ? 'animate-spin' : ''} /> Refresh
                                        </button>
                                    </div>
                                    <div className="border border-slate-700 rounded-lg max-h-72 overflow-y-auto divide-y divide-slate-800">
                                        {tools.length === 0 ? (
                                            <div className="p-3 text-xs text-slate-500 italic">
                                                {toolsLoading ? 'Discovering tools...' : 'No tools discovered from the AI Gateway MCP. The agent will have no tools until some are exposed.'}
                                            </div>
                                        ) : tools.map(t => (
                                            <label key={t.id} className="flex items-start gap-3 p-3 cursor-pointer hover:bg-slate-800/50">
                                                <input type="checkbox" checked={toolIsSelected(t)} onChange={() => toggleTool(t)}
                                                    className="mt-0.5 text-indigo-600 focus:ring-indigo-500 bg-slate-900 border-slate-600 rounded" />
                                                <div>
                                                    <div className="text-sm text-slate-200 font-mono">{t.name}</div>
                                                    <div className="text-[10px] text-slate-500 font-mono">{t.id}</div>
                                                    <div className="text-xs text-slate-500">{t.description}</div>
                                                </div>
                                            </label>
                                        ))}
                                    </div>
                                    {selectedTools.filter(sel => !tools.some(av => av.id === sel || av.name === sel)).length > 0 && (
                                        <p className="text-xs text-amber-400 mt-2">
                                            Selected but not currently discoverable: {selectedTools.filter(sel => !tools.some(av => av.id === sel || av.name === sel)).join(', ')}
                                        </p>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {rightTab === 'tryit' && (
                        <div className="absolute inset-0 flex flex-col">
                            <div className="px-6 py-2.5 border-b border-slate-800 flex items-center justify-between shrink-0">
                                <div className="text-xs text-slate-400">
                                    Testing the <span className="text-slate-200 font-medium">unsaved</span> draft — tools stay constrained to your access; nothing is saved.
                                </div>
                                {tryMessages.length > 0 && (
                                    <button
                                        onClick={() => setTryMessages([])}
                                        disabled={tryRunning}
                                        className="flex items-center gap-1 text-xs text-slate-400 hover:text-rose-400 disabled:opacity-40">
                                        <Trash2 size={12} /> Clear
                                    </button>
                                )}
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 space-y-3">
                                {tryMessages.length === 0 ? (
                                    <div className="h-full flex flex-col items-center justify-center text-center text-slate-600">
                                        <Bot size={28} className="mb-2 text-slate-700" />
                                        <p className="text-sm">Ask the draft agent something to see how it responds.</p>
                                    </div>
                                ) : tryMessages.map((m, idx) => (
                                    <div key={idx} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                        <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                                            m.role === 'user'
                                                ? 'bg-indigo-600 text-white'
                                                : 'bg-slate-800 border border-slate-700 text-slate-200'
                                        }`}>
                                            {m.role === 'user' ? (
                                                <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                                            ) : (
                                                <>
                                                    {m.content ? (
                                                        <div className="prose prose-invert prose-sm max-w-none leading-relaxed">
                                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                                                        </div>
                                                    ) : (
                                                        <span className="inline-flex items-center gap-1.5 text-slate-500 text-xs">
                                                            <RefreshCw size={12} className="animate-spin" /> Thinking…
                                                        </span>
                                                    )}
                                                    {m.toolCalls && m.toolCalls.length > 0 && (
                                                        <div className="mt-2 pt-2 border-t border-slate-700 flex flex-wrap gap-1.5">
                                                            {m.toolCalls.map((t, i) => (
                                                                <span key={i} className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-slate-300">{t}</span>
                                                            ))}
                                                        </div>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                ))}
                                <div ref={tryEndRef} />
                            </div>

                            <div className="border-t border-slate-800 p-4 shrink-0">
                                <div className="flex items-end gap-2">
                                    <textarea
                                        value={tryInput}
                                        onChange={e => setTryInput(e.target.value)}
                                        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runTryIt(); } }}
                                        rows={1}
                                        placeholder="Ask the draft agent something…"
                                        disabled={tryRunning}
                                        className="flex-1 resize-none bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50 max-h-32"
                                    />
                                    <button
                                        onClick={runTryIt}
                                        disabled={tryRunning || !tryInput.trim()}
                                        className="flex items-center justify-center p-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded-lg shrink-0">
                                        {tryRunning ? <RefreshCw size={16} className="animate-spin" /> : <Send size={16} />}
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {showPromote && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowPromote(false)}>
                    <div className="w-full max-w-md bg-slate-800 border border-slate-600 rounded-xl shadow-2xl" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
                            <div className="flex items-center gap-2 text-slate-100 font-semibold">
                                <Rocket size={16} className="text-emerald-400" /> Promote "{name}"
                            </div>
                            <button onClick={() => setShowPromote(false)} className="text-slate-400 hover:text-slate-200"><X size={18} /></button>
                        </div>
                        <div className="p-5 space-y-4">
                            <p className="text-sm text-slate-400">
                                Copies this profile (AGENT.md + skills) into a shared location. The write only
                                succeeds if Unity Catalog grants you access to the target.
                            </p>
                            <div>
                                <label className="block text-sm font-medium text-slate-300 mb-1.5">Target location</label>
                                {promoteTargets.length === 0 ? (
                                    <p className="text-sm text-slate-500 italic">No shared targets available. Configure AGENT_STUDIO_PROMOTION_TARGETS or save a profile to a shared volume first.</p>
                                ) : (
                                    <select
                                        value={promoteTarget}
                                        onChange={e => setPromoteTarget(e.target.value)}
                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500">
                                        {promoteTargets.map(t => (
                                            <option key={`${t.store}|${t.base_path}`} value={`${t.store}|${t.base_path}`}>{t.label}</option>
                                        ))}
                                    </select>
                                )}
                            </div>
                        </div>
                        <div className="flex justify-end gap-2 px-5 py-4 border-t border-slate-700">
                            <button onClick={() => setShowPromote(false)} className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-md text-slate-200">Cancel</button>
                            <button onClick={handlePromote} disabled={isPromoting || !promoteTarget}
                                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-md text-white font-medium">
                                {isPromoting ? <RefreshCw size={14} className="animate-spin" /> : <Rocket size={14} />}
                                {isPromoting ? 'Promoting...' : 'Promote'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

const ReviewSection: React.FC<{ title: string; icon: any; empty: string; children: React.ReactNode }> = ({ title, icon: Icon, empty, children }) => {
    const items = React.Children.toArray(children);
    return (
        <div>
            <div className="flex items-center gap-2 text-slate-200 font-semibold mb-2"><Icon size={16} className="text-indigo-400" /> {title}</div>
            {items.length === 0 ? (
                <p className="text-sm text-slate-500 italic ml-6">{empty}</p>
            ) : (
                <ul className="space-y-1 ml-6 list-disc list-inside">{children}</ul>
            )}
        </div>
    );
};

export default AgentStudio;
