import React, { useState, useEffect } from 'react';
import { Play, Loader, CheckCircle, XCircle, Zap } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface N8NWidgetConfig {
    workflowId: string;
    name?: string;
    description?: string;
}

interface WorkflowParameter {
    name: string;
    label: string;
    type: string;
    required: boolean;
    default?: any;
    options?: string[];
    placeholder?: string;
}

interface WorkflowInfo {
    id: string;
    name: string;
    description: string;
    parameters: WorkflowParameter[];
}

export const N8NTriggerWidget: React.FC<WidgetProps> = ({ data }) => {
    const config = (data as N8NWidgetConfig) || {};
    const workflowId = config.workflowId;

    const [workflowInfo, setWorkflowInfo] = useState<WorkflowInfo | null>(null);
    const [parameters, setParameters] = useState<Record<string, any>>({});
    const [isLoading, setIsLoading] = useState(false);
    const [loadingInfo, setLoadingInfo] = useState(true);
    const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
    const [message, setMessage] = useState('');

    // Fetch workflow info
    useEffect(() => {
        if (!workflowId) {
            setLoadingInfo(false);
            return;
        }

        const fetchWorkflowInfo = async () => {
            try {
                const response = await fetch('/api/n8n/list');
                const data = await response.json();
                const workflow = data.workflows.find((w: any) => w.id === workflowId);

                if (workflow) {
                    setWorkflowInfo(workflow);
                    // Set default values
                    const defaults: Record<string, any> = {};
                    workflow.parameters?.forEach((param: WorkflowParameter) => {
                        if (param.default !== undefined) {
                            defaults[param.name] = param.default;
                        }
                    });
                    setParameters(defaults);
                }
            } catch (error) {
                console.error('Failed to fetch workflow info:', error);
            } finally {
                setLoadingInfo(false);
            }
        };

        fetchWorkflowInfo();
    }, [workflowId]);

    // Show message when no workflow is configured
    if (!workflowId) {
        return (
            <div className="h-full flex items-center justify-center p-4">
                <div className="text-center text-gray-500">
                    <Zap className="w-12 h-12 mx-auto mb-2 text-gray-400" />
                    <p className="font-semibold">No Workflow Configured</p>
                    <p className="text-sm mt-1">Please configure this widget to select an N8N workflow.</p>
                </div>
            </div>
        );
    }

    const handleTrigger = async () => {
        setIsLoading(true);
        setStatus('idle');
        setMessage('');

        try {
            const response = await fetch('/api/n8n/trigger', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    workflow_id: workflowId,
                    parameters,
                }),
            });

            const result = await response.json();

            if (response.ok) {
                setStatus('success');
                setMessage(result.message || 'Workflow triggered successfully!');
            } else {
                setStatus('error');
                setMessage(result.detail || 'Failed to trigger workflow');
            }
        } catch (error) {
            setStatus('error');
            setMessage('Network error: Failed to trigger workflow');
        } finally {
            setIsLoading(false);
            // Clear status after 5 seconds
            setTimeout(() => {
                setStatus('idle');
                setMessage('');
            }, 5000);
        }
    };

    const handleParameterChange = (paramName: string, value: any) => {
        setParameters((prev) => ({
            ...prev,
            [paramName]: value,
        }));
    };

    if (loadingInfo) {
        return (
            <div className="h-full flex items-center justify-center">
                <Loader className="w-8 h-8 animate-spin text-blue-500" />
            </div>
        );
    }

    const workflowName = workflowInfo?.name || config.name || 'N8N Workflow';
    const workflowDescription = workflowInfo?.description || config.description || '';
    const workflowParameters = workflowInfo?.parameters || [];

    return (
        <div className="h-full flex flex-col bg-gradient-to-br from-purple-50 to-blue-50 dark:from-gray-900 dark:to-gray-800 rounded-lg overflow-hidden">
            {/* Header */}
            <div className="bg-gradient-to-r from-purple-600 to-blue-600 text-white p-4">
                <div className="flex items-center space-x-2">
                    <Zap className="w-5 h-5" />
                    <h3 className="font-semibold">{workflowName}</h3>
                </div>
                {workflowDescription && (
                    <p className="text-sm text-white/80 mt-1">{workflowDescription}</p>
                )}
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {/* Parameters */}
                {workflowParameters.length > 0 && (
                    <div className="space-y-3">
                        {workflowParameters.map((param) => (
                            <div key={param.name}>
                                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                    {param.label}
                                    {param.required && <span className="text-red-500 ml-1">*</span>}
                                </label>

                                {param.type === 'select' && param.options ? (
                                    <select
                                        value={parameters[param.name] || ''}
                                        onChange={(e) => handleParameterChange(param.name, e.target.value)}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                                    >
                                        <option value="">Select...</option>
                                        {param.options.map((option) => (
                                            <option key={option} value={option}>
                                                {option}
                                            </option>
                                        ))}
                                    </select>
                                ) : param.type === 'textarea' ? (
                                    <textarea
                                        value={parameters[param.name] || ''}
                                        onChange={(e) => handleParameterChange(param.name, e.target.value)}
                                        placeholder={param.placeholder}
                                        rows={3}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                                    />
                                ) : (
                                    <input
                                        type={param.type === 'number' ? 'number' : 'text'}
                                        value={parameters[param.name] || ''}
                                        onChange={(e) => handleParameterChange(param.name, param.type === 'number' ? parseFloat(e.target.value) : e.target.value)}
                                        placeholder={param.placeholder}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                                    />
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {/* Trigger Button */}
                <button
                    onClick={handleTrigger}
                    disabled={isLoading}
                    className="w-full flex items-center justify-center space-x-2 px-4 py-3 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg hover:from-purple-700 hover:to-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg hover:shadow-xl"
                >
                    {isLoading ? (
                        <>
                            <Loader className="w-5 h-5 animate-spin" />
                            <span>Triggering...</span>
                        </>
                    ) : (
                        <>
                            <Play className="w-5 h-5" />
                            <span>Trigger Workflow</span>
                        </>
                    )}
                </button>

                {/* Status Message */}
                {status !== 'idle' && message && (
                    <div
                        className={`flex items-center space-x-2 p-3 rounded-lg ${status === 'success'
                                ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                                : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                            }`}
                    >
                        {status === 'success' ? (
                            <CheckCircle className="w-5 h-5" />
                        ) : (
                            <XCircle className="w-5 h-5" />
                        )}
                        <span className="text-sm">{message}</span>
                    </div>
                )}

                {workflowParameters.length === 0 && status === 'idle' && (
                    <div className="text-center text-gray-500 text-sm">
                        Click the button above to trigger the workflow
                    </div>
                )}
            </div>
        </div>
    );
};
