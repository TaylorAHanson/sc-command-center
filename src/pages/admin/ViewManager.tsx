import React, { useState, useEffect, useMemo } from 'react';
import { RefreshCw, Search, Filter, MailPlus, Plus, X, ChevronDown, Eye, Trash2, Archive, ArchiveRestore } from 'lucide-react';
import { useDashboardStore } from '../../store/dashboardStore';
import { ConfirmModal } from '../../components/ConfirmModal';

interface View {
    id: string;
    version: number;
    name: string;
    domain: string;
    username: string;
    is_global: boolean;
    is_locked: boolean;
    timestamp: string;
}

interface ConsolidatedView {
    id: string;
    name: string;
    domain: string;
    is_global: boolean;
    dev?: View;
    test?: View;
    prod?: View;
    maxVersion: number;
    latestAuthor: string;
    latestTimestamp: string;
}

type Env = 'dev' | 'test' | 'prod';
const ENVS: Env[] = ['dev', 'test', 'prod'];

interface ArchivedRow {
    id: string;
    name: string;
    domain: string;
    archived_by: string | null;
    archived_at: string | null;
}

// An archived view, gathered across environments. `envs` is where it is archived,
// which is where Restore and Delete have to be sent: the server will only delete
// a global view that is archived in the environment it is asked about.
interface ArchivedView extends ArchivedRow {
    envs: Env[];
}

const ENV_COLORS: Record<string, string> = {
    dev: 'bg-blue-100 text-blue-700',
    test: 'bg-purple-100 text-purple-700',
    prod: 'bg-green-100 text-green-700',
};

const ViewHistoryModal: React.FC<{ view: ConsolidatedView; onClose: () => void }> = ({ view, onClose }) => {
    const [entries, setEntries] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            setLoading(true);
            const envs = ['dev', 'test', 'prod'] as const;
            const results = await Promise.all(
                envs.map(async env => {
                    try {
                        const res = await fetch(`/api/views/history?view_id=${view.id}&env=${env}`);
                        if (!res.ok) return [];
                        const data = await res.json();
                        return (data.history || []).map((h: any) => ({ ...h, author: h.username || '—', env }));
                    } catch { return []; }
                })
            );
            setEntries(results.flat().sort((a, b) => b.version - a.version));
            setLoading(false);
        };
        load();
    }, [view.id]);

    const fmtTs = (ts: string) => {
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
                        <p className="text-sm text-gray-500 mt-0.5">{view.name}</p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition rounded p-1"><X size={20} /></button>
                </div>
                <div className="flex-1 overflow-auto p-4">
                    {loading ? (
                        <div className="flex items-center justify-center py-10 text-gray-400 text-sm">Loading history…</div>
                    ) : entries.length === 0 ? (
                        <div className="flex items-center justify-center py-10 text-gray-400 text-sm">No version history found.</div>
                    ) : (
                        <div className="relative">
                            <div className="absolute left-[7px] top-2 bottom-2 w-0.5 bg-gray-200" />
                            <ul className="space-y-4 pl-6">
                                {entries.map((h, i) => (
                                    <li key={`${h.env}-${h.version}-${i}`} className="relative">
                                        <div className="absolute -left-6 top-1.5 w-3.5 h-3.5 rounded-full border-2 border-white bg-gray-400 ring-2 ring-gray-200" />
                                        <div className="bg-gray-50 rounded-lg px-4 py-3 border border-gray-100">
                                            <div className="flex items-center gap-2 mb-1.5">
                                                <span className="font-mono text-xs font-semibold text-gray-700">v{h.version}</span>
                                                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${ENV_COLORS[h.env]}`}>{h.env}</span>
                                                {(() => { const a = getAction(h.env, h.version); return <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${a.cls}`}>{a.label}</span>; })()}
                                            </div>
                                            <div className="text-xs text-gray-500">
                                                <span className="font-medium text-gray-700">{h.author}</span>
                                                <span className="mx-1">·</span>
                                                <span>{fmtTs(h.timestamp)}</span>
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

export const ViewManager: React.FC = () => {
    const [devViews, setDevViews] = useState<View[]>([]);
    const [testViews, setTestViews] = useState<View[]>([]);
    const [prodViews, setProdViews] = useState<View[]>([]);
    const [archivedByEnv, setArchivedByEnv] = useState<Record<Env, ArchivedRow[]>>({ dev: [], test: [], prod: [] });
    const [showArchived, setShowArchived] = useState(false);
    const [pendingRemoval, setPendingRemoval] = useState<
        { kind: 'archive'; view: ConsolidatedView } | { kind: 'delete'; view: ArchivedView } | null
    >(null);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDomain, setSelectedDomain] = useState('All');

    // Dashboard store to trigger sidebar reloads
    const { fetchViews: refreshGlobalSidebar, isAdmin, domainPermissions } = useDashboardStore();

    // Modal state
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [newViewName, setNewViewName] = useState('');
    const [newViewDomain, setNewViewDomain] = useState('General');
    const [isCreating, setIsCreating] = useState(false);
    // The domains a global view may be filed under: the taxonomy's, narrowed to
    // those this user can edit (the same check `POST /api/views/` makes). This was
    // a hardcoded list that had drifted from the taxonomy — it offered
    // "Manufacturing" and "Finance" whether or not they existed, and nothing an
    // admin added under Categories & Domains.
    const [taxonomyDomains, setTaxonomyDomains] = useState<string[] | null>(null);
    const [taxonomyError, setTaxonomyError] = useState<string | null>(null);
    const loadTaxonomyDomains = async () => {
        try {
            const res = await fetch('/api/taxonomy/domains');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
            setTaxonomyDomains((data.domains || []).map((d: { name?: string }) => d.name).filter(Boolean));
            setTaxonomyError(null);
        } catch (e) {
            setTaxonomyError(e instanceof Error ? e.message : String(e));
        }
    };
    const creatableDomains = useMemo(
        () => (taxonomyDomains ?? []).filter(d => isAdmin || ['admin', 'editor'].includes(domainPermissions[d])),
        [taxonomyDomains, isAdmin, domainPermissions],
    );
    useEffect(() => {
        if (isCreateModalOpen && taxonomyDomains === null) loadTaxonomyDomains();
    }, [isCreateModalOpen, taxonomyDomains]);
    useEffect(() => {
        // Keep the choice valid as the list arrives: a default of "General" the
        // user can't file under would fail on save for a reason the form hid.
        if (creatableDomains.length && !creatableDomains.includes(newViewDomain)) setNewViewDomain(creatableDomains[0]);
    }, [creatableDomains, newViewDomain]);

    const checkIsPromoter = (domain: string) => {
        return isAdmin || domainPermissions[domain] === 'admin' || domainPermissions[domain] === 'editor';
    };
    const canCreateGlobalView = isAdmin || Object.values(domainPermissions).some(p => p === 'admin' || p === 'editor');

    // Preview + History modal state
    const [previewView, setPreviewView] = useState<ConsolidatedView | null>(null);
    const [historyView, setHistoryView] = useState<ConsolidatedView | null>(null);

    const [pendingTransfer, setPendingTransfer] = useState<{
        viewId: string; viewName: string; targetVersion: number;
        targetEnv: 'dev' | 'test' | 'prod'; envsData: any; action: string;
        sourceEnv: string;
    } | null>(null);


    // Consolidate views from all environments
    const consolidatedViews = useMemo<ConsolidatedView[]>(() => {
        const map = new Map<string, ConsolidatedView>();

        const process = (views: View[], env: 'dev' | 'test' | 'prod') => {
            views.forEach(v => {
                if (!map.has(v.id)) {
                    map.set(v.id, {
                        id: v.id,
                        name: v.name,
                        domain: v.domain || '',
                        is_global: v.is_global,
                        maxVersion: v.version,
                        latestAuthor: v.username || '—',
                        latestTimestamp: v.timestamp,
                    });
                }
                const entry = map.get(v.id)!;
                entry[env] = v;
                if (v.version > entry.maxVersion) {
                    entry.maxVersion = v.version;
                    entry.latestAuthor = v.username || '—';
                    entry.latestTimestamp = v.timestamp;
                }
                if (env === 'prod' || (!entry.prod && env === 'test') || (!entry.prod && !entry.test && env === 'dev')) {
                    entry.name = v.name;
                    entry.domain = v.domain || '';
                    entry.is_global = v.is_global;
                }
            });
        };

        process(devViews, 'dev');
        process(testViews, 'test');
        process(prodViews, 'prod');

        return Array.from(map.values()).filter(v => v.is_global);
    }, [devViews, testViews, prodViews]);

    // Get unique domains across all environments
    const allDomains = useMemo(() => {
        const domains = new Set<string>();
        consolidatedViews.forEach(v => {
            if (v.domain) domains.add(v.domain);
        });
        return ['All', ...Array.from(domains).sort()];
    }, [consolidatedViews]);

    const filteredViews = useMemo(() => {
        return consolidatedViews.filter(v => {
            const matchesSearch = v.name.toLowerCase().includes(searchQuery.toLowerCase());
            const matchesDomain = selectedDomain === 'All' || v.domain === selectedDomain;
            return matchesSearch && matchesDomain;
        });
    }, [consolidatedViews, searchQuery, selectedDomain]);

    const fetchViews = async (env: string) => {
        try {
            const res = await fetch(`/api/views/?env=${env}`);
            const data = await res.json();
            return data.views || [];
        } catch (e) {
            console.error(`Error fetching ${env} views:`, e);
            return [];
        }
    };

    const fetchArchived = async (env: Env): Promise<ArchivedRow[]> => {
        try {
            const res = await fetch(`/api/views/archived?env=${env}`);
            if (!res.ok) return [];
            const data = await res.json();
            return data.views || [];
        } catch (e) {
            console.error(`Error fetching archived ${env} views:`, e);
            return [];
        }
    };

    const loadAll = async () => {
        setLoading(true);
        const [dev, test, prod, archDev, archTest, archProd] = await Promise.all([
            fetchViews('dev'),
            fetchViews('test'),
            fetchViews('prod'),
            fetchArchived('dev'),
            fetchArchived('test'),
            fetchArchived('prod'),
        ]);
        setDevViews(dev);
        setTestViews(test);
        setProdViews(prod);
        setArchivedByEnv({ dev: archDev, test: archTest, prod: archProd });
        setLoading(false);
    };

    // One row per archived view, with the environments it is archived in.
    const archivedViews = useMemo<ArchivedView[]>(() => {
        const map = new Map<string, ArchivedView>();
        ENVS.forEach(env => {
            archivedByEnv[env].forEach(v => {
                const entry = map.get(v.id) ?? { ...v, envs: [] };
                entry.envs.push(env);
                map.set(v.id, entry);
            });
        });
        return Array.from(map.values()).sort((a, b) => (b.archived_at ?? '').localeCompare(a.archived_at ?? ''));
    }, [archivedByEnv]);

    // A view lives in up to three databases, so removing it is up to three calls.
    // They are made together and reported together: a refusal in one environment
    // (no Editor role there, say) must not be hidden by success in another, or the
    // view would look removed while still showing for users of the one that failed.
    const applyToEnvs = async (
        envs: Env[],
        request: (env: Env) => Promise<Response>,
    ): Promise<string[]> => {
        const results = await Promise.all(envs.map(async env => {
            try {
                const res = await request(env);
                if (res.ok) return null;
                const data = await res.json().catch(() => ({}));
                return `${env.toUpperCase()}: ${data?.detail || `HTTP ${res.status}`}`;
            } catch (e) {
                return `${env.toUpperCase()}: ${e instanceof Error ? e.message : String(e)}`;
            }
        }));
        return results.filter((r): r is string => r !== null);
    };

    const finishRemoval = async (failures: string[], verb: string) => {
        await loadAll();
        await refreshGlobalSidebar();
        if (failures.length) alert(`Could not ${verb} in every environment:\n${failures.join('\n')}`);
    };

    const handleArchive = async (view: ConsolidatedView) => {
        const envs = ENVS.filter(env => view[env]);
        const failures = await applyToEnvs(envs, env =>
            fetch(`/api/views/${encodeURIComponent(view.id)}/archive?env=${env}`, { method: 'POST' }));
        setPendingRemoval(null);
        await finishRemoval(failures, 'remove this view');
    };

    const handleRestore = async (view: ArchivedView) => {
        const failures = await applyToEnvs(view.envs, env =>
            fetch(`/api/views/${encodeURIComponent(view.id)}/restore?env=${env}`, { method: 'POST' }));
        await finishRemoval(failures, 'restore this view');
    };

    const handleDeleteForever = async (view: ArchivedView) => {
        const failures = await applyToEnvs(view.envs, env =>
            fetch(`/api/views/${encodeURIComponent(view.id)}?env=${env}`, { method: 'DELETE' }));
        setPendingRemoval(null);
        await finishRemoval(failures, 'delete this view');
    };

    useEffect(() => {
        loadAll();
    }, []);

    const handleVersionChange = async (viewId: string, viewName: string, targetVersion: number, targetEnv: 'dev' | 'test' | 'prod', envsData: any) => {
        const currentVersion = envsData[targetEnv] ? envsData[targetEnv].version : 0;
        if (targetVersion === currentVersion) return;

        let sourceEnv = 'dev';
        if (envsData.dev && envsData.dev.version >= targetVersion) sourceEnv = 'dev';
        else if (envsData.test && envsData.test.version >= targetVersion) sourceEnv = 'test';
        else if (envsData.prod && envsData.prod.version >= targetVersion) sourceEnv = 'prod';

        const action = targetVersion > currentVersion ? 'promote' : 'rollback';

        setPendingTransfer({ viewId, viewName, targetVersion, targetEnv, envsData, action, sourceEnv });
    };

    const executeTransfer = async () => {
        if (!pendingTransfer) return;
        const { viewId, targetVersion, targetEnv, sourceEnv } = pendingTransfer;
        setPendingTransfer(null);

        try {
            const res = await fetch('/api/promotion/transfer_view', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    view_id: viewId,
                    source_env: sourceEnv,
                    target_env: targetEnv,
                    version: targetVersion,
                    is_rollback: pendingTransfer?.action === 'rollback'
                })
            });
            if (res.ok) {
                loadAll();
                await refreshGlobalSidebar();
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail || data.message}`);
                loadAll();
            }
        } catch (e) {
            console.error("Transfer error:", e);
            alert("An error occurred during transfer.");
            loadAll();
        }
    };

    const handleRequestPromotion = (viewName: string, target: string) => {
        alert(`Promotion request for '${viewName}' to ${target.toUpperCase()} has been submitted to the platform administrators.`);
    };

    const handleCreateGlobalView = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newViewName.trim() || !newViewDomain.trim()) return;

        setIsCreating(true);
        try {
            const res = await fetch('/api/views/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: newViewName.trim(),
                    domain: newViewDomain.trim(),
                    is_global: true,
                    is_locked: false,
                    widgets: []
                })
            });
            if (res.ok) {
                await loadAll();
                await refreshGlobalSidebar();
                setIsCreateModalOpen(false);
                setNewViewName('');
                setNewViewDomain('General');
            } else {
                const data = await res.json();
                alert(`Error creating view: ${data.detail || 'Unknown error'}`);
            }
        } catch (e) {
            console.error('Failed to create view');
            alert('An error occurred while creating the view.');
        } finally {
            setIsCreating(false);
        }
    };

    const formatDate = (ts: string) => {
        if (!ts) return '—';
        try { return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); }
        catch { return ts; }
    };

    const renderVersionDropdown = (viewEntry: ConsolidatedView, env: 'dev' | 'test' | 'prod') => {
        const currentVersion = viewEntry[env]?.version ?? 0;
        const options = Array.from({ length: viewEntry.maxVersion }, (_, i) => i + 1);

        if (!checkIsPromoter(viewEntry.domain)) {
            return (
                <div className="flex items-center gap-2">
                    <span className="px-2 py-1 bg-gray-100 rounded-md font-mono text-xs">
                        {currentVersion > 0 ? `v${currentVersion}` : 'None'}
                    </span>
                    {env !== 'dev' && viewEntry.dev && currentVersion < viewEntry.maxVersion && (
                        <button
                            onClick={() => handleRequestPromotion(viewEntry.name, env)}
                            className="text-xs p-1 text-gray-500 hover:text-brand-blue"
                            title="Request Promotion"
                        >
                            <MailPlus size={14} />
                        </button>
                    )}
                </div>
            );
        }

        return (
            <div className="relative inline-block">
                <select
                    value={currentVersion}
                    onChange={(e) => handleVersionChange(viewEntry.id, viewEntry.name, parseInt(e.target.value), env, viewEntry)}
                    className="appearance-none w-32 py-1.5 pl-3 pr-8 text-sm font-mono border border-gray-300 bg-white rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue focus:border-brand-blue"
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

    return (
        <div className="h-full flex flex-col bg-gray-50">
            <div className="p-6 border-b border-gray-200 bg-white flex justify-between items-center shrink-0">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">View Promotion</h1>
                    <p className="text-sm text-gray-500 mt-1">Manage global view lifecycles across Dev, Test, and Prod.</p>
                </div>
                <div className="flex items-center gap-2">
                    {canCreateGlobalView && (
                        <button
                            onClick={() => setIsCreateModalOpen(true)}
                            className="px-4 py-2 bg-brand-blue text-white rounded-md hover:bg-blue-700 transition text-sm font-medium flex items-center gap-2"
                        >
                            <Plus size={16} />
                            Create Global View
                        </button>
                    )}
                    <button
                        onClick={() => setShowArchived(s => !s)}
                        className={`px-3 py-2 rounded-md transition text-sm font-medium flex items-center gap-2 border ${showArchived ? 'bg-gray-800 text-white border-gray-800' : 'text-gray-600 border-gray-300 hover:bg-gray-50'}`}
                        title="Views that were removed but can still be restored"
                    >
                        <Archive size={16} />
                        Archived{archivedViews.length > 0 ? ` (${archivedViews.length})` : ''}
                    </button>
                    <button
                        onClick={loadAll}
                        className="p-2 text-gray-500 hover:text-brand-blue hover:bg-blue-50 rounded-md transition"
                        title="Refresh View Environments"
                    >
                        <RefreshCw size={20} className={loading ? "animate-spin" : ""} />
                    </button>
                </div>
            </div>

            <div className={`bg-white border-b border-gray-200 px-6 py-3 flex flex-col sm:flex-row gap-3 ${showArchived ? 'hidden' : ''}`}>
                <div className="relative flex-1 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                    <input
                        type="text"
                        placeholder="Search views by name..."
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        className="w-full pl-9 pr-4 py-1.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-brand-blue focus:border-brand-blue text-sm"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <Filter size={16} className="text-gray-500" />
                    <div className="relative inline-block">
                        <select
                            value={selectedDomain}
                            onChange={e => setSelectedDomain(e.target.value)}
                            className="appearance-none py-1.5 pl-3 pr-8 border border-gray-300 rounded-md focus:ring-2 focus:ring-brand-blue focus:border-brand-blue text-sm"
                        >
                            {allDomains.map((d: string) => (
                                <option key={d} value={d}>{d}</option>
                            ))}
                        </select>
                        <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-gray-400">
                            <ChevronDown size={14} />
                        </div>
                    </div>
                </div>
            </div>

            {showArchived && (
                <div className="flex-1 p-6 overflow-hidden">
                    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden flex flex-col h-full">
                        <div className="px-6 py-3 border-b border-gray-200 text-sm text-gray-500">
                            Archived views are hidden from everyone's sidebar but keep every version. Restore one to bring it back exactly as it was, or delete it permanently.
                        </div>
                        <div className="flex-1 overflow-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                                <thead className="bg-gray-50 sticky top-0 shadow-sm z-10">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">View Name</th>
                                        <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Domain</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Archived</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">By</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Environments</th>
                                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"></th>
                                    </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-gray-200">
                                    {archivedViews.length === 0 ? (
                                        <tr><td colSpan={6} className="px-6 py-10 text-center text-sm text-gray-400">Nothing is archived.</td></tr>
                                    ) : archivedViews.map(v => (
                                        <tr key={v.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4 font-medium text-sm text-gray-900">{v.name}</td>
                                            <td className="px-6 py-4">
                                                <span className="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">{v.domain}</span>
                                            </td>
                                            <td className="px-4 py-4 text-xs text-gray-500 whitespace-nowrap">{v.archived_at ? formatDate(v.archived_at) : '—'}</td>
                                            <td className="px-4 py-4 text-xs text-gray-500">{v.archived_by || '—'}</td>
                                            <td className="px-4 py-4">
                                                <div className="flex gap-1">
                                                    {v.envs.map(env => (
                                                        <span key={env} className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${ENV_COLORS[env]}`}>{env}</span>
                                                    ))}
                                                </div>
                                            </td>
                                            <td className="px-4 py-4">
                                                <div className="flex items-center justify-end gap-2">
                                                    <button
                                                        onClick={() => handleRestore(v)}
                                                        className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-100 hover:border-gray-300 transition"
                                                    >
                                                        <ArchiveRestore size={13} /> Restore
                                                    </button>
                                                    <button
                                                        onClick={() => setPendingRemoval({ kind: 'delete', view: v })}
                                                        className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-red-200 text-red-600 rounded-md hover:bg-red-50 transition"
                                                    >
                                                        <Trash2 size={13} /> Delete permanently
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}

            <div className={`flex-1 p-6 overflow-hidden ${showArchived ? 'hidden' : ''}`}>
                <div className="bg-white border border-gray-200 rounded-lg overflow-hidden flex flex-col h-full">
                    <div className="flex-1 overflow-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50 sticky top-0 shadow-sm z-10">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">View Name</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Domain</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Last Modified</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Author</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-blue-50/60">Dev</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-purple-50/60">Test</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider bg-green-50/60">Prod</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Preview</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">History</th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Remove</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {filteredViews.length === 0 ? (
                                    <tr><td colSpan={10} className="px-6 py-10 text-center text-sm text-gray-400">No views found.</td></tr>
                                ) : (
                                    filteredViews.map(v => (
                                        <tr key={v.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4">
                                                <div className="font-medium text-sm text-gray-900">{v.name}</div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <span className="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
                                                    {v.domain}
                                                </span>
                                            </td>
                                            <td className="px-4 py-4 text-xs text-gray-500 whitespace-nowrap">{formatDate(v.latestTimestamp)}</td>
                                            <td className="px-4 py-4 text-xs text-gray-500">{v.latestAuthor}</td>
                                            <td className="px-4 py-4 bg-blue-50/20">{renderVersionDropdown(v, 'dev')}</td>
                                            <td className="px-4 py-4 bg-purple-50/20">{renderVersionDropdown(v, 'test')}</td>
                                            <td className="px-4 py-4 bg-green-50/20">{renderVersionDropdown(v, 'prod')}</td>
                                            <td className="px-4 py-4">
                                                <button
                                                    onClick={() => setPreviewView(v)}
                                                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-100 hover:border-gray-300 transition"
                                                >
                                                    <Eye size={13} /> Preview
                                                </button>
                                            </td>
                                            <td className="px-4 py-4">
                                                <button
                                                    onClick={() => setHistoryView(v)}
                                                    className="text-xs text-brand-blue hover:underline whitespace-nowrap"
                                                >
                                                    Version History
                                                </button>
                                            </td>
                                            <td className="px-4 py-4">
                                                {checkIsPromoter(v.domain) ? (
                                                    <button
                                                        onClick={() => setPendingRemoval({ kind: 'archive', view: v })}
                                                        className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-md hover:bg-red-50 hover:border-red-200 hover:text-red-600 transition"
                                                        title="Remove this view for everyone. It is archived first, so it can be restored."
                                                    >
                                                        <Trash2 size={13} /> Remove
                                                    </button>
                                                ) : (
                                                    <span className="text-xs text-gray-300" title="Editor or Admin access on this domain is required">—</span>
                                                )}
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            {/* Create Global View Modal */}
            {isCreateModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-md overflow-hidden">
                        <div className="flex items-center justify-between p-4 border-b border-gray-200">
                            <h2 className="text-lg font-bold text-gray-900">Create Global View</h2>
                            <button
                                onClick={() => setIsCreateModalOpen(false)}
                                className="text-gray-400 hover:text-gray-600 transition"
                            >
                                <X size={20} />
                            </button>
                        </div>
                        <form onSubmit={handleCreateGlobalView} className="p-6">
                            <div className="space-y-4">
                                <div>
                                    <label htmlFor="viewName" className="block text-sm font-medium text-gray-700 mb-1">
                                        View Name
                                    </label>
                                    <input
                                        id="viewName"
                                        type="text"
                                        required
                                        value={newViewName}
                                        onChange={(e) => setNewViewName(e.target.value)}
                                        placeholder="e.g., Executive Summary"
                                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:border-brand-blue focus:ring-1 focus:ring-brand-blue"
                                        autoFocus
                                    />
                                </div>
                                <div>
                                    <label htmlFor="viewDomain" className="block text-sm font-medium text-gray-700 mb-1">
                                        Domain
                                    </label>
                                    <div className="relative">
                                        <select
                                            id="viewDomain"
                                            value={newViewDomain}
                                            onChange={(e) => setNewViewDomain(e.target.value)}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:border-brand-blue focus:ring-1 focus:ring-brand-blue appearance-none"
                                        >
                                            {taxonomyDomains === null && <option value={newViewDomain}>Loading domains…</option>}
                                            {creatableDomains.map(d => <option key={d} value={d}>{d}</option>)}
                                        </select>
                                        <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                                            <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path>
                                            </svg>
                                        </div>
                                    </div>
                                    {taxonomyError && (
                                        <p className="mt-1 text-xs text-amber-700">
                                            Couldn't load domains: {taxonomyError}{' '}
                                            <button type="button" onClick={loadTaxonomyDomains} className="underline">Retry</button>
                                        </p>
                                    )}
                                    {taxonomyDomains !== null && creatableDomains.length === 0 && !taxonomyError && (
                                        <p className="mt-1 text-xs text-gray-500">You can't edit any domain, so there is nowhere to file a global view.</p>
                                    )}
                                </div>
                            </div>
                            <div className="mt-6 flex justify-end gap-3">
                                <button
                                    type="button"
                                    onClick={() => setIsCreateModalOpen(false)}
                                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-brand-blue"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={isCreating || !newViewName.trim() || !creatableDomains.includes(newViewDomain)}
                                    className="px-4 py-2 text-sm font-medium text-white bg-brand-blue border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-brand-blue disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                                >
                                    {isCreating && <RefreshCw size={14} className="animate-spin" />}
                                    Create View
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* View Preview Modal */}
            {previewView && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col overflow-hidden">
                        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                            <div>
                                <h2 className="text-lg font-bold text-gray-900">{previewView.name}</h2>
                                <p className="text-xs text-gray-400 mt-0.5">by {previewView.latestAuthor} · {formatDate(previewView.latestTimestamp)}</p>
                            </div>
                            <button onClick={() => setPreviewView(null)} className="text-gray-400 hover:text-gray-600 transition rounded p-1">
                                <X size={20} />
                            </button>
                        </div>
                        <div className="flex-1 overflow-auto p-6">
                            <div className="grid grid-cols-2 gap-4 text-sm mb-4">
                                <div>
                                    <span className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Domain</span>
                                    <span className="text-gray-800">{previewView.domain || '—'}</span>
                                </div>
                                <div>
                                    <span className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Max Version</span>
                                    <span className="font-mono text-gray-800">v{previewView.maxVersion}</span>
                                </div>
                            </div>
                            <div className="space-y-2">
                                <span className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Environment Status</span>
                                {(['dev', 'test', 'prod'] as const).map(env => (
                                    <div key={env} className="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-md">
                                        <span className="text-xs font-medium text-gray-600 uppercase">{env}</span>
                                        {previewView[env] ? (
                                            <span className="font-mono text-xs text-gray-800">v{previewView[env]!.version} · {formatDate(previewView[env]!.timestamp)}</span>
                                        ) : (
                                            <span className="text-xs text-gray-400">Not installed</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {historyView && <ViewHistoryModal view={historyView} onClose={() => setHistoryView(null)} />}
            {pendingRemoval?.kind === 'archive' && (
                <ConfirmModal
                    title="Remove View"
                    message={`Remove '${pendingRemoval.view.name}' for everyone?`}
                    detail="It disappears from every user's Global Views in Dev, Test and Prod. Nothing is deleted: open Archived to restore it, or to delete it permanently."
                    confirmLabel="Remove"
                    variant="warning"
                    onConfirm={() => handleArchive(pendingRemoval.view)}
                    onCancel={() => setPendingRemoval(null)}
                />
            )}
            {pendingRemoval?.kind === 'delete' && (
                <ConfirmModal
                    title="Delete Permanently"
                    message={`Permanently delete '${pendingRemoval.view.name}'?`}
                    detail={`Every version is deleted from ${pendingRemoval.view.envs.map(e => e.toUpperCase()).join(', ')}. This cannot be undone. Personal copies users made from it are not affected.`}
                    confirmLabel="Delete permanently"
                    variant="danger"
                    onConfirm={() => handleDeleteForever(pendingRemoval.view)}
                    onCancel={() => setPendingRemoval(null)}
                />
            )}
            {pendingTransfer && (() => {
                const isRollback = pendingTransfer.action === 'rollback';
                return (
                    <ConfirmModal
                        title={isRollback ? 'Roll Back View' : 'Promote View'}
                        message={
                            isRollback
                                ? `Roll back '${pendingTransfer.viewName}' in ${pendingTransfer.targetEnv.toUpperCase()} to v${pendingTransfer.targetVersion}?`
                                : `Promote '${pendingTransfer.viewName}' to v${pendingTransfer.targetVersion} in ${pendingTransfer.targetEnv.toUpperCase()}?`
                        }
                        confirmLabel={isRollback ? `Roll Back to v${pendingTransfer.targetVersion}` : 'Promote'}
                        variant={isRollback ? 'warning' : 'primary'}
                        onConfirm={executeTransfer}
                        onCancel={() => { setPendingTransfer(null); loadAll(); }}
                    />
                );
            })()}
        </div>
    );
};
