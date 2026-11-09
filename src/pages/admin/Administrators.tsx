import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, Plus, RefreshCw, ShieldCheck, Trash2, User, Users, X } from 'lucide-react';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PrincipalPicker, type PickedPrincipal, type PrincipalPickerHandle } from '../../components/sharing';
import { EVERYONE, fetchMe, requestJson, samePrincipal, type Me, type PrincipalType } from '../../sharing';
import { formatServerTime } from './time';

interface AdminRow {
    principal: string;
    principal_type: PrincipalType | null;
    added_by: string | null;
    added_at: string | null;
}

const ADMINS_URL = '/api/sharing/admins';

/**
 * Admin Panel → Administrators. App admins manage every view, widget and agent
 * and see this panel; everything else is shared object by object. The server
 * refuses to remove the last one (`access.remove_admin`), and its reason is shown
 * as is rather than second-guessed here.
 */
export const Administrators: React.FC = () => {
    const [admins, setAdmins] = useState<AdminRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [text, setText] = useState('');
    const [adding, setAdding] = useState(false);
    const [pendingRemove, setPendingRemove] = useState<AdminRow | null>(null);
    const [removing, setRemoving] = useState<string | null>(null);
    const [me, setMe] = useState<Me | null>(null);
    const pickerRef = useRef<PrincipalPickerHandle>(null);

    const settle = useCallback((request: Promise<{ admins?: AdminRow[] }>) => request
        .then(data => { setAdmins(data.admins || []); setLoadError(null); })
        // An empty list here would read as "nobody is an admin", which is never true.
        .catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false)), []);

    const load = () => {
        setLoading(true);
        settle(requestJson(ADMINS_URL));
    };

    useEffect(() => { settle(requestJson(ADMINS_URL)); }, [settle]);
    useEffect(() => { fetchMe().then(setMe).catch(() => { /* "(you)" is cosmetic */ }); }, []);

    const add = async ({ principal, principal_type }: PickedPrincipal) => {
        const p = principal.trim();
        if (!p) return;
        setActionError(null);
        if (p === EVERYONE) {
            setActionError("Everyone can't be an administrator. Name a user or a group.");
            return;
        }
        if (admins.some(a => samePrincipal(a.principal, p))) {
            setActionError(`${p} is already an administrator.`);
            setText('');
            return;
        }
        setAdding(true);
        try {
            const data = await requestJson<{ admins?: AdminRow[] }>(ADMINS_URL, {
                method: 'POST',
                body: JSON.stringify({ principal: p, principal_type }),
            });
            setAdmins(data.admins || []);
            setText('');
        } catch (e) {
            setActionError(e instanceof Error ? e.message : String(e));
        } finally {
            setAdding(false);
        }
    };

    const remove = async () => {
        const row = pendingRemove;
        setPendingRemove(null);
        if (!row) return;
        setActionError(null);
        setRemoving(row.principal);
        try {
            const data = await requestJson<{ admins?: AdminRow[] }>(
                `${ADMINS_URL}?principal=${encodeURIComponent(row.principal)}`,
                { method: 'DELETE' },
            );
            setAdmins(data.admins || []);
        } catch (e) {
            setActionError(e instanceof Error ? e.message : String(e));
        } finally {
            setRemoving(null);
        }
    };

    const removingSelf = !!pendingRemove && samePrincipal(pendingRemove.principal, me?.username);

    return (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200">
            <div className="p-6 border-b border-gray-200 flex justify-between items-start gap-4">
                <div>
                    <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                        <ShieldCheck className="text-brand-blue" size={20} />
                        Administrators
                    </h2>
                    <p className="text-sm text-gray-500 mt-1 max-w-2xl">
                        Administrators can manage every view, widget and agent in this app, and open this panel.
                        Everyone else gets access object by object, from each one's Share button. Name a user by
                        their email, or a group by its exact Databricks name.
                    </p>
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
                <div className="flex gap-3 items-start bg-gray-50 p-4 rounded-lg border border-gray-200 mb-4">
                    <PrincipalPicker
                        ref={pickerRef}
                        value={text}
                        onChange={setText}
                        onSubmit={add}
                        placeholder="Add a user or group"
                        exclude={admins.map(a => a.principal)}
                        disabled={adding}
                        className="min-w-0 flex-1"
                    />
                    <button
                        type="button"
                        onClick={() => { if (!pickerRef.current?.submit()) pickerRef.current?.focus(); }}
                        disabled={adding || !text.trim()}
                        className="px-4 py-2 bg-brand-blue hover:bg-blue-700 text-white rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        {adding ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                        Add administrator
                    </button>
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

                <div className="overflow-hidden border border-gray-200 rounded-lg">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User or group</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Added by</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Added</th>
                                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Remove</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {loading && admins.length === 0 ? (
                                <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-500 text-sm">Loading...</td></tr>
                            ) : loadError ? (
                                <tr><td colSpan={4} className="px-6 py-8 text-center text-sm">
                                    <p className="text-red-600 font-medium">Could not load administrators.</p>
                                    <p className="text-gray-500 mt-1">{loadError}</p>
                                    <button onClick={load} className="mt-3 px-3 py-1.5 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 inline-flex items-center gap-1.5">
                                        <RefreshCw size={14} /> Retry
                                    </button>
                                </td></tr>
                            ) : admins.length === 0 ? (
                                <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-500 text-sm">No administrators are listed.</td></tr>
                            ) : (
                                admins.map(row => {
                                    const isGroup = row.principal_type === 'group';
                                    const last = admins.length <= 1;
                                    return (
                                        <tr key={row.principal} className="hover:bg-gray-50">
                                            <td className="px-6 py-3 text-sm text-gray-900">
                                                <div className="flex items-center gap-2">
                                                    {isGroup
                                                        ? <Users size={15} className="shrink-0 text-gray-400" aria-label="Group" />
                                                        : <User size={15} className="shrink-0 text-gray-400" aria-label="User" />}
                                                    <span className="font-medium truncate" title={row.principal}>{row.principal}</span>
                                                    {samePrincipal(row.principal, me?.username) && <span className="text-gray-500">(you)</span>}
                                                    {isGroup && <span className="text-xs text-gray-500">Group</span>}
                                                </div>
                                            </td>
                                            <td className="px-6 py-3 text-sm text-gray-500">{row.added_by || '—'}</td>
                                            <td className="px-6 py-3 text-sm text-gray-500">{formatServerTime(row.added_at)}</td>
                                            <td className="px-6 py-3 text-right">
                                                <button
                                                    onClick={() => setPendingRemove(row)}
                                                    disabled={last || removing === row.principal}
                                                    title={last ? 'Add another administrator before removing the last one' : 'Remove'}
                                                    className="text-gray-400 hover:text-red-600 p-1 rounded hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-gray-400"
                                                >
                                                    {removing === row.principal ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                                                </button>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
                <p className="mt-2 text-xs text-gray-400">
                    A group's members are administrators while they are in it. There must always be at least one.
                </p>
            </div>

            {pendingRemove && (
                <ConfirmModal
                    title="Remove administrator"
                    message={`Remove ${pendingRemove.principal} from Administrators?`}
                    detail={removingSelf
                        ? 'That is you. Unless a group you are in is also listed, you lose this panel and keep only what is shared with you.'
                        : 'They keep whatever is shared with them directly.'}
                    confirmLabel="Remove"
                    variant="danger"
                    onConfirm={remove}
                    onCancel={() => setPendingRemove(null)}
                />
            )}
        </div>
    );
};
