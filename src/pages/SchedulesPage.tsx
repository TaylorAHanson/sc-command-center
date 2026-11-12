import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    AlertCircle, CalendarClock, ChevronDown, ChevronRight, Link2, Loader2, Pause, Pencil, Play, RefreshCw, Trash2, Zap,
} from 'lucide-react';
import { findCapability, useCapabilities } from '../capabilities';
import { ConfirmModal } from '../components/ConfirmModal';
import { ScheduleDialog } from '../components/ScheduleDialog';
import {
    connectUrl, currentReturnPath, deleteSchedule, describeRecurrence, disconnectAccount, expiresIn, expiresWithin,
    fetchConnection, formatWhen, formOf, KIND_LABELS, listRuns, listSchedules, patchPayload, pauseSchedule,
    RECONNECT_REASONS, relativeTime, resumeSchedule, RUN_STATUS_LABELS, runScheduleNow, SCHEDULING_UNAVAILABLE,
    statusLabel, TRIGGER_LABELS, updateSchedule,
    type ConnectionStatus, type Result, type Schedule, type ScheduleRun,
} from '../schedules';

type ListResult = Result<{ schedules: Schedule[]; can_see_all: boolean }>;
type Notice = { kind: 'ok' | 'error'; text: string };
type Action = 'run' | 'pause' | 'resume' | 'delete';

/** The scheduler picks a queued run up within about 30 seconds; look again just after. */
const RUN_REFRESH_MS = 35_000;

const without = <T,>(record: Record<string, T>, key: string): Record<string, T> => {
    const next = { ...record };
    delete next[key];
    return next;
};

const PRIMARY = 'flex items-center gap-1.5 rounded-lg bg-brand-blue px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50';
const SECONDARY = 'flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';
const ICON_BUTTON = 'flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-brand-blue disabled:cursor-not-allowed disabled:opacity-40';

const STATUS_STYLES: Record<string, string> = {
    active: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    paused: 'border-gray-200 bg-gray-100 text-gray-700',
    failures: 'border-red-200 bg-red-50 text-red-800',
    needs_reconnect: 'border-amber-200 bg-amber-50 text-amber-900',
};

const RUN_STYLES: Record<string, string> = {
    ok: 'text-emerald-700',
    skipped: 'text-gray-600',
    failed: 'text-red-700',
    needs_reconnect: 'text-amber-800',
};

const StatusBadge: React.FC<{ schedule: Schedule }> = ({ schedule }) => {
    const style = schedule.status === 'paused' && schedule.paused_reason === 'failures' ? 'failures' : schedule.status;
    return (
        <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[style] || STATUS_STYLES.paused}`}>
            {statusLabel(schedule)}
        </span>
    );
};

/** A link stored with a schedule, made clickable only when it points back at this app. */
const ownLink = (link: string | null): string | null => {
    if (!link) return null;
    try {
        const url = new URL(link, window.location.origin);
        return url.origin === window.location.origin ? url.href : null;
    } catch {
        return null;
    }
};

const emailedText = (emailed: ScheduleRun['emailed']): string =>
    typeof emailed === 'boolean' ? (emailed ? 'Yes' : 'No') : typeof emailed === 'number' ? emailed.toLocaleString() : '—';

const RunHistory: React.FC<{ state: Result<{ runs: ScheduleRun[] }> | 'loading' | undefined; report: boolean }> = ({ state, report }) => {
    if (!state || state === 'loading') {
        return <p className="flex items-center gap-2 py-2 text-xs text-gray-500"><Loader2 size={12} className="animate-spin" /> Loading runs…</p>;
    }
    if (!state.ok) return <p role="alert" className="py-2 text-xs text-red-600">Couldn’t load the runs: {state.error}</p>;
    if (!state.data.runs.length) return <p className="py-2 text-xs text-gray-500">No runs yet.</p>;
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
                <thead className="text-gray-500">
                    <tr>
                        <th className="py-1.5 pr-3 font-semibold">Started</th>
                        <th className="py-1.5 pr-3 font-semibold">How</th>
                        <th className="py-1.5 pr-3 font-semibold">Result</th>
                        <th className="py-1.5 pr-3 text-right font-semibold">Rows</th>
                        {report && <th className="py-1.5 pr-3 text-right font-semibold">Emailed</th>}
                        <th className="py-1.5 font-semibold">Details</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 text-gray-800">
                    {state.data.runs.map(run => (
                        <tr key={String(run.id)} className="align-top">
                            <td className="whitespace-nowrap py-1.5 pr-3" title={run.finished_at ? `Finished ${formatWhen(run.finished_at)}` : undefined}>
                                {formatWhen(run.started_at) || '—'}
                            </td>
                            <td className="whitespace-nowrap py-1.5 pr-3">{TRIGGER_LABELS[run.trigger] || run.trigger}</td>
                            <td className={`whitespace-nowrap py-1.5 pr-3 font-medium ${RUN_STYLES[run.status] || ''}`}>
                                {RUN_STATUS_LABELS[run.status] || run.status}
                            </td>
                            <td className="py-1.5 pr-3 text-right tabular-nums">{run.rows ?? '—'}</td>
                            {report && <td className="py-1.5 pr-3 text-right tabular-nums">{emailedText(run.emailed)}</td>}
                            <td className="break-words py-1.5 text-gray-600">
                                {run.error || (run.status === 'skipped' ? 'Nothing sent under its Send rule.' : '')}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

const ConnectionCard: React.FC<{
    devMode: boolean;
    state: Result<ConnectionStatus> | null;
    onConnect: () => void;
    onDisconnect: () => void;
    onRetry: () => void;
}> = ({ devMode, state, onConnect, onDisconnect, onRetry }) => {
    let tone = 'border-gray-200 bg-white';
    let body: React.ReactNode;
    let actions: React.ReactNode = null;

    if (devMode) {
        body = <p className="text-sm text-gray-700">Local run: schedules run as the app’s service principal, so there’s no account to connect.</p>;
    } else if (!state) {
        body = <p className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Checking your connection…</p>;
    } else if (!state.ok) {
        body = <p className="text-sm text-red-600">Couldn’t check your connection: {state.error}</p>;
        actions = <button type="button" onClick={onRetry} className={SECONDARY}><RefreshCw size={14} /> Try again</button>;
    } else if (state.data.connected && !state.data.needs_reconnect) {
        const c = state.data;
        const soon = expiresWithin(c.expires_at, 7);
        if (soon) tone = 'border-amber-200 bg-amber-50';
        body = (
            <>
                <p className="text-sm font-medium text-gray-900">
                    Connected{c.expires_at ? ` · ${expiresIn(c.expires_at)}` : ''}
                </p>
                <p className="text-xs text-gray-600">
                    {soon
                        ? 'Reconnect before then, or your schedules stop running until you do.'
                        : 'Your schedules run as you while it lasts. Reconnecting renews it.'}
                    {c.connected_at ? ` Connected ${formatWhen(c.connected_at)}.` : ''}
                </p>
            </>
        );
        actions = (
            <>
                <button type="button" onClick={onConnect} className={soon ? PRIMARY : SECONDARY}><RefreshCw size={14} /> Reconnect</button>
                <button type="button" onClick={onDisconnect} className="rounded-lg px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50">Disconnect</button>
            </>
        );
    } else if (state.data.needs_reconnect) {
        tone = 'border-amber-200 bg-amber-50';
        body = (
            <>
                <p className="text-sm font-medium text-amber-900">Needs reconnecting</p>
                <p className="text-xs text-amber-900">
                    {RECONNECT_REASONS[state.data.reason || ''] || 'Your connection stopped working.'} Your schedules wait until you reconnect.
                </p>
            </>
        );
        actions = <button type="button" onClick={onConnect} className={PRIMARY}><Link2 size={14} /> Reconnect</button>;
    } else {
        body = (
            <>
                <p className="text-sm font-medium text-gray-900">Not connected</p>
                <p className="text-xs text-gray-600">Schedules run as you, so connect your account once and they can run while you’re away.</p>
            </>
        );
        actions = <button type="button" onClick={onConnect} className={PRIMARY}><Link2 size={14} /> Connect your account</button>;
    }

    return (
        <section aria-label="Your connection" className={`flex flex-wrap items-center gap-4 rounded-xl border px-5 py-4 shadow-sm ${tone}`}>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-brand-blue" aria-hidden="true">
                <Link2 size={17} />
            </span>
            <div className="min-w-0 flex-1 space-y-0.5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Your Databricks account</h2>
                {body}
            </div>
            {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </section>
    );
};

const ScheduleRow: React.FC<{
    schedule: Schedule;
    showOwner: boolean;
    busy: Action | undefined;
    notice: Notice | undefined;
    expanded: boolean;
    runs: Result<{ runs: ScheduleRun[] }> | 'loading' | undefined;
    onAction: (action: Action) => void;
    onEdit: () => void;
    onToggleRuns: () => void;
}> = ({ schedule: s, showOwner, busy, notice, expanded, runs, onAction, onEdit, onToggleRuns }) => {
    const report = s.kind === 'email_report';
    const recipients = s.recipients?.length ?? 0;
    const link = ownLink(s.view_link);
    const last = s.last_run;
    const lastAt = last?.finished_at || last?.started_at || null;
    const paused = s.status === 'paused';
    const historyId = `runs-${String(s.id)}`;

    return (
        <li className="px-5 py-4">
            <div className="flex flex-wrap items-start gap-3">
                <button
                    type="button"
                    onClick={onToggleRuns}
                    aria-expanded={expanded}
                    aria-controls={historyId}
                    aria-label={expanded ? 'Hide run history' : 'Show run history'}
                    className="mt-0.5 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                >
                    {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-sm font-semibold text-gray-900">{s.name}</h3>
                        <StatusBadge schedule={s} />
                    </div>
                    <p className="text-xs text-gray-600">
                        {KIND_LABELS[s.kind]} · {describeRecurrence(s.recurrence)}
                        {report ? ` · ${recipients} ${recipients === 1 ? 'recipient' : 'recipients'}` : ''}
                    </p>
                    <p className="text-xs text-gray-600">
                        {showOwner && <>Owner <span className="font-medium text-gray-800">{s.owner}</span> · </>}
                        {s.view_name && (
                            <>From {link
                                ? <a href={link} className="font-medium text-brand-blue hover:underline">{s.view_name}</a>
                                : <span className="font-medium text-gray-800">{s.view_name}</span>} · </>
                        )}
                        Last run{' '}
                        {last ? (
                            <span title={formatWhen(lastAt)}>
                                <span className={`font-medium ${RUN_STYLES[last.status] || ''}`}>{RUN_STATUS_LABELS[last.status] || last.status}</span>
                                {lastAt ? ` ${relativeTime(lastAt)}` : ''}
                            </span>
                        ) : 'never'}
                        {' · '}Next run{' '}
                        {s.status === 'active' && s.next_run_at
                            ? <span title={formatWhen(s.next_run_at)}>{formatWhen(s.next_run_at)} ({relativeTime(s.next_run_at)})</span>
                            : s.status === 'needs_reconnect' ? 'waits for a reconnect' : paused ? 'none while paused' : '—'}
                    </p>
                    {paused && s.paused_reason === 'failures' && (
                        <p className="text-xs text-red-700">
                            Paused after {s.failure_count > 0 ? `${s.failure_count} failed runs in a row` : 'repeated failures'}. Fix the cause, then Resume.
                        </p>
                    )}
                    {last?.status === 'failed' && last.error && !(paused && s.paused_reason === 'failures') && (
                        <p className="line-clamp-2 text-xs text-red-700" title={last.error}>{last.error}</p>
                    )}
                    {notice && (
                        <p role={notice.kind === 'error' ? 'alert' : 'status'} className={`flex items-start gap-1 text-xs ${notice.kind === 'error' ? 'text-red-600' : 'text-emerald-700'}`}>
                            {notice.kind === 'error' && <AlertCircle size={13} className="mt-px shrink-0" />} {notice.text}
                        </p>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    <button type="button" onClick={() => onAction('run')} disabled={!!busy} className={ICON_BUTTON} title="Run it once now, outside its timetable">
                        {busy === 'run' ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />} Run now
                    </button>
                    {paused ? (
                        <button type="button" onClick={() => onAction('resume')} disabled={!!busy} className={ICON_BUTTON}>
                            {busy === 'resume' ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} Resume
                        </button>
                    ) : (
                        <button type="button" onClick={() => onAction('pause')} disabled={!!busy} className={ICON_BUTTON}>
                            {busy === 'pause' ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />} Pause
                        </button>
                    )}
                    <button type="button" onClick={onEdit} disabled={!!busy} className={ICON_BUTTON}>
                        <Pencil size={13} /> Edit
                    </button>
                    <button type="button" onClick={() => onAction('delete')} disabled={!!busy} className={`${ICON_BUTTON} hover:text-red-600`}>
                        {busy === 'delete' ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />} Delete
                    </button>
                </div>
            </div>
            {expanded && (
                <div id={historyId} className="ml-8 mt-3 rounded-lg border border-gray-100 bg-gray-50 px-3 py-1">
                    <RunHistory state={runs} report={report} />
                </div>
            )}
        </li>
    );
};

/**
 * My schedules (`#/schedules`): the connection scheduled work runs on, and
 * every schedule the person owns, or, for an administrator who asks, everyone's.
 * Schedules are made from a widget's Schedule button, not here.
 */
export const SchedulesPage: React.FC = () => {
    const capabilities = useCapabilities();
    const scheduling = findCapability(capabilities, 'scheduling');
    const enabled = !!scheduling?.available;
    const devMode = scheduling?.mode === 'dev';

    const [showAll, setShowAll] = useState(false);
    const [list, setList] = useState<{ all: boolean; result: ListResult } | null>(null);
    const [listKey, setListKey] = useState(0);
    const [connection, setConnection] = useState<Result<ConnectionStatus> | null>(null);
    const [connectionKey, setConnectionKey] = useState(0);
    const [busy, setBusy] = useState<Record<string, Action>>({});
    const [notices, setNotices] = useState<Record<string, Notice>>({});
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const [runs, setRuns] = useState<Record<string, Result<{ runs: ScheduleRun[] }> | 'loading'>>({});
    const [editing, setEditing] = useState<Schedule | null>(null);
    const [deleting, setDeleting] = useState<Schedule | null>(null);
    const [disconnecting, setDisconnecting] = useState(false);
    const [pageError, setPageError] = useState<string | null>(null);
    const expandedRef = useRef(expanded);
    const timers = useRef<number[]>([]);

    useEffect(() => { expandedRef.current = expanded; }, [expanded]);
    useEffect(() => () => { timers.current.forEach(t => window.clearTimeout(t)); }, []);

    useEffect(() => {
        if (!enabled) return;
        let live = true;
        void listSchedules(showAll).then(result => { if (live) setList({ all: showAll, result }); });
        return () => { live = false; };
    }, [enabled, showAll, listKey]);

    useEffect(() => {
        if (!enabled || devMode) return;
        let live = true;
        void fetchConnection().then(result => { if (live) setConnection(result); });
        return () => { live = false; };
    }, [enabled, devMode, connectionKey]);

    const current = list && list.all === showAll ? list.result : null;
    const canSeeAll = showAll || !!(list?.result.ok && list.result.data.can_see_all);

    const replace = (s: Schedule) => setList(prev => (prev && prev.result.ok ? {
        ...prev,
        result: { ...prev.result, data: { ...prev.result.data, schedules: prev.result.data.schedules.map(x => (String(x.id) === String(s.id) ? s : x)) } },
    } : prev));

    const remove = (id: string) => setList(prev => (prev && prev.result.ok ? {
        ...prev,
        result: { ...prev.result, data: { ...prev.result.data, schedules: prev.result.data.schedules.filter(x => String(x.id) !== id) } },
    } : prev));

    const loadRuns = useCallback(async (id: string) => {
        setRuns(r => ({ ...r, [id]: r[id] && r[id] !== 'loading' ? r[id] : 'loading' }));
        const result = await listRuns(id, 20);
        setRuns(r => ({ ...r, [id]: result }));
    }, []);

    const toggleRuns = (id: string) => {
        const open = !expanded[id];
        setExpanded(e => ({ ...e, [id]: open }));
        if (open) void loadRuns(id);
    };

    const act = async (s: Schedule, action: Exclude<Action, 'delete'>) => {
        const id = String(s.id);
        setBusy(b => ({ ...b, [id]: action }));
        setNotices(n => without(n, id));
        const call = action === 'run' ? runScheduleNow : action === 'pause' ? pauseSchedule : resumeSchedule;
        const result = await call(id);
        setBusy(b => without(b, id));
        if (!result.ok) {
            setNotices(n => ({ ...n, [id]: { kind: 'error', text: result.error } }));
            return;
        }
        replace(result.data);
        if (action === 'run') {
            setNotices(n => ({ ...n, [id]: { kind: 'ok', text: 'Queued: it runs within about 30 seconds.' } }));
            timers.current.push(window.setTimeout(() => {
                setNotices(n => without(n, id));
                setListKey(k => k + 1);
                if (expandedRef.current[id]) void loadRuns(id);
            }, RUN_REFRESH_MS));
        }
    };

    const confirmDelete = async () => {
        const s = deleting;
        if (!s) return;
        const id = String(s.id);
        setDeleting(null);
        setBusy(b => ({ ...b, [id]: 'delete' }));
        const result = await deleteSchedule(id);
        setBusy(b => without(b, id));
        if (result.ok) remove(id);
        else setNotices(n => ({ ...n, [id]: { kind: 'error', text: result.error } }));
    };

    const connect = () => window.location.assign(connectUrl(currentReturnPath()));

    const confirmDisconnect = async () => {
        setDisconnecting(false);
        setPageError(null);
        const result = await disconnectAccount();
        if (!result.ok) {
            setPageError(result.error);
            return;
        }
        setConnection(null);
        setConnectionKey(k => k + 1);
        setListKey(k => k + 1);
    };

    const schedules = current?.ok ? current.data.schedules : [];

    return (
        <div className="h-full overflow-y-auto bg-gray-50">
            <div className="mx-auto max-w-5xl space-y-5 p-6">
                <p className="text-sm text-gray-600">
                    Reports and statements you’ve scheduled from widgets. They run as you, with your access to data, while you’re away.
                </p>

                {!capabilities ? (
                    <p className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Loading…</p>
                ) : !enabled ? (
                    <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800">
                        <p className="font-semibold">{SCHEDULING_UNAVAILABLE}</p>
                        <p className="mt-0.5 text-xs">{scheduling?.next_step || 'An administrator can set it up under Admin Panel → Settings.'}</p>
                    </div>
                ) : (
                    <>
                        <ConnectionCard
                            devMode={devMode}
                            state={connection}
                            onConnect={connect}
                            onDisconnect={() => setDisconnecting(true)}
                            onRetry={() => { setConnection(null); setConnectionKey(k => k + 1); }}
                        />
                        {pageError && (
                            <p role="alert" className="flex items-start gap-1.5 text-sm text-red-600"><AlertCircle size={15} className="mt-0.5 shrink-0" /> {pageError}</p>
                        )}

                        <section aria-labelledby="schedules-heading" className="rounded-xl border border-gray-200 bg-white shadow-sm">
                            <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 px-5 py-3">
                                <h2 id="schedules-heading" className="text-sm font-semibold text-brand-navy">
                                    {showAll ? 'Everyone’s schedules' : 'Your schedules'}
                                    {current?.ok ? <span className="ml-1.5 font-normal text-gray-500">({schedules.length})</span> : null}
                                </h2>
                                <div className="ml-auto flex items-center gap-3">
                                    {canSeeAll && (
                                        <label className="flex items-center gap-2 text-sm text-gray-700">
                                            <input
                                                type="checkbox"
                                                checked={showAll}
                                                onChange={e => setShowAll(e.target.checked)}
                                                className="h-4 w-4 rounded border-gray-300 text-brand-blue focus:ring-brand-blue"
                                            />
                                            Everyone’s schedules
                                        </label>
                                    )}
                                    <button type="button" onClick={() => setListKey(k => k + 1)} className={ICON_BUTTON} title="Refresh the list">
                                        <RefreshCw size={13} /> Refresh
                                    </button>
                                </div>
                            </div>

                            {!current ? (
                                <p className="flex items-center gap-2 px-5 py-6 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Loading schedules…</p>
                            ) : !current.ok ? (
                                <p role="alert" className="px-5 py-6 text-sm text-red-600">{current.error}</p>
                            ) : !schedules.length ? (
                                <div className="flex flex-col items-center px-5 py-12 text-center">
                                    <CalendarClock size={28} className="text-gray-300" aria-hidden="true" />
                                    <p className="mt-2 text-sm font-medium text-gray-800">{showAll ? 'Nobody has a schedule yet.' : 'You have no schedules yet.'}</p>
                                    {!showAll && (
                                        <p className="mt-1 max-w-md text-sm text-gray-500">
                                            A widget with a Schedule button can email its results on a timetable you choose. Open a view, press Schedule on one of its widgets, and the schedule appears here.
                                        </p>
                                    )}
                                </div>
                            ) : (
                                <ul className="divide-y divide-gray-100">
                                    {schedules.map(s => {
                                        const id = String(s.id);
                                        return (
                                            <ScheduleRow
                                                key={id}
                                                schedule={s}
                                                showOwner={showAll}
                                                busy={busy[id]}
                                                notice={notices[id]}
                                                expanded={!!expanded[id]}
                                                runs={runs[id]}
                                                onAction={action => (action === 'delete' ? setDeleting(s) : void act(s, action))}
                                                onEdit={() => setEditing(s)}
                                                onToggleRuns={() => toggleRuns(id)}
                                            />
                                        );
                                    })}
                                </ul>
                            )}
                        </section>
                    </>
                )}
            </div>

            {editing && (
                <ScheduleDialog
                    schedule={editing}
                    initial={formOf(editing)}
                    sql={editing.sql}
                    allowStatement={false}
                    viewName={editing.view_name}
                    save={async form => {
                        const result = await updateSchedule(String(editing.id), patchPayload(form));
                        return result.ok ? { ok: true, schedule: result.data } : { ok: false, error: result.error };
                    }}
                    onClose={saved => {
                        setEditing(null);
                        if (saved) replace(saved);
                    }}
                />
            )}

            {deleting && (
                <ConfirmModal
                    title="Delete this schedule?"
                    message={`“${deleting.name}” stops running and can’t be brought back.`}
                    confirmLabel="Delete"
                    variant="danger"
                    onConfirm={() => void confirmDelete()}
                    onCancel={() => setDeleting(null)}
                />
            )}

            {disconnecting && (
                <ConfirmModal
                    title="Disconnect your account?"
                    message="Your schedules stop running until you connect again. They aren’t deleted."
                    confirmLabel="Disconnect"
                    variant="warning"
                    onConfirm={() => void confirmDisconnect()}
                    onCancel={() => setDisconnecting(false)}
                />
            )}
        </div>
    );
};

export default SchedulesPage;
