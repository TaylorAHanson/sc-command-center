import React, { useState, useEffect } from 'react';
import { Plus, Trash2, Shield, RefreshCw, Pencil, Check, X, AlertTriangle } from 'lucide-react';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PrincipalSelect } from '../../components/PrincipalSelect';
import { principalAllowsSave } from '../../principals';
import type { PrincipalVerdict } from '../../principals';

// Domains that mean "every domain" to the permission check (`roles.py`), so they
// are valid on a mapping without being taxonomy entries.
const GLOBAL_DOMAINS = ['global', 'all', 'app'];
const isGlobalDomain = (d: string) => GLOBAL_DOMAINS.includes(d.trim().toLowerCase());

interface RoleMapping {
    id: number;
    external_role: string;
    domain: string;
    permission_level: 'viewer' | 'editor' | 'admin';
    timestamp: string;
}

export const RoleMappings: React.FC = () => {
    const [mappings, setMappings] = useState<RoleMapping[]>([]);
    const [loading, setLoading] = useState(true);
    const [newRole, setNewRole] = useState('');
    const [newDomain, setNewDomain] = useState('');
    const [newPermission, setNewPermission] = useState<'viewer' | 'editor' | 'admin'>('editor');
    const [isSaving, setIsSaving] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<RoleMapping | null>(null);

    // Global Admin state
    const [newGlobalAdminRole, setNewGlobalAdminRole] = useState('');
    const [isSavingGlobal, setIsSavingGlobal] = useState(false);

    // Editing state
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editRole, setEditRole] = useState('');
    const [editDomain, setEditDomain] = useState('');
    const [editPermission, setEditPermission] = useState<'viewer' | 'editor' | 'admin'>('editor');
    const [editOriginal, setEditOriginal] = useState<RoleMapping | null>(null);

    // What the name in each role field resolves to in Databricks. Save is refused
    // for a name no user could ever hold — see PrincipalSelect.
    const [globalVerdict, setGlobalVerdict] = useState<PrincipalVerdict | null>(null);
    const [newVerdict, setNewVerdict] = useState<PrincipalVerdict | null>(null);
    const [editVerdict, setEditVerdict] = useState<PrincipalVerdict | null>(null);

    // Mapped domains are picked from the taxonomy rather than typed: a mapping to
    // a domain nothing can be filed under grants nothing. `null` = not loaded.
    const [domains, setDomains] = useState<string[] | null>(null);
    const [domainError, setDomainError] = useState<string | null>(null);

    const fetchDomains = async () => {
        try {
            const res = await fetch('/api/taxonomy/domains');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
            const names: string[] = (data.domains || []).map((d: { name?: string }) => d.name).filter(Boolean);
            setDomains(names);
            setDomainError(null);
        } catch (e) {
            // Keep whatever list we had: an empty picker reads as "no domains exist".
            setDomainError(e instanceof Error ? e.message : String(e));
        }
    };

    const fetchMappings = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/roles/mapping');
            const data = await res.json();
            if (res.ok) {
                setMappings(data.mappings || []);
            }
        } catch (e) {
            console.error("Error fetching role mappings:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchMappings();
        fetchDomains();
    }, []);

    const knownDomain = (d: string) => isGlobalDomain(d) || (domains ?? []).includes(d);
    // An edit may keep a value the checks would now refuse (a mapping saved before
    // they existed); only what the admin changed has to pass. The server agrees.
    const editRoleOk = !!editOriginal && (editRole.trim() === editOriginal.external_role || principalAllowsSave(editVerdict, editRole));
    const editDomainOk = !!editOriginal && (editDomain === editOriginal.domain || knownDomain(editDomain));

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newRole.trim() || !newDomain.trim() || !principalAllowsSave(newVerdict, newRole)) return;

        setIsSaving(true);
        try {
            const res = await fetch('/api/roles/mapping', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    external_role: newRole.trim(),
                    domain: newDomain.trim(),
                    permission_level: newPermission
                })
            });

            if (res.ok) {
                await fetchMappings();
                setNewRole('');
                setNewDomain('');
                setNewPermission('editor');
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail}`);
            }
        } catch (e) {
            console.error("Error creating mapping:", e);
            alert("Network error");
        } finally {
            setIsSaving(false);
        }
    };

    const handleCreateGlobalAdmin = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newGlobalAdminRole.trim() || !principalAllowsSave(globalVerdict, newGlobalAdminRole)) return;

        setIsSavingGlobal(true);
        try {
            const res = await fetch('/api/roles/mapping', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    external_role: newGlobalAdminRole.trim(),
                    domain: 'Global',
                    permission_level: 'admin'
                })
            });

            if (res.ok) {
                await fetchMappings();
                setNewGlobalAdminRole('');
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail}`);
            }
        } catch (e) {
            console.error("Error creating global admin mapping:", e);
            alert("Network error");
        } finally {
            setIsSavingGlobal(false);
        }
    };

    const handleDelete = async (mapping: RoleMapping) => {
        setPendingDelete(mapping);
    };

    const executeDelete = async () => {
        if (!pendingDelete) return;
        const id = pendingDelete.id;
        setPendingDelete(null);
        try {
            const res = await fetch(`/api/roles/mapping/${id}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                setMappings(mappings.filter(m => m.id !== id));
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail}`);
            }
        } catch (e) {
            console.error("Error deleting mapping:", e);
        }
    };

    const handleSaveEdit = async (id: number) => {
        if (!editRole.trim() || !editDomain.trim() || !editRoleOk || !editDomainOk) return;

        try {
            const res = await fetch(`/api/roles/mapping/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    external_role: editRole.trim(),
                    domain: editDomain.trim(),
                    permission_level: editPermission
                })
            });

            if (res.ok) {
                setMappings(mappings.map(m => m.id === id ? { ...m, external_role: editRole.trim(), domain: editDomain.trim(), permission_level: editPermission } : m));
                setEditingId(null);
                setEditOriginal(null);
            } else {
                const data = await res.json();
                alert(`Error: ${data.detail}`);
            }
        } catch (e) {
            console.error("Error updating mapping:", e);
        }
    };

    const startEditing = (mapping: RoleMapping) => {
        setEditingId(mapping.id);
        setEditOriginal(mapping);
        setEditVerdict(null);
        setEditRole(mapping.external_role);
        setEditDomain(mapping.domain);
        setEditPermission(mapping.permission_level);
    };

    return (
        <>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200">
                <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                    <div>
                        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                            <Shield className="text-qualcomm-blue" size={20} />
                            Role to Domain Mappings
                        </h2>
                        <p className="text-sm text-gray-500 mt-1">
                            Map external AD/LDAP roles to dashboard Domains. Users with these roles will be able to manage widgets in the assigned Domain.
                        </p>
                    </div>
                    <button
                        onClick={fetchMappings}
                        className="p-2 text-gray-400 hover:text-qualcomm-blue transition-colors rounded-lg hover:bg-gray-50 bg-gray-50/50"
                        title="Refresh mappings"
                    >
                        <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
                    </button>
                </div>

                <div className="p-6">
                    {/* Global Admin Form */}
                    <div className="mb-8">
                        <h3 className="text-md font-semibold text-gray-900 mb-2">Assign Global Administrator</h3>
                        <p className="text-sm text-gray-500 mb-3">
                            Users with this role will have full admin access across the entire application and all domains. By default, setting <code>DEV_MODE=true</code> grants you global admin rights locally.
                        </p>
                        <form onSubmit={handleCreateGlobalAdmin} className="flex gap-4 items-start bg-blue-50 p-4 rounded-lg border border-blue-100">
                            <div className="flex-1">
                                <label className="block text-sm font-medium text-gray-700 mb-1">Databricks group or user</label>
                                <PrincipalSelect
                                    value={newGlobalAdminRole}
                                    onChange={setNewGlobalAdminRole}
                                    onVerdict={setGlobalVerdict}
                                    ariaLabel="Global administrator group or user"
                                    placeholder="e.g. global_app_admins"
                                />
                            </div>
                            <button
                                type="submit"
                                disabled={isSavingGlobal || !newGlobalAdminRole.trim() || !principalAllowsSave(globalVerdict, newGlobalAdminRole)}
                                className="mt-6 px-4 py-2 bg-qualcomm-blue hover:bg-blue-700 text-white rounded-md text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors h-[38px]"
                            >
                                <Shield size={16} />
                                {isSavingGlobal ? 'Adding...' : 'Grant Global Admin'}
                            </button>
                        </form>
                    </div>

                    <div className="mb-6">
                        <h3 className="text-md font-semibold text-gray-900 mb-2">Create Domain Mapping</h3>
                        <form onSubmit={handleCreate} className="flex gap-4 items-start bg-gray-50 p-4 rounded-lg border border-gray-200">
                            <div className="flex-1">
                                <label className="block text-sm font-medium text-gray-700 mb-1">Databricks group or user</label>
                                <PrincipalSelect
                                    value={newRole}
                                    onChange={setNewRole}
                                    onVerdict={setNewVerdict}
                                    ariaLabel="Group or user for this domain"
                                    placeholder="e.g. corp_sc_admins"
                                />
                            </div>
                            <div className="flex-1">
                                <label className="block text-sm font-medium text-gray-700 mb-1">Mapped Domain</label>
                                <DomainSelect
                                    value={newDomain}
                                    onChange={setNewDomain}
                                    domains={domains}
                                    error={domainError}
                                    onRetry={fetchDomains}
                                />
                            </div>
                            <div className="flex-1">
                                <label className="block text-sm font-medium text-gray-700 mb-1">Role Type</label>
                                <select
                                    value={newPermission}
                                    onChange={(e) => setNewPermission(e.target.value as 'viewer' | 'editor' | 'admin')}
                                    className="w-full bg-white border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue"
                                >
                                    <option value="viewer">Viewer</option>
                                    <option value="editor">Editor</option>
                                    <option value="admin">Admin</option>
                                </select>
                            </div>
                            <button
                                type="submit"
                                disabled={isSaving || !newRole.trim() || !newDomain.trim() || !principalAllowsSave(newVerdict, newRole)}
                                className="mt-6 px-4 py-2 bg-qualcomm-blue hover:bg-blue-700 text-white rounded-md text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors h-[38px]"
                            >
                                <Plus size={16} />
                                {isSaving ? 'Adding...' : 'Add Mapping'}
                            </button>
                        </form>
                    </div>

                    <div className="overflow-hidden border border-gray-200 rounded-lg">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Domain
                                    </th>
                                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        External Role
                                    </th>
                                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Role Type
                                    </th>
                                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Created
                                    </th>
                                    <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Actions
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {loading ? (
                                    <tr><td colSpan={5} className="px-6 py-8 text-center text-gray-500 text-sm">Loading mappings...</td></tr>
                                ) : mappings.length === 0 ? (
                                    <tr><td colSpan={5} className="px-6 py-8 text-center text-gray-500 text-sm">No role mappings configured. Admin operations will be restricted.</td></tr>
                                ) : (
                                    mappings.map((mapping) => (
                                        <tr key={mapping.id} className="hover:bg-gray-50 group">
                                            {editingId === mapping.id ? (
                                                <>
                                                    <td className="px-6 py-4 whitespace-nowrap border-l-[3px] border-qualcomm-blue">
                                                        <DomainSelect
                                                            value={editDomain}
                                                            onChange={setEditDomain}
                                                            domains={domains}
                                                            error={domainError}
                                                            onRetry={fetchDomains}
                                                            keep={mapping.domain}
                                                            compact
                                                        />
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <PrincipalSelect
                                                            value={editRole}
                                                            onChange={setEditRole}
                                                            onVerdict={setEditVerdict}
                                                            ariaLabel="Group or user"
                                                            compact
                                                        />
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <select
                                                            value={editPermission}
                                                            onChange={(e) => setEditPermission(e.target.value as 'viewer' | 'editor' | 'admin')}
                                                            className="w-full bg-white border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:border-qualcomm-blue"
                                                        >
                                                            <option value="viewer">Viewer</option>
                                                            <option value="editor">Editor</option>
                                                            <option value="admin">Admin</option>
                                                        </select>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                        {new Date(mapping.timestamp).toLocaleString()}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                                        <div className="flex justify-end gap-2">
                                                            <button
                                                                onClick={() => handleSaveEdit(mapping.id)}
                                                                disabled={!editRoleOk || !editDomainOk}
                                                                className="text-green-600 hover:text-green-800 transition-colors p-1 rounded-md hover:bg-green-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                                                title={editRoleOk && editDomainOk ? 'Save changes' : 'Fix the group or domain first'}
                                                            >
                                                                <Check size={16} />
                                                            </button>
                                                            <button
                                                                onClick={() => { setEditingId(null); setEditOriginal(null); }}
                                                                className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-md hover:bg-gray-100"
                                                                title="Cancel editing"
                                                            >
                                                                <X size={16} />
                                                            </button>
                                                        </div>
                                                    </td>
                                                </>
                                            ) : (
                                                <>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 border-l-[3px] border-transparent group-hover:border-qualcomm-blue transition-colors">
                                                        {mapping.domain}
                                                        {domains && !knownDomain(mapping.domain) && (
                                                            <span className="ml-2 inline-flex items-center gap-1 text-[11px] font-normal text-amber-700" title="Not in Categories & Domains, so no widget or view can be filed under it.">
                                                                <AlertTriangle size={12} /> not a domain
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 font-mono">
                                                        {mapping.external_role}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                        <span className={`px-2.5 py-1 rounded-md text-xs font-medium ${mapping.permission_level === 'admin' ? 'bg-purple-100 text-purple-700' : mapping.permission_level === 'viewer' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'}`}>
                                                            {mapping.permission_level === 'admin' ? 'Admin' : mapping.permission_level === 'viewer' ? 'Viewer' : 'Editor'}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                        {new Date(mapping.timestamp).toLocaleString()}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                                        <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            <button
                                                                onClick={() => startEditing(mapping)}
                                                                className="text-gray-400 hover:text-qualcomm-blue transition-colors p-1 rounded-md hover:bg-blue-50"
                                                                title="Edit mapping"
                                                            >
                                                                <Pencil size={16} />
                                                            </button>
                                                            <button
                                                                onClick={() => handleDelete(mapping)}
                                                                className="text-gray-400 hover:text-red-600 transition-colors p-1 rounded-md hover:bg-red-50"
                                                                title="Delete mapping"
                                                            >
                                                                <Trash2 size={16} />
                                                            </button>
                                                        </div>
                                                    </td>
                                                </>
                                            )}
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            {pendingDelete && (
                <ConfirmModal
                    title="Delete Role Mapping"
                    message={`Remove the mapping for role "${pendingDelete.external_role}" → ${pendingDelete.domain}?`}
                    detail="This cannot be undone. Users with this role will lose domain access."
                    confirmLabel="Delete"
                    variant="danger"
                    onConfirm={executeDelete}
                    onCancel={() => setPendingDelete(null)}
                />
            )}
        </>
    );
};

/**
 * A select over the taxonomy's domains. `keep` is the value a row already had:
 * shown even if it is no longer a domain, so opening an old mapping for edit
 * doesn't silently change it to the first option.
 */
const DomainSelect: React.FC<{
    value: string;
    onChange: (next: string) => void;
    domains: string[] | null;
    error: string | null;
    onRetry: () => void;
    keep?: string;
    compact?: boolean;
}> = ({ value, onChange, domains, error, onRetry, keep, compact }) => {
    const options = [...(domains ?? [])];
    const stale = keep && !options.includes(keep) && !isGlobalDomain(keep) ? keep : null;
    return (
        <div>
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                aria-label="Mapped domain"
                className={`w-full bg-white border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue ${compact ? 'px-2 py-1' : 'px-3 py-2'}`}
            >
                <option value="" disabled>{domains === null ? 'Loading domains…' : 'Choose a domain'}</option>
                {stale && <option value={stale}>{stale} (not a domain)</option>}
                {options.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            {error && (
                <p className="mt-1 text-[11px] text-amber-700">
                    Couldn't load domains: {error}{' '}
                    <button type="button" onClick={onRetry} className="underline">Retry</button>
                </p>
            )}
            {domains !== null && domains.length === 0 && !error && (
                <p className="mt-1 text-[11px] text-gray-500">No domains yet — add one under Categories &amp; Domains.</p>
            )}
        </div>
    );
};
