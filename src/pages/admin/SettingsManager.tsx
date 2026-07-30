import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, Loader2, RefreshCw, RotateCcw, Save, Sliders } from 'lucide-react';
import clsx from 'clsx';
import { ModelSelect } from '../../components/ModelSelect';

/**
 * Deployment settings that used to live only in `databricks.yml` — which model each
 * agent calls, and the chat agent's limits. Global admins only, and global rather
 * than per-environment: it's a property of the deployment, not of the data.
 */

interface Setting {
    key: string;
    label: string;
    help: string;
    kind: 'endpoint' | 'int';
    /** Value in force right now, whatever its source. */
    value: string;
    /** The admin override, empty when the value is inherited. */
    stored: string;
    source: 'database' | 'environment' | 'default';
    env_var: string;
    fallback: string;
    minimum: number | null;
    maximum: number | null;
}

const SOURCE_NOTE: Record<Setting['source'], string> = {
    database: 'Set here',
    environment: 'From the deployment configuration',
    default: 'Built-in default',
};

export const SettingsManager: React.FC = () => {
    const [settings, setSettings] = useState<Setting[]>([]);
    const [draft, setDraft] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
    const [savedAt, setSavedAt] = useState<number | null>(null);

    // Fields the admin has touched since the last load or save. A fetch that lands
    // afterwards must not write over them: React StrictMode mounts this twice in
    // development, so two loads are in flight, the form renders on the first, and
    // the second used to silently reset whatever had been typed in between.
    const editedRef = useRef<Set<string>>(new Set());

    const edit = (key: string, value: string) => {
        editedRef.current.add(key);
        setDraft(d => ({ ...d, [key]: value }));
    };

    const apply = (items: Setting[]) => {
        setSettings(items);
        // The draft holds *effective* values, so the form shows what is actually in
        // force. Saving therefore persists an inherited value as an explicit
        // override only for the fields the admin actually changed.
        setDraft(d => Object.fromEntries(items.map(s =>
            [s.key, editedRef.current.has(s.key) ? (d[s.key] ?? s.value) : s.value],
        )));
    };

    const applyAndClearEdits = (items: Setting[]) => {
        editedRef.current.clear();
        apply(items);
    };

    // Reload is an explicit "show me what the server has", so it drops pending
    // edits; the load on mount keeps them, since nobody asked for it.
    const load = async (discardEdits = false) => {
        setLoading(true);
        try {
            const res = await fetch('/api/settings');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data?.detail || `${res.statusText} (HTTP ${res.status})`);
            (discardEdits ? applyAndClearEdits : apply)(data.settings || []);
            setError(null);
        } catch (e: any) {
            setError(e?.message || String(e));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const changed = useMemo(
        () => settings.filter(s => (draft[s.key] ?? '') !== s.value).map(s => s.key),
        [settings, draft],
    );

    const save = async () => {
        if (!changed.length) return;
        setSaving(true);
        setFieldErrors({});
        try {
            // Choosing the value the deployment already supplies clears the
            // override instead of storing an identical row, so the field keeps
            // tracking the deployment if that ever changes.
            const payload = Object.fromEntries(changed.map(key => {
                const value = (draft[key] ?? '').trim();
                const fallback = settings.find(s => s.key === key)?.fallback;
                return [key, value === fallback ? '' : value];
            }));
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: payload }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                // The backend rejects the whole request on any invalid field and
                // returns them keyed by setting, so map them onto the inputs.
                if (data?.detail && typeof data.detail === 'object') {
                    setFieldErrors(data.detail as Record<string, string>);
                    throw new Error('Some values were rejected.');
                }
                throw new Error(data?.detail || `${res.statusText} (HTTP ${res.status})`);
            }
            applyAndClearEdits(data.settings || []);
            setError(null);
            setSavedAt(Date.now());
        } catch (e: any) {
            setError(e?.message || String(e));
        } finally {
            setSaving(false);
        }
    };

    const revert = (key: string) => {
        const setting = settings.find(s => s.key === key);
        if (setting) edit(key, setting.fallback);
    };

    if (loading) {
        return (
            <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader2 size={16} className="animate-spin" /> Loading settings…
            </div>
        );
    }

    const models = settings.filter(s => s.kind === 'endpoint');
    const limits = settings.filter(s => s.kind === 'int');

    return (
        <div className="max-w-3xl space-y-6">
            <div className="rounded-lg border border-gray-200 bg-white">
                <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                    <div className="flex items-center gap-2">
                        <Sliders size={16} className="text-qualcomm-blue" />
                        <h2 className="text-base font-semibold text-gray-900">Models</h2>
                    </div>
                    <button onClick={() => load(true)} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800">
                        <RefreshCw size={13} /> Reload
                    </button>
                </div>
                <div className="space-y-5 px-5 py-5">
                    <p className="text-xs leading-relaxed text-gray-500">
                        Names beginning <code className="font-mono">system.ai.</code> are called through the AI Gateway;
                        plain endpoint names go straight to the serving endpoint. Either works — the route follows the
                        name you pick.
                    </p>
                    {models.map(setting => (
                        <div key={setting.key}>
                            <div className="mb-1 flex items-baseline justify-between gap-3">
                                <label className="text-sm font-medium text-gray-800">{setting.label}</label>
                                <span className="text-[11px] text-gray-400">{SOURCE_NOTE[setting.source]}</span>
                            </div>
                            <ModelSelect
                                value={draft[setting.key] ?? ''}
                                onChange={next => edit(setting.key, next)}
                                ariaLabel={setting.label}
                            />
                            <p className="mt-1 text-xs text-gray-500">{setting.help}</p>
                            {fieldErrors[setting.key] && (
                                <p className="mt-1 flex items-center gap-1 text-xs text-red-600">
                                    <AlertCircle size={12} /> {fieldErrors[setting.key]}
                                </p>
                            )}
                            {(draft[setting.key] ?? '') !== setting.fallback && (
                                <button onClick={() => revert(setting.key)} className="mt-1 flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-700">
                                    <RotateCcw size={11} /> Reset to {setting.fallback}
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className="rounded-lg border border-gray-200 bg-white">
                <div className="border-b border-gray-100 px-5 py-4">
                    <h2 className="text-base font-semibold text-gray-900">Chat agent limits</h2>
                </div>
                <div className="grid gap-5 px-5 py-5 sm:grid-cols-2">
                    {limits.map(setting => (
                        <div key={setting.key}>
                            <div className="mb-1 flex items-baseline justify-between gap-2">
                                <label className="text-sm font-medium text-gray-800">{setting.label}</label>
                                <span className="text-[11px] text-gray-400">{SOURCE_NOTE[setting.source]}</span>
                            </div>
                            <input
                                type="number"
                                min={setting.minimum ?? undefined}
                                max={setting.maximum ?? undefined}
                                value={draft[setting.key] ?? ''}
                                onChange={e => edit(setting.key, e.target.value)}
                                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-qualcomm-blue focus:outline-none"
                            />
                            <p className="mt-1 text-xs text-gray-500">{setting.help}</p>
                            {fieldErrors[setting.key] && (
                                <p className="mt-1 flex items-center gap-1 text-xs text-red-600">
                                    <AlertCircle size={12} /> {fieldErrors[setting.key]}
                                </p>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {error && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    <AlertCircle size={15} className="mt-0.5 shrink-0" /> {error}
                </div>
            )}

            <div className="flex items-center gap-3">
                <button
                    onClick={save}
                    disabled={!changed.length || saving}
                    className={clsx(
                        'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                        changed.length && !saving
                            ? 'bg-qualcomm-blue text-white hover:opacity-90'
                            : 'cursor-not-allowed bg-gray-200 text-gray-500',
                    )}
                >
                    {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                    {saving ? 'Saving…' : changed.length ? `Save ${changed.length} change${changed.length > 1 ? 's' : ''}` : 'Saved'}
                </button>
                {savedAt && !changed.length && (
                    <span className="flex items-center gap-1 text-xs text-green-700">
                        <Check size={13} /> Applies to new conversations; open ones finish on the previous model.
                    </span>
                )}
            </div>
        </div>
    );
};
