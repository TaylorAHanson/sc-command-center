import React, { useState, useEffect } from 'react';
import { Plus, Trash2, Shield, RefreshCw, Pencil, Check, X } from 'lucide-react';
import { ConfirmModal } from '../../components/ConfirmModal';

interface RoleMapping {
    id: number;
    external_role: string;
    domain: string;
    permission_level: 'editor' | 'promoter';
    timestamp: string;
}

export const RoleMappings: React.FC = () => {
    const [mappings, setMappings] = useState<RoleMapping[]>([]);
    const [loading, setLoading] = useState(true);
    const [newRole, setNewRole] = useState('');
    const [newDomain, setNewDomain] = useState('');
    const [newPermission, setNewPermission] = useState<'editor' | 'promoter'>('editor');
    const [isSaving, setIsSaving] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<RoleMapping | null>(null);

    // Editing state
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editRole, setEditRole] = useState('');
    const [editDomain, setEditDomain] = useState('');
    const [editPermission, setEditPermission] = useState<'editor' | 'promoter'>('editor');

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
    }, []);

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newRole.trim() || !newDomain.trim()) return;

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
        if (!editRole.trim() || !editDomain.trim()) return;

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
                    <form onSubmit={handleCreate} className="flex gap-4 items-end mb-8 bg-gray-50 p-4 rounded-lg border border-gray-200">
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-1">External Role Name</label>
                            <input
                                type="text"
                                value={newRole}
                                onChange={(e) => setNewRole(e.target.value)}
                                className="w-full bg-white border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue"
                                placeholder="e.g. corp_sc_admins"
                                required
                            />
                        </div>
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-1">Mapped Domain</label>
                            <input
                                type="text"
                                value={newDomain}
                                onChange={(e) => setNewDomain(e.target.value)}
                                className="w-full bg-white border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue"
                                placeholder="e.g. Logistics"
                                required
                            />
                        </div>
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-1">Role Type</label>
                            <select
                                value={newPermission}
                                onChange={(e) => setNewPermission(e.target.value as 'editor' | 'promoter')}
                                className="w-full bg-white border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue"
                            >
                                <option value="editor">Editor</option>
                                <option value="promoter">Promoter</option>
                            </select>
                        </div>
                        <button
                            type="submit"
                            disabled={isSaving || !newRole.trim() || !newDomain.trim()}
                            className="px-4 py-2 bg-qualcomm-blue hover:bg-blue-700 text-white rounded-md text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors h-[38px]"
                        >
                            <Plus size={16} />
                            {isSaving ? 'Adding...' : 'Add Mapping'}
                        </button>
                    </form>

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
                                    <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-500 text-sm">Loading mappings...</td></tr>
                                ) : mappings.length === 0 ? (
                                    <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-500 text-sm">No role mappings configured. Admin operations will be restricted.</td></tr>
                                ) : (
                                    mappings.map((mapping) => (
                                        <tr key={mapping.id} className="hover:bg-gray-50 group">
                                            {editingId === mapping.id ? (
                                                <>
                                                    <td className="px-6 py-4 whitespace-nowrap border-l-[3px] border-qualcomm-blue">
                                                        <input
                                                            type="text"
                                                            value={editDomain}
                                                            onChange={(e) => setEditDomain(e.target.value)}
                                                            className="w-full bg-white border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:border-qualcomm-blue"
                                                        />
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <input
                                                            type="text"
                                                            value={editRole}
                                                            onChange={(e) => setEditRole(e.target.value)}
                                                            className="w-full bg-white border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:border-qualcomm-blue font-mono"
                                                        />
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <select
                                                            value={editPermission}
                                                            onChange={(e) => setEditPermission(e.target.value as 'editor' | 'promoter')}
                                                            className="w-full bg-white border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:border-qualcomm-blue"
                                                        >
                                                            <option value="editor">Editor</option>
                                                            <option value="promoter">Promoter</option>
                                                        </select>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                        {new Date(mapping.timestamp).toLocaleString()}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                                        <div className="flex justify-end gap-2">
                                                            <button
                                                                onClick={() => handleSaveEdit(mapping.id)}
                                                                className="text-green-600 hover:text-green-800 transition-colors p-1 rounded-md hover:bg-green-50"
                                                                title="Save changes"
                                                            >
                                                                <Check size={16} />
                                                            </button>
                                                            <button
                                                                onClick={() => setEditingId(null)}
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
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 font-mono">
                                                        {mapping.external_role}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                        <span className={`px-2.5 py-1 rounded-md text-xs font-medium ${mapping.permission_level === 'promoter' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                                                            {mapping.permission_level === 'promoter' ? 'Promoter' : 'Editor'}
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
