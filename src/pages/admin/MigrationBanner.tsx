import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    AlertCircle, AlertTriangle, CheckCircle2, ChevronRight, Loader2, Minus, Plus, RefreshCw, Search, User, Users, X,
} from 'lucide-react';
import clsx from 'clsx';
import { requestJson, type PrincipalType } from '../../sharing';
import { formatServerTime, parseServerTime } from './time';

interface MigrationPrincipal {
    principal: string;
    principal_type: PrincipalType;
    gained: string[];
    lost: string[];
}

interface MigrationReport {
    ran: boolean;
    failed: boolean;
    ran_at: string | null;
    summary: Partial<Record<'admins' | 'grants' | 'drafts_created' | 'pins_dropped' | 'objects', number>>;
    principals: MigrationPrincipal[];
    notes: string[];
}

const REPORT_URL = '/api/sharing/migration/report';
const RETRY_URL = '/api/sharing/migration/retry';
// The banner is for the weeks after the cutover; a failure shows however old it is.
const RECENT_DAYS = 30;
const DISMISS_KEY = 'sccc-migration-banner-dismissed';
const PRINCIPALS_SHOWN = 200;

const SUMMARY_LABELS: [keyof MigrationReport['summary'], string][] = [
    ['objects', 'Objects given access lists'],
    ['grants', 'Grants written'],
    ['admins', 'Administrators'],
    ['drafts_created', 'Drafts from Dev / Test'],
    ['pins_dropped', 'Widget pins dropped'],
];

const recent = (ranAt: string | null): boolean => {
    const d = parseServerTime(ranAt);
    return !d || Date.now() - d.getTime() < RECENT_DAYS * 24 * 60 * 60 * 1000;
};

const readDismissed = (): string | null => {
    try { return localStorage.getItem(DISMISS_KEY); } catch { return null; }
};

/**
 * The cutover from role mappings and Dev/Test/Prod workspaces to sharing and
 * drafts runs once at startup (`services/access_migration.py`,
 * `services/consolidation.py`). This tells admins it happened, or that it failed
 * and some access or work may not have carried over (startup carries on either
 * way, so Retry is the only way to finish it), and who gained or lost what.
 * It goes with the migrations in the next release.
 */
export const MigrationBanner: React.FC = () => {
    const [report, setReport] = useState<MigrationReport | null>(null);
    const [open, setOpen] = useState(false);
    const [dismissed, setDismissed] = useState<string | null>(readDismissed);

    const load = useCallback(() => requestJson<MigrationReport>(REPORT_URL)
        .then(setReport)
        // No report to read (older server, or not an admin): no banner.
        .catch(() => setReport(null)), []);

    useEffect(() => { load(); }, [load]);

    if (!report) return null;
    const failed = !!report.failed;
    const dismissKey = report.ran_at || 'ran';
    const show = failed || (report.ran && recent(report.ran_at) && dismissed !== dismissKey);
    if (!show && !open) return null;

    const dismiss = () => {
        try { localStorage.setItem(DISMISS_KEY, dismissKey); } catch { /* private browsing */ }
        setDismissed(dismissKey);
    };

    const lost = (report.principals || []).filter(p => p.lost.length > 0).length;

    return (
        <>
            {show && (
                <div
                    role={failed ? 'alert' : 'status'}
                    className={clsx(
                        'mx-6 mt-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm',
                        failed ? 'border-red-200 bg-red-50 text-red-800' : 'border-blue-200 bg-blue-50 text-brand-navy',
                    )}
                >
                    {failed
                        ? <AlertTriangle size={18} className="mt-0.5 shrink-0 text-red-500" />
                        : <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-brand-blue" />}
                    <div className="flex-1 min-w-0">
                        <p className="font-semibold">
                            {failed ? 'Moving to sharing and drafts didn’t finish' : 'This app moved to sharing and drafts'}
                        </p>
                        <p className="mt-0.5 text-xs opacity-90">
                            {failed
                                ? 'Some access from role mappings, or some Dev and Test work, may not have carried over. Review what happened, then retry.'
                                : <>
                                    Role mappings became direct shares, and Dev and Test work became drafts
                                    {report.ran_at ? <> on {formatServerTime(report.ran_at)}</> : null}.
                                    {lost > 0 && <> {lost} {lost === 1 ? 'person or group' : 'people or groups'} lost some access.</>}
                                </>}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => setOpen(true)}
                        className={clsx(
                            'shrink-0 inline-flex items-center gap-1 text-xs font-semibold hover:underline',
                            failed ? 'text-red-700' : 'text-brand-blue',
                        )}
                    >
                        View details <ChevronRight size={14} />
                    </button>
                    {!failed && (
                        <button type="button" onClick={dismiss} aria-label="Dismiss" className="shrink-0 rounded p-0.5 opacity-60 hover:opacity-100">
                            <X size={14} />
                        </button>
                    )}
                </div>
            )}
            {open && <MigrationDetails report={report} onClose={() => setOpen(false)} onReload={load} />}
        </>
    );
};

const MigrationDetails: React.FC<{
    report: MigrationReport;
    onClose: () => void;
    onReload: () => Promise<void>;
}> = ({ report, onClose, onReload }) => {
    const [query, setQuery] = useState('');
    const [onlyLost, setOnlyLost] = useState(false);
    const [retrying, setRetrying] = useState(false);
    const [retryError, setRetryError] = useState<string | null>(null);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [onClose]);

    const principals = useMemo(() => {
        const q = query.trim().toLowerCase();
        return (report.principals || []).filter(p => {
            if (onlyLost && p.lost.length === 0) return false;
            if (!q) return true;
            return p.principal.toLowerCase().includes(q)
                || p.gained.some(g => g.toLowerCase().includes(q))
                || p.lost.some(l => l.toLowerCase().includes(q));
        });
    }, [report.principals, query, onlyLost]);

    const retry = async () => {
        setRetrying(true);
        setRetryError(null);
        try {
            await requestJson(RETRY_URL, { method: 'POST' });
            await onReload();
        } catch (e) {
            setRetryError(e instanceof Error ? e.message : String(e));
        } finally {
            setRetrying(false);
        }
    };

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Migration report"
                className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150"
            >
                <div className="flex items-start gap-3 px-6 pt-5 pb-3 border-b border-gray-100">
                    <div className="flex-1 min-w-0">
                        <h2 className="text-lg font-semibold text-gray-900">Moving to sharing and drafts</h2>
                        <p className="text-xs text-gray-500 mt-0.5">
                            {report.failed
                                ? 'The last attempt failed.'
                                : report.ran
                                    ? `Ran ${formatServerTime(report.ran_at)}.`
                                    : 'Not run yet.'}
                            {' '}Access before is what role mappings and the Dev/Test/Prod workspaces gave; access after is each object's share list.
                        </p>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Close" className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                        <X size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
                    {report.failed && (
                        <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-red-500" />
                            <div className="flex-1">
                                <p>Startup carried on without it. Retry runs it again; anything already moved is left as it is.</p>
                                {retryError && <p className="mt-1 text-xs">Retry failed: {retryError}</p>}
                            </div>
                            <button
                                type="button"
                                onClick={retry}
                                disabled={retrying}
                                className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                            >
                                {retrying ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                                Retry
                            </button>
                        </div>
                    )}

                    <dl className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                        {SUMMARY_LABELS.map(([key, label]) => (
                            <div key={key} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                                <dt className="text-[11px] text-gray-500 leading-tight">{label}</dt>
                                <dd className="text-lg font-semibold text-gray-900">{report.summary?.[key] ?? 0}</dd>
                            </div>
                        ))}
                    </dl>

                    {report.notes?.length > 0 && (
                        <div>
                            <h3 className="text-sm font-semibold text-gray-800 mb-1">Notes</h3>
                            <ul className="list-disc pl-5 space-y-1 text-sm text-gray-600">
                                {report.notes.map((n, i) => <li key={i}>{n}</li>)}
                            </ul>
                        </div>
                    )}

                    <div>
                        <div className="flex flex-wrap items-center gap-3 mb-2">
                            <h3 className="text-sm font-semibold text-gray-800">Who gained or lost access</h3>
                            <label className="flex items-center gap-1.5 text-xs text-gray-600">
                                <input type="checkbox" checked={onlyLost} onChange={e => setOnlyLost(e.target.checked)} className="rounded border-gray-300" />
                                Only those who lost something
                            </label>
                            <div className="relative ml-auto">
                                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 w-3.5 h-3.5" />
                                <input
                                    type="text"
                                    value={query}
                                    onChange={e => setQuery(e.target.value)}
                                    placeholder="Search"
                                    className="pl-8 pr-3 py-1 border border-gray-300 rounded-md text-xs focus:outline-none focus:ring-1 focus:ring-brand-blue focus:border-brand-blue"
                                />
                            </div>
                        </div>
                        {principals.length === 0 ? (
                            <p className="text-sm text-gray-500 py-4 text-center border border-dashed border-gray-200 rounded-lg">
                                {(report.principals || []).length === 0 ? 'Nobody’s access changed.' : 'Nobody matches.'}
                            </p>
                        ) : (
                            <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
                                {principals.slice(0, PRINCIPALS_SHOWN).map(p => (
                                    <li key={p.principal} className="px-3 py-2">
                                        <div className="flex items-center gap-2 text-sm font-medium text-gray-900">
                                            {p.principal_type === 'group'
                                                ? <Users size={14} className="shrink-0 text-gray-400" aria-label="Group" />
                                                : <User size={14} className="shrink-0 text-gray-400" aria-label="User" />}
                                            <span className="truncate" title={p.principal}>{p.principal}</span>
                                        </div>
                                        <div className="mt-1 pl-6 space-y-0.5">
                                            {p.gained.map((g, i) => (
                                                <p key={`g${i}`} className="flex items-start gap-1.5 text-xs text-emerald-700">
                                                    <Plus size={12} className="mt-px shrink-0" /> {g}
                                                </p>
                                            ))}
                                            {p.lost.map((l, i) => (
                                                <p key={`l${i}`} className="flex items-start gap-1.5 text-xs text-red-700">
                                                    <Minus size={12} className="mt-px shrink-0" /> {l}
                                                </p>
                                            ))}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {principals.length > PRINCIPALS_SHOWN && (
                            <p className="mt-1 text-xs text-gray-500 flex items-center gap-1">
                                <AlertCircle size={12} /> Showing {PRINCIPALS_SHOWN} of {principals.length}. Search to narrow it down.
                            </p>
                        )}
                    </div>
                </div>

                <div className="flex justify-end px-6 py-3 bg-gray-50 border-t border-gray-100">
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg bg-brand-blue px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-navy"
                    >
                        Done
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
};
