import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowDown, Award, RefreshCw, Rocket, X } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';
import { useDashboardStore } from '../store/dashboardStore';
import {
    ENV_LABELS, canPromote, certifyWidget, loadWidgetPromotion, parseServerTime, transferWidget,
} from '../promotion';
import type { Env, EnvPromotion, PromotionVersion, WidgetPromotion } from '../promotion';

interface WidgetPromotionPanelProps {
    widgetId: string | null;
    domain: string;
    onClose: () => void;
    onNotice: (n: { tone: 'ok' | 'error'; text: string }) => void;
}

type PendingAction =
    | { kind: 'promote'; source: Env; target: Env; version: number }
    | { kind: 'rollback'; env: Env; version: number; retired: number[] }
    | { kind: 'certify'; version: number };

const ENV_CHIP: Record<Env, string> = {
    dev: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    test: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    prod: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
};

const label = (env: Env, version: number) => `${ENV_LABELS[env]} v${version}`;

const when = (ts: string | null): string => {
    const date = parseServerTime(ts);
    if (!date) return '';
    const minutes = Math.max(0, (Date.now() - date.getTime()) / 60000);
    if (minutes < 1.5) return 'just now';
    if (minutes < 60) return `${Math.round(minutes)}m ago`;
    const hours = minutes / 60;
    if (hours < 24) return `${Math.round(hours)}h ago`;
    const days = hours / 24;
    return days < 7 ? `${Math.round(days)}d ago` : date.toLocaleDateString();
};

const versionRange = (versions: number[]) => {
    const sorted = [...versions].sort((a, b) => a - b);
    if (sorted.length === 0) return '';
    return sorted.length === 1 ? `v${sorted[0]}` : `v${sorted[0]}–v${sorted[sorted.length - 1]}`;
};

const Stage: React.FC<{
    env: Env;
    state: EnvPromotion;
    canWrite: boolean;
    busy: boolean;
    onRetry: () => void;
    onRollback: (version: number) => void;
    onCertify: (head: PromotionVersion) => void;
}> = ({ env, state, canWrite, busy, onRetry, onRollback, onCertify }) => {
    const { head, versions, error } = state;
    const older = versions.slice(1);
    // The author is copied along with the code, so outside Dev the name is who
    // wrote the version, not who promoted it — the timestamp is the promotion.
    const byline = head
        ? `${env === 'dev' ? 'Saved' : 'Promoted'} ${when(head.timestamp)}${head.created_by ? ` · ${env === 'dev' ? 'by' : 'written by'} ${head.created_by}` : ''}`
        : '';

    return (
        <div className="border border-slate-700 rounded-lg bg-slate-800/60 p-3">
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider ${ENV_CHIP[env]}`}>
                    {ENV_LABELS[env]}
                </span>
                {head && <span className="text-sm text-slate-200 font-medium">{label(env, head.version)}</span>}
                {env === 'prod' && head?.is_certified && (
                    <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-300 flex items-center gap-1">
                        <Award size={10} /> Certified
                    </span>
                )}
            </div>

            {error ? (
                <div className="mt-2 text-xs text-rose-300 bg-rose-950/40 border border-rose-900/50 rounded-md p-2 flex items-start justify-between gap-2">
                    <span className="break-words">Couldn't read {ENV_LABELS[env]}: {error}</span>
                    <button onClick={onRetry} className="shrink-0 underline hover:text-rose-200">Retry</button>
                </div>
            ) : head ? (
                <>
                    <div
                        className="mt-1 text-xs text-slate-400 break-words"
                        title={parseServerTime(head.timestamp)?.toLocaleString() ?? ''}
                    >
                        {byline}
                        <span className="text-slate-500"> · {head.lines} lines</span>
                    </div>
                    {canWrite && (older.length > 0 || (env === 'prod' && !head.is_certified)) && (
                        <div className="mt-2 flex items-center gap-2 flex-wrap">
                            {older.length > 0 && (
                                <select
                                    value=""
                                    disabled={busy}
                                    onChange={e => { if (e.target.value) onRollback(Number(e.target.value)); }}
                                    aria-label={`Roll back ${ENV_LABELS[env]}`}
                                    className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                                >
                                    <option value="">Roll back to…</option>
                                    {older.map(v => (
                                        <option key={v.version} value={v.version}>
                                            {label(env, v.version)} · {v.lines} lines{v.timestamp ? ` · ${when(v.timestamp)}` : ''}
                                        </option>
                                    ))}
                                </select>
                            )}
                            {env === 'prod' && !head.is_certified && (
                                <button
                                    onClick={() => onCertify(head)}
                                    disabled={busy}
                                    className="px-2.5 py-1 text-xs font-medium rounded-md bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
                                >
                                    <Award size={12} /> Certify
                                </button>
                            )}
                        </div>
                    )}
                </>
            ) : (
                <div className="mt-1 text-xs text-slate-500">Not in {ENV_LABELS[env]} yet</div>
            )}
        </div>
    );
};

const PromoteStep: React.FC<{
    source: Env;
    target: Env;
    data: WidgetPromotion;
    busy: boolean;
    onPromote: (source: Env, target: Env, version: number) => void;
}> = ({ source, target, data, busy, onPromote }) => {
    const head = data[source].head;
    const blocked = !head || !!data[source].error || !!data[target].error;
    return (
        <div className="flex items-center gap-2 pl-3">
            <ArrowDown size={14} className="text-slate-600 shrink-0" />
            <button
                onClick={() => head && onPromote(source, target, head.version)}
                disabled={busy || blocked}
                className="px-2.5 py-1 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
                Promote to {ENV_LABELS[target]}
            </button>
            <span className="text-xs text-slate-500">
                {head ? `copies ${label(source, head.version)}` : `nothing in ${ENV_LABELS[source]} to copy`}
            </span>
        </div>
    );
};

/**
 * Dev → Test → Prod for the widget open in Widget Studio: what each env serves,
 * and — for editors and admins on its domain — promote, roll back and certify.
 * The same operations as Admin Panel → Widget Promotion, through `promotion.ts`.
 */
export const WidgetPromotionPanel: React.FC<WidgetPromotionPanelProps> = ({ widgetId, domain, onClose, onNotice }) => {
    const { isAdmin, domainPermissions } = useDashboardStore();
    // Tagged with the widget it describes, so switching widgets shows the spinner
    // instead of the previous widget's pipeline.
    const [loaded, setLoaded] = useState<{ id: string; data: WidgetPromotion } | null>(null);
    const [reloading, setReloading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [pending, setPending] = useState<PendingAction | null>(null);
    // Only the newest load may land; a slow read finishing after a write's reload
    // would otherwise put the pre-write state back on screen.
    const runRef = useRef(0);

    const load = useCallback(async () => {
        if (!widgetId) return;
        const run = ++runRef.current;
        const data = await loadWidgetPromotion(widgetId);
        if (run !== runRef.current) return;
        setLoaded({ id: widgetId, data });
        setReloading(false);
    }, [widgetId]);

    useEffect(() => { load(); }, [load]);

    const refresh = () => { setReloading(true); load(); };

    const data = loaded && loaded.id === widgetId ? loaded.data : null;
    // The server checks the saved row's domain, which may differ from an unsaved
    // edit to the Domain field.
    const savedDomain = data?.dev.head?.domain || data?.test.head?.domain || data?.prod.head?.domain || domain;
    const promoter = canPromote(isAdmin, domainPermissions, savedDomain);
    const widgetName = data?.prod.head?.name || data?.test.head?.name || data?.dev.head?.name || 'this widget';

    const execute = async () => {
        if (!pending || !widgetId) return;
        const action = pending;
        setPending(null);
        setBusy(true);
        const result = action.kind === 'certify'
            ? await certifyWidget(widgetId, action.version)
            : action.kind === 'rollback'
                // A rollback reads the version from its source before retiring the
                // newer ones, and the env being rolled back is the one place that
                // version is certain to exist.
                ? await transferWidget({ widgetId, version: action.version, sourceEnv: action.env, targetEnv: action.env, isRollback: true })
                : await transferWidget({ widgetId, version: action.version, sourceEnv: action.source, targetEnv: action.target });
        onNotice({ tone: result.ok ? 'ok' : 'error', text: result.message });
        await load();
        setBusy(false);
    };

    const confirm = (() => {
        if (!pending) return null;
        if (pending.kind === 'promote') {
            return (
                <ConfirmModal
                    title="Promote Widget"
                    message={`Promote '${widgetName}' to ${ENV_LABELS[pending.target]}? This copies ${label(pending.source, pending.version)}.`}
                    detail={`It becomes ${ENV_LABELS[pending.target]}'s next version. Unsaved edits in the editor are not included.`}
                    confirmLabel="Promote"
                    variant="primary"
                    onConfirm={execute}
                    onCancel={() => setPending(null)}
                />
            );
        }
        if (pending.kind === 'rollback') {
            return (
                <ConfirmModal
                    title="Roll Back Widget"
                    message={`Roll back '${widgetName}' in ${ENV_LABELS[pending.env]} to ${label(pending.env, pending.version)}?`}
                    detail={`${ENV_LABELS[pending.env]} ${versionRange(pending.retired)} will be deprecated, so ${label(pending.env, pending.version)} becomes what ${ENV_LABELS[pending.env]} serves.`}
                    confirmLabel={`Roll Back to v${pending.version}`}
                    variant="warning"
                    onConfirm={execute}
                    onCancel={() => setPending(null)}
                />
            );
        }
        return (
            <ConfirmModal
                title="Certify Widget"
                message={`Mark '${widgetName}' ${label('prod', pending.version)} as Enterprise Ready?`}
                detail="This widget will be flagged as certified and visible to all users as enterprise-grade."
                confirmLabel="Certify"
                variant="primary"
                onConfirm={execute}
                onCancel={() => setPending(null)}
            />
        );
    })();

    const stage = (env: Env) => data && (
        <Stage
            env={env}
            state={data[env]}
            canWrite={promoter}
            busy={busy}
            onRetry={refresh}
            onRollback={version => setPending({
                kind: 'rollback', env, version,
                retired: data[env].versions.filter(v => v.version > version).map(v => v.version),
            })}
            onCertify={head => setPending({ kind: 'certify', version: head.version })}
        />
    );

    const promoteStep = (source: Env, target: Env) => data && (!promoter ? (
        <div className="pl-3"><ArrowDown size={14} className="text-slate-600" /></div>
    ) : (
        <PromoteStep
            source={source}
            target={target}
            data={data}
            busy={busy}
            onPromote={(s, t, version) => setPending({ kind: 'promote', source: s, target: t, version })}
        />
    ));

    return (
        <div className="absolute inset-y-0 right-0 w-[26rem] max-w-full bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col z-20">
            <div className="p-4 border-b border-slate-700 flex items-start justify-between gap-2">
                <div>
                    <div className="flex items-center gap-2 text-slate-100 font-semibold">
                        <Rocket size={16} className="text-indigo-400" />
                        Promotion
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                        Promotion copies the last saved version, not unsaved edits in the editor.
                    </p>
                </div>
                <div className="flex items-center gap-1">
                    {widgetId && (
                        <button
                            onClick={refresh}
                            disabled={busy || reloading}
                            aria-label="Refresh promotion status"
                            className="p-1 text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-800 transition-colors disabled:opacity-50"
                        >
                            <RefreshCw size={16} className={reloading || busy ? 'animate-spin' : ''} />
                        </button>
                    )}
                    <button onClick={onClose} aria-label="Close promotion" className="p-1 text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-800 transition-colors">
                        <X size={16} />
                    </button>
                </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-2">
                {!widgetId ? (
                    <p className="text-xs text-slate-500">
                        This widget hasn't been published yet. Save it first, then promote it from Dev to Test and Prod.
                    </p>
                ) : !data ? (
                    <p className="text-xs text-slate-500 flex items-center gap-2"><RefreshCw size={12} className="animate-spin" /> Loading…</p>
                ) : (
                    <>
                        {stage('dev')}
                        {promoteStep('dev', 'test')}
                        {stage('test')}
                        {promoteStep('test', 'prod')}
                        {stage('prod')}
                        {!promoter && (
                            <p className="pt-2 text-xs text-slate-500">
                                Only an editor or admin on the {savedDomain || 'General'} domain can promote this widget.
                            </p>
                        )}
                    </>
                )}
            </div>

            {confirm && createPortal(confirm, document.body)}
        </div>
    );
};

export default WidgetPromotionPanel;
