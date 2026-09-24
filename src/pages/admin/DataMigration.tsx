import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowRightLeft, Download, FileUp, Loader2, RefreshCw, Upload } from 'lucide-react';
import clsx from 'clsx';
import { ConfirmModal } from '../../components/ConfirmModal';

/**
 * Admin Panel → Data Migration. Moves a deployment's data to another app — dev's
 * widgets and agents into the test app, say — as a snapshot file: download here,
 * upload there. The apps never talk to each other or share database credentials;
 * see `server/services/data_migration.py` for why that is the design.
 *
 * Import is two steps on purpose. Preview runs the real import and rolls it back,
 * so the numbers shown are what Import will do; Import is only offered for the
 * exact file and options that were previewed.
 */

type Env = 'dev' | 'test' | 'prod';
type Mode = 'merge' | 'replace';

interface Group { key: string; label: string; help: string; default: boolean }
interface TableSummary { table: string; group: string; rows: number; bytes: number; error?: string }
interface ReportRow {
    table: string; group: string; in_file: number; inserted: number; skipped: number; deleted: number;
    dropped_columns: string[]; note?: string;
}
interface ImportResult {
    dry_run: boolean; env: Env; mode: Mode; groups: string[];
    tables: ReportRow[];
    totals: { in_file: number; inserted: number; skipped: number; deleted: number };
    ignored_tables: string[];
    snapshot: { exported_at?: string; exported_by?: string; source?: Record<string, string>; groups?: string[] };
}

const ENVS: Env[] = ['dev', 'test', 'prod'];

const formatBytes = (n: number) => {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
};

const readError = async (res: Response) => {
    const data = await res.json().catch(() => ({}));
    return data?.detail || `${res.statusText} (HTTP ${res.status})`;
};

export const DataMigration: React.FC = () => {
    const [groups, setGroups] = useState<Group[]>([]);
    const [thisApp, setThisApp] = useState<Record<string, string>>({});
    const [loadError, setLoadError] = useState<string | null>(null);

    // --- export
    const [exportEnv, setExportEnv] = useState<Env>('dev');
    const [exportGroups, setExportGroups] = useState<string[]>([]);
    const [summary, setSummary] = useState<TableSummary[] | null>(null);
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState<string | null>(null);

    // --- import
    const [file, setFile] = useState<File | null>(null);
    const [importEnv, setImportEnv] = useState<Env>('dev');
    const [mode, setMode] = useState<Mode>('merge');
    const [importGroups, setImportGroups] = useState<string[]>([]);
    const [busy, setBusy] = useState<'preview' | 'import' | null>(null);
    const [importError, setImportError] = useState<string | null>(null);
    const [result, setResult] = useState<ImportResult | null>(null);
    const [previewedKey, setPreviewedKey] = useState<string | null>(null);
    const [confirming, setConfirming] = useState(false);

    useEffect(() => {
        (async () => {
            try {
                const res = await fetch('/api/migration/groups');
                if (!res.ok) throw new Error(await readError(res));
                const data = await res.json();
                setGroups(data.groups || []);
                setThisApp(data.this_app || {});
                const defaults = (data.groups || []).filter((g: Group) => g.default).map((g: Group) => g.key);
                setExportGroups(defaults);
                setImportGroups(defaults);
            } catch (e) {
                setLoadError(e instanceof Error ? e.message : String(e));
            }
        })();
    }, []);

    const loadSummary = async (env: Env) => {
        setSummaryLoading(true);
        try {
            const res = await fetch(`/api/migration/summary?env=${env}`);
            if (!res.ok) throw new Error(await readError(res));
            setSummary((await res.json()).tables || []);
        } catch (e) {
            setExportError(e instanceof Error ? e.message : String(e));
        } finally {
            setSummaryLoading(false);
        }
    };
    useEffect(() => { loadSummary(exportEnv); }, [exportEnv]);

    const groupTotals = useMemo(() => {
        const out: Record<string, { rows: number; bytes: number }> = {};
        for (const t of summary || []) {
            out[t.group] = out[t.group] || { rows: 0, bytes: 0 };
            out[t.group].rows += t.rows;
            out[t.group].bytes += t.bytes;
        }
        return out;
    }, [summary]);

    const toggle = (list: string[], key: string) => list.includes(key) ? list.filter(k => k !== key) : [...list, key];

    const handleExport = async () => {
        setExporting(true);
        setExportError(null);
        try {
            const res = await fetch(`/api/migration/export?env=${exportEnv}&groups=${exportGroups.join(',')}`);
            if (!res.ok) throw new Error(await readError(res));
            const blob = await res.blob();
            const disposition = res.headers.get('Content-Disposition') || '';
            const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `command-center-${exportEnv}.json.gz`;
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = name;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            setExportError(e instanceof Error ? e.message : String(e));
        } finally {
            setExporting(false);
        }
    };

    // Import is offered only for what was previewed. Changing the file or any
    // option after a preview makes its numbers describe a different import.
    const optionsKey = file ? `${file.name}|${file.size}|${file.lastModified}|${importEnv}|${mode}|${[...importGroups].sort().join(',')}` : null;
    const previewCurrent = !!optionsKey && optionsKey === previewedKey;

    const runImport = async (dryRun: boolean) => {
        if (!file) return;
        setBusy(dryRun ? 'preview' : 'import');
        setImportError(null);
        const form = new FormData();
        form.append('file', file);
        form.append('env', importEnv);
        form.append('mode', mode);
        form.append('groups', importGroups.join(','));
        form.append('dry_run', dryRun ? 'true' : 'false');
        try {
            const res = await fetch('/api/migration/import', { method: 'POST', body: form });
            if (!res.ok) throw new Error(await readError(res));
            const data: ImportResult = await res.json();
            setResult(data);
            setPreviewedKey(dryRun ? optionsKey : null);
        } catch (e) {
            setImportError(e instanceof Error ? e.message : String(e));
            setPreviewedKey(null);
        } finally {
            setBusy(null);
        }
    };

    if (loadError) {
        return (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                <AlertCircle size={16} className="mr-1 inline" /> Could not open Data Migration: {loadError}
            </div>
        );
    }

    const groupLabel = (key: string) => groups.find(g => g.key === key)?.label || key;

    return (
        <div className="space-y-6">
            <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
                <h2 className="flex items-center gap-2 text-lg font-bold text-gray-900">
                    <ArrowRightLeft className="text-qualcomm-blue" size={20} /> Data Migration
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                    Move this app's widgets, views, agents and settings to another Command Center app — for example from the
                    dev app to the test app, which has its own database. Download a snapshot here, then open Data Migration
                    in the other app and import it. Promotion (the Widget and View tabs) is still how single items move
                    between Dev, Test and Prod inside one app.
                </p>
                {thisApp.app_environment && (
                    <p className="mt-2 text-xs text-gray-500">
                        This app: <span className="font-mono">{thisApp.app_environment}</span>
                        {thisApp.instance && <> · database <span className="font-mono">{thisApp.instance}</span></>}
                    </p>
                )}
            </div>

            {/* ---------------------------------------------------------- export */}
            <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
                <div className="flex items-center justify-between border-b border-gray-200 p-6">
                    <div>
                        <h3 className="flex items-center gap-2 text-md font-semibold text-gray-900"><Download size={16} /> 1. Export a snapshot</h3>
                        <p className="mt-1 text-sm text-gray-500">A compressed file holding every row of what you pick. Treat it like a database backup.</p>
                    </div>
                    <button onClick={() => loadSummary(exportEnv)} className="rounded-lg p-2 text-gray-400 hover:bg-gray-50 hover:text-qualcomm-blue" title="Refresh counts">
                        <RefreshCw size={18} className={summaryLoading ? 'animate-spin' : ''} />
                    </button>
                </div>
                <div className="space-y-4 p-6">
                    <EnvPicker label="Export the data stored under" value={exportEnv} onChange={setExportEnv} />
                    <div className="space-y-2">
                        {groups.map(g => (
                            <label key={g.key} className="flex items-start gap-3 rounded-md border border-gray-200 p-3 hover:bg-gray-50">
                                <input type="checkbox" className="mt-1 h-4 w-4" checked={exportGroups.includes(g.key)} onChange={() => setExportGroups(toggle(exportGroups, g.key))} />
                                <span className="flex-1">
                                    <span className="text-sm font-medium text-gray-900">{g.label}</span>
                                    <span className="block text-xs text-gray-500">{g.help}</span>
                                </span>
                                <span className="whitespace-nowrap text-xs text-gray-500">
                                    {groupTotals[g.key] ? `${groupTotals[g.key].rows.toLocaleString()} rows · ${formatBytes(groupTotals[g.key].bytes)}` : summaryLoading ? '…' : ''}
                                </span>
                            </label>
                        ))}
                    </div>
                    {exportGroups.includes('conversations') && (
                        <p className="flex items-start gap-1 text-xs text-amber-700">
                            <AlertCircle size={12} className="mt-0.5 shrink-0" />
                            The snapshot will contain every user's conversations and attached files. Anyone holding the file can read them.
                        </p>
                    )}
                    {exportError && <p className="text-sm text-red-600">{exportError}</p>}
                    <button
                        onClick={handleExport}
                        disabled={exporting || exportGroups.length === 0}
                        className="flex items-center gap-2 rounded-md bg-qualcomm-blue px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                        {exporting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                        {exporting ? 'Preparing…' : 'Download snapshot'}
                    </button>
                </div>
            </div>

            {/* ---------------------------------------------------------- import */}
            <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-gray-200 p-6">
                    <h3 className="flex items-center gap-2 text-md font-semibold text-gray-900"><Upload size={16} /> 2. Import a snapshot into this app</h3>
                    <p className="mt-1 text-sm text-gray-500">Preview first: it runs the whole import and then undoes it, so you see exactly what would change.</p>
                </div>
                <div className="space-y-4 p-6">
                    <label className="flex cursor-pointer items-center gap-3 rounded-md border border-dashed border-gray-300 p-4 hover:bg-gray-50">
                        <FileUp size={20} className="text-gray-400" />
                        <span className="text-sm text-gray-700">{file ? <><span className="font-mono">{file.name}</span> · {formatBytes(file.size)}</> : 'Choose a snapshot file (.json.gz)'}</span>
                        <input type="file" accept=".gz,.json,application/gzip,application/json" className="hidden"
                            onChange={e => { setFile(e.target.files?.[0] || null); setResult(null); setPreviewedKey(null); setImportError(null); }} />
                    </label>

                    <EnvPicker label="Import into the data stored under" value={importEnv} onChange={setImportEnv} />

                    <fieldset>
                        <legend className="mb-1 text-sm font-medium text-gray-700">How</legend>
                        <div className="grid gap-2 sm:grid-cols-2">
                            {([
                                ['merge', 'Merge', "Add what this app is missing. Nothing here is changed or deleted, and running it twice adds nothing the second time."],
                                ['replace', 'Replace', "Make the chosen parts of this app an exact copy of the snapshot. This app's own rows in them are deleted."],
                            ] as [Mode, string, string][]).map(([key, label, help]) => (
                                <label key={key} className={clsx('flex items-start gap-2 rounded-md border p-3', mode === key ? (key === 'replace' ? 'border-red-300 bg-red-50' : 'border-qualcomm-blue bg-blue-50') : 'border-gray-200')}>
                                    <input type="radio" name="mode" className="mt-1" checked={mode === key} onChange={() => setMode(key)} />
                                    <span><span className="text-sm font-medium text-gray-900">{label}</span><span className="block text-xs text-gray-600">{help}</span></span>
                                </label>
                            ))}
                        </div>
                    </fieldset>

                    <fieldset>
                        <legend className="mb-1 text-sm font-medium text-gray-700">What</legend>
                        <div className="flex flex-wrap gap-2">
                            {groups.map(g => (
                                <label key={g.key} className="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-800">
                                    <input type="checkbox" checked={importGroups.includes(g.key)} onChange={() => setImportGroups(toggle(importGroups, g.key))} />
                                    {g.label}
                                </label>
                            ))}
                        </div>
                    </fieldset>

                    {importError && (
                        <p className="flex items-start gap-1 text-sm text-red-600"><AlertCircle size={14} className="mt-0.5 shrink-0" /> {importError}</p>
                    )}

                    <div className="flex gap-3">
                        <button
                            onClick={() => runImport(true)}
                            disabled={!file || busy !== null || importGroups.length === 0}
                            className="flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
                        >
                            {busy === 'preview' && <Loader2 size={16} className="animate-spin" />} Preview
                        </button>
                        <button
                            onClick={() => setConfirming(true)}
                            disabled={!previewCurrent || busy !== null}
                            title={previewCurrent ? undefined : 'Preview this file and these options first'}
                            className={clsx('flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50',
                                mode === 'replace' ? 'bg-red-600 hover:bg-red-700' : 'bg-qualcomm-blue hover:bg-blue-700')}
                        >
                            {busy === 'import' && <Loader2 size={16} className="animate-spin" />} Import
                        </button>
                    </div>

                    {result && <ImportReport result={result} groupLabel={groupLabel} />}
                </div>
            </div>

            {confirming && result && (
                <ConfirmModal
                    title={mode === 'replace' ? 'Replace data in this app?' : 'Import this snapshot?'}
                    message={mode === 'replace'
                        ? `This deletes ${result.totals.deleted.toLocaleString()} row(s) in ${importEnv} and writes ${result.totals.inserted.toLocaleString()} from the snapshot.`
                        : `This adds ${result.totals.inserted.toLocaleString()} row(s) to ${importEnv}. Nothing already here is changed.`}
                    detail={mode === 'replace' ? 'There is no undo other than importing a snapshot of this app taken beforehand.' : 'The import is recorded in Action Logs.'}
                    confirmLabel={mode === 'replace' ? 'Replace' : 'Import'}
                    variant={mode === 'replace' ? 'danger' : 'primary'}
                    onConfirm={() => { setConfirming(false); runImport(false); }}
                    onCancel={() => setConfirming(false)}
                />
            )}
        </div>
    );
};

const EnvPicker: React.FC<{ label: string; value: Env; onChange: (e: Env) => void }> = ({ label, value, onChange }) => (
    <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <select value={value} onChange={e => onChange(e.target.value as Env)} className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm">
            {ENVS.map(e => <option key={e} value={e}>{e[0].toUpperCase() + e.slice(1)}</option>)}
        </select>
        <span className="text-xs text-gray-500">Day-to-day data lives under Dev unless you promote it.</span>
    </div>
);

const ImportReport: React.FC<{ result: ImportResult; groupLabel: (k: string) => string }> = ({ result, groupLabel }) => {
    const src = result.snapshot.source || {};
    const rows = result.tables.filter(t => t.in_file || t.deleted || t.note);
    return (
        <div className={clsx('rounded-md border p-4', result.dry_run ? 'border-gray-200 bg-gray-50' : 'border-green-200 bg-green-50')}>
            <p className="text-sm font-medium text-gray-900">
                {result.dry_run ? 'Preview — nothing has been changed yet.' : 'Imported.'}{' '}
                <span className="font-normal text-gray-600">
                    {result.totals.inserted.toLocaleString()} added · {result.totals.skipped.toLocaleString()} already here
                    {result.mode === 'replace' ? ` · ${result.totals.deleted.toLocaleString()} deleted` : ''}
                </span>
            </p>
            <p className="mt-1 text-xs text-gray-500">
                Snapshot of <span className="font-mono">{src.app_environment || '?'}</span> / {src.env || '?'}
                {src.instance && <> ({src.instance})</>}, taken {result.snapshot.exported_at ? new Date(result.snapshot.exported_at).toLocaleString() : 'at an unknown time'}
                {result.snapshot.exported_by && <> by {result.snapshot.exported_by}</>}.
            </p>
            <table className="mt-3 min-w-full text-sm">
                <thead>
                    <tr className="text-left text-xs uppercase tracking-wider text-gray-500">
                        <th className="py-1 pr-4">Table</th><th className="py-1 pr-4 text-right">In file</th>
                        <th className="py-1 pr-4 text-right">Added</th><th className="py-1 pr-4 text-right">Already here</th>
                        {result.mode === 'replace' && <th className="py-1 pr-4 text-right">Deleted</th>}
                        <th className="py-1">Notes</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                    {rows.map(r => (
                        <tr key={r.table}>
                            <td className="py-1 pr-4"><span className="font-mono text-xs">{r.table}</span> <span className="text-[11px] text-gray-400">{groupLabel(r.group)}</span></td>
                            <td className="py-1 pr-4 text-right">{r.in_file.toLocaleString()}</td>
                            <td className="py-1 pr-4 text-right">{r.inserted.toLocaleString()}</td>
                            <td className="py-1 pr-4 text-right">{r.skipped.toLocaleString()}</td>
                            {result.mode === 'replace' && <td className="py-1 pr-4 text-right">{r.deleted.toLocaleString()}</td>}
                            <td className="py-1 text-xs text-gray-500">
                                {r.note}
                                {r.dropped_columns.length > 0 && <>Columns this app doesn't have were left out: {r.dropped_columns.join(', ')}</>}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {result.ignored_tables.length > 0 && (
                <p className="mt-2 text-xs text-gray-500">Ignored tables this app doesn't know: {result.ignored_tables.join(', ')}</p>
            )}
        </div>
    );
};
