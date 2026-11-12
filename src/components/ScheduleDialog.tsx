import React, { useContext, useEffect, useId, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, CalendarClock, CheckCircle2, Link2, Loader2, X } from 'lucide-react';
import { findCapability, isAvailable, useCapabilities } from '../capabilities';
import { EMAIL_UNAVAILABLE, type ExecuteAction } from '../email';
import { WidgetInstanceContext } from '../hooks/useLinkState';
import { logAndCreate } from '../hooks/useWidgetSchedule';
import {
    connectUrl, createPayload, currentReturnPath, describeRecurrence, expiresIn, expiresWithin, fetchConnection,
    formatWhen, formProblem, FREQUENCIES, KIND_LABELS, looksLikeEmail, MAX_NAME_LENGTH, normalizeScheduleRequest,
    parseRecipients, RECONNECT_REASONS, relativeTime, SCHEDULING_UNAVAILABLE, SEND_WHEN, WEEKDAYS, withFrequency,
    type ConnectionStatus, type Recurrence, type Result, type Schedule, type ScheduleForm, type ScheduleKind,
    type ScheduleOutcome, type ScheduleRequest, type ScheduleSource, type SendWhen,
} from '../schedules';
import { tabLabel } from '../store/appSpec';
import { useDashboardStore } from '../store/dashboardStore';
import { resolveWidget } from '../widgetRegistry';
import { useDialog } from './sharing/useDialog';

export type SaveResult =
    | { ok: true; schedule: Schedule; connection?: ConnectionStatus | null }
    | { ok: false; error: string };

export interface ScheduleDialogProps {
    /** The schedule being edited; absent for a new one. */
    schedule?: Schedule;
    initial: ScheduleForm;
    /** The statement it runs. Shown, never edited: the schedule keeps the text it was created with. */
    sql: string;
    /** Whether "Run the statement" may be chosen, which only an executable widget offers. */
    allowStatement: boolean;
    /** A sentence above the form about what was asked for. */
    notice?: string | null;
    viewName?: string | null;
    save: (form: ScheduleForm) => Promise<SaveResult>;
    onClose: (saved: Schedule | null) => void;
}

type Phase =
    | { kind: 'editing' }
    | { kind: 'saving' }
    | { kind: 'saved'; schedule: Schedule; connection: ConnectionStatus | null };

const LABEL = 'block text-xs font-semibold uppercase tracking-wide text-gray-500';
const INPUT = 'mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-brand-blue focus:outline-none focus:ring-1 focus:ring-brand-blue disabled:bg-gray-50';
const PRIMARY = 'flex items-center gap-1.5 rounded-lg bg-brand-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50';
const SECONDARY = 'rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50';

const toggleDay = (days: number[], day: number) =>
    days.includes(day) ? days.filter(d => d !== day) : [...days, day].sort((a, b) => a - b);

let zoneList: string[] | null = null;

const timeZones = (current: string): string[] => {
    if (!zoneList) {
        try {
            zoneList = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? [];
        } catch {
            zoneList = [];
        }
    }
    return current && !zoneList.includes(current) ? [current, ...zoneList] : zoneList;
};

const segment = (on: boolean) =>
    `rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 ${on
        ? 'bg-brand-blue text-white'
        : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}`;

const RecurrenceEditor: React.FC<{ value: Recurrence; onChange: (r: Recurrence) => void; disabled: boolean }> = ({ value, onChange, disabled }) => {
    const timeId = useId();
    const zoneId = useId();
    const zones = useMemo(() => timeZones(value.tz), [value.tz]);
    const set = (patch: Partial<Recurrence>) => onChange({ ...value, ...patch });
    const minute = value.time.slice(3, 5) || '00';

    return (
        <div className="space-y-3">
            <div>
                <span className={LABEL}>How often</span>
                <div role="group" aria-label="How often" className="mt-1 flex flex-wrap gap-1.5">
                    {FREQUENCIES.map(f => (
                        <button
                            key={f.id}
                            type="button"
                            aria-pressed={value.freq === f.id}
                            disabled={disabled}
                            onClick={() => onChange(withFrequency(value, f.id))}
                            className={segment(value.freq === f.id)}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>

            {value.freq === 'weekly' && (
                <div>
                    <div className="flex items-center justify-between">
                        <span className={LABEL}>On</span>
                        <button
                            type="button"
                            disabled={disabled}
                            onClick={() => set({ days: [1, 2, 3, 4, 5] })}
                            className="text-xs font-medium text-brand-blue hover:underline disabled:opacity-50"
                        >
                            Weekdays
                        </button>
                    </div>
                    <div role="group" aria-label="Days of the week" className="mt-1 flex flex-wrap gap-1.5">
                        {WEEKDAYS.map((day, i) => (
                            <button
                                key={day}
                                type="button"
                                aria-pressed={value.days.includes(i + 1)}
                                aria-label={day}
                                disabled={disabled}
                                onClick={() => set({ days: toggleDay(value.days, i + 1) })}
                                className={`w-12 ${segment(value.days.includes(i + 1))}`}
                            >
                                {day.slice(0, 3)}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {value.freq === 'monthly' && (
                <div>
                    <span className={LABEL}>On these days</span>
                    <div role="group" aria-label="Days of the month" className="mt-1 grid grid-cols-8 gap-1 sm:grid-cols-11">
                        {Array.from({ length: 31 }, (_, i) => i + 1).map(day => (
                            <button
                                key={day}
                                type="button"
                                aria-pressed={value.days.includes(day)}
                                disabled={disabled}
                                onClick={() => set({ days: toggleDay(value.days, day) })}
                                className={`px-0 ${segment(value.days.includes(day))}`}
                            >
                                {day}
                            </button>
                        ))}
                    </div>
                    {value.days.some(d => d > 28) && (
                        <p className="mt-1 text-xs text-gray-500">In a shorter month, a day past its end runs on the month’s last day.</p>
                    )}
                </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
                <div>
                    <label htmlFor={timeId} className={LABEL}>{value.freq === 'hourly' ? 'Minutes past the hour' : 'At'}</label>
                    {value.freq === 'hourly' ? (
                        <select
                            id={timeId}
                            value={minute}
                            disabled={disabled}
                            onChange={e => set({ time: `${value.time.slice(0, 2) || '00'}:${e.target.value}` })}
                            className={INPUT}
                        >
                            {Array.from({ length: 60 }, (_, m) => String(m).padStart(2, '0')).map(m => (
                                <option key={m} value={m}>:{m}</option>
                            ))}
                        </select>
                    ) : (
                        <input
                            id={timeId}
                            type="time"
                            step={60}
                            required
                            value={value.time}
                            disabled={disabled}
                            onChange={e => set({ time: e.target.value })}
                            className={INPUT}
                        />
                    )}
                </div>
                <div>
                    <label htmlFor={zoneId} className={LABEL}>Time zone</label>
                    <select id={zoneId} value={value.tz} disabled={disabled} onChange={e => set({ tz: e.target.value })} className={INPUT}>
                        {zones.map(z => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}
                    </select>
                </div>
            </div>

            <p className="text-sm text-gray-700">
                <CalendarClock size={14} className="mr-1 inline -mt-0.5 text-gray-500" aria-hidden="true" />
                {describeRecurrence(value)}
            </p>
        </div>
    );
};

const RecipientsField: React.FC<{
    id: string;
    value: string[];
    onChange: (next: string[]) => void;
    draft: string;
    onDraft: (text: string) => void;
    disabled: boolean;
}> = ({ id, value, onChange, draft, onDraft, disabled }) => {
    const commit = (text: string) => {
        const added = parseRecipients(text);
        if (added.length) onChange(parseRecipients([...value, ...added]));
        onDraft('');
    };
    return (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 rounded-lg border border-gray-300 px-2 py-1.5 focus-within:border-brand-blue focus-within:ring-1 focus-within:ring-brand-blue">
            {value.map(address => (
                <span
                    key={address}
                    className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${looksLikeEmail(address)
                        ? 'bg-blue-50 text-blue-900'
                        : 'bg-red-50 text-red-800'}`}
                    title={looksLikeEmail(address) ? undefined : 'This doesn’t look like an email address.'}
                >
                    {address}
                    <button
                        type="button"
                        disabled={disabled}
                        aria-label={`Remove ${address}`}
                        onClick={() => onChange(value.filter(a => a !== address))}
                        className="rounded-full p-0.5 hover:bg-black/10"
                    >
                        <X size={11} />
                    </button>
                </span>
            ))}
            <input
                id={id}
                type="text"
                value={draft}
                disabled={disabled}
                placeholder={value.length ? 'Add another' : 'name@example.com'}
                onChange={e => {
                    const text = e.target.value;
                    if (/[\s,;]$/.test(text)) commit(text);
                    else onDraft(text);
                }}
                onKeyDown={e => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        commit(draft);
                    } else if (e.key === 'Backspace' && !draft && value.length) {
                        onChange(value.slice(0, -1));
                    }
                }}
                onBlur={() => commit(draft)}
                onPaste={e => {
                    const pasted = e.clipboardData.getData('text');
                    if (/[\s,;]/.test(pasted)) {
                        e.preventDefault();
                        commit(draft + pasted);
                    }
                }}
                className="min-w-[10rem] flex-1 border-0 bg-transparent p-1 text-sm text-gray-900 focus:outline-none focus:ring-0"
            />
        </div>
    );
};

/** What the dialog says about running as the person, before they save. */
const ConnectionNote: React.FC<{ state: Result<ConnectionStatus> | null }> = ({ state }) => {
    if (!state) {
        return (
            <p className="flex items-center gap-2 text-xs text-gray-500">
                <Loader2 size={12} className="animate-spin" /> Checking your connection…
            </p>
        );
    }
    if (!state.ok) {
        return <p className="text-xs text-gray-500">Couldn’t check your connection ({state.error}). You can still save.</p>;
    }
    const c = state.data;
    if (c.connected && !c.needs_reconnect) {
        const soon = expiresWithin(c.expires_at, 7);
        return (
            <p className={`flex items-start gap-1.5 rounded-lg border px-3 py-2 text-xs ${soon
                ? 'border-amber-200 bg-amber-50 text-amber-900'
                : 'border-emerald-200 bg-emerald-50 text-emerald-900'}`}>
                <Link2 size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>
                    Your account is connected{c.expires_at ? ` · ${expiresIn(c.expires_at)}` : ''}.
                    {soon ? ' Reconnect from My schedules to keep your schedules running.' : ''}
                </span>
            </p>
        );
    }
    return (
        <p className="flex items-start gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            <Link2 size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>
                {c.needs_reconnect
                    ? `${RECONNECT_REASONS[c.reason || ''] || 'Your connection stopped working.'} `
                    : 'Schedules run as you, so your account needs connecting once. '}
                Save, then {c.needs_reconnect ? 'reconnect' : 'connect'}: the schedule waits until you do.
            </span>
        </p>
    );
};

/**
 * The Schedule dialog: a new schedule from a widget's `props.app.schedule`, or
 * an existing one from My schedules. The person chooses when it runs and who
 * gets it; the query is the widget's and is shown, not edited. Saving a new one
 * never waits for a connection: a schedule without one is created and waits,
 * and the dialog then offers Connect.
 */
export const ScheduleDialog: React.FC<ScheduleDialogProps> = ({
    schedule, initial, sql, allowStatement, notice, viewName, save, onClose,
}) => {
    const editing = !!schedule;
    const capabilities = useCapabilities();
    const scheduling = findCapability(capabilities, 'scheduling');
    const email = findCapability(capabilities, 'email');
    const devMode = scheduling?.mode === 'dev';
    const [form, setForm] = useState<ScheduleForm>(initial);
    const [draft, setDraft] = useState('');
    const [phase, setPhase] = useState<Phase>({ kind: 'editing' });
    const [error, setError] = useState<string | null>(null);
    const [connection, setConnection] = useState<Result<ConnectionStatus> | null>(null);
    const titleId = useId();
    const nameId = useId();
    const toId = useId();
    const subjectId = useId();
    const messageId = useId();
    const sendWhenId = useId();

    const checkConnection = !editing && !!scheduling?.available && !devMode;
    useEffect(() => {
        if (!checkConnection) return;
        let live = true;
        void fetchConnection().then(result => { if (live) setConnection(result); });
        return () => { live = false; };
    }, [checkConnection]);

    const report = form.kind === 'email_report';
    const set = (patch: Partial<ScheduleForm>) => setForm(f => ({ ...f, ...patch }));
    const withDraft = useMemo(
        () => (draft.trim() ? { ...form, recipients: parseRecipients([...form.recipients, draft]) } : form),
        [form, draft],
    );

    const unavailable = !capabilities ? null
        : !scheduling?.available ? SCHEDULING_UNAVAILABLE
            : report && !email?.available ? EMAIL_UNAVAILABLE
                : null;
    const problem = formProblem(withDraft, sql);
    const saving = phase.kind === 'saving';
    const canSave = phase.kind === 'editing' && !!capabilities && !unavailable && !problem;

    const close = () => {
        if (saving) return;
        onClose(phase.kind === 'saved' ? phase.schedule : null);
    };
    const { ref, onKeyDown } = useDialog<HTMLDivElement>(close, saving);

    const submit = async () => {
        if (!canSave) return;
        setError(null);
        setPhase({ kind: 'saving' });
        setForm(withDraft);
        setDraft('');
        const result = await save(withDraft);
        if (!result.ok) {
            setPhase({ kind: 'editing' });
            setError(result.error);
        } else if (editing) {
            onClose(result.schedule);
        } else {
            setPhase({ kind: 'saved', schedule: result.schedule, connection: result.connection ?? null });
        }
    };

    const saved = phase.kind === 'saved' ? phase : null;
    const needsConnect = !!saved && !devMode && (
        saved.schedule.status === 'needs_reconnect'
        || (!!saved.connection && (!saved.connection.connected || saved.connection.needs_reconnect))
    );
    const connect = () => {
        const url = connectUrl(currentReturnPath());
        if (saved) onClose(saved.schedule);
        window.location.assign(url);
    };

    const title = editing ? 'Edit schedule' : report ? 'Schedule a report' : 'Schedule the statement';

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            // Portalled, but still inside the widget's React tree: keep its handlers out of this.
            onClick={e => e.stopPropagation()}
            onMouseDown={e => { e.stopPropagation(); if (e.target === e.currentTarget) close(); }}
        >
            <div
                ref={ref}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-busy={saving}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-150 focus:outline-none"
            >
                <div className="flex items-start gap-3 px-6 pt-5 pb-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-brand-blue" aria-hidden="true">
                        <CalendarClock size={17} />
                    </span>
                    <div className="min-w-0 flex-1">
                        <h2 id={titleId} className="text-base font-bold text-gray-900">{title}</h2>
                        <p className="truncate text-sm text-gray-600">
                            {devMode ? 'Local run: it runs as the app’s service principal.' : 'It runs as you, with your access to data.'}
                            {viewName ? ` From ${viewName}.` : ''}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={close}
                        disabled={saving}
                        aria-label="Close"
                        className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
                    >
                        <X size={18} />
                    </button>
                </div>

                {saved ? (
                    <div className="space-y-3 px-6 py-5 text-sm text-gray-700" role="status">
                        <div className="flex items-start gap-3">
                            <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-emerald-600" />
                            <div className="min-w-0">
                                <p className="font-medium text-gray-900">Saved “{saved.schedule.name}”.</p>
                                <p>
                                    {describeRecurrence(saved.schedule.recurrence)}
                                    {saved.schedule.kind === 'email_report'
                                        ? `, to ${saved.schedule.recipients?.length ?? 0} ${saved.schedule.recipients?.length === 1 ? 'recipient' : 'recipients'}.`
                                        : '.'}
                                </p>
                                {!needsConnect && saved.schedule.next_run_at && (
                                    <p className="text-gray-600">
                                        Next run {formatWhen(saved.schedule.next_run_at)} ({relativeTime(saved.schedule.next_run_at)}).
                                    </p>
                                )}
                            </div>
                        </div>
                        {needsConnect && (
                            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                                <p className="font-semibold">One more step: connect your account</p>
                                <p className="mt-0.5 text-xs">
                                    The schedule runs as you, so it waits until you connect. You’ll sign in to Databricks and come back here.
                                </p>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-4">
                        {unavailable && (
                            <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                                <p className="font-semibold">{unavailable}</p>
                                <p className="mt-0.5 text-xs">
                                    {(unavailable === SCHEDULING_UNAVAILABLE ? scheduling : email)?.next_step
                                        || 'An administrator can set it up under Admin Panel → Settings.'}
                                </p>
                            </div>
                        )}
                        {notice && (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{notice}</p>
                        )}

                        {!editing && allowStatement && (
                            <div>
                                <span className={LABEL}>What it does</span>
                                <div role="radiogroup" aria-label="What it does" className="mt-1 flex flex-wrap gap-1.5">
                                    {(['email_report', 'run_statement'] as ScheduleKind[]).map(kind => (
                                        <button
                                            key={kind}
                                            type="button"
                                            role="radio"
                                            aria-checked={form.kind === kind}
                                            disabled={saving}
                                            onClick={() => set({ kind })}
                                            className={segment(form.kind === kind)}
                                        >
                                            {kind === 'email_report' ? 'Email the results' : 'Run the statement'}
                                        </button>
                                    ))}
                                </div>
                                {!report && (
                                    <p className="mt-1 text-xs text-gray-500">Each run is recorded in the action log, like pressing the widget’s button. Nobody is emailed.</p>
                                )}
                            </div>
                        )}
                        {editing && (
                            <p className="text-xs text-gray-500">
                                {KIND_LABELS[form.kind]}{form.kind === 'run_statement' ? ': each run is recorded in the action log.' : '.'}
                            </p>
                        )}

                        <div>
                            <label htmlFor={nameId} className={LABEL}>Name</label>
                            <input
                                id={nameId}
                                data-autofocus
                                type="text"
                                value={form.name}
                                maxLength={MAX_NAME_LENGTH}
                                disabled={saving}
                                onChange={e => set({ name: e.target.value })}
                                className={INPUT}
                            />
                        </div>

                        <RecurrenceEditor value={form.recurrence} onChange={recurrence => set({ recurrence })} disabled={saving} />

                        {report && (
                            <>
                                <div>
                                    <label htmlFor={toId} className={LABEL}>Recipients</label>
                                    <RecipientsField
                                        id={toId}
                                        value={form.recipients}
                                        onChange={recipients => set({ recipients })}
                                        draft={draft}
                                        onDraft={setDraft}
                                        disabled={saving}
                                    />
                                    <p className="mt-0.5 text-xs text-gray-500">Press Enter or type a comma after each address. Who may be emailed is set by an administrator.</p>
                                </div>

                                <div>
                                    <label htmlFor={subjectId} className={LABEL}>Subject</label>
                                    <input
                                        id={subjectId}
                                        type="text"
                                        value={form.subject}
                                        maxLength={200}
                                        disabled={saving}
                                        onChange={e => set({ subject: e.target.value })}
                                        className={INPUT}
                                    />
                                </div>

                                <div>
                                    <label htmlFor={messageId} className={LABEL}>Message</label>
                                    <textarea
                                        id={messageId}
                                        rows={3}
                                        value={form.message}
                                        disabled={saving}
                                        onChange={e => set({ message: e.target.value })}
                                        placeholder="Shown above the results. Markdown works."
                                        className={`${INPUT} resize-y`}
                                    />
                                </div>

                                <div className="grid gap-3 sm:grid-cols-2 sm:items-end">
                                    <div>
                                        <label htmlFor={sendWhenId} className={LABEL}>Send</label>
                                        <select
                                            id={sendWhenId}
                                            value={form.sendWhen}
                                            disabled={saving}
                                            onChange={e => set({ sendWhen: e.target.value as SendWhen })}
                                            className={INPUT}
                                        >
                                            {SEND_WHEN.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
                                        </select>
                                    </div>
                                    <label className="flex items-center gap-2 py-2 text-sm text-gray-800">
                                        <input
                                            type="checkbox"
                                            checked={form.attachCsv}
                                            disabled={saving}
                                            onChange={e => set({ attachCsv: e.target.checked })}
                                            className="h-4 w-4 rounded border-gray-300 text-brand-blue focus:ring-brand-blue"
                                        />
                                        Attach the results as a CSV file
                                    </label>
                                </div>
                            </>
                        )}

                        <details className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-gray-500">The query it runs</summary>
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-gray-800">{sql || '(none)'}</pre>
                            <p className="mt-1 text-xs text-gray-500">The schedule keeps this exact statement. To change it, change the widget and schedule it again.</p>
                        </details>

                        {!editing && !unavailable && (devMode ? (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                                Local run: schedules run as the app’s service principal, so there’s no account to connect.
                            </p>
                        ) : checkConnection && <ConnectionNote state={connection} />)}

                        {error && (
                            <p role="alert" className="flex items-start gap-1.5 text-sm text-red-600">
                                <AlertCircle size={15} className="mt-0.5 shrink-0" /> {error}
                            </p>
                        )}
                    </div>
                )}

                <div className="flex items-center gap-3 rounded-b-xl border-t border-gray-100 bg-gray-50 px-6 py-3">
                    {saved ? (
                        <>
                            <a href="#/schedules" onClick={() => onClose(saved.schedule)} className="text-sm font-medium text-brand-blue hover:underline">
                                Open My schedules
                            </a>
                            {needsConnect ? (
                                <>
                                    <button type="button" onClick={close} className={`ml-auto ${SECONDARY}`}>Later</button>
                                    <button type="button" onClick={connect} className={PRIMARY}>
                                        <Link2 size={14} /> Connect your account
                                    </button>
                                </>
                            ) : (
                                <button type="button" onClick={close} className={`ml-auto ${PRIMARY}`}>Done</button>
                            )}
                        </>
                    ) : (
                        <>
                            {problem && !unavailable && <span className="text-xs text-gray-500">{problem}</span>}
                            <button type="button" onClick={close} disabled={saving} className={`ml-auto ${SECONDARY}`}>
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={submit}
                                disabled={!canSave}
                                title={unavailable || problem || undefined}
                                className={PRIMARY}
                            >
                                {saving && <Loader2 size={14} className="animate-spin" />}
                                {saving ? 'Saving…' : editing ? 'Save changes' : 'Save schedule'}
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>,
        document.body,
    );
};

export interface WidgetScheduleDialogProps {
    /** What the widget passed to `props.app.schedule`, as it passed it. */
    request: ScheduleRequest;
    /** The widget's own, so the Save lands in the action log under its name. */
    executeAction: ExecuteAction;
    onClose: (outcome: ScheduleOutcome) => void;
}

/**
 * The dialog behind `props.app.schedule`. Where the schedule came from (the
 * view, the widget, the link with its settings) is captured when it opens, so
 * moving around behind the dialog doesn't change what gets saved.
 */
export const WidgetScheduleDialog: React.FC<WidgetScheduleDialogProps> = ({ request, executeAction, onClose }) => {
    const { activeApp, activeAppTab, modeOf, generateShareLink, username } = useDashboardStore();
    const capabilities = useCapabilities();
    const instance = useContext(WidgetInstanceContext);

    const [opened] = useState(() => {
        const placed = activeAppTab?.widgets.find(w => w.i === instance);
        const draftMode = activeApp?.access === 'MANAGE' && modeOf(activeApp) === 'draft';
        const def = placed ? resolveWidget(placed.type, placed.props?._version, draftMode) : undefined;
        const executable = !!def?.isExecutable;
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        const asked = normalizeScheduleRequest(request, { tz, executable });
        let viewName: string | null = null;
        if (activeApp) {
            const index = activeAppTab ? activeApp.spec.tabs.findIndex(t => t.id === activeAppTab.id) : -1;
            const tabName = activeAppTab && activeApp.spec.tabs.length > 1 ? tabLabel(activeApp, activeAppTab, Math.max(index, 0)) : '';
            viewName = tabName && tabName !== activeApp.name ? `${activeApp.name} – ${tabName}` : activeApp.name;
        }
        const source: ScheduleSource = {
            source_app_id: activeApp ? String(activeApp.id) : null,
            source_widget_instance: instance,
            source_widget_id: placed?.type ?? null,
            view_name: viewName,
            view_link: activeApp ? generateShareLink() : null,
        };
        const fallbackName = def?.name || 'Scheduled report';
        const initial: ScheduleForm = {
            name: asked.name || asked.subject || fallbackName,
            kind: asked.kind,
            recipients: asked.recipients ?? (username.includes('@') ? [username] : []),
            subject: asked.subject || asked.name || fallbackName,
            message: asked.message,
            sendWhen: asked.sendWhen,
            attachCsv: asked.attachCsv,
            recurrence: asked.recurrence,
        };
        return { asked, executable, source, initial };
    });

    const save = (form: ScheduleForm): Promise<SaveResult> => logAndCreate(
        executeAction,
        form.kind === 'run_statement' ? 'Schedule statement' : 'Schedule report',
        createPayload(form, opened.asked.sql, opened.source),
    );

    return (
        <ScheduleDialog
            initial={opened.initial}
            sql={opened.asked.sql}
            allowStatement={opened.executable}
            notice={opened.asked.statementRefused
                ? 'This widget asked to run its statement on a schedule, which only an executable widget may do, so this schedules a report of its results instead.'
                : null}
            viewName={opened.source.view_name}
            save={save}
            onClose={saved => onClose(saved
                ? { scheduled: true, id: String(saved.id), status: saved.status }
                : { scheduled: false, status: capabilities && !isAvailable(capabilities, 'scheduling') ? 'unavailable' : 'cancelled' })}
        />
    );
};

export default ScheduleDialog;
