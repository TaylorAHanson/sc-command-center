import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertCircle, Archive, ArchiveRestore, Bot, ExternalLink, Layers, LayoutGrid, Loader2, Pencil, RefreshCw, Search, Share2, Trash2, X,
} from 'lucide-react';
import clsx from 'clsx';
import { ConfirmModal } from '../../components/ConfirmModal';
import { AccessIcon, ShareDialog } from '../../components/sharing';
import { useWorkspaceTools } from '../../contexts/WorkspaceTools';
import { OPEN_LABEL, openObject } from './openObject';
import {
    EVERYONE, STATE_LABELS, accessSummaryFromCount, requestJson,
    type AccessSummary, type Acl, type ObjectType, type PublishState,
} from '../../sharing';
import { formatServerTime } from './time';

interface ContentItem {
    object_type: ObjectType;
    object_id: string;
    name: string;
    owner: string | null;
    state: PublishState;
    published_version: number | null;
    archived: boolean;
    entries: number;
    everyone: boolean;
    updated_at: string | null;
}

const CONTENT_URL = '/api/sharing/content';

type TypeFilter = 'all' | ObjectType;
type StateFilter = 'all' | PublishState | 'archived';
type Pending = { kind: 'archive' | 'restore' | 'delete'; item: ContentItem };

const TYPE_META: Record<ObjectType, { label: string; plural: string; Icon: typeof LayoutGrid }> = {
    app: { label: 'View', plural: 'Views', Icon: LayoutGrid },
    widget: { label: 'Widget', plural: 'Widgets', Icon: Layers },
    agent: { label: 'Agent', plural: 'Agents', Icon: Bot },
};

const STATE_CHIP: Record<PublishState, string> = {
    draft_only: 'bg-gray-100 text-gray-700',
    published: 'bg-emerald-50 text-emerald-700',
    published_with_draft: 'bg-amber-50 text-amber-800',
};

const ACCESS_LABEL: Record<AccessSummary, string> = {
    private: 'Private',
    shared: 'Shared',
    everyone: 'Everyone',
};

// What each kind of object answers to; the server checks MANAGE, which admins
// always have. A view is archived before it can be deleted (409 otherwise).
const deleteUrl = (item: ContentItem): string => {
    const id = encodeURIComponent(item.object_id);
    if (item.object_type === 'app') return `/api/apps/${id}`;
    if (item.object_type === 'widget') return `/api/widgets/custom/${id}`;
    return `/api/agent/studio/profiles/${id}`;
};

const viewLink = (id: string) =>
    `${window.location.origin}${window.location.pathname}#/app/${encodeURIComponent(id)}`;

const filterBtn = (active: boolean) => clsx(
    'px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap',
    active ? 'bg-white text-brand-navy shadow-sm' : 'text-gray-600 hover:text-gray-900',
);

/**
 * Admin Panel → Content: every view, widget and agent in the app, whoever owns
 * it, with its publish state and how widely it is shared. Replaces the old View
 * and Widget Promotion screens; there is nothing to promote between any more,
 * only drafts and published versions of one object.
 */
export const AdminContent: React.FC = () => {
    const [items, setItems] = useState<ContentItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
    const [stateFilter, setStateFilter] = useState<StateFilter>('all');
    const [search, setSearch] = useState('');
    const [sharing, setSharing] = useState<ContentItem | null>(null);
    const [pending, setPending] = useState<Pending | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const tools = useWorkspaceTools();

    const openItem = (item: ContentItem) => {
        if (!openObject(item.object_type, item.object_id, tools)) {
            setActionError(`Couldn't open “${item.name}” from here. Open Widget Studio from the sidebar instead.`);
        }
    };

    const settle = useCallback((request: Promise<{ items?: ContentItem[] }>) => request
        .then(data => { setItems(data.items || []); setLoadError(null); })
        // Keep the last list: an empty table would read as "the app has no content".
        .catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false)), []);

    const load = () => {
        setLoading(true);
        return settle(requestJson(CONTENT_URL));
    };

    useEffect(() => { settle(requestJson(CONTENT_URL)); }, [settle]);

    const counts = useMemo(() => {
        const c: Record<ObjectType, number> = { app: 0, widget: 0, agent: 0 };
        items.forEach(i => { c[i.object_type] += 1; });
        return c;
    }, [items]);

    const shown = useMemo(() => {
        const q = search.trim().toLowerCase();
        return items.filter(i => {
            if (typeFilter !== 'all' && i.object_type !== typeFilter) return false;
            if (stateFilter === 'archived' ? !i.archived : stateFilter !== 'all' && i.state !== stateFilter) return false;
            if (!q) return true;
            return i.name.toLowerCase().includes(q)
                || (i.owner || '').toLowerCase().includes(q)
                || i.object_id.toLowerCase().includes(q);
        });
    }, [items, typeFilter, stateFilter, search]);

    const keyOf = (i: ContentItem) => `${i.object_type}:${i.object_id}`;

    const onShared = (item: ContentItem, acl: Acl) => {
        const everyone = acl.entries.some(e => e.principal === EVERYONE);
        setItems(prev => prev.map(i => (keyOf(i) === keyOf(item) ? { ...i, entries: acl.entries.length, everyone } : i)));
    };

    const run = async () => {
        const p = pending;
        setPending(null);
        if (!p) return;
        const id = encodeURIComponent(p.item.object_id);
        setActionError(null);
        setBusy(keyOf(p.item));
        try {
            if (p.kind === 'archive') await requestJson(`/api/apps/${id}/archive`, { method: 'POST' });
            else if (p.kind === 'restore') await requestJson(`/api/apps/${id}/restore`, { method: 'POST' });
            else await requestJson(deleteUrl(p.item), { method: 'DELETE' });
            await load();
        } catch (e) {
            setActionError(`Couldn't ${p.kind} “${p.item.name}”: ${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setBusy(null);
        }
    };

    const confirmCopy = (p: Pending) => {
        const what = TYPE_META[p.item.object_type].label.toLowerCase();
        if (p.kind === 'archive') return {
            title: 'Archive view',
            message: `Archive “${p.item.name}”?`,
            detail: 'It leaves everyone’s sidebar, including the people it is shared with. Nothing is deleted: restore it here, or delete it permanently.',
            label: 'Archive',
            variant: 'warning' as const,
        };
        if (p.kind === 'restore') return {
            title: 'Restore view',
            message: `Restore “${p.item.name}”?`,
            detail: 'It comes back for everyone it is shared with, exactly as it was archived.',
            label: 'Restore',
            variant: 'primary' as const,
        };
        return {
            title: `Delete ${what}`,
            message: `Permanently delete “${p.item.name}”?`,
            detail: `Every published version, its draft and who it is shared with are removed. This can't be undone.`,
            label: 'Delete',
            variant: 'danger' as const,
        };
    };

    const pendingCopy = pending ? confirmCopy(pending) : null;

    return (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200">
            <div className="p-6 border-b border-gray-200 flex justify-between items-start gap-4">
                <div>
                    <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                        <LayoutGrid className="text-brand-blue" size={20} />
                        Content
                    </h2>
                    <p className="text-sm text-gray-500 mt-1 max-w-2xl">
                        Every view, widget and agent in this app. As an administrator you can manage all of them:
                        open or edit any of them, share them, and archive, restore or delete them.
                    </p>
                    {!loading && !loadError && (
                        <p className="text-xs text-gray-400 mt-1">
                            {counts.app} views · {counts.widget} widgets · {counts.agent} agents
                        </p>
                    )}
                </div>
                <button
                    onClick={load}
                    className="p-2 text-gray-400 hover:text-brand-blue transition-colors rounded-lg hover:bg-gray-50 bg-gray-50/50"
                    title="Refresh"
                >
                    <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div className="p-6">
                <div className="flex flex-wrap items-center gap-3 mb-4">
                    <div className="flex items-center gap-1 rounded-lg bg-gray-100 p-1" role="group" aria-label="Type">
                        <button type="button" onClick={() => setTypeFilter('all')} className={filterBtn(typeFilter === 'all')}>All</button>
                        {(Object.keys(TYPE_META) as ObjectType[]).map(t => (
                            <button key={t} type="button" onClick={() => setTypeFilter(t)} className={filterBtn(typeFilter === t)}>
                                {TYPE_META[t].plural}
                            </button>
                        ))}
                    </div>
                    <select
                        aria-label="State"
                        value={stateFilter}
                        onChange={e => setStateFilter(e.target.value as StateFilter)}
                        className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:border-brand-blue"
                    >
                        <option value="all">Any state</option>
                        <option value="published_with_draft">{STATE_LABELS.published_with_draft}</option>
                        <option value="published">{STATE_LABELS.published}</option>
                        <option value="draft_only">{STATE_LABELS.draft_only}</option>
                        <option value="archived">Archived</option>
                    </select>
                    <div className="relative flex-1 min-w-[12rem]">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                        <input
                            type="text"
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="Search by name, owner or id"
                            className="w-full pl-9 pr-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-brand-blue focus:border-brand-blue"
                        />
                    </div>
                </div>

                {actionError && (
                    <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                        <AlertCircle size={16} className="mt-0.5 shrink-0" />
                        <span className="flex-1">{actionError}</span>
                        <button type="button" aria-label="Dismiss" onClick={() => setActionError(null)} className="opacity-60 hover:opacity-100">
                            <X size={14} />
                        </button>
                    </div>
                )}
                {loadError && items.length > 0 && (
                    <div role="alert" className="mb-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        <AlertCircle size={16} className="shrink-0" />
                        <span className="flex-1">Couldn't refresh: {loadError}. Showing the last list.</span>
                        <button type="button" onClick={load} className="font-medium underline">Retry</button>
                    </div>
                )}

                <div className="overflow-x-auto border border-gray-200 rounded-lg">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">State</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Access</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Owner</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Updated</th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {loading && items.length === 0 ? (
                                <tr><td colSpan={6} className="px-6 py-8 text-center text-gray-500 text-sm">Loading...</td></tr>
                            ) : loadError && items.length === 0 ? (
                                <tr><td colSpan={6} className="px-6 py-8 text-center text-sm">
                                    <p className="text-red-600 font-medium">Could not load content.</p>
                                    <p className="text-gray-500 mt-1">{loadError}</p>
                                    <button onClick={load} className="mt-3 px-3 py-1.5 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 inline-flex items-center gap-1.5">
                                        <RefreshCw size={14} /> Retry
                                    </button>
                                </td></tr>
                            ) : shown.length === 0 ? (
                                <tr><td colSpan={6} className="px-6 py-8 text-center text-gray-500 text-sm">
                                    {items.length === 0 ? 'Nothing has been built yet.' : 'Nothing matches these filters.'}
                                </td></tr>
                            ) : (
                                shown.map(item => {
                                    const { Icon, label } = TYPE_META[item.object_type];
                                    const summary = accessSummaryFromCount(item.entries, item.everyone);
                                    const key = keyOf(item);
                                    const isView = item.object_type === 'app';
                                    const rowBusy = busy === key;
                                    return (
                                        <tr key={key} className={clsx('hover:bg-gray-50', item.archived && 'bg-gray-50/60')}>
                                            <td className="px-4 py-3 text-sm">
                                                <div className="flex items-center gap-2 min-w-0">
                                                    <Icon size={15} className="shrink-0 text-gray-400" aria-label={label} />
                                                    <div className="min-w-0">
                                                        <div className={clsx('font-medium truncate max-w-xs', item.archived ? 'text-gray-500' : 'text-gray-900')} title={item.name}>
                                                            {item.name}
                                                        </div>
                                                        <div className="text-[11px] text-gray-400 font-mono truncate max-w-xs" title={item.object_id}>
                                                            {label} · {item.object_id}
                                                        </div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-sm whitespace-nowrap">
                                                <div className="flex items-center gap-1.5">
                                                    <span className={clsx('inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium', STATE_CHIP[item.state])}>
                                                        {STATE_LABELS[item.state]}
                                                    </span>
                                                    {item.published_version != null && (
                                                        <span className="text-xs text-gray-400" title="Latest published version">v{item.published_version}</span>
                                                    )}
                                                    {item.archived && (
                                                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-200 text-gray-700">Archived</span>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                                                <span className="inline-flex items-center gap-1.5">
                                                    <AccessIcon summary={summary} className="text-gray-500" />
                                                    {ACCESS_LABEL[summary]}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-600 truncate max-w-[14rem]" title={item.owner || undefined}>
                                                {item.owner || <span className="text-gray-400">—</span>}
                                            </td>
                                            <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{formatServerTime(item.updated_at)}</td>
                                            <td className="px-4 py-3 text-right whitespace-nowrap">
                                                <div className="flex justify-end items-center gap-1">
                                                    {rowBusy && <Loader2 size={16} className="animate-spin text-gray-400 mr-1" />}
                                                    {!item.archived && (
                                                        <button
                                                            onClick={() => openItem(item)}
                                                            disabled={rowBusy}
                                                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                                                            title={isView ? 'Open this view' : `Edit in ${item.object_type === 'widget' ? 'Widget' : 'Agent'} Studio`}
                                                        >
                                                            {isView ? <ExternalLink size={14} /> : <Pencil size={14} />} {OPEN_LABEL[item.object_type]}
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => setSharing(item)}
                                                        disabled={rowBusy}
                                                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-brand-blue hover:bg-blue-50 disabled:opacity-40"
                                                        title="Share"
                                                    >
                                                        <Share2 size={14} /> Share
                                                    </button>
                                                    {isView && !item.archived && (
                                                        <button
                                                            onClick={() => setPending({ kind: 'archive', item })}
                                                            disabled={rowBusy}
                                                            className="text-gray-400 hover:text-amber-600 p-1 rounded hover:bg-amber-50 disabled:opacity-40"
                                                            title="Archive"
                                                        >
                                                            <Archive size={16} />
                                                        </button>
                                                    )}
                                                    {isView && item.archived && (
                                                        <button
                                                            onClick={() => setPending({ kind: 'restore', item })}
                                                            disabled={rowBusy}
                                                            className="text-gray-400 hover:text-brand-blue p-1 rounded hover:bg-blue-50 disabled:opacity-40"
                                                            title="Restore"
                                                        >
                                                            <ArchiveRestore size={16} />
                                                        </button>
                                                    )}
                                                    {(!isView || item.archived) && (
                                                        <button
                                                            onClick={() => setPending({ kind: 'delete', item })}
                                                            disabled={rowBusy}
                                                            className="text-gray-400 hover:text-red-600 p-1 rounded hover:bg-red-50 disabled:opacity-40"
                                                            title="Delete permanently"
                                                        >
                                                            <Trash2 size={16} />
                                                        </button>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {sharing && (
                <ShareDialog
                    objectType={sharing.object_type}
                    objectId={sharing.object_id}
                    name={sharing.name}
                    published={sharing.published_version != null}
                    link={sharing.object_type === 'app' ? viewLink(sharing.object_id) : undefined}
                    onClose={() => setSharing(null)}
                    onChanged={acl => onShared(sharing, acl)}
                />
            )}
            {pending && pendingCopy && (
                <ConfirmModal
                    title={pendingCopy.title}
                    message={pendingCopy.message}
                    detail={pendingCopy.detail}
                    confirmLabel={pendingCopy.label}
                    variant={pendingCopy.variant}
                    onConfirm={run}
                    onCancel={() => setPending(null)}
                />
            )}
        </div>
    );
};
