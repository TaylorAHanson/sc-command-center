import React, { useEffect, useState } from 'react';
import { Plus, Trash2, RefreshCw, Pencil, Check, X, Tag, Globe } from 'lucide-react';
import { ConfirmModal } from '../../components/ConfirmModal';

interface TaxonomyItem {
    id: number;
    name: string;
    timestamp: string;
}

type Kind = 'categories' | 'domains';

const KIND_META: Record<Kind, { label: string; singular: string; icon: React.ComponentType<any>; description: string }> = {
    categories: {
        label: 'Categories',
        singular: 'Category',
        icon: Tag,
        description: 'Categories group widgets by function (e.g. Monitoring, Analytics). They appear in the Widget Studio and Widget Library.',
    },
    domains: {
        label: 'Domains',
        singular: 'Domain',
        icon: Globe,
        description: 'Domains scope widgets and views to a business area (e.g. Logistics). They drive the domain filter in the Widget Library.',
    },
};

const TaxonomySection: React.FC<{ kind: Kind }> = ({ kind }) => {
    const meta = KIND_META[kind];
    const Icon = meta.icon;
    const [items, setItems] = useState<TaxonomyItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [newName, setNewName] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<TaxonomyItem | null>(null);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editName, setEditName] = useState('');

    const load = async () => {
        setLoading(true);
        try {
            const res = await fetch(`/api/taxonomy/${kind}`);
            const data = await res.json();
            if (res.ok) {
                setItems(data[kind] || []);
            }
        } catch (e) {
            console.error(`Error loading ${kind}:`, e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newName.trim()) return;
        setIsSaving(true);
        try {
            const res = await fetch(`/api/taxonomy/${kind}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName.trim() }),
            });
            if (res.ok) {
                setNewName('');
                await load();
            } else {
                const data = await res.json().catch(() => ({}));
                alert(`Error: ${data.detail || res.statusText}`);
            }
        } finally {
            setIsSaving(false);
        }
    };

    const handleSaveEdit = async (id: number) => {
        if (!editName.trim()) return;
        try {
            const res = await fetch(`/api/taxonomy/${kind}/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: editName.trim() }),
            });
            if (res.ok) {
                setItems(items.map(i => i.id === id ? { ...i, name: editName.trim() } : i));
                setEditingId(null);
            } else {
                const data = await res.json().catch(() => ({}));
                alert(`Error: ${data.detail || res.statusText}`);
            }
        } catch (e) {
            console.error(e);
        }
    };

    const executeDelete = async () => {
        if (!pendingDelete) return;
        const id = pendingDelete.id;
        setPendingDelete(null);
        try {
            const res = await fetch(`/api/taxonomy/${kind}/${id}`, { method: 'DELETE' });
            if (res.ok) {
                setItems(items.filter(i => i.id !== id));
            } else {
                const data = await res.json().catch(() => ({}));
                alert(`Error: ${data.detail || res.statusText}`);
            }
        } catch (e) {
            console.error(e);
        }
    };

    return (
        <>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200">
                <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                    <div>
                        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                            <Icon className="text-qualcomm-blue" size={20} />
                            {meta.label}
                        </h2>
                        <p className="text-sm text-gray-500 mt-1">{meta.description}</p>
                    </div>
                    <button
                        onClick={load}
                        className="p-2 text-gray-400 hover:text-qualcomm-blue transition-colors rounded-lg hover:bg-gray-50 bg-gray-50/50"
                        title="Refresh"
                    >
                        <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                <div className="p-6">
                    <form onSubmit={handleCreate} className="flex gap-4 items-end bg-gray-50 p-4 rounded-lg border border-gray-200 mb-6">
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-1">{meta.singular} name</label>
                            <input
                                type="text"
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                                className="w-full bg-white border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-qualcomm-blue focus:border-qualcomm-blue"
                                placeholder={`e.g. ${kind === 'categories' ? 'Forecasting' : 'Logistics'}`}
                                required
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={isSaving || !newName.trim()}
                            className="px-4 py-2 bg-qualcomm-blue hover:bg-blue-700 text-white rounded-md text-sm font-medium flex items-center gap-2 disabled:opacity-50 transition-colors h-[38px]"
                        >
                            <Plus size={16} />
                            {isSaving ? 'Adding...' : `Add ${meta.singular}`}
                        </button>
                    </form>

                    <div className="overflow-hidden border border-gray-200 rounded-lg">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {loading ? (
                                    <tr><td colSpan={3} className="px-6 py-8 text-center text-gray-500 text-sm">Loading...</td></tr>
                                ) : items.length === 0 ? (
                                    <tr><td colSpan={3} className="px-6 py-8 text-center text-gray-500 text-sm">No {meta.label.toLowerCase()} yet.</td></tr>
                                ) : (
                                    items.map((item) => (
                                        <tr key={item.id} className="hover:bg-gray-50 group">
                                            {editingId === item.id ? (
                                                <>
                                                    <td className="px-6 py-4">
                                                        <input
                                                            type="text"
                                                            value={editName}
                                                            onChange={e => setEditName(e.target.value)}
                                                            className="w-full bg-white border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:border-qualcomm-blue"
                                                        />
                                                    </td>
                                                    <td className="px-6 py-4 text-sm text-gray-500">{new Date(item.timestamp).toLocaleString()}</td>
                                                    <td className="px-6 py-4 text-right">
                                                        <div className="flex justify-end gap-2">
                                                            <button onClick={() => handleSaveEdit(item.id)} className="text-green-600 hover:text-green-800 p-1 rounded hover:bg-green-50"><Check size={16} /></button>
                                                            <button onClick={() => setEditingId(null)} className="text-gray-400 hover:text-gray-600 p-1 rounded hover:bg-gray-100"><X size={16} /></button>
                                                        </div>
                                                    </td>
                                                </>
                                            ) : (
                                                <>
                                                    <td className="px-6 py-4 text-sm font-medium text-gray-900">{item.name}</td>
                                                    <td className="px-6 py-4 text-sm text-gray-500">{new Date(item.timestamp).toLocaleString()}</td>
                                                    <td className="px-6 py-4 text-right">
                                                        <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            <button onClick={() => { setEditingId(item.id); setEditName(item.name); }} className="text-gray-400 hover:text-qualcomm-blue p-1 rounded hover:bg-blue-50"><Pencil size={16} /></button>
                                                            <button onClick={() => setPendingDelete(item)} className="text-gray-400 hover:text-red-600 p-1 rounded hover:bg-red-50"><Trash2 size={16} /></button>
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
                    title={`Delete ${meta.singular}`}
                    message={`Remove "${pendingDelete.name}"?`}
                    detail={`Existing widgets and views referencing "${pendingDelete.name}" will keep that label but it will no longer appear in dropdowns.`}
                    confirmLabel="Delete"
                    variant="danger"
                    onConfirm={executeDelete}
                    onCancel={() => setPendingDelete(null)}
                />
            )}
        </>
    );
};

export const TaxonomyManager: React.FC = () => {
    return (
        <div className="space-y-6">
            <TaxonomySection kind="categories" />
            <TaxonomySection kind="domains" />
        </div>
    );
};
