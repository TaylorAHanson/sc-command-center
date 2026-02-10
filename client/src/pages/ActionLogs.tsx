import React, { useEffect, useState } from 'react';
import { Loader2, ChevronDown, ChevronRight, Search } from 'lucide-react';

interface ActionLog {
    id: number;
    widget_id: string;
    widget_name: string;
    user_explanation: string;
    dashboard_context: string;
    timestamp: string;
}

export const ActionLogs: React.FC = () => {
    const [logs, setLogs] = useState<ActionLog[]>([]);
    const [loading, setLoading] = useState(true);
    const [expandedRow, setExpandedRow] = useState<number | null>(null);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const response = await fetch('http://localhost:8000/api/actions/');
                if (response.ok) {
                    const data = await response.json();
                    setLogs(data);
                }
            } catch (error) {
                console.error('Failed to fetch action logs', error);
            } finally {
                setLoading(false);
            }
        };

        fetchLogs();
    }, []);

    const toggleRow = (id: number) => {
        if (expandedRow === id) {
            setExpandedRow(null);
        } else {
            setExpandedRow(id);
        }
    };

    const filteredLogs = logs.filter(log =>
        log.widget_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        log.user_explanation.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="p-6 h-full flex flex-col">
            <div className="flex justify-between items-center mb-6">
                <h1 className="text-2xl font-bold text-qualcomm-navy">Action Logs (Telemetry)</h1>
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                    <input
                        type="text"
                        placeholder="Search logs..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                    />
                </div>
            </div>

            {loading ? (
                <div className="flex-1 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 animate-spin text-qualcomm-blue" />
                </div>
            ) : (
                <div className="flex-1 overflow-auto bg-white rounded-lg shadow border border-gray-200">
                    <table className="w-full text-sm text-left text-gray-500">
                        <thead className="text-xs text-gray-700 uppercase bg-gray-50 border-b border-gray-200 sticky top-0">
                            <tr>
                                <th className="px-6 py-3 w-10"></th>
                                <th className="px-6 py-3">Timestamp</th>
                                <th className="px-6 py-3">Widget</th>
                                <th className="px-6 py-3">User Explanation</th>
                                <th className="px-6 py-3">Action ID</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredLogs.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="px-6 py-10 text-center text-gray-500">
                                        No logs found
                                    </td>
                                </tr>
                            ) : (
                                filteredLogs.map((log) => (
                                    <React.Fragment key={log.id}>
                                        <tr
                                            className={`border-b hover:bg-gray-50 cursor-pointer ${expandedRow === log.id ? 'bg-blue-50' : ''}`}
                                            onClick={() => toggleRow(log.id)}
                                        >
                                            <td className="px-6 py-4">
                                                {expandedRow === log.id ? (
                                                    <ChevronDown className="w-4 h-4" />
                                                ) : (
                                                    <ChevronRight className="w-4 h-4" />
                                                )}
                                            </td>
                                            <td className="px-6 py-4 font-mono text-xs">
                                                {new Date(log.timestamp).toLocaleString()}
                                            </td>
                                            <td className="px-6 py-4 font-medium text-gray-900">
                                                {log.widget_name}
                                            </td>
                                            <td className="px-6 py-4">
                                                {log.user_explanation}
                                            </td>
                                            <td className="px-6 py-4 font-mono text-xs text-gray-400">
                                                #{log.id}
                                            </td>
                                        </tr>
                                        {expandedRow === log.id && (
                                            <tr className="bg-gray-50">
                                                <td colSpan={5} className="px-6 py-4 border-b">
                                                    <div className="space-y-2">
                                                        <h4 className="text-xs font-semibold uppercase text-gray-500">Dashboard Context</h4>
                                                        <pre className="bg-gray-900 text-gray-100 p-4 rounded-md text-xs font-mono overflow-auto max-h-96">
                                                            {JSON.stringify(JSON.parse(log.dashboard_context), null, 2)}
                                                        </pre>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};
