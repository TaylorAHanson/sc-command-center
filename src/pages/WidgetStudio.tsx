import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { Terminal, Code, Eye, RefreshCw, Send, Save, AlertCircle, AlertTriangle, Check, Settings, Plus, Trash2, Download, Upload, History, RotateCcw, X, Paperclip, Camera, Sliders, Loader2, Wrench, Lightbulb } from 'lucide-react';
import { toPng } from 'html-to-image';
import { loadCustomWidgets, getWidgetDomains, useWidgetRegistry } from '../widgetRegistry';
import type { ConfigField } from '../widgetRegistry';
import { useScript } from '../hooks/useScript';
import { useChatUploads } from '../hooks/useChatUploads';
import { BaseWidget } from '../components/BaseWidget';
import { CodeEditor } from '../components/CodeEditor';
import { AttachmentChip, SentAttachments } from '../components/AttachmentChip';
import { ThinkingDisclosure } from '../components/ThinkingDisclosure';
import { ExecuteActionPropInjector } from '../contexts/ActionContext';
import { useDashboardStore } from '../store/dashboardStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface WidgetStudioProps {
    editWidgetId?: string | null;
    cloneWidgetId?: string | null;
    onClose?: () => void;
}

class WidgetErrorBoundary extends React.Component<
    {
        children: React.ReactNode;
        /** Change this to give new code a clean slate. See componentDidUpdate. */
        resetKey?: unknown;
        onReset?: () => void;
        onError?: (error: Error) => void;
    },
    { hasError: boolean; error: Error | null }
> {
    constructor(props: any) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error) {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('Widget preview error:', error, errorInfo);
        this.props.onError?.(error);
    }

    /**
     * A boundary that has caught something goes on showing it forever — new
     * children don't clear it. That made a fixed widget indistinguishable from an
     * ignored request: the agent repaired the code, it compiled, and the pane kept
     * rendering the old crash. Recompiling produces a new component function, so
     * the component identity is the signal that this error belongs to code that
     * no longer exists.
     */
    componentDidUpdate(prev: { resetKey?: unknown }) {
        if (this.state.hasError && prev.resetKey !== this.props.resetKey) {
            this.setState({ hasError: false, error: null });
        }
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="w-full h-full p-6 flex flex-col items-center justify-center bg-rose-50 border-4 border-dashed border-rose-200 text-center">
                    <AlertCircle className="text-rose-500 mb-4" size={48} />
                    <h3 className="text-lg font-bold text-rose-800 mb-2">Build Succeeded, Render Failed</h3>
                    <p className="text-sm text-rose-600 mb-4 max-w-md">The widget code compiled successfully but crashed when React tried to render it.</p>
                    <pre className="text-xs text-left bg-white p-4 rounded-lg shadow-inner border border-rose-100 text-rose-900 max-w-lg w-full overflow-x-auto whitespace-pre-wrap">
                        {this.state.error?.message}
                    </pre>
                    <button
                        onClick={() => {
                            this.setState({ hasError: false, error: null });
                            this.props.onReset?.();
                        }}
                        className="mt-6 px-4 py-2 bg-rose-600 text-white rounded-md hover:bg-rose-700 font-medium text-sm transition-colors"
                    >
                        Try Again
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

const WIDGET_STUDIO_SESSION_KEY = "sc_widget_studio_session";

const DEFAULT_WIDGET_CODE = "export default function MyWidget() {\n  return (\n    <div className=\"p-4 bg-white rounded-lg shadow h-full flex items-center justify-center\">\n      <h3 className=\"text-xl font-bold text-slate-800\">Hello Widget</h3>\n    </div>\n  );\n}";

/**
 * The editor's contents as they were just before something replaced them.
 *
 * Agent turns are why this exists. A reply that swapped a working widget for a
 * fragment used to be unrecoverable in the studio, and people were re-publishing
 * older versions from the admin panel to get their work back. Everything that
 * writes the editor programmatically leaves one of these behind first.
 */
type CodeCheckpoint = {
    id: string;
    code: string;
    /** What was about to happen, phrased so the row reads as a place to return to. */
    label: string;
    at: number;
};

// sessionStorage gives the whole origin a few megabytes and the studio session
// shares it with the rest of the app, so history is bounded by size as well as
// count. Oldest snapshots go first; the newest is the one someone is reaching for.
const MAX_CHECKPOINTS = 25;
const MAX_HISTORY_CHARS = 600_000;
// One snapshot per burst of typing rather than one per keystroke.
const MANUAL_CHECKPOINT_GAP_MS = 60_000;
const MANUAL_EDIT_LABEL = "Before manual edits";

const trimHistory = (list: CodeCheckpoint[]): CodeCheckpoint[] => {
    const kept: CodeCheckpoint[] = [];
    let chars = 0;
    for (const entry of list.slice(0, MAX_CHECKPOINTS)) {
        chars += entry.code.length;
        // Never drop the newest, however big it is — with nothing kept there is
        // nothing to restore, which is the situation this whole feature exists for.
        if (kept.length && chars > MAX_HISTORY_CHARS) break;
        kept.push(entry);
    }
    return kept;
};

const countLines = (code: string) => (code || "").split("\n").filter(l => l.trim()).length;

const relativeTime = (at: number) => {
    const seconds = Math.max(0, Math.round((Date.now() - at) / 1000));
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return new Date(at).toLocaleDateString();
};

type PublishedVersion = { version: number; name: string; created_by: string; timestamp: string; lines: number };

/**
 * One step of a planned generation, as the server reports it while it works.
 *
 * A request that asks for several things is broken into steps and applied one at a
 * time, so the studio shows the plan and ticks it off. `skipped` means the run ran
 * out of time or was stopped before reaching that step — the steps before it are
 * still applied.
 */
type GenerationStage = {
    title: string;
    detail?: string;
    status?: 'running' | 'done' | 'failed' | 'skipped';
    note?: string;
};

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * One turn in the studio's chat.
 *
 * `thinking` is the account the server gives of what it decided while it worked
 * — the plan it made, a rewrite it refused, a step it ran out of time for. It is
 * not the model's reasoning, which these models keep to themselves; it is the
 * decisions taken around them, which is the part worth reading.
 */
type StudioMessage = {
    role: 'user' | 'assistant' | 'system';
    content: string;
    thinking?: string;
    /** Questions the agent wants answered before it spends a generation. */
    questions?: string[];
    /** What the review would do next, as prompts a click away. */
    suggestions?: StudioSuggestion[];
    attachments?: { id: string; filename: string; kind: string }[];
};

/** One follow-up the review offered: a defect it left, or an improvement.
 *
 *  `prompt` is written as an instruction to the agent rather than a description,
 *  because clicking one puts it in the message box for the user to send or edit.
 */
type StudioSuggestion = {
    kind: 'fix' | 'idea';
    label: string;
    prompt: string;
};

/**
 * A turn as the user should read it.
 *
 * The server marks a question set with an HTML comment so it can recognise one in
 * the history it gets back, and that has to survive in `content` for the round
 * trip — but a comment is only invisible in HTML, and this is markdown rendered
 * without raw-HTML support, so it was being printed to the user verbatim. Strip
 * it here, at the last possible moment, rather than from the stored message.
 */
const displayText = (content: string) => content.replace(/<!--[\s\S]*?-->/g, '').trim();

/** What a settled generation or review turn came back with. */
type JobResult = {
    /** Absent when nothing was applied — a review that found nothing, or a
     *  question asked instead of an answer. The editor keeps what it has. */
    code?: string | null;
    explanation?: string;
    questions?: string[];
    suggestions?: StudioSuggestion[];
    settings?: Record<string, unknown>;
};

// Studio preferences, per person and per browser rather than per deployment:
// whether to review after a change is a working style, not something an admin
// should decide for everyone (and app_settings is deployment-global by design).
const AGENT_PREFS_KEY = "sc_widget_studio_agent_prefs";

type AgentPrefs = { reviewAfterChange: boolean; askQuestions: boolean };

const DEFAULT_AGENT_PREFS: AgentPrefs = {
    // Off: it is another model call after the work has already finished, and the
    // wait is the cost people notice most.
    reviewAfterChange: false,
    askQuestions: true,
};

const readAgentPrefs = (): AgentPrefs => {
    try {
        const stored = localStorage.getItem(AGENT_PREFS_KEY);
        return stored ? { ...DEFAULT_AGENT_PREFS, ...JSON.parse(stored) } : DEFAULT_AGENT_PREFS;
    } catch {
        return DEFAULT_AGENT_PREFS;
    }
};

/** The state of one planned step, at a glance. */
const StageMark: React.FC<{ status?: GenerationStage['status'] }> = ({ status }) => {
    if (status === 'done') return <Check size={12} className="mt-0.5 text-emerald-400 shrink-0" />;
    if (status === 'running') return <RefreshCw size={12} className="mt-0.5 text-indigo-400 animate-spin shrink-0" />;
    if (status === 'failed') return <AlertTriangle size={12} className="mt-0.5 text-amber-400 shrink-0" />;
    return <span className="mt-0.5 w-3 shrink-0 text-center text-slate-600">·</span>;
};

/**
 * Somewhere to go back to, in two parts: snapshots from this studio session, and
 * the versions already published to the widget library.
 *
 * Restoring only ever loads code into the editor — it publishes nothing and
 * touches no settings — so an accidental restore is itself just another
 * checkpoint away from being undone.
 */
const CodeHistoryPanel: React.FC<{
    checkpoints: CodeCheckpoint[];
    currentCode: string;
    widgetId: string | null;
    onRestore: (code: string, description: string) => void;
    onClose: () => void;
}> = ({ checkpoints, currentCode, widgetId, onRestore, onClose }) => {
    // null means "not fetched yet", which is what renders the spinner. Deriving the
    // loading state from the data avoids a third state variable that has to be kept
    // in step with the other two.
    const [published, setPublished] = useState<PublishedVersion[] | null>(null);
    const [publishedError, setPublishedError] = useState<string | null>(null);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [busyVersion, setBusyVersion] = useState<number | null>(null);
    const currentLines = countLines(currentCode);

    const loadPublished = React.useCallback(async () => {
        if (!widgetId) return;
        try {
            const res = await fetch(`/api/widgets/history?widget_id=${encodeURIComponent(widgetId)}&env=dev`);
            if (!res.ok) {
                let detail = res.statusText;
                try { detail = (await res.json()).detail || detail; } catch { /* non-JSON body */ }
                throw new Error(`${detail} (HTTP ${res.status})`);
            }
            const data = await res.json();
            setPublished(data.history || []);
            setPublishedError(null);
        } catch (e) {
            setPublished([]);
            setPublishedError(errorText(e));
        }
    }, [widgetId]);

    useEffect(() => { loadPublished(); }, [loadPublished]);

    const retryPublished = () => {
        setPublished(null);
        setPublishedError(null);
        loadPublished();
    };

    const restorePublished = async (entry: PublishedVersion) => {
        setBusyVersion(entry.version);
        setPublishedError(null);
        try {
            const res = await fetch(`/api/widgets/version?widget_id=${encodeURIComponent(widgetId!)}&version=${entry.version}&env=dev`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `${res.statusText} (HTTP ${res.status})`);
            const code = data.widget?.tsx_code;
            if (!code || !code.trim()) throw new Error('That version has no code stored.');
            onRestore(code, `published v${entry.version}`);
        } catch (e) {
            setPublishedError(errorText(e));
        } finally {
            setBusyVersion(null);
        }
    };

    const LineCount: React.FC<{ lines: number }> = ({ lines }) => {
        const delta = lines - currentLines;
        return (
            <span className="text-slate-500">
                {lines} lines
                {delta !== 0 && (
                    <span className={delta < 0 ? 'text-amber-400' : 'text-emerald-400'}>
                        {' '}({delta > 0 ? '+' : ''}{delta} vs now)
                    </span>
                )}
            </span>
        );
    };

    const Row: React.FC<{
        rowKey: string; title: string; subtitle: string; lines: number; code?: string;
        onRestoreClick: () => void; busy?: boolean;
    }> = ({ rowKey, title, subtitle, lines, code, onRestoreClick, busy }) => (
        <div className="border border-slate-700 rounded-lg bg-slate-800/60 overflow-hidden">
            <div className="p-3">
                <div className="text-sm text-slate-200 font-medium break-words">{title}</div>
                <div className="mt-0.5 text-xs flex flex-wrap items-center gap-x-2">
                    <span className="text-slate-400">{subtitle}</span>
                    <LineCount lines={lines} />
                </div>
                <div className="mt-2 flex items-center gap-2">
                    <button
                        onClick={onRestoreClick}
                        disabled={busy}
                        className="px-2.5 py-1 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
                    >
                        {busy ? <RefreshCw size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                        Restore
                    </button>
                    {code !== undefined && (
                        <button
                            onClick={() => setExpanded(expanded === rowKey ? null : rowKey)}
                            className="px-2.5 py-1 text-xs rounded-md text-slate-300 bg-slate-700 hover:bg-slate-600 transition-colors"
                        >
                            {expanded === rowKey ? 'Hide code' : 'View code'}
                        </button>
                    )}
                </div>
            </div>
            {code !== undefined && expanded === rowKey && (
                <CodeEditor className="h-64 border-t border-slate-700 bg-[#1e1e1e]" language="tsx" value={code} ariaLabel={`${title} source`} />
            )}
        </div>
    );

    return (
        <div className="absolute inset-y-0 right-0 w-[26rem] max-w-full bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col z-20">
            <div className="p-4 border-b border-slate-700 flex items-start justify-between gap-2">
                <div>
                    <div className="flex items-center gap-2 text-slate-100 font-semibold">
                        <History size={16} className="text-indigo-400" />
                        History
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                        Restores code into the editor only. Settings stay as they are, and nothing is published until you say so.
                    </p>
                </div>
                <button onClick={onClose} aria-label="Close history" className="p-1 text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-800 transition-colors">
                    <X size={16} />
                </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-5">
                <div className="text-xs text-slate-400 flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">Now</span>
                    {currentLines} lines in the editor
                </div>

                <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">This session</h3>
                    {checkpoints.length === 0 ? (
                        <p className="text-xs text-slate-500">
                            No snapshots yet. One is taken automatically before the agent or an import changes your code.
                        </p>
                    ) : (
                        <div className="space-y-2">
                            {checkpoints.map(entry => (
                                <Row
                                    key={entry.id}
                                    rowKey={entry.id}
                                    title={entry.label}
                                    subtitle={relativeTime(entry.at)}
                                    lines={countLines(entry.code)}
                                    code={entry.code}
                                    onRestoreClick={() => onRestore(entry.code, `the version from ${relativeTime(entry.at)}`)}
                                />
                            ))}
                        </div>
                    )}
                </div>

                <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Published versions</h3>
                    {!widgetId ? (
                        <p className="text-xs text-slate-500">
                            This widget hasn't been published yet, so there are no saved versions to go back to.
                        </p>
                    ) : published === null ? (
                        <p className="text-xs text-slate-500 flex items-center gap-2"><RefreshCw size={12} className="animate-spin" /> Loading…</p>
                    ) : (
                        <div className="space-y-2">
                            {publishedError && (
                                <div className="text-xs text-rose-300 bg-rose-950/40 border border-rose-900/50 rounded-md p-2 flex items-start justify-between gap-2">
                                    <span className="break-words">{publishedError}</span>
                                    <button onClick={retryPublished} className="shrink-0 underline hover:text-rose-200">Retry</button>
                                </div>
                            )}
                            {published.length === 0 && !publishedError && (
                                <p className="text-xs text-slate-500">No saved versions found.</p>
                            )}
                            {published.map(entry => (
                                <Row
                                    key={entry.version}
                                    rowKey={`v${entry.version}`}
                                    title={`v${entry.version} — ${entry.name}`}
                                    subtitle={`${entry.created_by || 'unknown'} · ${entry.timestamp ? new Date(entry.timestamp).toLocaleString() : ''}`}
                                    lines={entry.lines ?? 0}
                                    onRestoreClick={() => restorePublished(entry)}
                                    busy={busyVersion === entry.version}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

// The settings the agent is allowed to propose. Same key names as the
// `widget-meta` block described in server/routes/agent_instructions.md.
const SETTING_KEYS = ['name', 'description', 'helpText', 'category', 'domain', 'defaultW', 'defaultH', 'isExecutable'];
const DEFAULT_WIDGET_NAME = "New Custom Widget";

// Basic skeleton for the page
export const WidgetStudio: React.FC<WidgetStudioProps> = ({ editWidgetId, cloneWidgetId, onClose }) => {
    // Helper to genericize session storage retrieval
    const getSessionState = () => {
        const stored = sessionStorage.getItem(WIDGET_STUDIO_SESSION_KEY);
        if (stored) {
            try { return JSON.parse(stored); } catch (e) { console.error("Could not parse widget studio session.", e); }
        }
        return null;
    };

    const sessionState = getSessionState();
    const { username } = useDashboardStore();

    const [messages, setMessages] = useState<StudioMessage[]>(sessionState?.messages || [{
        role: 'assistant',
        content: "Welcome to the Widget Studio! Briefly describe the widget you want to build."
    }]);

    const [prompt, setPrompt] = useState(sessionState?.prompt || "");
    const composerRef = useRef<HTMLTextAreaElement>(null);
    // Set when text is placed in the composer on the user's behalf, so the caret
    // follows it there without hijacking the cursor during ordinary typing.
    const focusComposerRef = useRef(false);
    const [isGenerating, setIsGenerating] = useState(false);
    // Seconds spent on the request in flight. A big widget takes minutes, and a
    // spinner with no clock on it is indistinguishable from a hang.
    const [elapsed, setElapsed] = useState(0);
    // The plan for a big request, if the server decided to work in steps. Ticks
    // over as each step lands, so a multi-minute generation shows what it is doing
    // instead of one spinner.
    const [stages, setStages] = useState<GenerationStage[]>([]);
    // What the run in flight has decided so far. Shown live, then attached to the
    // answer it belongs to so it can be read back afterwards.
    const [liveThinking, setLiveThinking] = useState<string[]>([]);
    const [stopping, setStopping] = useState(false);
    const [agentPrefs, setAgentPrefs] = useState<AgentPrefs>(readAgentPrefs);
    const [showAgentPrefs, setShowAgentPrefs] = useState(false);
    const [isCapturing, setIsCapturing] = useState(false);
    const attachInputRef = useRef<HTMLInputElement>(null);
    const [isPublishing, setIsPublishing] = useState(false);
    // Outcome of the last save, shown inline and briefly. Saving keeps you on the
    // page now, so this replaced an alert — see handlePublish.
    const [saveNotice, setSaveNotice] = useState<{ text: string; tone: 'ok' | 'error' } | null>(null);
    const [code, setCode] = useState<string>(sessionState?.code || DEFAULT_WIDGET_CODE);
    const [checkpoints, setCheckpoints] = useState<CodeCheckpoint[]>(sessionState?.checkpoints || []);
    const [showHistory, setShowHistory] = useState(false);
    const [viewMode, setViewMode] = useState<'preview' | 'code' | 'config'>(sessionState?.viewMode || 'preview');
    const [previewComponent, setPreviewComponent] = useState<React.ComponentType | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);

    // Widget Settings State
    const [widgetName, setWidgetName] = useState(sessionState?.widgetName || "New Custom Widget");
    const [widgetDescription, setWidgetDescription] = useState(sessionState?.widgetDescription || "");
    const [widgetHelpText, setWidgetHelpText] = useState(sessionState?.widgetHelpText || "");
    const [widgetCategory, setWidgetCategory] = useState(sessionState?.widgetCategory || "");
    const [widgetDomain, setWidgetDomain] = useState(sessionState?.widgetDomain || "");
    const [isExecutable, setIsExecutable] = useState(sessionState?.isExecutable || false);
    const [openInNewTabLink, setOpenInNewTabLink] = useState(sessionState?.openInNewTabLink || "");
    const [dataSourceType, setDataSourceType] = useState<"none" | "api" | "sql" | "databricks_api">(sessionState?.dataSourceType || "none");
    const [dataSource, setDataSource] = useState(sessionState?.dataSource || "");
    const [dataSourceSchema, setDataSourceSchema] = useState<any>(sessionState?.dataSourceSchema || null);
    // How many rows the tested query returns. Sent with every request: without it
    // the agent has no way to know whether to page in SQL or in the browser, and
    // guessing wrong is how a 40,000-row table ends up being fetched in batches.
    const [rowEstimate, setRowEstimate] = useState<number | null>(sessionState?.rowEstimate ?? null);
    const [isTestingDataSource, setIsTestingDataSource] = useState(false);
    const [dataSourceTestError, setDataSourceTestError] = useState<string | null>(null);
    const [defaultW, setDefaultW] = useState(sessionState?.defaultW || 6);
    const [defaultH, setDefaultH] = useState(sessionState?.defaultH || 6);
    const [configMode, setConfigMode] = useState<'none' | 'config_allowed' | 'config_required'>(sessionState?.configMode || 'none');
    const [configSchema, setConfigSchema] = useState<ConfigField[]>(sessionState?.configSchema || []);
    const [editingId, setEditingId] = useState<string | null>(sessionState?.editingId || null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const importInputRef = useRef<HTMLInputElement>(null);
    // Bounds the compile-error auto-retry loop. Each failed compile can kick off
    // a fresh generation; if the model keeps returning code that won't compile
    // this would otherwise call the LLM forever. Reset on a clean compile or a
    // manual generate.
    const autoRetryCountRef = useRef(0);
    // Counted separately from compile failures, because a render crash follows a
    // *successful* compile — which clears the counter above. Only a deliberate act
    // (a typed request, Reload, a restore) resets this one.
    const renderRetryCountRef = useRef(0);
    const MAX_AUTO_RETRIES = 3;
    // The generation being polled, so Stop has something to address.
    const jobIdRef = useRef<string | null>(null);
    const [availableDomains, setAvailableDomains] = useState<string[]>(['General']);
    const [availableCategories, setAvailableCategories] = useState<string[]>([]);
    // Configuration fields the user has decided for themselves (typed into,
    // picked, or inherited by opening an existing widget). The agent proposes
    // values for the rest; it never overwrites what's in here.
    const touchedSettingsRef = useRef<Set<string>>(new Set());
    const markSettingTouched = (key: string) => { touchedSettingsRef.current.add(key); };

    // Bumped by the Reload button. Recompiling produces a fresh component
    // function, which React treats as a different type and therefore remounts —
    // that's what re-fires mount-time data loads without touching the code.
    const [previewNonce, setPreviewNonce] = useState(0);
    const [taxonomyError, setTaxonomyError] = useState<string | null>(null);
    const [isLoadingTaxonomy, setIsLoadingTaxonomy] = useState(true);
    // Monotonic counter so a slow response from an earlier load can never
    // overwrite the result of a later one.
    const taxonomyRunRef = useRef(0);
    const [variables, setVariables] = useState<Record<string, any>>({});

    const setVariable = React.useCallback((key: string, value: any) => {
        setVariables(prev => ({ ...prev, [key]: value }));
    }, []);

    const { version: registryVersion } = useWidgetRegistry();

    // Files are stored against a conversation id, and the studio has no
    // conversation — so it mints one per session. Nothing reads it back; it only
    // has to be stable and unique, so the per-conversation attachment limit
    // applies to this studio session rather than to every session at once.
    // Minted on first use rather than on render, since generating it is not
    // something a render may do.
    const uploadConversationId = useRef(sessionState?.uploadConversationId || '');
    const conversationId = React.useCallback(() => {
        if (!uploadConversationId.current) {
            uploadConversationId.current = `widget-studio-${crypto.randomUUID().slice(0, 8)}`;
        }
        return uploadConversationId.current;
    }, []);
    const {
        attachments, setAttachments, attachFiles, attachBlob, removeAttachment,
        isUploading, uploadError, setUploadError, clearUploadError,
    } = useChatUploads({ conversationId });

    useEffect(() => {
        try { localStorage.setItem(AGENT_PREFS_KEY, JSON.stringify(agentPrefs)); } catch { /* private browsing */ }
    }, [agentPrefs]);

    // What's in the editor right now, readable from callbacks that were created
    // before the latest keystroke — a checkpoint has to capture what the user can
    // see, not what `code` was when the agent request went out.
    const codeRef = useRef(code);
    useEffect(() => { codeRef.current = code; }, [code]);

    // Latest values for the compile effect further down. That effect must run when
    // the code changes and at no other time, but the auto-fix inside it still needs
    // the current generate function and flags when it does run. Naming them as
    // dependencies would recompile the preview on every render instead, and reading
    // `handleGenerate` directly would reach for a function declared below it.
    const generateRef = useRef<(error?: string) => void | Promise<void>>(() => { });
    const reviewRef = useRef<(request: string) => void | Promise<void>>(() => { });
    const isGeneratingRef = useRef(isGenerating);
    const previewErrorRef = useRef(previewError);
    // Set when a generation produced code and the review pass is switched on;
    // consumed by the next clean compile. Holding it here rather than in state is
    // what makes "after the code builds" expressible: the compile effect is the
    // only thing that knows, and it must not re-run when this changes.
    const reviewPendingRef = useRef<{ request: string } | null>(null);
    // The last thing actually asked for, so "Build it anyway" can re-send it
    // without the user retyping a request they have already made.
    const lastRequestRef = useRef("");

    const pushCheckpoint = React.useCallback((snapshot: string, label: string) => {
        if (!snapshot || !snapshot.trim()) return;
        setCheckpoints(prev => (
            prev[0]?.code === snapshot
                ? prev  // nothing has changed since the last snapshot
                : trimHistory([{ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, code: snapshot, label, at: Date.now() }, ...prev])
        ));
    }, []);

    /**
     * The one way code gets replaced programmatically: snapshot first, and refuse
     * an empty payload outright. A response that parsed to nothing used to land in
     * the editor as a blank widget.
     */
    const replaceCode = React.useCallback((next: string, label: string): boolean => {
        if (typeof next !== 'string' || !next.trim()) return false;
        const before = codeRef.current;
        if (next === before) return false;
        pushCheckpoint(before, label);
        setCode(next);
        return true;
    }, [pushCheckpoint]);

    // Typing gets one snapshot per burst, so a long editing session leaves a
    // usable trail without filling history with keystrokes.
    const handleCodeEdit = React.useCallback((next: string) => {
        const before = codeRef.current;
        setCheckpoints(prev => {
            const newest = prev[0];
            const withinBurst = newest && newest.label === MANUAL_EDIT_LABEL && Date.now() - newest.at < MANUAL_CHECKPOINT_GAP_MS;
            if (withinBurst || !before.trim() || newest?.code === before) return prev;
            return trimHistory([{ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, code: before, label: MANUAL_EDIT_LABEL, at: Date.now() }, ...prev]);
        });
        setCode(next);
    }, []);

    const restoreCode = React.useCallback((next: string, description: string) => {
        if (!replaceCode(next, `Before restoring ${description}`)) {
            setMessages(prev => [...prev, { role: 'system', content: `That version is identical to what's already in the editor.` }]);
            return;
        }
        setPreviewError(null);
        // A deliberate restore starts with a clean auto-fix budget rather than
        // inheriting the count from whatever error prompted it.
        autoRetryCountRef.current = 0;
        renderRetryCountRef.current = 0;
        setViewMode('code');
        setMessages(prev => [...prev, {
            role: 'system',
            content: `Restored ${description}. Nothing is saved yet — press ${editingId ? 'Save' : 'Publish'} to keep it, or open History again to go back.`
        }]);
    }, [replaceCode, editingId]);

    // Loads the category/domain pickers. Anything that fails here leaves the
    // previously-loaded values in place and surfaces a retry, because quietly
    // falling back to an empty list makes a transient backend error look like
    // an administrator wiped the taxonomy.
    const loadTaxonomy = React.useCallback(async () => {
        const run = ++taxonomyRunRef.current;
        const isCurrent = () => run === taxonomyRunRef.current;
        setIsLoadingTaxonomy(true);

        const readJson = async (url: string) => {
            const r = await fetch(url);
            if (!r.ok) {
                let detail = r.statusText;
                try { detail = (await r.json()).detail || detail; } catch { /* non-JSON body */ }
                throw new Error(`${detail} (HTTP ${r.status})`);
            }
            return r.json();
        };

        try {
            // Role-derived domains are supplementary; the admin-managed lists are
            // the ones worth failing the load over.
            const [adminRes, catRes, rolesRes] = await Promise.all([
                readJson('/api/taxonomy/domains'),
                readJson('/api/taxonomy/categories'),
                readJson('/api/roles/my-domains').catch(() => ({ domains: [] })),
            ]);
            if (!isCurrent()) return;

            const adminDomains: string[] = (adminRes.domains || []).map((d: any) => d.name).filter(Boolean);
            const roleDomains: string[] = rolesRes.domains || [];
            const existingDomains = getWidgetDomains();
            setAvailableDomains(Array.from(new Set(['General', ...adminDomains, ...existingDomains, ...roleDomains])));
            setAvailableCategories((catRes.categories || []).map((c: any) => c.name).filter(Boolean));
            setTaxonomyError(null);
        } catch (e: any) {
            if (!isCurrent()) return;
            setTaxonomyError(e?.message || String(e));
        } finally {
            if (isCurrent()) setIsLoadingTaxonomy(false);
        }
    }, []);

    useEffect(() => { loadTaxonomy(); }, [registryVersion, loadTaxonomy]);

    // Save state changes to session storage
    useEffect(() => {
        if (!editWidgetId && !cloneWidgetId) { // We only automatically sync to session storage if we aren't loading an externally provided edit ID over it. Let the edit load effect take priority.
            const currentState = {
                messages, prompt, code, viewMode, widgetName, widgetDescription, widgetHelpText, widgetCategory, widgetDomain,
                isExecutable, openInNewTabLink, dataSourceType, dataSource, dataSourceSchema, rowEstimate, defaultW, defaultH, configMode, configSchema, editingId,
                checkpoints, uploadConversationId: uploadConversationId.current
            };
            try {
                sessionStorage.setItem(WIDGET_STUDIO_SESSION_KEY, JSON.stringify(currentState));
            } catch (e) {
                // Out of quota. The work in progress matters more than its history,
                // so drop the snapshots and keep the session itself persisting.
                console.warn("Widget studio session too large; saving without code history.", e);
                try {
                    sessionStorage.setItem(WIDGET_STUDIO_SESSION_KEY, JSON.stringify({ ...currentState, checkpoints: [] }));
                } catch (inner) {
                    console.error("Could not save the widget studio session.", inner);
                }
            }
        }
    }, [messages, prompt, code, viewMode, widgetName, widgetDescription, widgetHelpText, widgetCategory, widgetDomain,
        isExecutable, openInNewTabLink, dataSourceType, dataSource, dataSourceSchema, rowEstimate, defaultW, defaultH, configMode, configSchema, editingId,
        checkpoints, editWidgetId, cloneWidgetId]);

    // Load existing widget data when editWidgetId or cloneWidgetId is provided
    useEffect(() => {
        const targetId = editWidgetId || cloneWidgetId;
        if (!targetId) return;
        fetch('/api/widgets/custom')
            .then(r => r.json())
            .then(data => {
                // Explicitly the current version. The list carries every version so
                // the version dropdown knows they exist, but only the current one
                // carries its source — landing on any other would open the editor
                // empty and publish that over the widget.
                const versions = (data.widgets || []).filter((x: any) => x.id === targetId);
                const w = versions.find((x: any) => x.is_latest)
                    || versions.reduce((best: any, x: any) => (!best || x.version > best.version ? x : best), null);
                if (!w || !w.tsx_code) {
                    console.error(`Widget ${targetId} came back without its source; refusing to open an empty editor over it.`);
                    return;
                }
                
                const isClone = !!cloneWidgetId;

                // A published widget's settings were decided by a person, so the
                // agent leaves all of them alone from here on.
                SETTING_KEYS.forEach(markSettingTouched);

                // Opening a widget over unsaved work is its own way to lose code,
                // so the session keeps what was here.
                if (codeRef.current.trim() && codeRef.current !== DEFAULT_WIDGET_CODE && codeRef.current !== w.tsx_code) {
                    pushCheckpoint(codeRef.current, `Before opening "${w.name}"`);
                }

                setEditingId(isClone ? null : w.id);
                setWidgetName(isClone ? `Clone of ${w.name}` : w.name);
                setWidgetDescription(w.description || '');
                setWidgetCategory(w.category || 'Custom');
                setWidgetDomain(w.domain || '');
                setCode(w.tsx_code);
                setDataSourceType((w.data_source_type as any) || 'none');
                setDataSource(w.data_source || '');
                setOpenInNewTabLink(w.open_in_new_tab_link || '');
                setIsExecutable(w.is_executable === 1);
                setDefaultW(w.default_w || 6);
                setDefaultH(w.default_h || 6);
                setConfigMode(w.configuration_mode || 'none');
                
                let loadedSchema = [];
                try {
                    loadedSchema = w.config_schema ? JSON.parse(w.config_schema) : [];
                } catch (e) {
                    loadedSchema = [];
                }
                setConfigSchema(loadedSchema);
                
                const initMessages = [{ role: 'assistant' as const, content: isClone ? `Loaded a clone of "${w.name}". You are creating a new widget.` : `Loaded "${w.name}" for editing. Describe what you'd like to change.` }];
                setMessages(initMessages);

                // Overwrite the session storage right after loading existing widget
                const currentState = {
                    messages: initMessages, prompt: "", code: w.tsx_code, viewMode: 'preview', widgetName: isClone ? `Clone of ${w.name}` : w.name, widgetDescription: w.description || '', widgetHelpText: w.helpText || '', widgetCategory: w.category || 'Custom', widgetDomain: w.domain || '',
                    isExecutable: w.is_executable === 1, openInNewTabLink: w.open_in_new_tab_link || '', dataSourceType: (w.data_source_type as any) || 'none', dataSource: w.data_source || '', dataSourceSchema: null, defaultW: w.default_w || 6, defaultH: w.default_h || 6, configMode: w.configuration_mode || 'none', configSchema: loadedSchema, editingId: isClone ? null : w.id
                };
                sessionStorage.setItem(WIDGET_STUDIO_SESSION_KEY, JSON.stringify(currentState));
            })
            .catch(console.error);
    }, [editWidgetId, cloneWidgetId, pushCheckpoint]);

    useEffect(() => {
        const timeoutId = setTimeout(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
        return () => clearTimeout(timeoutId);
    }, [messages, isGenerating]);

    // A successful save clears itself; a failure stays until the next attempt,
    // because it names something that still needs doing.
    useEffect(() => {
        if (saveNotice?.tone !== 'ok') return;
        const timer = setTimeout(() => setSaveNotice(null), 6000);
        return () => clearTimeout(timer);
    }, [saveNotice]);

    // Count up while a request is in flight. The first tick lands a second in, so
    // a fast generation never flashes a stray "0s".
    useEffect(() => {
        if (!isGenerating) return;
        const startedAt = Date.now();
        const ticker = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
        return () => clearInterval(ticker);
    }, [isGenerating]);

    useEffect(() => {
        // Attempt to evaluate code whenever it changes
        const evaluateCode = () => {
            try {
                setPreviewError(null);
                // @ts-ignore
                if (!window.Babel) {
                    throw new Error("Babel compiler missing. Please ensure babel-standalone CDN is loaded.");
                }

                if (!code || code.trim() === '') {
                    setPreviewComponent(() => () => (
                        <div className="w-full h-full flex items-center justify-center text-slate-500">
                            <p>Provide a prompt to generate a widget preview</p>
                        </div>
                    ));
                    return;
                }

                // Two-pass Babel transform (mirrors widgetRegistry.ts so the preview
                // matches what dashboards run). Pass 1 strips TS types/type-only imports
                // and compiles JSX; pass 2 converts any remaining runtime ES `import`/
                // `export` to CommonJS so widgets authored with `import` statements don't
                // throw "Cannot use import statement outside a module".
                // @ts-ignore
                const stripped = window.Babel.transform(code, {
                    filename: 'widget.tsx',
                    presets: ['react', 'typescript']
                }).code;
                // @ts-ignore
                const transpiled = window.Babel.transform(stripped, {
                    filename: 'widget.js',
                    plugins: ['transform-modules-commonjs']
                }).code;

                // Fallback to window object if globals aren't directly available in module scope
                // @ts-ignore
                const HC = typeof Highcharts !== 'undefined' ? Highcharts : window.Highcharts;

                // Minimal CommonJS sandbox: `require` resolves to injected React or
                // runtime globals (e.g. window.Highcharts via useScript), else throws.
                const executableCode = `
                    var module = { exports: {} };
                    var exports = module.exports;
                    var require = function (name) {
                      if (name === 'react') return React;
                      if (name === 'react-dom') return (typeof window !== 'undefined' ? window.ReactDOM : undefined);
                      if (typeof window !== 'undefined') {
                        var g = window[name] || window[name.charAt(0).toUpperCase() + name.slice(1)];
                        if (g) return g;
                      }
                      throw new Error("Module '" + name + "' is not available in this sandbox. Use the useScript() hook for external libraries.");
                    };
                    ${transpiled}
                    return (module.exports && module.exports.default) ? module.exports.default : module.exports;
                `;

                // eslint-disable-next-line no-new-func
                const createComponent = new Function('React', 'useScript', 'Highcharts', executableCode);
                const Component = createComponent(React, useScript, HC);
                setPreviewComponent(() => Component);
                // Clean compile: clear the auto-retry budget for the next error.
                autoRetryCountRef.current = 0;

                // The code builds, so the review pass has something worth reading.
                // This is the only place that can know that — the compiler is the
                // browser's, so the server cannot wait for it.
                const pending = reviewPendingRef.current;
                if (pending && !isGeneratingRef.current) {
                    reviewPendingRef.current = null;
                    setTimeout(() => reviewRef.current(pending.request), 400);
                }
            } catch (err) {
                const errorMsg = errorText(err);
                if (previewErrorRef.current !== errorMsg) {
                    setPreviewError(errorMsg);
                    setPreviewComponent(null);

                    // Trigger auto-retry after a small delay to let state settle,
                    // but cap consecutive attempts so a persistently-uncompilable
                    // widget can't loop the generation endpoint forever.
                    if (!isGeneratingRef.current && autoRetryCountRef.current < MAX_AUTO_RETRIES) {
                        autoRetryCountRef.current += 1;
                        setTimeout(() => generateRef.current(errorMsg), 1000);
                    }
                }
            }
        };

        // add small debounce
        const timeoutid = setTimeout(evaluateCode, 500);
        return () => clearTimeout(timeoutid);
    }, [code, previewNonce]);

    const handleReloadPreview = () => {
        setViewMode('preview');
        setPreviewError(null);
        setPreviewComponent(null);
        // A deliberate reload shouldn't consume either retry budget.
        autoRetryCountRef.current = 0;
        renderRetryCountRef.current = 0;
        setPreviewNonce(n => n + 1);
    };

    // Applies the settings the agent proposed — but only to fields the user has
    // neither touched nor already filled in. Returns labels for what changed so
    // the conversation can say so rather than silently editing another tab.
    const applySuggestedSettings = (settings?: Record<string, any>): string[] => {
        if (!settings) return [];
        const applied: string[] = [];

        const take = (key: string, label: string, current: any, isUnset: boolean, apply: (value: any) => void) => {
            const value = settings[key];
            if (value === undefined || value === null || value === current) return;
            if (touchedSettingsRef.current.has(key) || !isUnset) return;
            apply(value);
            // Filled once. From here the field belongs to the user.
            markSettingTouched(key);
            applied.push(label);
        };

        take('name', 'name', widgetName, !widgetName.trim() || widgetName === DEFAULT_WIDGET_NAME, setWidgetName);
        take('description', 'description', widgetDescription, !widgetDescription.trim(), setWidgetDescription);
        take('helpText', 'help text', widgetHelpText, !widgetHelpText.trim(), setWidgetHelpText);
        // The backend already restricts these to the values we sent it. Checking
        // again is cheap, and an off-list value would leave a select with nothing
        // selected rather than failing visibly.
        if (availableCategories.includes(settings.category)) {
            take('category', 'category', widgetCategory, !widgetCategory || widgetCategory === 'Custom', setWidgetCategory);
        }
        if (availableDomains.includes(settings.domain)) {
            take('domain', 'domain', widgetDomain, !widgetDomain, setWidgetDomain);
        }
        take('defaultW', 'width', defaultW, defaultW === 6, setDefaultW);
        take('defaultH', 'height', defaultH, defaultH === 6, setDefaultH);
        take('isExecutable', 'executable action', isExecutable, isExecutable === false, setIsExecutable);

        return applied;
    };

    const describeGeneration = (result: any, fallback: string): string => {
        const applied = applySuggestedSettings(result?.settings);
        let text = result?.explanation || fallback;
        if (applied.length) {
            text += `\n\n_Filled in ${applied.join(', ')} on the Configuration tab. Change anything you like — I won't touch those again._`;
        }
        return text;
    };

    /**
     * Ask a planned run to stop once the step in flight is finished.
     *
     * The steps already applied stay in the editor — this is "that's enough", not
     * "undo it", and History has an entry per step for anyone who wants to go back.
     */
    const handleStopGeneration = async () => {
        const jobId = jobIdRef.current;
        if (!jobId) return;
        setStopping(true);
        try {
            await fetch(`/api/agent/widget/generate/${jobId}`, { method: 'DELETE' });
        } catch {
            // Nothing to recover: the run finishes on its own and polling reports it.
            setStopping(false);
        }
    };

    /**
     * Everything the agent needs to know about the widget as it stands.
     *
     * Shared by generation and the review pass, which has to be looking at the
     * same widget through the same lens — a reviewer told nothing about the data
     * source reports the data handling as broken.
     */
    const requestContext = () => ({
        current_code: codeRef.current,
        data_source_schema: dataSourceSchema,
        data_source: dataSourceType !== 'none' ? dataSource : null,
        data_source_type: dataSourceType !== 'none' ? dataSourceType : null,
        data_source_row_estimate: rowEstimate,
        configuration_mode: configMode,
        config_schema: dataSourceType !== 'none'
            ? [{ key: 'dataSource', label: 'Data Source', type: 'textarea' }, ...configSchema]
            : configSchema,
        available_categories: availableCategories,
        available_domains: availableDomains,
        locked_settings: SETTING_KEYS.filter(k => touchedSettingsRef.current.has(k)),
    });

    /**
     * Start a job on the widget agent and follow it to the end.
     *
     * Generation and review are the same thing from here: a POST that returns a
     * job id, a poll that reports steps, narration and code as they land, and one
     * assistant turn at the end. Sharing this is what lets the review pass reuse
     * the staged-progress UI, the History checkpoints and the failure handling
     * rather than growing a second copy of all three.
     */
    const runJob = async (endpoint: 'generate' | 'review', body: Record<string, unknown>, opts: {
        baseMessages: StudioMessage[];
        checkpointLabel: string;
        fallbackText: string;
        /** Ran with the settled result, for whatever should follow this turn. */
        onSettled?: (result: JobResult) => void;
    }) => {
        const { baseMessages, checkpointLabel, fallbackText, onSettled } = opts;
        const finish = (extra: StudioMessage) => {
            setIsGenerating(false);
            jobIdRef.current = null;
            setMessages([...baseMessages, extra]);
            setLiveThinking([]);
        };

        setIsGenerating(true);
        setElapsed(0);
        setStages([]);
        setStopping(false);
        setLiveThinking([]);

        try {
            const resp = await fetch(`/api/agent/widget/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();

            if (!resp.ok) {
                finish({ role: 'system', content: `Server Error: ${data.detail || resp.statusText}` });
                return;
            }

            if (!data.job_id) {
                // Fallback if the backend returns the code directly.
                if (data.code) {
                    replaceCode(data.code, checkpointLabel);
                    finish({ role: 'assistant', content: describeGeneration(data, fallbackText) });
                } else {
                    setIsGenerating(false);
                }
                return;
            }

            const jobId = data.job_id;
            let pollCount = 0;
            // The server says how long it is prepared to work (Admin Panel →
            // Settings), and we wait that long plus a margin for the last poll.
            // A hardcoded five minutes here used to declare a timeout while the
            // server was still going, so raising the limit changed nothing.
            const serverBudget = Number(data.timeout_seconds) || 300;
            const maxPolls = Math.ceil((serverBudget + 20) / 2);
            // Steps we have already put in the editor. A planned run publishes
            // each step's code as it lands so the work shows up while the rest is
            // still running, and so a step that fails later can't take the
            // finished ones with it.
            let stepsApplied = 0;
            let thinking: string[] = [];
            jobIdRef.current = jobId;

            const pollInterval = setInterval(async () => {
                try {
                    pollCount++;
                    const statusResp = await fetch(`/api/agent/widget/generate/${jobId}`);
                    const statusData = await statusResp.json();

                    if (Array.isArray(statusData.stages)) setStages(statusData.stages);
                    if (Array.isArray(statusData.trace)) {
                        thinking = statusData.trace;
                        setLiveThinking(thinking);
                    }
                    // Each step's snapshot is labelled with the step it precedes,
                    // so History reads as a list of places to go back to.
                    const stepLabel = (n: number) => {
                        if (stepsApplied === 0) return checkpointLabel;
                        const title = statusData.stages?.[n - 1]?.title;
                        return `Before step ${n}${title ? `: ${title}` : ''}`;
                    };

                    const landed = Number(statusData.stage_index) || 0;
                    if (statusData.stage_code && landed > stepsApplied) {
                        replaceCode(statusData.stage_code, stepLabel(landed));
                        stepsApplied = landed;
                    }

                    if (statusData.status === 'completed') {
                        clearInterval(pollInterval);
                        const result = statusData.result || {};
                        // A planned run has already applied its steps as they
                        // landed; writing the same code again would only add an
                        // identical history entry.
                        if (result.code && result.code !== codeRef.current) {
                            replaceCode(result.code, stepLabel(stepsApplied + 1));
                        }
                        finish({
                            role: 'assistant',
                            content: describeGeneration(result, fallbackText),
                            thinking: thinking.join('\n'),
                            questions: Array.isArray(result.questions) ? result.questions : undefined,
                            suggestions: Array.isArray(result.suggestions) && result.suggestions.length
                                ? result.suggestions
                                : undefined,
                        });
                        onSettled?.(result);
                    } else if (statusData.status === 'failed') {
                        clearInterval(pollInterval);
                        finish({
                            role: 'system',
                            content: `Generation Error: ${statusData.error}`,
                            thinking: thinking.join('\n'),
                        });
                    } else if (pollCount > maxPolls) {
                        clearInterval(pollInterval);
                        finish({
                            role: 'system',
                            content: `The server stopped responding about this request after ${serverBudget}s. `
                                + 'Ask for one part of the widget at a time, or raise the widget generation '
                                + 'timeout in Admin Panel → Settings.',
                            thinking: thinking.join('\n'),
                        });
                    }
                } catch (pollErr) {
                    clearInterval(pollInterval);
                    finish({ role: 'system', content: `Polling Error: ${errorText(pollErr)}` });
                }
            }, 2000);
        } catch (e) {
            finish({ role: 'system', content: `Network Error: ${errorText(e)}` });
        }
    };

    const handleGenerate = async (autoRetryError?: string, options?: {
        allowClarify?: boolean;
        overridePrompt?: string;
        /** Which kind of failure we're asking it to fix. Compiling and rendering
         *  fail for different reasons, and telling the model "compile error" about
         *  a crash sends it looking at the syntax of code that parsed fine. */
        errorKind?: 'compile' | 'render';
    }) => {
        const asking = options?.overridePrompt ?? prompt;
        if (!asking && !autoRetryError) return;

        const rendering = options?.errorKind === 'render';

        // Captured before the box is cleared, to label the snapshot this turn leaves
        // behind with the request that caused it.
        const asked = asking.trim().replace(/\s+/g, ' ');
        if (!autoRetryError && !options?.overridePrompt) lastRequestRef.current = asked;
        const checkpointLabel = autoRetryError
            ? `Before an automatic ${rendering ? 'render' : 'compile'} fix`
            : `Before "${asked.length > 60 ? `${asked.slice(0, 57)}…` : asked}"`;

        // This turn answers a question the agent asked, so it must not be met with
        // another. The server has its own guard on the history; this one is local
        // and exact, and doesn't depend on a marker surviving the round trip.
        const answeringQuestions = messages[messages.length - 1]?.questions?.length ? true : false;

        const sending = attachments.filter(a => a.status === 'ready');
        const newMessages = [...messages];
        if (autoRetryError) {
            newMessages.push({
                role: 'system',
                content: `Auto-retrying to fix a ${rendering ? 'render' : 'compile'} error: ${autoRetryError}`,
            });
            setMessages(newMessages);
        } else {
            newMessages.push({
                role: 'user',
                content: asking,
                attachments: sending.map(a => ({ id: a.id, filename: a.filename, kind: a.kind })),
            });
            setMessages(newMessages);
            if (!options?.overridePrompt) setPrompt("");
            // Clear any old preview errors on a fresh prompt
            setPreviewError(null);
            // A manual generate restarts both auto-retry budgets.
            autoRetryCountRef.current = 0;
            renderRetryCountRef.current = 0;
            // Files ride on the turn that sent them. The chips go now so the
            // composer is clear; the rows stay on the server, which is what the
            // agent reads them from.
            setAttachments([]);
        }

        // Review is chained off the compile that follows this turn, not off the
        // turn itself: there is no point auditing code that doesn't build, and
        // the studio is the only thing here that knows whether it does.
        reviewPendingRef.current = null;

        await runJob('generate', {
            ...requestContext(),
            prompt: asking || (rendering
                ? "The widget compiled but threw while React was rendering it. Fix the cause of "
                  + "that error. The syntax is fine — look at what runs on mount and on first paint."
                : "Please fix the compilation error in the code."),
            history: messages.filter(m => m.role !== 'system').map(m => ({ role: m.role, content: m.content })),
            error_log: autoRetryError || previewError,
            attachment_ids: autoRetryError ? [] : sending.map(a => a.id),
            allow_clarify: (options?.allowClarify ?? agentPrefs.askQuestions)
                && !autoRetryError && !answeringQuestions,
        }, {
            baseMessages: newMessages,
            checkpointLabel,
            fallbackText: autoRetryError ? "I've attempted to fix the compilation error." : "Widget code generated.",
            onSettled: result => {
                // Nothing changed, or the agent asked a question instead of
                // building — either way there is nothing to review.
                if (agentPrefs.reviewAfterChange && result.code && !result.questions?.length) {
                    reviewPendingRef.current = { request: asked };
                }
            },
        });
    };

    /**
     * The QA pass, run once the code the agent produced has compiled.
     *
     * Nothing here re-triggers a review: a review is a change like any other, so
     * without that the two would take turns indefinitely.
     */
    const handleReview = async (request: string) => {
        const opening: StudioMessage = { role: 'system', content: 'Reviewing the change…' };
        const baseMessages = [...messages, opening];
        setMessages(baseMessages);
        await runJob('review', { ...requestContext(), prompt: request }, {
            baseMessages,
            checkpointLabel: 'Before the review pass',
            fallbackText: 'Reviewed the widget; nothing needed changing.',
        });
    };

    /** Load a review's follow-up into the message box, ready to send or edit.
     *
     * Deliberately not sent on click. These are the agent's ideas rather than the
     * user's, and each one costs a minute of generation and rewrites the widget —
     * so the last word stays with the person whose widget it is. Landing in the
     * box also makes the prompt editable, which is where "sortable columns"
     * becomes "sortable columns, default to spend descending".
     */
    const applySuggestion = (suggestion: StudioSuggestion) => {
        setPrompt(suggestion.prompt);
        focusComposerRef.current = true;
    };

    /** Size the composer to its content, however the content got there.
     *
     * The change handler used to do this, which covered typing and nothing else:
     * text arriving from a suggestion chip, a restored session, or the clear after
     * send never fires `onChange`, so the box stayed one line tall with the rest
     * of the prompt clipped out of sight. Reading `scrollHeight` inside the click
     * handler doesn't work either — React hasn't re-rendered, so it measures the
     * value that was there before.
     *
     * A layout effect runs after the DOM has the new value but before the browser
     * paints, so a long prompt is never briefly shown as one line.
     */
    useLayoutEffect(() => {
        const box = composerRef.current;
        if (!box) return;
        box.style.height = 'auto';
        box.style.height = `${box.scrollHeight}px`;
        // Caret to the end, but only when the text was put there for the user.
        // Doing it on every change would drag the cursor along while they type.
        if (focusComposerRef.current) {
            focusComposerRef.current = false;
            box.focus();
            box.setSelectionRange(box.value.length, box.value.length);
        }
    }, [prompt]);

    // Kept current for the compile effect above, which reads them through refs so it
    // isn't re-run by anything but a code change.
    useEffect(() => {
        generateRef.current = handleGenerate;
        reviewRef.current = handleReview;
        isGeneratingRef.current = isGenerating;
        previewErrorRef.current = previewError;
    });

    const handlePublish = async () => {
        const missing = !widgetName.trim() ? 'a Widget Name'
            : !widgetDescription.trim() ? 'a Description'
                : (!widgetCategory || widgetCategory === 'Custom') ? 'a Category'
                    : (!widgetDomain || widgetDomain.toLowerCase() === 'custom') ? 'a Domain'
                        : null;
        if (missing) {
            setSaveNotice({ tone: 'error', text: `Fill in ${missing} on the Configuration tab first.` });
            setViewMode('config');
            return;
        }

        const isEditing = !!editingId;
        const url = isEditing ? `/api/widgets/custom/${editingId}` : '/api/widgets/custom';
        const method = isEditing ? 'PUT' : 'POST';

        setIsPublishing(true);
        let snapshotDataUrl = null;
        try {
            // Ensure we're in preview mode so the node exists
            if (viewMode !== 'preview') {
                setViewMode('preview');
                // Allow a brief moment for React to render the DOM
                await new Promise(r => setTimeout(r, 300));
            }
            const captureArea = document.getElementById('widget-preview-capture-area');
            if (captureArea) {
                snapshotDataUrl = await toPng(captureArea, { cacheBust: true, pixelRatio: 1 });
            }
        } catch (e) {
            console.warn("Failed to capture widget snapshot:", e);
        }

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: widgetName,
                    description: widgetDescription,
                    help_text: widgetHelpText,
                    category: widgetCategory,
                    domain: widgetDomain,
                    tsx_code: code,
                    isExecutable: isExecutable,
                    open_in_new_tab_link: openInNewTabLink,
                    data_source_type: dataSourceType,
                    data_source: dataSource,
                    snapshot: snapshotDataUrl,
                    default_w: defaultW,
                    default_h: defaultH,
                    configurationMode: configMode,
                    configSchema: dataSourceType !== 'none' ? JSON.stringify([{ key: 'dataSource', label: 'Data Source', type: 'textarea' }, ...configSchema]) : JSON.stringify(configSchema)
                })
            });
            
            // For a new widget we need the id to update editingId, so parse response here instead of below
            let responseData: any = null;
            if (res.ok) {
                try {
                    responseData = await res.json();
                } catch(e) {}
            }

            if (res.ok) {
                await loadCustomWidgets();
                // Saving no longer closes the studio, so this can't be an alert:
                // people save every few minutes while they work, and a modal to
                // dismiss on every one of them is worse than no confirmation. The
                // session is kept for the same reason — clearing it while staying
                // on the page would mean a reload lost everything.
                setSaveNotice({
                    tone: 'ok',
                    text: isEditing
                        ? `Saved. "${widgetName}" is live in the Widget Library.`
                        : `Published. Open the Widget Library (press W) to find "${widgetName}".`,
                });

                // If it was a new publish, update editingId so subsequent saves are updates
                if (!isEditing && responseData?.id) {
                    setEditingId(responseData.id);
                }
            } else {
                const err = responseData || await res.json().catch(() => ({ detail: res.statusText }));
                setSaveNotice({ tone: 'error', text: `Could not save: ${err.detail || res.statusText}` });
            }
        } catch (err) {
            setSaveNotice({ tone: 'error', text: `Could not save: ${errorText(err)}` });
        } finally {
            setIsPublishing(false);
        }
    };

    const handleTestDataSource = async () => {
        if (dataSourceType === "none" || !dataSource) return;
        setIsTestingDataSource(true);
        setDataSourceTestError(null);
        setDataSourceSchema(null);
        setRowEstimate(null);
        try {
            const res = await fetch('/api/agent/widget/datasource/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    data_source_type: dataSourceType,
                    data_source: dataSource
                })
            });
            const data = await res.json();
            if (res.ok) {
                setDataSourceSchema(data.schema);
                // Absent for API sources, and for a query the warehouse wouldn't
                // count. The agent is told "size unknown" in that case rather than
                // being left to assume it is small.
                setRowEstimate(typeof data.row_estimate === 'number' ? data.row_estimate : null);
            } else {
                setDataSourceTestError(data.detail || "Error testing data source");
            }
        } catch (err: any) {
            setDataSourceTestError(err.message || String(err));
        } finally {
            setIsTestingDataSource(false);
        }
    };

    /**
     * Put a picture of the rendered widget in the composer, ready to be sent.
     *
     * Attaching rather than sending is the point: "this column is too narrow" only
     * means something alongside the thing it is describing, and the sentence is
     * the user's to write. Only one screenshot is kept — a second replaces the
     * first, since two pictures of the same widget say nothing extra and the
     * per-conversation attachment limit is small.
     */
    const handleInjectScreenshot = async () => {
        const captureArea = document.getElementById('widget-preview-capture-area');
        if (!captureArea) return;
        setIsCapturing(true);
        clearUploadError();
        try {
            const dataUrl = await toPng(captureArea, { cacheBust: true, pixelRatio: 1 });
            const blob = await (await fetch(dataUrl)).blob();

            // Drop the previous screenshot first, so repeatedly grabbing one
            // during a back-and-forth can't exhaust the attachment limit.
            const previous = attachments.filter(a => a.filename.startsWith('widget-screenshot'));
            await Promise.all(previous.map(a => removeAttachment(a.id)));

            const landed = await attachBlob(blob, `widget-screenshot-${Date.now()}.png`);
            if (!landed) return;
            setMessages(prev => [...prev, {
                role: 'system',
                content: 'Screenshot attached. Say what you want changed about it and press send.',
            }]);
        } catch (e) {
            // Unlike the publish snapshot, a failure here is the whole point of
            // the button, so it has to be visible rather than logged.
            setUploadError(`Could not capture the widget: ${errorText(e)}. A widget drawing from a cross-origin image or canvas can't be captured.`);
        } finally {
            setIsCapturing(false);
        }
    };

    const handleReset = () => {
        if (!confirm("Are you sure you want to reset the Widget Studio? All unsaved changes will be lost.")) return;
        sessionStorage.removeItem(WIDGET_STUDIO_SESSION_KEY);
        // Reset is confirmed, but a misfired one shouldn't be the end of the code.
        pushCheckpoint(codeRef.current, 'Before Reset');
        touchedSettingsRef.current.clear();
        setEditingId(null);
        setWidgetName(DEFAULT_WIDGET_NAME);
        setWidgetDescription("");
        setWidgetCategory("");
        setWidgetDomain("");
        setIsExecutable(false);
        setOpenInNewTabLink("");
        setDataSourceType("none");
        setDataSource("");
        setDataSourceSchema(null);
        setDefaultW(6);
        setDefaultH(6);
        setConfigMode('none');
        setConfigSchema([]);
        setPrompt("");
        setCode(DEFAULT_WIDGET_CODE);
        setMessages([{
            role: 'assistant',
            content: "Welcome to the Widget Studio! Briefly describe the widget you want to build."
        }]);
        setViewMode('preview');
        setPreviewError(null);
        setRowEstimate(null);
        setAttachments([]);
        setSaveNotice(null);
    };

    // Export the current widget definition (code + all settings) as a portable
    // JSON file so it can be moved between environments or shared, then imported
    // back via the Import button below.
    const handleExport = () => {
        const payload = {
            __type: 'sccc-widget',
            version: 1,
            exported_at: new Date().toISOString(),
            widget: {
                name: widgetName,
                description: widgetDescription,
                help_text: widgetHelpText,
                category: widgetCategory,
                domain: widgetDomain,
                tsx_code: code,
                is_executable: isExecutable,
                open_in_new_tab_link: openInNewTabLink,
                data_source_type: dataSourceType,
                data_source: dataSource,
                default_w: defaultW,
                default_h: defaultH,
                configuration_mode: configMode,
                config_schema: configSchema,
            },
        };
        const slug = (widgetName || 'widget').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'widget';
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${slug}.widget.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    const handleImportFile = async (file: File) => {
        try {
            const parsed = JSON.parse(await file.text());
            // Tolerate either our wrapper ({ widget: {...} }) or a raw widget object.
            const w = (parsed && typeof parsed === 'object' && parsed.widget) ? parsed.widget : parsed;
            if (!w || typeof w !== 'object' || (!w.tsx_code && !w.name)) {
                throw new Error('This does not look like an exported widget file.');
            }
            // An import always creates a NEW widget; clear editingId so Publish inserts.
            setEditingId(null);
            // The imported file's settings were somebody's decision; keep them.
            SETTING_KEYS.forEach(markSettingTouched);
            setWidgetName(w.name || 'Imported Widget');
            setWidgetDescription(w.description || '');
            setWidgetHelpText(w.help_text || '');
            setWidgetCategory(w.category || '');
            setWidgetDomain(w.domain || '');
            replaceCode(w.tsx_code || code, `Before importing "${w.name || 'a widget file'}"`);
            setIsExecutable(w.is_executable === true || w.is_executable === 1);
            setOpenInNewTabLink(w.open_in_new_tab_link || '');
            setDataSourceType((w.data_source_type as any) || 'none');
            setDataSource(w.data_source || '');
            setDataSourceSchema(null);
            setDefaultW(w.default_w || 6);
            setDefaultH(w.default_h || 6);
            setConfigMode(w.configuration_mode || 'none');
            let schema: ConfigField[] = [];
            if (Array.isArray(w.config_schema)) schema = w.config_schema;
            else if (typeof w.config_schema === 'string') { try { schema = JSON.parse(w.config_schema); } catch { schema = []; } }
            setConfigSchema(schema || []);
            setViewMode('preview');
            setPreviewError(null);
            setMessages([{ role: 'assistant', content: `Imported "${w.name || 'widget'}" from file. Review it, then Publish to save it as a new widget.` }]);
        } catch (e: any) {
            alert(`Could not import widget: ${e.message || e}`);
        }
    };

    return (
        <div className="flex h-full w-full bg-slate-900 text-slate-100 overflow-hidden font-sans">
            {/* LEFT PANE: Chat Interface (1/3 width) */}
            <div className="w-1/3 flex flex-col border-r border-slate-700 bg-slate-800">
                <div className="p-4 border-b border-slate-700 bg-slate-900 flex justify-between items-center h-14">
                    <div className="flex items-center gap-2 text-indigo-400 font-semibold tracking-wide">
                        <Terminal size={18} />
                        <span>Widget Studio</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <input
                            ref={importInputRef}
                            type="file"
                            accept="application/json,.json"
                            className="hidden"
                            onChange={e => { const f = e.target.files?.[0]; if (f) handleImportFile(f); e.target.value = ''; }}
                        />
                        <div className="relative">
                            <button
                                onClick={() => setShowAgentPrefs(v => !v)}
                                title="Agent settings"
                                className={`flex items-center justify-center p-1.5 rounded-md transition-colors ${showAgentPrefs ? 'bg-indigo-600 text-white' : 'text-slate-300 bg-slate-700 hover:bg-slate-600'}`}>
                                <Sliders size={14} />
                            </button>
                            {showAgentPrefs && (
                                <>
                                    {/* Click-away, behind the panel: a popover this small is more
                                        annoying to dismiss with a second click on the gear. */}
                                    <div className="fixed inset-0 z-30" onClick={() => setShowAgentPrefs(false)} />
                                    <div className="absolute left-0 top-full mt-2 z-40 w-72 rounded-lg border border-slate-600 bg-slate-800 p-3 shadow-xl">
                                        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Agent settings</div>
                                        <label className="flex gap-2 cursor-pointer py-1.5">
                                            <input
                                                type="checkbox"
                                                checked={agentPrefs.reviewAfterChange}
                                                onChange={e => setAgentPrefs(p => ({ ...p, reviewAfterChange: e.target.checked }))}
                                                className="mt-0.5 accent-indigo-500"
                                            />
                                            <span className="text-xs">
                                                <span className="font-medium text-slate-200">Conduct review after change</span>
                                                <span className="block text-slate-400 mt-0.5">
                                                    Once new code compiles, the agent re-reads it for broken behaviour,
                                                    layout and styling problems, and fixes what it finds. It then suggests
                                                    what would make the widget better without building it. Slower, and it
                                                    costs an extra turn.
                                                </span>
                                            </span>
                                        </label>
                                        <label className="flex gap-2 cursor-pointer py-1.5">
                                            <input
                                                type="checkbox"
                                                checked={agentPrefs.askQuestions}
                                                onChange={e => setAgentPrefs(p => ({ ...p, askQuestions: e.target.checked }))}
                                                className="mt-0.5 accent-indigo-500"
                                            />
                                            <span className="text-xs">
                                                <span className="font-medium text-slate-200">Ask before large builds</span>
                                                <span className="block text-slate-400 mt-0.5">
                                                    On a big or vague request the agent asks a couple of questions first
                                                    instead of guessing and building the wrong widget.
                                                </span>
                                            </span>
                                        </label>
                                        <div className="mt-1 pt-2 border-t border-slate-700 text-[10px] text-slate-500">
                                            Saved in this browser.
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                        <button
                            onClick={() => importInputRef.current?.click()}
                            title="Import a widget from a .json file"
                            className="flex items-center justify-center p-1.5 text-slate-300 bg-slate-700 hover:bg-slate-600 rounded-md transition-colors">
                            <Upload size={14} />
                        </button>
                        <button
                            onClick={handleExport}
                            title="Export this widget to a .json file"
                            className="flex items-center justify-center p-1.5 text-slate-300 bg-slate-700 hover:bg-slate-600 rounded-md transition-colors">
                            <Download size={14} />
                        </button>
                        <button
                            onClick={handleReset}
                            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded-md transition-colors font-medium">
                            <RefreshCw size={14} />
                            Reset
                        </button>
                        <button
                            onClick={handlePublish}
                            disabled={isPublishing}
                            className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors font-medium ${isPublishing ? 'bg-indigo-400 cursor-not-allowed text-indigo-100' : 'bg-indigo-600 hover:bg-indigo-500 text-white'}`}>
                            {isPublishing ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                            {isPublishing ? (editingId ? 'Saving...' : 'Publishing...') : (editingId ? 'Save' : 'Publish')}
                        </button>
                        {/* Saving keeps you here, so leaving needs its own button —
                            and it is the only exit that clears the widget the
                            studio was opened on. */}
                        <button
                            onClick={onClose}
                            title="Close the studio and go back to your dashboard"
                            className="flex items-center justify-center p-1.5 text-slate-300 bg-slate-700 hover:bg-slate-600 rounded-md transition-colors">
                            <X size={14} />
                        </button>
                    </div>
                </div>

                {saveNotice && (
                    <div className={`px-4 py-2 text-xs flex items-start gap-2 border-b ${saveNotice.tone === 'ok'
                        ? 'bg-emerald-950/40 border-emerald-900/50 text-emerald-300'
                        : 'bg-rose-950/40 border-rose-900/50 text-rose-300'}`}>
                        {saveNotice.tone === 'ok' ? <Check size={13} className="mt-0.5 shrink-0" /> : <AlertTriangle size={13} className="mt-0.5 shrink-0" />}
                        <span className="flex-1 break-words">{saveNotice.text}</span>
                        <button onClick={() => setSaveNotice(null)} aria-label="Dismiss" className="shrink-0 opacity-70 hover:opacity-100">
                            <X size={12} />
                        </button>
                    </div>
                )}

                {/* Chat History */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((m, i) => (
                        <div key={i} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className={`max-w-[85%] rounded-lg p-3 text-sm shadow-sm ${m.role === 'user' ? 'bg-indigo-600 text-white rounded-br-none' :
                                m.role === 'system' ? 'bg-slate-700/50 text-slate-300 border border-slate-600/50 rounded-bl-none' :
                                    'bg-slate-700 text-slate-200 rounded-bl-none border border-slate-600'
                                }`}>
                                <SentAttachments files={m.attachments || []} />
                                {m.thinking && (
                                    <ThinkingDisclosure text={m.thinking} label="Thoughts" defaultOpen={false} variant="dark" />
                                )}
                                <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-li:my-0">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {displayText(m.content)}
                                    </ReactMarkdown>
                                </div>
                                {/* Only the newest question set is answerable — an older one has
                                    already been answered or abandoned. */}
                                {m.questions && m.questions.length > 0 && i === messages.length - 1 && !isGenerating && (
                                    <button
                                        onClick={() => handleGenerate(undefined, {
                                            allowClarify: false,
                                            overridePrompt: `${lastRequestRef.current} — go ahead and pick sensible defaults for anything you asked about.`,
                                        })}
                                        className="mt-2 px-2.5 py-1 text-xs font-medium rounded-md bg-slate-600 hover:bg-slate-500 text-slate-100 transition-colors"
                                    >
                                        Build it anyway
                                    </button>
                                )}
                                {/* Only on the newest turn: once the widget has moved on, what
                                    the review suggested may no longer be what it would say. */}
                                {m.suggestions && m.suggestions.length > 0 && i === messages.length - 1 && !isGenerating && (
                                    <div className="mt-2.5 pt-2.5 border-t border-slate-600">
                                        <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-1.5">
                                            Do next
                                        </p>
                                        <div className="flex flex-wrap gap-1.5">
                                            {m.suggestions.map((s, n) => (
                                                <button
                                                    key={n}
                                                    onClick={() => applySuggestion(s)}
                                                    title={s.prompt}
                                                    className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                                                        s.kind === 'fix'
                                                            ? 'bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40'
                                                            : 'bg-slate-600 hover:bg-slate-500 text-slate-100 border border-slate-500'
                                                    }`}
                                                >
                                                    {s.kind === 'fix' ? <Wrench size={12} /> : <Lightbulb size={12} />}
                                                    {s.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {isGenerating && (
                        <div className="flex items-start">
                            <div className="bg-slate-700 text-slate-400 rounded-lg p-3 rounded-bl-none text-sm border border-slate-600 max-w-[90%]">
                                <div className="flex items-center gap-2">
                                    <RefreshCw size={14} className="animate-spin" />
                                    <span>
                                        {stages.length
                                            ? `Working through ${stages.length} steps`
                                            : 'Generating widget'}
                                        {elapsed ? ` — ${elapsed}s` : ''}...
                                    </span>
                                </div>
                                {liveThinking.length > 0 && (
                                    <div className="mt-2">
                                        <ThinkingDisclosure
                                            text={liveThinking.join('\n')}
                                            label="Thinking…"
                                            defaultOpen
                                            variant="dark"
                                        />
                                    </div>
                                )}
                                {stages.length > 0 && (
                                    <ul className="mt-2 space-y-1">
                                        {stages.map((stage, i) => (
                                            <li key={i} className="flex items-start gap-2 text-xs">
                                                <StageMark status={stage.status} />
                                                <span className={
                                                    stage.status === 'done' ? 'text-slate-300'
                                                        : stage.status === 'running' ? 'text-indigo-300'
                                                            : stage.status === 'failed' ? 'text-amber-400'
                                                                : 'text-slate-500'
                                                }>
                                                    {stage.title}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {stages.length > 0 && (
                                    <button
                                        onClick={handleStopGeneration}
                                        disabled={stopping}
                                        className="mt-2 text-xs text-slate-400 hover:text-slate-200 underline disabled:no-underline disabled:text-slate-500"
                                    >
                                        {stopping ? 'Stopping after this step…' : 'Stop after this step'}
                                    </button>
                                )}
                                {elapsed >= 90 && stages.length === 0 && (
                                    <div className="mt-1 text-xs text-slate-500">a large change can take a few minutes</div>
                                )}
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                <div className="p-4 border-t border-slate-700 bg-slate-800/50">
                    {/* Data source context pill */}
                    {dataSourceType !== 'none' && dataSource && (
                        <div className="mb-2 flex items-center gap-2 px-3 py-1.5 bg-slate-700/60 border border-slate-600 rounded-md text-xs text-slate-300">
                            <span className={`px-1.5 py-0.5 rounded font-mono font-bold text-[10px] ${dataSourceType === 'sql' ? 'bg-indigo-900 text-indigo-300' : dataSourceType === 'databricks_api' ? 'bg-orange-900 text-orange-300' : 'bg-emerald-900 text-emerald-300'}`}>
                                {dataSourceType === 'databricks_api' ? 'DATABRICKS API' : dataSourceType.toUpperCase()}
                            </span>
                            <span className="truncate text-slate-400 font-mono">{dataSource.replace(/\s+/g, ' ').slice(0, 80)}{dataSource.length > 80 ? '…' : ''}</span>
                            {rowEstimate !== null && (
                                <span className="ml-auto shrink-0 text-slate-400" title="Rows this query returns. The agent uses this to decide whether to page in SQL or in the browser.">
                                    {rowEstimate.toLocaleString()} rows
                                </span>
                            )}
                        </div>
                    )}
                    {uploadError && (
                        <div className="mb-2 flex items-start gap-1.5 rounded-md border border-rose-900/50 bg-rose-950/40 px-2 py-1.5 text-[11px] text-rose-300">
                            <AlertCircle size={13} className="mt-px shrink-0" />
                            <span className="flex-1 break-words">{uploadError}</span>
                            <button type="button" onClick={clearUploadError} title="Dismiss" className="p-0.5 hover:text-rose-200">
                                <X size={12} />
                            </button>
                        </div>
                    )}
                    {attachments.length > 0 && (
                        <div className="mb-2 flex flex-wrap gap-1.5">
                            {attachments.map(file => (
                                <AttachmentChip key={file.id} file={file} onRemove={removeAttachment} variant="dark" />
                            ))}
                        </div>
                    )}
                    <div className="flex border border-slate-600 rounded-md bg-slate-900 focus-within:border-indigo-500 ring-1 focus-within:ring-indigo-500 overflow-hidden transition-all shadow-inner items-end">
                        <input
                            ref={attachInputRef}
                            type="file"
                            multiple
                            className="hidden"
                            accept=".csv,.tsv,.xlsx,.xlsm,.json,.ndjson,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
                            onChange={e => {
                                if (e.target.files?.length) attachFiles(e.target.files);
                                // Reset so re-picking the same file still fires a change.
                                e.target.value = '';
                            }}
                        />
                        <button
                            onClick={() => attachInputRef.current?.click()}
                            disabled={isUploading}
                            title="Attach a spreadsheet, document, or screenshot for the agent to read"
                            className="px-3 py-3 self-stretch text-slate-400 hover:text-indigo-400 disabled:opacity-40 transition-colors"
                        >
                            {isUploading ? <Loader2 size={16} className="animate-spin" /> : <Paperclip size={16} />}
                        </button>
                        <textarea
                            ref={composerRef}
                            className="flex-1 bg-transparent border-none px-4 py-3 text-sm focus:outline-none text-slate-200 placeholder-slate-500 resize-none min-h-[44px] max-h-32 overflow-y-auto"
                            placeholder="Create a bar chart showing total sales..."
                            value={prompt}
                            onChange={e => setPrompt(e.target.value)}
                            onKeyDown={e => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleGenerate();
                                }
                            }}
                            rows={1}
                        />
                        <button
                            onClick={() => {
                                handleGenerate();
                                // We can't easily reset height here without a ref, so we rely on prompt clearing (it might not resize until manual edit, but good enough for now - or we could use a ref).
                            }}
                            disabled={isGenerating || !prompt}
                            className="px-4 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition-colors flex items-center justify-center self-stretch"
                        >
                            <Send size={16} />
                        </button>
                    </div>
                </div>
            </div>

            {/* RIGHT PANE: Workspace (2/3 width) */}
            <div className="w-2/3 flex flex-col bg-slate-900">
                <div className="flex border-b border-slate-800 bg-slate-900/50 px-4 pt-2 gap-2 h-14 items-end">
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'preview' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('preview')}
                    >
                        <Eye size={14} /> Live Preview
                    </button>
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'code' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('code')}
                    >
                        <Code size={14} /> TSX Editor
                    </button>
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'config' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('config')}
                    >
                        <Settings size={14} /> Configuration
                    </button>
                    <button
                        onClick={() => setShowHistory(v => !v)}
                        className={`ml-auto mb-1 px-3 py-1.5 flex items-center gap-2 rounded-md text-sm border transition-colors ${showHistory ? 'bg-indigo-600 border-indigo-500 text-white' : 'text-slate-300 bg-slate-800 border-slate-700 hover:bg-slate-700 hover:text-white'}`}
                        title="Restore an earlier version of this widget's code"
                    >
                        <History size={14} /> History{checkpoints.length ? ` (${checkpoints.length})` : ''}
                    </button>
                    <button
                        onClick={handleReloadPreview}
                        disabled={!code}
                        className="mb-1 px-3 py-1.5 flex items-center gap-2 rounded-md text-sm text-slate-300 bg-slate-800 border border-slate-700 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        title="Re-run the widget: recompile and remount so mount-time data loads fire again"
                    >
                        <RefreshCw size={14} /> Reload
                    </button>
                </div>

                <div className="flex-1 relative overflow-hidden bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCI+CjxjaXJjbGUgY3g9IjIiIGN5PSIyIiByPSIxIiBmaWxsPSJyZ2JhKDI1NSwyNTUsMjU1LDAuMDMpIi8+Cjwvc3ZnPg==')]">
                    {viewMode === 'preview' ? (
                        <div className="absolute inset-0 p-8 overflow-auto w-full h-full flex items-start justify-center">
                            <div className="min-w-min min-h-min pb-16">
                                {previewError ? (
                                    <div className="w-full max-w-2xl bg-rose-950/40 border border-rose-900/50 rounded-xl p-6 text-rose-200">
                                        <div className="flex items-center gap-2 mb-4">
                                            <AlertCircle className="text-rose-500" size={24} />
                                            <h3 className="font-semibold text-lg">Compilation Error</h3>
                                        </div>
                                        <pre className="text-sm overflow-x-auto whitespace-pre-wrap p-4 bg-black/30 rounded-lg border border-rose-900/20">{previewError}</pre>
                                    </div>
                                ) : previewComponent ? (
                                    <div className="min-w-min min-h-min">
                                        <div
                                            id="widget-preview-capture-area"
                                            style={{
                                                // Assume ~80px width per grid column, ~60px height per row to give a rough feel for Grid layout.
                                                width: `${Math.max(300, defaultW * 80)}px`,
                                                height: `${Math.max(200, defaultH * 60)}px`,
                                                resize: 'both',
                                                overflow: 'auto'
                                            }}
                                            className="bg-gray-100 rounded-xl shadow-2xl overflow-hidden flex flex-col border border-gray-300 pb-1 pr-1"
                                        >
                                            <BaseWidget
                                                id="preview-widget"
                                                title={widgetName}
                                                helpText={widgetHelpText}
                                                className="h-full w-full"
                                                onConfigure={configMode !== 'none' ? () => setViewMode('config') : undefined}
                                                customActions={openInNewTabLink ? (
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            window.open(openInNewTabLink, '_blank');
                                                        }}
                                                        className="text-gray-400 hover:text-qualcomm-blue transition-colors"
                                                        title="Open in New Tab"
                                                    >
                                                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                                    </button>
                                                ) : undefined}
                                            >
                                                {/* */}
                                                <WidgetErrorBoundary
                                                    resetKey={previewComponent}
                                                    onReset={handleReloadPreview}
                                                    onError={(err) => {
                                                        // Its own budget, not the compile one: a render
                                                        // crash only happens *after* a successful
                                                        // compile, which resets that counter — so
                                                        // sharing it would mean no limit at all, and a
                                                        // widget that throws every render would
                                                        // generate, crash and generate again forever.
                                                        if (isGenerating || renderRetryCountRef.current >= MAX_AUTO_RETRIES) return;
                                                        renderRetryCountRef.current += 1;
                                                        setTimeout(() => handleGenerate(
                                                            err.message || String(err),
                                                            { errorKind: 'render' },
                                                        ), 1000);
                                                    }}
                                                >
                                                    <ExecuteActionPropInjector>
                                                        {React.createElement(previewComponent as any, {
                                                            id: "preview-widget",
                                                            data: {
                                                                dataSource: dataSource,
                                                                dataSourceType: dataSourceType,
                                                                ...(configSchema || []).reduce((acc, field) => {
                                                                    if (field.key) {
                                                                        // Attempt to map back to number if type is number, though string will usually suffice for preview
                                                                        acc[field.key] = field.type === 'number' && field.defaultValue ? Number(field.defaultValue) : field.defaultValue;
                                                                    }
                                                                    return acc;
                                                                }, {} as Record<string, any>),
                                                                username: username,
                                                                variables: variables,
                                                                setVariable: setVariable
                                                            }
                                                        })}
                                                    </ExecuteActionPropInjector>
                                                </WidgetErrorBoundary>
                                            </BaseWidget>
                                        </div>
                                        {/* Under the widget, because what it captures is the widget
                                            as drawn — including the resize the user just did. */}
                                        <div className="mt-3 flex items-center gap-2">
                                            <button
                                                onClick={handleInjectScreenshot}
                                                disabled={isCapturing || isUploading}
                                                title="Attach a picture of the widget as it looks now to your next message"
                                                className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium text-slate-300 bg-slate-800 border border-slate-700 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                            >
                                                {isCapturing
                                                    ? <Loader2 size={13} className="animate-spin" />
                                                    : <Camera size={13} />}
                                                {isCapturing ? 'Capturing…' : 'Send screenshot to agent'}
                                            </button>
                                            <span className="text-[11px] text-slate-500">
                                                Then describe what to change about what it sees.
                                            </span>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="w-full max-w-2xl bg-slate-800 rounded-xl border border-slate-700 p-8 shadow-2xl flex flex-col items-center justify-center gap-4 text-center">
                                        <RefreshCw size={32} className="text-indigo-500 mb-2 animate-spin" />
                                        <h3 className="text-lg font-medium text-slate-200">Evaluating Component...</h3>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : viewMode === 'code' ? (
                        <CodeEditor
                            className="absolute inset-0 bg-[#1e1e1e]"
                            language="tsx"
                            value={code}
                            onChange={handleCodeEdit}
                            ariaLabel="Widget TSX source"
                        />
                    ) : (
                        <div className="absolute inset-0 flex items-start justify-center p-8 overflow-y-auto w-full h-full">
                            <div className="w-full max-w-3xl bg-slate-800 border border-slate-700 rounded-xl p-8 shadow-xl space-y-6">
                                <h2 className="text-xl font-semibold text-slate-100 border-b border-slate-700 pb-4">Widget Configuration</h2>

                                <div className="grid grid-cols-2 gap-6">
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Widget Name</label>
                                        <input
                                            value={widgetName} onChange={e => { markSettingTouched('name'); setWidgetName(e.target.value); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Description</label>
                                        <textarea
                                            value={widgetDescription} onChange={e => { markSettingTouched('description'); setWidgetDescription(e.target.value); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-none h-24"
                                        />
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Help Text (Optional)</label>
                                        <textarea
                                            value={widgetHelpText} onChange={e => { markSettingTouched('helpText'); setWidgetHelpText(e.target.value); }}
                                            placeholder="Markdown supported. Provide instructions on how to use this widget."
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-none h-24"
                                        />
                                    </div>
                                    {taxonomyError && (
                                        <div className="col-span-2 flex items-start justify-between gap-4 bg-amber-950/40 border border-amber-800/60 rounded-lg px-3 py-2.5">
                                            <div className="text-xs text-amber-200">
                                                <p className="font-medium">Couldn't load categories and domains.</p>
                                                <p className="text-amber-300/80 mt-0.5">{taxonomyError}</p>
                                            </div>
                                            <button
                                                onClick={loadTaxonomy}
                                                disabled={isLoadingTaxonomy}
                                                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 bg-amber-900/60 hover:bg-amber-900 disabled:opacity-50 border border-amber-700/60 rounded-md text-xs text-amber-100"
                                            >
                                                <RefreshCw size={12} className={isLoadingTaxonomy ? 'animate-spin' : ''} /> Retry
                                            </button>
                                        </div>
                                    )}
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Category</label>
                                        <select
                                            value={widgetCategory === 'Custom' ? '' : widgetCategory} onChange={e => { markSettingTouched('category'); setWidgetCategory(e.target.value); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        >
                                            <option value="" disabled>{isLoadingTaxonomy ? 'Loading categories…' : 'Select a Category...'}</option>
                                            {availableCategories.map(c => (
                                                <option key={c} value={c}>{c}</option>
                                            ))}
                                            {/* If a widget already references a category that is no longer managed,
                                                still expose it so the editor can keep the selection. */}
                                            {widgetCategory && widgetCategory !== 'Custom' && !availableCategories.includes(widgetCategory) && (
                                                <option value={widgetCategory}>{widgetCategory} (legacy)</option>
                                            )}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Domain</label>
                                        <select
                                            value={widgetDomain === 'Custom' ? '' : widgetDomain} onChange={e => { markSettingTouched('domain'); setWidgetDomain(e.target.value); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        >
                                            <option value="" disabled>Select a Domain...</option>
                                            {availableDomains.map(d => (
                                                <option key={d} value={d}>{d}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Default Width (cols)</label>
                                        <input
                                            type="number" min="1" max="12"
                                            value={defaultW} onChange={e => { markSettingTouched('defaultW'); setDefaultW(parseInt(e.target.value)); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                        <p className="text-xs text-slate-500 mt-1">Grid width representation (1-12)</p>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Default Height (rows)</label>
                                        <input
                                            type="number" min="1" max="12"
                                            value={defaultH} onChange={e => { markSettingTouched('defaultH'); setDefaultH(parseInt(e.target.value)); }}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                        <p className="text-xs text-slate-500 mt-1">Grid height representation (1-12)</p>
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Data Source</label>
                                        <div className="flex gap-4 mb-4">
                                            {["none", "api", "databricks_api", "sql"].map(type => (
                                                <label key={type} className="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
                                                    <input
                                                        type="radio"
                                                        checked={dataSourceType === type}
                                                        onChange={() => {
                                                            setDataSourceType(type as any);
                                                            setDataSource("");
                                                            setDataSourceSchema(null);
                                                            setDataSourceTestError(null);
                                                        }}
                                                        className="text-indigo-600 focus:ring-indigo-500 bg-slate-900 border-slate-600"
                                                    />
                                                    {type === 'databricks_api' ? 'DATABRICKS API' : type.toUpperCase()}
                                                </label>
                                            ))}
                                        </div>

                                        {dataSourceType !== "none" && (
                                            <div className="space-y-4 p-4 border border-slate-600 rounded-lg bg-slate-800/50">
                                                <label className="block text-sm font-medium text-slate-300 mb-1.5">
                                                    {dataSourceType === 'api' ? 'API Endpoint URL' : dataSourceType === 'databricks_api' ? 'Databricks API Path' : 'SQL Query'}
                                                </label>
                                                {dataSourceType === 'api' || dataSourceType === 'databricks_api' ? (
                                                    <input
                                                        value={dataSource} onChange={e => setDataSource(e.target.value)}
                                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                        placeholder={dataSourceType === 'api' ? "https://api.example.com/data" : "/api/2.0/serving-endpoints/endpoint-name/invocations"}
                                                    />
                                                ) : (
                                                    <CodeEditor
                                                        value={dataSource}
                                                        onChange={setDataSource}
                                                        language="sql"
                                                        className="h-24 w-full rounded-lg border border-slate-600 bg-slate-900 focus-within:border-indigo-500"
                                                        placeholder="SELECT * FROM table_name LIMIT 10"
                                                        ariaLabel="SQL query"
                                                    />
                                                )}

                                                <button
                                                    onClick={handleTestDataSource}
                                                    disabled={isTestingDataSource || !dataSource}
                                                    className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors w-max"
                                                >
                                                    {isTestingDataSource ? <RefreshCw size={14} className="animate-spin" /> : <Code size={14} />}
                                                    Test & Extract Schema
                                                </button>

                                                {dataSourceTestError && (
                                                    <div className="p-3 bg-rose-900/30 border border-rose-800/50 rounded-lg text-rose-300 text-xs">
                                                        {dataSourceTestError}
                                                    </div>
                                                )}

                                                {dataSourceSchema && (
                                                    <div className="space-y-2">
                                                        <div className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
                                                            Schema Extracted Successfully!
                                                        </div>
                                                        <pre className="p-3 bg-slate-900 border border-slate-700 rounded-lg text-slate-300 text-xs overflow-x-auto">
                                                            {JSON.stringify(dataSourceSchema, null, 2)}
                                                        </pre>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div className="col-span-2">
                                        <label className="flex items-center gap-3 cursor-pointer p-3 bg-slate-900 border border-slate-600 rounded-lg hover:border-indigo-500 transition-colors">
                                            <input
                                                type="checkbox"
                                                checked={isExecutable}
                                                onChange={e => { markSettingTouched('isExecutable'); setIsExecutable(e.target.checked); }}
                                                className="w-5 h-5 rounded border-slate-500 bg-slate-800 text-indigo-600 focus:ring-indigo-500 focus:ring-opacity-25"
                                            />
                                            <div>
                                                <div className="text-sm font-medium text-slate-200">Is Executable Action</div>
                                                <div className="text-xs text-slate-400">Enable if this widget submits forms, triggers pipelines, or executes server actions.</div>
                                            </div>
                                        </label>
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Open in New Tab Link</label>
                                        <input
                                            type="url"
                                            value={openInNewTabLink}
                                            onChange={e => setOpenInNewTabLink(e.target.value)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                            placeholder="https://example.com"
                                        />
                                        <p className="text-xs text-slate-500 mt-1">If set, a button will appear in the widget header to open this link in a new tab.</p>
                                    </div>
                                    <div className="col-span-2 pt-4 border-t border-slate-700">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Configuration Mode</label>
                                        <select
                                            value={configMode}
                                            onChange={e => setConfigMode(e.target.value as any)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        >
                                            <option value="none">None (No custom user configurations)</option>
                                            <option value="config_allowed">Allowed (Users can configure properties)</option>
                                            <option value="config_required">Required (Users MUST configure before rendering)</option>
                                        </select>
                                        <p className="text-xs text-slate-500 mt-1">Allow users to provide dynamic configuration inputs to the widget.</p>
                                    </div>

                                    {configMode !== 'none' && (
                                        <div className="col-span-2 space-y-4">
                                            <div className="flex items-center justify-between">
                                                <label className="block text-sm font-medium text-slate-300">Configuration Schema</label>
                                                <button
                                                    onClick={() => setConfigSchema([...configSchema, { key: '', label: '', type: 'text' }])}
                                                    className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs font-medium transition-colors"
                                                >
                                                    <Plus size={14} /> Add Field
                                                </button>
                                            </div>

                                            {configSchema.length === 0 ? (
                                                <div className="text-sm text-slate-500 italic p-4 text-center border border-dashed border-slate-700 rounded-lg">
                                                    No configuration fields added. Click "Add Field" to begin.
                                                </div>
                                            ) : (
                                                <div className="space-y-4">
                                                    {configSchema.map((field, index) => (
                                                        <div key={index} className="p-4 bg-slate-900 border border-slate-700 rounded-lg flex flex-col gap-3 relative group">
                                                            <button
                                                                onClick={() => setConfigSchema(configSchema.filter((_, i) => i !== index))}
                                                                className="absolute top-2 right-2 p-1.5 text-slate-500 hover:text-rose-500 hover:bg-rose-500/10 rounded transition-colors opacity-0 group-hover:opacity-100"
                                                                title="Remove Field"
                                                            >
                                                                <Trash2 size={16} />
                                                            </button>

                                                            <div className="grid grid-cols-2 gap-4">
                                                                <div>
                                                                    <label className="block text-xs font-medium text-slate-400 mb-1">Key (camelCase)</label>
                                                                    <input
                                                                        value={field.key}
                                                                        onChange={e => {
                                                                            const newSchema = [...configSchema];
                                                                            newSchema[index] = { ...field, key: e.target.value };
                                                                            setConfigSchema(newSchema);
                                                                        }}
                                                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                                        placeholder="e.g. chartColor"
                                                                    />
                                                                </div>
                                                                <div>
                                                                    <label className="block text-xs font-medium text-slate-400 mb-1">Label (Display Name)</label>
                                                                    <input
                                                                        value={field.label}
                                                                        onChange={e => {
                                                                            const newSchema = [...configSchema];
                                                                            newSchema[index] = { ...field, label: e.target.value };
                                                                            setConfigSchema(newSchema);
                                                                        }}
                                                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                                        placeholder="e.g. Chart Color"
                                                                    />
                                                                </div>
                                                                <div>
                                                                    <label className="block text-xs font-medium text-slate-400 mb-1">Type</label>
                                                                    <select
                                                                        value={field.type}
                                                                        onChange={e => {
                                                                            const newSchema = [...configSchema];
                                                                            newSchema[index] = { ...field, type: e.target.value as any };
                                                                            setConfigSchema(newSchema);
                                                                        }}
                                                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                                    >
                                                                        <option value="text">Text / String</option>
                                                                        <option value="number">Number</option>
                                                                        <option value="textarea">Large Text (Textarea)</option>
                                                                    </select>
                                                                </div>
                                                                <div>
                                                                    <label className="block text-xs font-medium text-slate-400 mb-1">Default Value (Optional)</label>
                                                                    <input
                                                                        value={field.defaultValue || ''}
                                                                        onChange={e => {
                                                                            const newSchema = [...configSchema];
                                                                            newSchema[index] = { ...field, defaultValue: e.target.value };
                                                                            setConfigSchema(newSchema);
                                                                        }}
                                                                        className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                                        placeholder="Default string/num"
                                                                    />
                                                                </div>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {showHistory && (
                        <CodeHistoryPanel
                            checkpoints={checkpoints}
                            currentCode={code}
                            widgetId={editingId}
                            onRestore={restoreCode}
                            onClose={() => setShowHistory(false)}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
