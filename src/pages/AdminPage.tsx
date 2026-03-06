import React, { useState } from 'react';
import { ActionLogs } from './ActionLogs';
import { RoleMappings } from './admin/RoleMappings';
import { WidgetManager } from './admin/WidgetManager';
import { ViewManager } from './admin/ViewManager';
import clsx from 'clsx';
import { List, Shield, Layers, LayoutGrid } from 'lucide-react';

interface AdminPageProps {
    onNavigate: (page: string | null) => void;
}

export const AdminPage: React.FC<AdminPageProps> = ({ onNavigate }) => {
    const [activeTab, setActiveTab] = useState<'logs' | 'roles' | 'widgets' | 'views'>('views');

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
                        onClick={() => setActiveTab('roles')}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
                            activeTab === 'roles' ? "bg-qualcomm-blue text-white" : "text-gray-600 hover:bg-gray-100"
                        )}
                    >
                        <Shield size={16} />
                        Role Mappings
                    </button>
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
                {activeTab === 'roles' && <RoleMappings />}
                {activeTab === 'logs' && <div className="bg-white border text-gray-900 border-gray-200 rounded-lg h-full overflow-hidden"><ActionLogs onNavigate={onNavigate} /></div>}
            </div>
        </div>
    );
};
