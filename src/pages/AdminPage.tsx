import React, { useEffect, useState } from 'react';
import { ActionLogs } from './ActionLogs';
import { AdminContent } from './admin/AdminContent';
import { Administrators } from './admin/Administrators';
import { TaxonomyManager } from './admin/TaxonomyManager';
import { SettingsManager } from './admin/SettingsManager';
import { DataMigration } from './admin/DataMigration';
import { MigrationBanner } from './admin/MigrationBanner';
import { ActivityLog } from './admin/ActivityLog';
import clsx from 'clsx';
import { Activity, ArrowLeft, ArrowRightLeft, LayoutGrid, List, Loader2, ShieldCheck, Sliders, Tag } from 'lucide-react';
import { fetchMe } from '../sharing';

interface AdminPageProps {
    onNavigate: (page: string | null) => void;
}

type AdminTab = 'content' | 'activity' | 'taxonomy' | 'admins' | 'settings' | 'migration' | 'logs';

const TABS: { id: AdminTab; label: string; Icon: typeof List }[] = [
    { id: 'content', label: 'Content', Icon: LayoutGrid },
    { id: 'activity', label: 'Activity', Icon: Activity },
    { id: 'taxonomy', label: 'Categories & Domains', Icon: Tag },
    { id: 'admins', label: 'Administrators', Icon: ShieldCheck },
    { id: 'settings', label: 'Settings', Icon: Sliders },
    { id: 'migration', label: 'Data Migration', Icon: ArrowRightLeft },
    { id: 'logs', label: 'Action Logs', Icon: List },
];

/**
 * The Admin Panel is for app administrators only; everything on it is
 * deployment-wide, and the server refuses its changes from anyone else.
 * Asking `my-permissions` here, rather than trusting the store's flag, keeps a
 * non-admin who reaches `#/admin` from seeing tabs flash before the store loads.
 */
export const AdminPage: React.FC<AdminPageProps> = ({ onNavigate }) => {
    const [activeTab, setActiveTab] = useState<AdminTab>('content');
    const [access, setAccess] = useState<'checking' | 'admin' | 'denied' | 'error'>('checking');

    useEffect(() => {
        let cancelled = false;
        fetchMe()
            .then(me => { if (!cancelled) setAccess(me.is_admin ? 'admin' : 'denied'); })
            .catch(() => { if (!cancelled) setAccess('error'); });
        return () => { cancelled = true; };
    }, []);

    if (access === 'checking') {
        return (
            <div className="flex h-full items-center justify-center bg-gray-50" role="status" aria-label="Checking access">
                <Loader2 className="w-6 h-6 animate-spin text-brand-blue" />
            </div>
        );
    }

    if (access !== 'admin') {
        return (
            <div className="flex h-full items-center justify-center bg-gray-50 p-6">
                <div className="max-w-md rounded-xl border border-gray-200 bg-white p-6 text-center shadow-sm">
                    <ShieldCheck className="mx-auto mb-3 text-gray-400" size={28} />
                    <h1 className="text-base font-bold text-gray-900">
                        {access === 'denied' ? 'Administrators only' : 'Couldn’t check your access'}
                    </h1>
                    <p className="mt-1 text-sm text-gray-600">
                        {access === 'denied'
                            ? 'The Admin Panel is for this app’s administrators. To get access to a view, widget or agent, ask someone who can manage it to share it with you.'
                            : 'Reload the page to try again.'}
                    </p>
                    <button
                        type="button"
                        onClick={() => onNavigate(null)}
                        className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                        <ArrowLeft size={14} /> Back
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-gray-50">
            <div className="bg-white border-b border-gray-200">
                <div className="px-6 py-4 border-b border-gray-100">
                    <h1 className="text-xl font-bold text-gray-900">Admin Panel</h1>
                    <p className="text-xs text-gray-500 mt-1">
                        Everything here applies to the whole app. Administrators can manage every view, widget and agent.
                    </p>
                </div>
                <div className="flex px-4 py-2 space-x-2 overflow-x-auto">
                    {TABS.map(({ id, label, Icon }) => (
                        <button
                            key={id}
                            onClick={() => setActiveTab(id)}
                            className={clsx(
                                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap',
                                activeTab === id ? 'bg-brand-blue text-white' : 'text-gray-600 hover:bg-gray-100',
                            )}
                        >
                            <Icon size={16} />
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            <MigrationBanner />

            <div className="flex-1 overflow-auto p-6 lg:p-8">
                {activeTab === 'content' && <AdminContent />}
                {activeTab === 'activity' && <ActivityLog />}
                {activeTab === 'taxonomy' && <TaxonomyManager />}
                {activeTab === 'admins' && <Administrators />}
                {activeTab === 'settings' && <SettingsManager />}
                {activeTab === 'migration' && <DataMigration />}
                {activeTab === 'logs' && <div className="bg-white border text-gray-900 border-gray-200 rounded-lg h-full overflow-hidden"><ActionLogs onNavigate={onNavigate} /></div>}
            </div>
        </div>
    );
};
