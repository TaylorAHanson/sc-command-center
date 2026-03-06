import React, { useState, useEffect, useMemo } from 'react';
import { Award, RefreshCw, Search, Filter, MailPlus, Eye, X, ChevronDown, AlertCircle } from 'lucide-react';
import { useScript } from '../../hooks/useScript';
import { ConfirmModal } from '../../components/ConfirmModal';

interface Widget {
    id: string;
    name: string;
    version: number;
    description: string;
    domain: string;
    category: string;
    created_by: string;
    timestamp: string;
    is_certified: boolean;
    tsx_code?: string;
}

interface ConsolidatedWidget {
    id: string;
    name: string;
    domain: string;
    description: string;
    is_certified: boolean;
    dev?: Widget;
    test?: Widget;
    prod?: Widget;
    maxVersion: number;
    latestAuthor: string;
    latestTimestamp: string;
}

// ─── Live Widget Renderer ────────────────────────────────────────────────────
class WidgetErrorBoundary extends React.Component<
    { children: React.ReactNode },
    { hasError: boolean; error: string | null }
> {
    constructor(props: any) {
        super(props);
        this.state = { hasError: false, error: null };
    }
    static getDerivedStateFromError(error: Error) {
        return { hasError: true, error: error.message };
    }
    render() {
        if (this.state.hasError) {
            return (
                <div className="flex flex-col items-center justify-center h-full p-4 text-center bg-rose-50">
                    <AlertCircle className="text-rose-400 mb-2" size={28} />
                    <p className="text-xs text-rose-600 font-medium">Render error</p>
                    <pre className="mt-2 text-[10px] text-rose-500 whitespace-pre-wrap max-w-full overflow-auto">{this.state.error}</pre>
                </div>
            );
        }
        return this.props.children;
    }
}

const LiveWidgetRenderer: React.FC<{ tsxCode: string }> = ({ tsxCode }) => {
    const [babelLoaded] = useScript(
        'https://unpkg.com/@babel/standalone/babel.min.js',
        'Babel'
    );
    const [Component, setComponent] = useState<React.ComponentType<any> | null>(null);
    const [compileError, setCompileError] = useState<string | null>(null);

    useEffect(() => {
        if (!babelLoaded) return;
        try {
            setCompileError(null);
            // @ts-ignore
            const transpiled = window.Babel.transform(tsxCode, {
                filename: 'widget.tsx',
                presets: ['react', 'typescript']
            }).code;
            const executableCode = transpiled
                .replace(/export\s+default\s+(function|class)/, 'return $1')
                .replace(/export\s+default\s+/, 'return ');
            // @ts-ignore
            const HC = typeof Highcharts !== 'undefined' ? Highcharts : (window as any).Highcharts;
            // eslint-disable-next-line no-new-func
            const createComp = new Function('React', 'useScript', 'Highcharts', executableCode);
            const Comp = createComp(React, useScript, HC);
            setComponent(() => Comp);
        } catch (err: any) {
            setCompileError(err.message || String(err));
            setComponent(null);
        }
    }, [tsxCode, babelLoaded]);

    if (!babelLoaded) {
        return <div className="flex items-center justify-center h-full text-xs text-gray-400">Loading compiler…</div>;
    }
    if (compileError) {
        return (
            <div className="flex flex-col items-center justify-center h-full p-4 text-center bg-rose-50">
                <AlertCircle className="text-rose-400 mb-2" size={28} />
                <p className="text-xs text-rose-600 font-medium">Compile error</p>
                <pre className="mt-2 text-[10px] text-rose-500 whitespace-pre-wrap max-w-full overflow-auto">{compileError}</pre>
            </div>
        );
    }
    if (!Component) {
        return <div className="flex items-center justify-center h-full text-xs text-gray-400">Compiling…</div>;
    }
    return (
        <WidgetErrorBoundary>
            <Component id="admin-preview" data={{}} />
        </WidgetErrorBoundary>
    );
};

// ─── Version History Modal ─────────────────────────────────────────────────
interface VersionEntry {
    version: number;
    name: string;
    author: string;
    timestamp: string;
    env: string;
}

const VersionHistoryModal: React.FC<{
    entityId: string;
    entityName: string;
    historyUrl: (env: string) => string;
    authorField: string; // 'created_by' for widgets, 'username' for views
    onClose: () => void;
}> = ({ entityId, entityName, historyUrl, authorField, onClose }) => {
    const [history, setHistory] = useState<VersionEntry[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            setLoading(true);
            const envs: string[] = ['dev', 'test', 'prod'];
            const results = await Promise.all(
                envs.map(async env => {
                    try {
                        const res = await fetch(historyUrl(env));
                        if (!res.ok) return [];
                        const data = await res.json();
                        return (data.history || []).map((h: any) => ({
                            version: h.version,
                            name: h.name,
                            author: h[authorField] || '—',
                            timestamp: h.timestamp,
                            env
                        }));
                    } catch { return []; }
                })
            );
            // Merge and deduplicate by env+version, newest first
            const merged = results.flat().sort((a, b) => {
                if (b.version !== a.version) return b.version - a.version;
                return ['prod', 'test', 'dev'].indexOf(a.env) - ['prod', 'test', 'dev'].indexOf(b.env);
            });
            setHistory(merged);
            setLoading(false);
        };
        load();
    }, [entityId]);

    const envColors: Record<string, string> = {
        dev: 'bg-blue-100 text-blue-700',
        test: 'bg-purple-100 text-purple-700',
        prod: 'bg-green-100 text-green-700',
    };

    const formatTs = (ts: string) => {
        try { return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
        catch { return ts; }
    };

    const getAction = (env: string, version: number) => {
        if (env === 'dev' && version === 1) return { label: 'Created', cls: 'bg-gray-100 text-gray-600' };
        if (env === 'dev') return { label: 'Modified', cls: 'bg-amber-100 text-amber-700' };
        if (env === 'test') return { label: 'Promoted to Test', cls: 'bg-purple-100 text-purple-700' };
        if (env === 'prod') return { label: 'Promoted to Prod', cls: 'bg-green-100 text-green-700' };
        return { label: 'Updated', cls: 'bg-gray-100 text-gray-600' };
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                    <div>
                        <h2 className="text-lg font-bold text-gray-900">Version History</h2>
                        <p className="text-sm text-gray-500 mt-0.5">{entityName}</p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition rounded p-1">
                        <X size={20} />
                    </button>
                </div>
                <div className="flex-1 overflow-auto p-4">
                    {loading ? (
                        <div className="flex items-center justify-center py-10 text-gray-400 text-sm">Loading history…</div>
                    ) : history.length === 0 ? (
                        <div className="flex items-center justify-center py-10 text-gray-400 text-sm">No version history found.</div>
                    ) : (
                        <div className="relative">
                            {/* Timeline line */}
                            <div className="absolute left-[7px] top-2 bottom-2 w-0.5 bg-gray-200" />
                            <ul className="space-y-4 pl-6">
                                {history.map((h, i) => (
                                    <li key={`${h.env}-${h.version}-${i}`} className="relative">
                                        {/* Dot */}
                                        <div className="absolute -left-6 top-1.5 w-3.5 h-3.5 rounded-full border-2 border-white bg-gray-400 ring-2 ring-gray-200" />
                                        <div className="bg-gray-50 rounded-lg px-4 py-3 border border-gray-100">
                                            <div className="flex items-center gap-2 mb-1.5">
                                                <span className="font-mono text-xs font-semibold text-gray-700">v{h.version}</span>
                                                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${envColors[h.env]}`}>{h.env}</span>
                                                {(() => { const a = getAction(h.env, h.version); return <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${a.cls}`}>{a.label}</span>; })()}
                                            </div>
                                            <div className="text-xs text-gray-500">
                                                <span className="font-medium text-gray-700">{h.author}</span>
                                                <span className="mx-1">·</span>
                                                <span>{formatTs(h.timestamp)}</span>
                                            </div>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

// ─── Shared select helpers ─────────────────────────────────────────────────
const EnvVersionSelect: React.FC<{
    currentVersion: number;
    maxVersion: number;
    onChange: (v: number) => void;
    disabled?: boolean;
}> = ({ currentVersion, maxVersion, onChange, disabled }) => {
    const options = Array.from({ length: maxVersion }, (_, i) => i + 1);
    return (
        <div className="relative inline-block">
            <select
                value={currentVersion}
                disabled={disabled}
                onChange={(e) => onChange(parseInt(e.target.value))}
                className="appearance-none w-32 py-1.5 pl-3 pr-8 text-sm font-mono border border-gray-300 bg-white rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-qualcomm-blue disabled:opacity-50 disabled:cursor-not-allowed"
            >
                <option value={0}>None</option>
                {options.map(v => (
                    <option key={v} value={v}>v{v}</option>
                ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-gray-400">
                <ChevronDown size={14} />
            </div>
        </div>
    );
};

// Preview Modal
const PreviewModal: React.FC<{
    widget: ConsolidatedWidget;
    onClose: () => void;
}> = ({ widget, onClose }) => {
    const [previewVersion, setPreviewVersion] = useState<number>(
        widget.prod?.version ?? widget.test?.version ?? widget.dev?.version ?? widget.maxVersion
    );

    const allVersionWidgets: { [v: number]: Widget } = {};
    [widget.dev, widget.test, widget.prod].forEach(w => {
        if (w) allVersionWidgets[w.version] = w;
    });

    const selectedWidget = allVersionWidgets[previewVersion];
    const options = Object.keys(allVersionWidgets).map(Number).sort((a, b) => a - b);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                    <div>
                        <h2 className="text-lg font-bold text-gray-900">{widget.name}</h2>
                        <p className="text-sm text-gray-500 mt-0.5">{widget.description}</p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition rounded-md p-1">
                        <X size={20} />
                    </button>
                </div>

                {/* Version Selector */}
                <div className="px-6 py-3 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
                    <span className="text-sm font-medium text-gray-600">Preview version:</span>
                    <div className="relative inline-block">
                        <select
                            value={previewVersion}
                            onChange={e => setPreviewVersion(parseInt(e.target.value))}
                            className="appearance-none w-32 py-1.5 pl-3 pr-8 text-sm font-mono border border-gray-300 bg-white rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
                        >
                            {options.map(v => (
                                <option key={v} value={v}>v{v}</option>
                            ))}
                        </select>
                        <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-gray-400">
                            <ChevronDown size={14} />
                        </div>
                    </div>
                    {selectedWidget && (
                        <span className="text-xs text-gray-400 ml-auto">
                            by {selectedWidget.created_by} · {new Date(selectedWidget.timestamp).toLocaleDateString()}
                        </span>
                    )}
                </div>

                {/* Live preview */}
                <div className="flex-1 overflow-hidden bg-gray-100 p-4 min-h-[360px]">
                    {selectedWidget?.tsx_code ? (
                        <div className="bg-white rounded-lg border border-gray-200 h-full overflow-hidden flex flex-col">
                            <div className="flex-1 overflow-auto p-4">
                                <LiveWidgetRenderer tsxCode={selectedWidget.tsx_code} />
                            </div>
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-full text-sm text-gray-400">
                            No source code available for this version.
                        </div>
                    )}
                </div>

                {/* Metadata footer */}
                <div className="px-6 py-3 bg-gray-50 border-t border-gray-200 flex gap-6 text-xs text-gray-500">
                    <span><span className="font-medium text-gray-600">Category:</span> {selectedWidget?.category || '—'}</span>
                    <span><span className="font-medium text-gray-600">Domain:</span> {selectedWidget?.domain || '—'}</span>
                    {!!selectedWidget?.is_certified && (
                        <span className="flex items-center gap-1 text-green-700">
                            <Award size={11} /> Certified
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};

export const WidgetManager: React.FC = () => {
    const [devWidgets, setDevWidgets] = useState<Widget[]>([]);
    const [testWidgets, setTestWidgets] = useState<Widget[]>([]);
    const [prodWidgets, setProdWidgets] = useState<Widget[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDomain, setSelectedDomain] = useState('All');
    const [previewWidget, setPreviewWidget] = useState<ConsolidatedWidget | null>(null);
    const [historyWidget, setHistoryWidget] = useState<ConsolidatedWidget | null>(null);

    // Pending confirmation state
    const [pendingTransfer, setPendingTransfer] = useState<{
        widgetId: string; widgetName: string; targetVersion: number;
        targetEnv: 'dev' | 'test' | 'prod'; envsData: ConsolidatedWidget; action: string;
    } | null>(null);
    const [pendingCertify, setPendingCertify] = useState<{ widgetId: string; version: number; name: string } | null>(null);

    const isPromoter = true;

    const consolidatedWidgets = useMemo<ConsolidatedWidget[]>(() => {
        const map = new Map<string, ConsolidatedWidget>();

        const process = (widgets: Widget[], env: 'dev' | 'test' | 'prod') => {
            widgets.forEach(w => {
                if (!map.has(w.id)) {
                    map.set(w.id, {
                        id: w.id,
                        name: w.name,
                        domain: w.domain,
                        description: w.description,
                        is_certified: w.is_certified,
                        maxVersion: w.version,
                        latestAuthor: w.created_by,
                        latestTimestamp: w.timestamp,
                    });
                }
                const entry = map.get(w.id)!;
                entry[env] = w;
                if (w.version > entry.maxVersion) {
                    entry.maxVersion = w.version;
                    entry.latestAuthor = w.created_by;
                    entry.latestTimestamp = w.timestamp;
                }
                if (env === 'prod' || (!entry.prod && env === 'test') || (!entry.prod && !entry.test && env === 'dev')) {
                    entry.name = w.name;
                    entry.domain = w.domain;
                    entry.description = w.description;
                    entry.is_certified = w.is_certified || entry.is_certified;
                }
            });
        };

        process(devWidgets, 'dev');
        process(testWidgets, 'test');
        process(prodWidgets, 'prod');

        return Array.from(map.values());
    }, [devWidgets, testWidgets, prodWidgets]);

    const allDomains = useMemo(() => {
        const domains = new Set<string>();
        consolidatedWidgets.forEach(w => domains.add(w.domain));
        return ['All', ...Array.from(domains).sort()];
    }, [consolidatedWidgets]);

    const filteredWidgets = useMemo(() => {
        return consolidatedWidgets.filter(w => {
            const matchesSearch = w.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                w.description.toLowerCase().includes(searchQuery.toLowerCase());
            const matchesDomain = selectedDomain === 'All' || w.domain === selectedDomain;
            return matchesSearch && matchesDomain;
        });
    }, [consolidatedWidgets, searchQuery, selectedDomain]);

    const fetchWidgets = async (env: string) => {
        try {
            const res = await fetch(`/api/widgets/custom?env=${env}`);
            const data = await res.json();
            return data.widgets || [];
        } catch (e) {
            console.error(`Error fetching ${env} widgets:`, e);
            return [];
        }
    };

    const loadAll = async () => {
        setLoading(true);
        const [dev, test, prod] = await Promise.all([
            fetchWidgets('dev'),
            fetchWidgets('test'),
            fetchWidgets('prod')
        ]);
        setDevWidgets(dev);
        setTestWidgets(test);
        setProdWidgets(prod);
        setLoading(false);
    };

    useEffect(() => { loadAll(); }, []);

    const handleVersionChange = async (widgetId: string, widgetName: string, targetVersion: number, targetEnv: 'dev' | 'test' | 'prod', envsData: ConsolidatedWidget) => {
        const currentVersion = envsData[targetEnv] ? envsData[targetEnv]!.version : 0;
        if (targetVersion === currentVersion) return;

        const action = targetVersion > currentVersion ? 'promote' : 'rollback';

        setPendingTransfer({ widgetId, widgetName, targetVersion, targetEnv, envsData, action });
    };

    const executeTransfer = async () => {
        if (!pendingTransfer) return;
        const { widgetId, targetVersion, targetEnv, envsData } = pendingTransfer;
        let sourceEnv: 'dev' | 'test' | 'prod' = 'dev';
        if (envsData.dev && envsData.dev.version >= targetVersion) sourceEnv = 'dev';
        else if (envsData.test && envsData.test.version >= targetVersion) sourceEnv = 'test';
        else if (envsData.prod && envsData.prod.version >= targetVersion) sourceEnv = 'prod';
        setPendingTransfer(null);
        try {
            const res = await fetch('/api/promotion/transfer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: widgetId, version: targetVersion, source_env: sourceEnv, target_env: targetEnv, is_rollback: pendingTransfer?.action === 'rollback' })
            });
            if (res.ok) { loadAll(); }
            else { const data = await res.json(); alert(`Error: ${data.detail || data.message}`); loadAll(); }
        } catch (e) {
            console.error('Transfer error:', e);
            alert('An error occurred during transfer.');
            loadAll();
        }
    };

    const handleCertify = async (widgetId: string, version: number, name: string) => {
        setPendingCertify({ widgetId, version, name });
    };

    const executeCertify = async () => {
        if (!pendingCertify) return;
        const { widgetId, version } = pendingCertify;
        setPendingCertify(null);
        try {
            const res = await fetch('/api/promotion/certify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: widgetId, version })
            });
            if (res.ok) loadAll();
            else { const data = await res.json(); alert(`Error: ${data.detail || data.message}`); }
        } catch (e) {
            console.error('Certify error:', e);
            alert('An error occurred during certification.');
        }
    };

    const handleRequestPromotion = (widgetName: string, target: string) => {
        alert(`Promotion request for '${widgetName}' to ${target.toUpperCase()} has been submitted.`);
    };

    const renderVersionCell = (w: ConsolidatedWidget, env: 'dev' | 'test' | 'prod') => {
        const currentVersion = w[env]?.version ?? 0;

        if (!isPromoter) {
            return (
                <div className="flex items-center gap-2">
                    <span className="px-2 py-1 bg-gray-100 rounded-md font-mono text-xs">
                        {currentVersion > 0 ? `v${currentVersion}` : 'None'}
                    </span>
                    {env !== 'dev' && w.dev && currentVersion < w.maxVersion && (
                        <button onClick={() => handleRequestPromotion(w.name, env)} className="text-xs p-1 text-gray-500 hover:text-qualcomm-blue" title="Request Promotion">
                            <MailPlus size={14} />
                        </button>
                    )}
                </div>
            );
        }

        return (
            <div className="flex flex-col gap-1.5">
                <EnvVersionSelect
                    currentVersion={currentVersion}
                    maxVersion={w.maxVersion}
                    onChange={(v) => handleVersionChange(w.id, w.name, v, env, w)}
                />
                {env === 'prod' && isPromoter && w.prod && !w.is_certified && (
                    <button
                        onClick={() => handleCertify(w.id, w.prod!.version, w.name)}
                        className="text-[11px] px-2 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded hover:bg-green-100 transition flex items-center gap-1 w-fit"
                    >
                        <Award size={11} /> Certify
                    </button>
                )}
            </div>
        );
    };

    const formatDate = (ts: string) => {
        if (!ts) return '—';
        try { return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); }
        catch { return ts; }
    };

    return (
        <div className="h-full flex flex-col bg-gray-50">
            <div className="p-6 border-b border-gray-200 bg-white flex justify-between items-center shrink-0">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Widget Promotion</h1>
                    <p className="text-sm text-gray-500 mt-1">Manage widget lifecycles across Dev, Test, and Prod.</p>
                </div>
                <button onClick={loadAll} className="p-2 text-gray-500 hover:text-qualcomm-blue hover:bg-blue-50 rounded-md transition" title="Refresh">
                    <RefreshCw size={20} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div className="bg-white border-b border-gray-200 px-6 py-3 flex flex-col sm:flex-row gap-3">
                <div className="relative flex-1 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                    <input
                        type="text"
                        placeholder="Search widgets..."
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        className="w-full pl-9 pr-4 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <Filter size={16} className="text-gray-500" />
                    <div className="relative inline-block">
                        <select
                            value={selectedDomain}
                            onChange={e => setSelectedDomain(e.target.value)}
                            className="appearance-none py-1.5 pl-3 pr-8 border border-gray-300 rounded-md focus:ring-2 focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                        >
                            {allDomains.map(d => <option key={d} value={d}>{d}</option>)}
                        </select>
                        <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-gray-400">
                            <ChevronDown size={14} />
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex-1 p-6 overflow-hidden">
                <div className="bg-white border border-gray-200 rounded-lg overflow-hidden flex flex-col h-full">
                    <div className="flex-1 overflow-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50 sticky top-0 shadow-sm z-10">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Widget</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Domain</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Last Modified</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Author</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-blue-50/60">Dev</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-purple-50/60">Test</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-green-50/60">Prod</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Preview</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">History</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {filteredWidgets.length === 0 ? (
                                    <tr><td colSpan={9} className="px-6 py-10 text-center text-sm text-gray-400">No widgets found.</td></tr>
                                ) : (
                                    filteredWidgets.map(w => (
                                        <tr key={w.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-2">
                                                    <div className="font-medium text-sm text-gray-900">{w.name}</div>
                                                    {!!w.is_certified && (
                                                        <span className="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-700 rounded-full flex items-center gap-1 font-medium">
                                                            <Award size={10} /> Certified
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="text-xs text-gray-400 mt-0.5 max-w-[200px] truncate">{w.description}</div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <span className="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">{w.domain}</span>
                                            </td>
                                            <td className="px-4 py-4 text-xs text-gray-500 whitespace-nowrap">{formatDate(w.latestTimestamp)}</td>
                                            <td className="px-4 py-4 text-xs text-gray-500">{w.latestAuthor || '—'}</td>
                                            <td className="px-4 py-4 bg-blue-50/20">{renderVersionCell(w, 'dev')}</td>
                                            <td className="px-4 py-4 bg-purple-50/20">{renderVersionCell(w, 'test')}</td>
                                            <td className="px-4 py-4 bg-green-50/20">{renderVersionCell(w, 'prod')}</td>
                                            <td className="px-4 py-4">
                                                <button
                                                    onClick={() => setPreviewWidget(w)}
                                                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-100 hover:border-gray-300 transition"
                                                >
                                                    <Eye size={13} /> Preview
                                                </button>
                                            </td>
                                            <td className="px-4 py-4">
                                                <button
                                                    onClick={() => setHistoryWidget(w)}
                                                    className="text-xs text-qualcomm-blue hover:underline whitespace-nowrap"
                                                >
                                                    Version History
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            {/* colSpan must match 9 cols now */}
            {previewWidget && <PreviewModal widget={previewWidget} onClose={() => setPreviewWidget(null)} />}
            {historyWidget && (
                <VersionHistoryModal
                    entityId={historyWidget.id}
                    entityName={historyWidget.name}
                    historyUrl={(env) => `/api/widgets/history?widget_id=${historyWidget.id}&env=${env}`}
                    authorField="created_by"
                    onClose={() => setHistoryWidget(null)}
                />
            )}
            {pendingTransfer && (() => {
                const isRollback = pendingTransfer.action === 'rollback';
                return (
                    <ConfirmModal
                        title={isRollback ? 'Roll Back Widget' : 'Promote Widget'}
                        message={
                            isRollback
                                ? `Roll back '${pendingTransfer.widgetName}' in ${pendingTransfer.targetEnv.toUpperCase()} to v${pendingTransfer.targetVersion}?`
                                : `Promote '${pendingTransfer.widgetName}' to v${pendingTransfer.targetVersion} in ${pendingTransfer.targetEnv.toUpperCase()}?`
                        }
                        confirmLabel={isRollback ? `Roll Back to v${pendingTransfer.targetVersion}` : 'Promote'}
                        variant={isRollback ? 'warning' : 'primary'}
                        onConfirm={executeTransfer}
                        onCancel={() => { setPendingTransfer(null); loadAll(); }}
                    />
                );
            })()}
            {pendingCertify && (
                <ConfirmModal
                    title="Certify Widget"
                    message={`Mark '${pendingCertify.name}' v${pendingCertify.version} as Enterprise Ready?`}
                    detail="This widget will be flagged as certified and visible to all users as enterprise-grade."
                    confirmLabel="Certify"
                    variant="primary"
                    onConfirm={executeCertify}
                    onCancel={() => setPendingCertify(null)}
                />
            )}
        </div>
    );
};
