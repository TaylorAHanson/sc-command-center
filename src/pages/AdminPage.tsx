import React, { useState } from 'react';
import { ActionLogs } from './ActionLogs';
import { RoleMappings } from './admin/RoleMappings';
import { WidgetManager } from './admin/WidgetManager';
import { ViewManager } from './admin/ViewManager';
import { TaxonomyManager } from './admin/TaxonomyManager';
import { SettingsManager } from './admin/SettingsManager';
import clsx from 'clsx';
import { List, Shield, Layers, LayoutGrid, Sliders, Tag } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';

interface AdminPageProps {
    onNavigate: (page: string | null) => void;
}

type AdminTab = 'logs' | 'roles' | 'widgets' | 'views' | 'taxonomy' | 'settings';

export const AdminPage: React.FC<AdminPageProps> = ({ onNavigate }) => {
    const [activeTab, setActiveTab] = useState<AdminTab>('views');
    // Domain admins reach this page too, but the settings are deployment-wide, so
    // the tab is hidden for them rather than answering 403 when they open it.
    const { isAdmin } = useDashboardStore();

    return (
        <div className="flex flex-col h-full bg-gray-50">
            {/* Top Navigation Bar */}
            <div className="bg-white border-b border-gray-200">
                <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
                    <h1 className="text-xl font-bold text-gray-900">Admin Panel</h1>
                </div>
                <div className="flex px-4 py-2 space-x-2 overflow-x-auto">
                    <button
                        onClick={() => setActiveTab('views')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'views' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <LayoutGrid size={16} />
                        View Promotion
                    </button>
                    <button
                        onClick={() => setActiveTab('widgets')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'widgets' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <Layers size={16} />
                        Widget Promotion
                    </button>
                    <button
                        onClick={() => setActiveTab('taxonomy')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'taxonomy' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <Tag size={16} />
                        Categories &amp; Domains
                    </button>
                    <button
                        onClick={() => setActiveTab('roles')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'roles' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <Shield size={16} />
                        Role Mappings
                    </button>
                    {isAdmin && (
                        <button
                            onClick={() => setActiveTab('settings')}
                            className={clsx(
                                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                                activeTab === 'settings' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                            )}
                        >
                            <Sliders size={16} />
                            Settings
                        </button>
                    )}
                    <button
                        onClick={() => setActiveTab('logs')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'logs' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <List size={16} />
                        Action Logs
                    </button>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 overflow-auto p-6 lg:p-8">
                {activeTab === 'views' && <ViewManager />}
                {activeTab === 'widgets' && <WidgetManager />}
                {activeTab === 'taxonomy' && <TaxonomyManager />}
                {activeTab === 'roles' && <RoleMappings />}
                {activeTab === 'settings' && isAdmin && <SettingsManager />}
                {activeTab === 'logs' && <div className="bg-white border text-gray-900 border-gray-200 rounded-lg h-full overflow-hidden"><ActionLogs onNavigate={onNavigate} /></div>}
            </div>
        </div>
    );
};
