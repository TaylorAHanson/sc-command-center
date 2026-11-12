import React, { useEffect, useMemo, useState } from 'react';
import {
    Activity, AlertCircle, Bot, ExternalLink, Filter, Layers, LayoutGrid, Loader2, Pencil, RefreshCw, Search, User, X,
} from 'lucide-react';
import clsx from 'clsx';
import { useWorkspaceTools } from '../../contexts/WorkspaceTools';
import { requestJson, type ObjectType } from '../../sharing';
import { OPEN_LABEL, openObject } from './openObject';
import { formatServerTime, parseServerTime } from './time';

type ObjectState = 'published' | 'draft' | 'archived' | 'deleted';
type Detail = Record<string, string | number | boolean | null>;

interface ActivityEvent {
    key: string;
    source: 'event' | 'action';
    at: string;
    username: string;
    verb: string;
    object_type: string | null;
    object_id: string | null;
    object_name: string | null;
    object_state: ObjectState | null;
    detail: Detail;
}

interface FeedPage {
    events: ActivityEvent[];
    next_cursor: string | null;
}

interface ActivePerson {
    username: string;
    last_seen: string | null;
}

interface PersonSummary {
    username: string;
    days: number;
    total: number;
    last_seen: string | null;
    verbs: { verb: string; count: number; last_at: string | null }[];
    objects: {
        object_type: ObjectType;
        object_id: string;
        count: number;
        last_at: string | null;
        object_name: string | null;
        object_state: ObjectState | null;
    }[];
}

const PAGE_SIZE = 50;
const ACTIVE_MINUTES = 15;
const SUMMARY_DAYS = 30;

// Patterns the server understands (`*` is any run of characters), grouped the
// way an administrator asks: "what was published", "who shared what".
const KINDS: { pattern: string; label: string }[] = [
    { pattern: '', label: 'All activity' },
    { pattern: '*.publish,*.revert,*.discard', label: 'Publishing' },
    { pattern: '*.create', label: 'New drafts' },
    { pattern: '*.share,admin.*', label: 'Sharing & administrators' },
    { pattern: '*.archive,*.restore,*.delete', label: 'Archive & delete' },
    { pattern: '*.generate', label: 'Studio generations' },
    { pattern: 'chat.*', label: 'Chat' },
    { pattern: 'widget.action', label: 'Widget actions' },
    { pattern: 'settings.*', label: 'Settings' },
];

const VERB_LABELS: Record<string, string> = {
    'view.create': 'Created a view',
    'view.publish': 'Published a view',
    'view.discard': 'Discarded a view’s draft',
    'view.revert': 'Reverted a view',
    'view.archive': 'Archived a view',
    'view.restore': 'Restored a view',
    'view.delete': 'Deleted a view',
    'view.share': 'Changed who can see a view',
    'widget.create': 'Created a widget',
    'widget.publish': 'Published a widget',
    'widget.discard': 'Discarded a widget’s draft',
    'widget.revert': 'Reverted a widget',
    'widget.certify': 'Changed a widget’s certification',
    'widget.delete': 'Deleted a widget',
    'widget.share': 'Changed who can use a widget',
    'widget.generate': 'Generated in Widget Studio',
    'widget.action': 'Ran a widget action',
    'agent.create': 'Created an agent',
    'agent.publish': 'Published an agent',
    'agent.discard': 'Discarded an agent’s draft',
    'agent.revert': 'Reverted an agent',
    'agent.delete': 'Deleted an agent',
    'agent.share': 'Changed who can use an agent',
    'agent.generate': 'Drafted in Agent Studio',
    'chat.turn': 'Asked the assistant',
    'settings.update': 'Changed settings',
    'admin.add': 'Added an administrator',
    'admin.remove': 'Removed an administrator',
};

const RANGES = [
    { id: 'any', label: 'Any time', hours: 0 },
    { id: '1h', label: 'Last hour', hours: 1 },
    { id: '24h', label: 'Last 24 hours', hours: 24 },
    { id: '7d', label: 'Last 7 days', hours: 24 * 7 },
    { id: '30d', label: 'Last 30 days', hours: 24 * 30 },
    { id: 'custom', label: 'Custom range', hours: 0 },
] as const;
type RangeId = typeof RANGES[number]['id'];

const TYPE_META: Record<ObjectType, { label: string; plural: string; Icon: typeof LayoutGrid }> = {
    app: { label: 'View', plural: 'Views', Icon: LayoutGrid },
    widget: { label: 'Widget', plural: 'Widgets', Icon: Layers },
    agent: { label: 'Agent', plural: 'Agents', Icon: Bot },
};

const STATE_TAG: Partial<Record<ObjectState, string>> = {
    draft: 'Draft',
    archived: 'Archived',
    deleted: 'Deleted',
};

interface Filters {
    person: string;
    kind: string;
    objectType: '' | ObjectType;
    objectId: string;
    objectLabel: string;
    range: RangeId;
    from: string;
    to: string;
}

const NO_FILTERS: Filters = { person: '', kind: '', objectType: '', objectId: '', objectLabel: '', range: 'any', from: '', to: '' };

const isObjectType = (t: string | null): t is ObjectType => t === 'app' || t === 'widget' || t === 'agent';

const verbLabel = (verb: string) => VERB_LABELS[verb] || verb;

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

const localIso = (value: string): string | null => {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
};

/** The feed's address. Times are worked out here, at fetch time, so "last hour" means the last hour now. */
const feedUrl = (f: Filters, cursor: string | null): string => {
    const q = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (f.person) q.set('person', f.person);
    if (f.kind) q.set('verb', f.kind);
    if (f.objectType) q.set('object_type', f.objectType);
    if (f.objectId) q.set('object_id', f.objectId);
    const range = RANGES.find(r => r.id === f.range);
    if (range && range.hours > 0) {
        q.set('since', new Date(Date.now() - range.hours * 3600 * 1000).toISOString());
    } else if (f.range === 'custom') {
        const since = localIso(f.from);
        const until = localIso(f.to);
        if (since) q.set('since', since);
        if (until) q.set('until', until);
    }
    if (cursor) q.set('cursor', cursor);
    return `/api/activity?${q}`;
};

const ago = (value: string | null, now: number): string => {
    const d = parseServerTime(value);
    if (!d) return '—';
    const minutes = Math.floor(Math.max(0, now - d.getTime()) / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
    return d.toLocaleString();
};

const DetailChips: React.FC<{ detail: Detail }> = ({ detail }) => {
    const shown = Object.entries(detail || {}).filter(([, v]) => v !== false && v !== null && v !== '');
    if (shown.length === 0) return <span className="text-gray-300">—</span>;
    return (
        <div className="flex flex-wrap gap-1">
            {shown.map(([k, v]) => (
                <span key={k} className="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
                    {k.replace(/_/g, ' ')}{v === true ? '' : <span className="font-medium text-gray-800">{String(v)}</span>}
                </span>
            ))}
        </div>
    );
};

const selectClass = 'rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:border-brand-blue';

/**
 * Admin Panel → Activity: who did what in this app, newest first, from the
 * activity log and approved widget actions. Metadata only; the server never
 * sends what anyone wrote.
 */
export const ActivityLog: React.FC = () => {
    const tools = useWorkspaceTools();
    const [filters, setFilters] = useState<Filters>(NO_FILTERS);
    const [personDraft, setPersonDraft] = useState('');
    const [tick, setTick] = useState(0);
    const [now, setNow] = useState(() => Date.now());
    const [feed, setFeed] = useState<{ key: string; events: ActivityEvent[]; next: string | null; error: string | null } | null>(null);
    const [more, setMore] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
    const [active, setActive] = useState<{ people: ActivePerson[]; error: string | null } | null>(null);
    const [summary, setSummary] = useState<{ username: string; data: PersonSummary | null; error: string | null } | null>(null);
    const [openError, setOpenError] = useState<string | null>(null);

    const feedKey = useMemo(() => JSON.stringify([filters, tick]), [filters, tick]);
    const loading = feed?.key !== feedKey;

    useEffect(() => {
        let cancelled = false;
        requestJson<FeedPage>(feedUrl(filters, null))
            .then(page => {
                if (cancelled) return;
                setFeed({ key: feedKey, events: page.events || [], next: page.next_cursor, error: null });
                setMore({ busy: false, error: null });
                setNow(Date.now());
            })
            // Keep what was shown: an empty list would read as "nothing happened".
            .catch(e => { if (!cancelled) setFeed(prev => ({ key: feedKey, events: prev?.events ?? [], next: null, error: messageOf(e) })); });
        return () => { cancelled = true; };
    }, [feedKey, filters]);

    useEffect(() => {
        let cancelled = false;
        requestJson<{ people: ActivePerson[] }>(`/api/activity/active?minutes=${ACTIVE_MINUTES}`)
            .then(d => { if (!cancelled) setActive({ people: d.people || [], error: null }); })
            .catch(e => { if (!cancelled) setActive(prev => ({ people: prev?.people ?? [], error: messageOf(e) })); });
        return () => { cancelled = true; };
    }, [tick]);

    useEffect(() => {
        const username = filters.person;
        if (!username) return;
        let cancelled = false;
        requestJson<PersonSummary>(`/api/activity/person?username=${encodeURIComponent(username)}&days=${SUMMARY_DAYS}`)
            .then(data => { if (!cancelled) setSummary({ username, data, error: null }); })
            .catch(e => { if (!cancelled) setSummary({ username, data: null, error: messageOf(e) }); });
        return () => { cancelled = true; };
    }, [filters.person, tick]);

    const update = (change: Partial<Filters>) => setFilters(prev => ({ ...prev, ...change }));

    const showPerson = (username: string) => {
        setPersonDraft(username);
        update({ person: username });
    };

    const clearPerson = () => {
        setPersonDraft('');
        update({ person: '' });
    };

    const showObject = (e: { object_type: string | null; object_id: string | null; object_name: string | null }) => {
        if (!isObjectType(e.object_type) || !e.object_id) return;
        update({ objectType: e.object_type, objectId: e.object_id, objectLabel: e.object_name || e.object_id });
    };

    const loadMore = () => {
        const cursor = feed?.next;
        if (!cursor || more.busy) return;
        const key = feedKey;
        setMore({ busy: true, error: null });
        requestJson<FeedPage>(feedUrl(filters, cursor))
            .then(page => {
                setFeed(prev => (prev && prev.key === key
                    ? { ...prev, events: [...prev.events, ...(page.events || [])], next: page.next_cursor }
                    : prev));
                setMore({ busy: false, error: null });
            })
            .catch(e => setMore({ busy: false, error: messageOf(e) }));
    };

    const openItem = (type: ObjectType, id: string, name: string | null) => {
        setOpenError(null);
        if (!openObject(type, id, tools)) setOpenError(`Couldn't open “${name || id}” from here.`);
    };

    const canOpen = (e: ActivityEvent) =>
        isObjectType(e.object_type) && !!e.object_id && (e.object_state === 'published' || e.object_state === 'draft');

    const kindIsPreset = KINDS.some(k => k.pattern === filters.kind);
    const events = feed?.events ?? [];
    const personSummary = filters.person && summary?.username === filters.person ? summary : null;
    const filtered = filters.person || filters.kind || filters.objectType || filters.range !== 'any';

    return (
        <div className="space-y-6">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200">
                <div className="p-6 border-b border-gray-200 flex justify-between items-start gap-4">
                    <div>
                        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                            <Activity className="text-brand-blue" size={20} />
                            Activity
                        </h2>
                        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
                            Who did what in this app: publishing, sharing, archiving, studio generations, chat turns,
                            widget actions and setting changes. It records that something happened, never what anyone wrote.
                        </p>
                    </div>
                    <button
                        onClick={() => setTick(t => t + 1)}
                        className="p-2 text-gray-400 hover:text-brand-blue transition-colors rounded-lg hover:bg-gray-50 bg-gray-50/50"
                        title="Refresh"
                    >
                        <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                <div className="px-6 py-4 border-b border-gray-200 bg-gray-50/50">
                    <div className="flex items-center gap-2 text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
                        <span className="relative flex h-2 w-2">
                            <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 animate-ping" />
                            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                        </span>
                        Active in the last {ACTIVE_MINUTES} minutes
                    </div>
                    {active === null ? (
                        <p className="text-sm text-gray-400">Loading…</p>
                    ) : active.error && active.people.length === 0 ? (
                        <p className="text-sm text-red-600">Couldn't load who is active: {active.error}</p>
                    ) : active.people.length === 0 ? (
                        <p className="text-sm text-gray-500">Nobody in the last {ACTIVE_MINUTES} minutes.</p>
                    ) : (
                        <div className="flex flex-wrap gap-2">
                            {active.people.map(p => (
                                <button
                                    key={p.username}
                                    type="button"
                                    onClick={() => showPerson(p.username)}
                                    className={clsx(
                                        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                                        filters.person === p.username
                                            ? 'border-brand-blue bg-blue-50 text-brand-blue'
                                            : 'border-gray-200 bg-white text-gray-700 hover:border-brand-blue hover:text-brand-blue',
                                    )}
                                    title={`Last seen ${formatServerTime(p.last_seen)}`}
                                >
                                    <User size={12} /> {p.username}
                                    <span className="text-gray-400">{ago(p.last_seen, now)}</span>
                                </button>
                            ))}
                        </div>
                    )}
                    <p className="text-[11px] text-gray-400 mt-2">Someone counts as seen when they load a page; it is noted at most every ten minutes.</p>
                </div>
            </div>

            {filters.person && (
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <div className="flex justify-between items-start gap-4">
                        <div>
                            <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
                                <User className="text-brand-blue" size={18} /> {filters.person}
                            </h3>
                            <p className="text-xs text-gray-500 mt-1">
                                Last {SUMMARY_DAYS} days
                                {personSummary?.data && <> · {personSummary.data.total} events · last seen {formatServerTime(personSummary.data.last_seen)}</>}
                            </p>
                        </div>
                        <button type="button" onClick={clearPerson} className="p-1 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100" title="Back to everyone">
                            <X size={16} />
                        </button>
                    </div>
                    {!personSummary ? (
                        <p className="mt-4 text-sm text-gray-400 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
                    ) : personSummary.error ? (
                        <p className="mt-4 text-sm text-red-600">Couldn't load this person's summary: {personSummary.error}</p>
                    ) : personSummary.data && personSummary.data.total === 0 ? (
                        <p className="mt-4 text-sm text-gray-500">Nothing recorded for this person in the last {SUMMARY_DAYS} days.</p>
                    ) : personSummary.data && (
                        <div className="mt-4 grid gap-6 md:grid-cols-2">
                            <div>
                                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">What they did</div>
                                <div className="flex flex-wrap gap-1.5">
                                    {personSummary.data.verbs.map(v => (
                                        <button
                                            key={v.verb}
                                            type="button"
                                            onClick={() => update({ kind: v.verb })}
                                            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:border-brand-blue hover:text-brand-blue"
                                            title={`${v.verb} · last ${formatServerTime(v.last_at)}`}
                                        >
                                            {verbLabel(v.verb)} <span className="font-semibold text-gray-900">{v.count}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div>
                                <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">What they worked on most</div>
                                {personSummary.data.objects.length === 0 ? (
                                    <p className="text-sm text-gray-400">No views, widgets or agents.</p>
                                ) : (
                                    <ul className="space-y-1">
                                        {personSummary.data.objects.map(o => {
                                            const { Icon, label } = TYPE_META[o.object_type];
                                            return (
                                                <li key={`${o.object_type}:${o.object_id}`} className="flex items-center gap-2 text-sm">
                                                    <Icon size={14} className="shrink-0 text-gray-400" aria-label={label} />
                                                    <button type="button" onClick={() => showObject(o)} className="truncate text-left text-gray-800 hover:text-brand-blue" title="Show only this">
                                                        {o.object_name || o.object_id}
                                                    </button>
                                                    {o.object_state && STATE_TAG[o.object_state] && (
                                                        <span className="text-[11px] text-gray-400">{STATE_TAG[o.object_state]}</span>
                                                    )}
                                                    <span className="ml-auto text-xs text-gray-500">{o.count}</span>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            <div className="bg-white rounded-lg shadow-sm border border-gray-200">
                <div className="p-6">
                    <div className="flex flex-wrap items-center gap-3 mb-3">
                        <select
                            aria-label="Kind"
                            value={kindIsPreset ? filters.kind : '__custom'}
                            onChange={e => update({ kind: e.target.value })}
                            className={selectClass}
                        >
                            {KINDS.map(k => <option key={k.pattern} value={k.pattern}>{k.label}</option>)}
                            {!kindIsPreset && <option value="__custom" disabled>{verbLabel(filters.kind)}</option>}
                        </select>
                        <select
                            aria-label="Object type"
                            value={filters.objectType}
                            onChange={e => update({ objectType: e.target.value as Filters['objectType'], objectId: '', objectLabel: '' })}
                            className={selectClass}
                        >
                            <option value="">Any object</option>
                            {(Object.keys(TYPE_META) as ObjectType[]).map(t => <option key={t} value={t}>{TYPE_META[t].plural}</option>)}
                        </select>
                        <select
                            aria-label="Time range"
                            value={filters.range}
                            onChange={e => update({ range: e.target.value as RangeId })}
                            className={selectClass}
                        >
                            {RANGES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
                        </select>
                        {filters.range === 'custom' && (
                            <div className="flex items-center gap-2 text-sm text-gray-600">
                                <input type="datetime-local" aria-label="From" value={filters.from} onChange={e => update({ from: e.target.value })} className={selectClass} />
                                <span>to</span>
                                <input type="datetime-local" aria-label="To" value={filters.to} onChange={e => update({ to: e.target.value })} className={selectClass} />
                            </div>
                        )}
                        <form
                            className="relative flex-1 min-w-[12rem]"
                            onSubmit={e => { e.preventDefault(); update({ person: personDraft.trim() }); }}
                        >
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                            <input
                                type="text"
                                value={personDraft}
                                onChange={e => setPersonDraft(e.target.value)}
                                onBlur={() => { if (personDraft.trim() !== filters.person) update({ person: personDraft.trim() }); }}
                                placeholder="Person (exact username), then Enter"
                                aria-label="Person"
                                className="w-full pl-9 pr-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-brand-blue focus:border-brand-blue"
                            />
                        </form>
                    </div>

                    {(filters.objectId || !kindIsPreset || filtered) && (
                        <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
                            {filters.objectId && isObjectType(filters.objectType) && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-brand-blue">
                                    {TYPE_META[filters.objectType].label}: {filters.objectLabel}
                                    <button type="button" aria-label="Clear object" onClick={() => update({ objectId: '', objectLabel: '' })}><X size={12} /></button>
                                </span>
                            )}
                            {!kindIsPreset && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-1 text-brand-blue">
                                    {verbLabel(filters.kind)}
                                    <button type="button" aria-label="Clear kind" onClick={() => update({ kind: '' })}><X size={12} /></button>
                                </span>
                            )}
                            {filtered && (
                                <button type="button" onClick={() => { setPersonDraft(''); setFilters(NO_FILTERS); }} className="text-gray-500 underline hover:text-gray-800">
                                    Clear all filters
                                </button>
                            )}
                        </div>
                    )}

                    {(feed?.error || openError) && (
                        <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                            <AlertCircle size={16} className="mt-0.5 shrink-0" />
                            <span className="flex-1">{openError || `Couldn't load activity: ${feed?.error}`}</span>
                            {openError && (
                                <button type="button" aria-label="Dismiss" onClick={() => setOpenError(null)} className="opacity-60 hover:opacity-100">
                                    <X size={14} />
                                </button>
                            )}
                        </div>
                    )}

                    <div className="overflow-x-auto border border-gray-200 rounded-lg">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">When</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Who</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">What</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">On</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Details</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {loading && events.length === 0 ? (
                                    <tr><td colSpan={5} className="px-6 py-8 text-center text-gray-500 text-sm">Loading...</td></tr>
                                ) : events.length === 0 ? (
                                    <tr><td colSpan={5} className="px-6 py-8 text-center text-gray-500 text-sm">
                                        {filtered ? 'Nothing matches these filters.' : 'Nothing has been recorded yet.'}
                                    </td></tr>
                                ) : events.map(e => {
                                    const typed = isObjectType(e.object_type) ? TYPE_META[e.object_type] : null;
                                    const openable = canOpen(e);
                                    // An action's widget may be a built-in type, which has no row to find.
                                    const tag = e.source === 'event' && e.object_state ? STATE_TAG[e.object_state] : undefined;
                                    const gone = e.source === 'event' && e.object_state === 'deleted';
                                    return (
                                        <tr key={e.key} className={clsx('hover:bg-gray-50', loading && 'opacity-60')}>
                                            <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap" title={formatServerTime(e.at)}>{ago(e.at, now)}</td>
                                            <td className="px-4 py-3 text-sm whitespace-nowrap">
                                                <button type="button" onClick={() => showPerson(e.username)} className="text-gray-800 hover:text-brand-blue truncate max-w-[14rem]" title="Show this person">
                                                    {e.username}
                                                </button>
                                            </td>
                                            <td className="px-4 py-3 text-sm">
                                                <button type="button" onClick={() => update({ kind: e.verb })} className="text-left group" title="Show only this kind">
                                                    <div className="text-gray-900 group-hover:text-brand-blue">{verbLabel(e.verb)}</div>
                                                    <div className="text-[11px] text-gray-400 font-mono">{e.verb}</div>
                                                </button>
                                            </td>
                                            <td className="px-4 py-3 text-sm">
                                                {typed && e.object_id ? (
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        <typed.Icon size={15} className="shrink-0 text-gray-400" aria-label={typed.label} />
                                                        <div className="min-w-0">
                                                            <div className="flex items-center gap-1.5">
                                                                <span className={clsx('truncate max-w-[16rem]', gone ? 'text-gray-400 line-through' : 'text-gray-900')} title={e.object_id}>
                                                                    {e.object_name || (typeof e.detail.widget_name === 'string' ? e.detail.widget_name : e.object_id)}
                                                                </span>
                                                                {tag && <span className="text-[11px] text-gray-400">{tag}</span>}
                                                            </div>
                                                            <div className="flex items-center gap-2 mt-0.5">
                                                                {openable && (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => openItem(e.object_type as ObjectType, e.object_id as string, e.object_name)}
                                                                        className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-blue hover:underline"
                                                                    >
                                                                        {e.object_type === 'app' ? <ExternalLink size={11} /> : <Pencil size={11} />}
                                                                        {OPEN_LABEL[e.object_type as ObjectType]}
                                                                    </button>
                                                                )}
                                                                <button type="button" onClick={() => showObject(e)} className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-800">
                                                                    <Filter size={11} /> Only this
                                                                </button>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <span className="text-gray-400">{e.object_id || '—'}</span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-sm"><DetailChips detail={e.detail} /></td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {feed?.next && !loading && (
                        <div className="mt-4 flex items-center justify-center gap-3">
                            <button
                                type="button"
                                onClick={loadMore}
                                disabled={more.busy}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                            >
                                {more.busy && <Loader2 size={14} className="animate-spin" />} Show older
                            </button>
                            {more.error && <span className="text-sm text-red-600">{more.error}</span>}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
