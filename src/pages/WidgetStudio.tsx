import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Code, Eye, RefreshCw, Send, Save, AlertCircle, Settings, Plus, Trash2, Download, Upload, History, RotateCcw, X } from 'lucide-react';
import { toPng } from 'html-to-image';
import { loadCustomWidgets, getWidgetDomains, useWidgetRegistry } from '../widgetRegistry';
import type { ConfigField } from '../widgetRegistry';
import { useScript } from '../hooks/useScript';
import { BaseWidget } from '../components/BaseWidget';
import { CodeEditor } from '../components/CodeEditor';
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
    { children: React.ReactNode; onReset?: () => void; onError?: (error: Error) => void },
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

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

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

    const [messages, setMessages] = useState<{ role: 'user' | 'assistant' | 'system', content: string }[]>(sessionState?.messages || [{
        role: 'assistant',
        content: "Welcome to the Widget Studio! Briefly describe the widget you want to build."
    }]);

    const [prompt, setPrompt] = useState(sessionState?.prompt || "");
    const [isGenerating, setIsGenerating] = useState(false);
    const [isPublishing, setIsPublishing] = useState(false);
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
    const MAX_AUTO_RETRIES = 3;
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
    const isGeneratingRef = useRef(isGenerating);
    const previewErrorRef = useRef(previewError);

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
        setViewMode('code');
        setMessages(prev => [...prev, {
            role: 'system',
            content: `Restored ${description}. Nothing is published yet — press ${editingId ? 'Update' : 'Publish'} to keep it, or open History again to go back.`
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
                isExecutable, openInNewTabLink, dataSourceType, dataSource, dataSourceSchema, defaultW, defaultH, configMode, configSchema, editingId,
                checkpoints
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
        isExecutable, openInNewTabLink, dataSourceType, dataSource, dataSourceSchema, defaultW, defaultH, configMode, configSchema, editingId,
        checkpoints, editWidgetId, cloneWidgetId]);

    // Load existing widget data when editWidgetId or cloneWidgetId is provided
    useEffect(() => {
        const targetId = editWidgetId || cloneWidgetId;
        if (!targetId) return;
        fetch('/api/widgets/custom')
            .then(r => r.json())
            .then(data => {
                const w = data.widgets?.find((x: any) => x.id === targetId);
                if (!w) return;
                
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
        // A deliberate reload shouldn't consume the compile-error retry budget.
        autoRetryCountRef.current = 0;
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

    const handleGenerate = async (autoRetryError?: string) => {
        if (!prompt && !autoRetryError) return;

        // Captured before the box is cleared, to label the snapshot this turn leaves
        // behind with the request that caused it.
        const asked = prompt.trim().replace(/\s+/g, ' ');
        const checkpointLabel = autoRetryError
            ? 'Before an automatic compile fix'
            : `Before "${asked.length > 60 ? `${asked.slice(0, 57)}…` : asked}"`;

        let newMessages = [...messages];
        if (autoRetryError) {
            setMessages(prev => [...prev, { role: 'system', content: `Auto-retrying due to compilation error: ${autoRetryError}` }]);
            newMessages.push({ role: 'system', content: `Auto-retrying due to compilation error: ${autoRetryError}` });
        } else {
            newMessages.push({ role: 'user' as const, content: prompt });
            setMessages(newMessages);
            setPrompt("");
            // Clear any old preview errors on a fresh prompt
            setPreviewError(null);
            // A manual generate restarts the auto-retry budget.
            autoRetryCountRef.current = 0;
        }

        setIsGenerating(true);

        try {
            const resp = await fetch('/api/agent/widget/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt || "Please fix the compilation error in the code.",
                    history: messages.filter(m => m.role !== 'system'),
                    error_log: autoRetryError || previewError,
                    current_code: code,
                    data_source_schema: dataSourceSchema,
                    data_source: dataSourceType !== 'none' ? dataSource : null,
                    data_source_type: dataSourceType !== 'none' ? dataSourceType : null,
                    configuration_mode: configMode,
                    config_schema: dataSourceType !== 'none' ? [{ key: 'dataSource', label: 'Data Source', type: 'textarea' }, ...configSchema] : configSchema,
                    available_categories: availableCategories,
                    available_domains: availableDomains,
                    locked_settings: SETTING_KEYS.filter(k => touchedSettingsRef.current.has(k))
                })
            });

            const data = await resp.json();

            if (!resp.ok) {
                setMessages([...newMessages, { role: 'system', content: `Server Error: ${data.detail || resp.statusText}` }]);
                setIsGenerating(false);
                return;
            }

            if (data.job_id) {
                // Poll for completion
                const jobId = data.job_id;
                let pollCount = 0;
                
                const pollInterval = setInterval(async () => {
                    try {
                        pollCount++;
                        const statusResp = await fetch(`/api/agent/widget/generate/${jobId}`);
                        const statusData = await statusResp.json();

                        if (statusData.status === 'completed') {
                            clearInterval(pollInterval);
                            setIsGenerating(false);
                            
                            const result = statusData.result;
                            if (result.code) {
                                replaceCode(result.code, checkpointLabel);
                            }

                            setMessages([...newMessages, {
                                role: 'assistant',
                                content: describeGeneration(
                                    result,
                                    autoRetryError ? "I've attempted to fix the compilation error." : "Widget code generated."
                                )
                            }]);
                        } else if (statusData.status === 'failed') {
                            clearInterval(pollInterval);
                            setIsGenerating(false);
                            setMessages([...newMessages, { role: 'system', content: `Generation Error: ${statusData.error}` }]);
                        }
                        
                        // Failsafe timeout after 5 minutes (150 polls at 2s)
                        if (pollCount > 150) {
                            clearInterval(pollInterval);
                            setIsGenerating(false);
                            setMessages([...newMessages, { role: 'system', content: `Generation timed out on server.` }]);
                        }
                    } catch (pollErr) {
                        clearInterval(pollInterval);
                        setIsGenerating(false);
                        setMessages([...newMessages, { role: 'system', content: `Polling Error: ${pollErr}` }]);
                    }
                }, 2000);
            } else if (data.code) {
                // Fallback if backend hasn't updated yet or returns directly
                replaceCode(data.code, checkpointLabel);
                setMessages([...newMessages, {
                    role: 'assistant',
                    content: describeGeneration(
                        data,
                        autoRetryError ? "I've attempted to fix the compilation error." : "Widget code generated."
                    )
                }]);
                setIsGenerating(false);
            }
        } catch (e) {
            setMessages([...newMessages, { role: 'system', content: `Network Error: ${e}` }]);
            setIsGenerating(false);
        }
    };

    // Kept current for the compile effect above, which reads them through refs so it
    // isn't re-run by anything but a code change.
    useEffect(() => {
        generateRef.current = handleGenerate;
        isGeneratingRef.current = isGenerating;
        previewErrorRef.current = previewError;
    });

    const handlePublish = async () => {
        if (!widgetName.trim()) {
            alert('Please provide a Widget Name before publishing.');
            setViewMode('config');
            return;
        }
        if (!widgetDescription.trim()) {
            alert('Please provide a Description before publishing.');
            setViewMode('config');
            return;
        }
        if (!widgetCategory || widgetCategory === 'Custom') {
            alert('Please select a Category before publishing.');
            setViewMode('config');
            return;
        }
        if (!widgetDomain || widgetDomain.toLowerCase() === 'custom') {
            alert('Please select a Domain before publishing.');
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
                alert(isEditing
                    ? `"${widgetName}" updated! Changes are live in the Widget Library.`
                    : `"${widgetName}" published! Open the Widget Library (press W) to find it.`
                );
                
                // If it was a new publish, update editingId so subsequent publishes are updates
                if (!isEditing && responseData?.id) {
                    setEditingId(responseData.id);
                }
                
                // Clear session storage upon successful publish/update to avoid carrying state over for new widgets
                sessionStorage.removeItem(WIDGET_STUDIO_SESSION_KEY);
                if (isEditing) onClose?.();
            } else {
                const err = responseData || await res.json().catch(() => ({ detail: res.statusText }));
                alert(`Failed to ${isEditing ? 'update' : 'publish'} widget: ${err.detail || res.statusText}`);
            }
        } catch (err) {
            alert(`Error: ${err}`);
        } finally {
            setIsPublishing(false);
        }
    };

    const handleTestDataSource = async () => {
        if (dataSourceType === "none" || !dataSource) return;
        setIsTestingDataSource(true);
        setDataSourceTestError(null);
        setDataSourceSchema(null);
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
            } else {
                setDataSourceTestError(data.detail || "Error testing data source");
            }
        } catch (err: any) {
            setDataSourceTestError(err.message || String(err));
        } finally {
            setIsTestingDataSource(false);
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
                            {isPublishing ? (editingId ? 'Updating...' : 'Publishing...') : (editingId ? 'Update' : 'Publish')}
                        </button>
                    </div>
                </div>

                {/* Chat History */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((m, i) => (
                        <div key={i} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className={`max-w-[85%] rounded-lg p-3 text-sm shadow-sm ${m.role === 'user' ? 'bg-indigo-600 text-white rounded-br-none' :
                                m.role === 'system' ? 'bg-slate-700/50 text-slate-300 border border-slate-600/50 rounded-bl-none' :
                                    'bg-slate-700 text-slate-200 rounded-bl-none border border-slate-600'
                                }`}>
                                <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-li:my-0">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {m.content}
                                    </ReactMarkdown>
                                </div>
                            </div>
                        </div>
                    ))}
                    {isGenerating && (
                        <div className="flex items-start">
                            <div className="bg-slate-700 text-slate-400 rounded-lg p-3 rounded-bl-none text-sm border border-slate-600 flex items-center gap-2">
                                <RefreshCw size={14} className="animate-spin" />
                                Generating widget...
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
                        </div>
                    )}
                    <div className="flex border border-slate-600 rounded-md bg-slate-900 focus-within:border-indigo-500 ring-1 focus-within:ring-indigo-500 overflow-hidden transition-all shadow-inner items-end">
                        <textarea
                            className="flex-1 bg-transparent border-none px-4 py-3 text-sm focus:outline-none text-slate-200 placeholder-slate-500 resize-none min-h-[44px] max-h-32 overflow-hidden"
                            placeholder="Create a bar chart showing total sales..."
                            value={prompt}
                            onChange={e => {
                                setPrompt(e.target.value);
                                e.target.style.height = 'auto';
                                e.target.style.height = `${e.target.scrollHeight}px`;
                            }}
                            onKeyDown={e => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleGenerate();
                                    // Reset height on submit
                                    e.currentTarget.style.height = 'auto';
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
                                                    onReset={() => setPreviewComponent(null)}
                                                    onError={(err) => {
                                                        if (!isGenerating) {
                                                            setTimeout(() => handleGenerate(err.message || String(err)), 1000);
                                                        }
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
