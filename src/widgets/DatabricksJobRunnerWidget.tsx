import React, { useState, useEffect, useRef } from 'react';
import { Play, Loader2, CheckCircle, XCircle, AlertCircle, ExternalLink, X, StopCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface JobStatus {
    run_id: number;
    job_id: number;
    state: string;
    life_cycle_state: string;
    result_state?: string;
    state_message?: string;
    start_time?: number;
    end_time?: number;
    run_duration?: number;
    setup_duration?: number;
    execution_duration?: number;
    cleanup_duration?: number;
    run_page_url?: string;
    tasks?: Array<{
        task_key: string;
        state: string;
        result_state?: string;
        start_time?: number;
        end_time?: number;
        run_page_url?: string;
    }>;
}

interface JobOutput {
    run_id: number;
    job_id: number;
    notebook_output?: {
        result?: string;
        truncated?: boolean;
    };
    logs?: string;
    error?: string;
    error_trace?: string;
}

interface DatabricksJobRunnerWidgetData {
    job_id?: number;
    job_name?: string;
    default_params?: Record<string, string>;
}

export const DatabricksJobRunnerWidget: React.FC<WidgetProps> = ({ data }) => {
    const widgetData = data as DatabricksJobRunnerWidgetData;

    // Job ID is required from widget data
    const jobId = widgetData?.job_id;

    const [status, setStatus] = useState<'idle' | 'triggering' | 'running' | 'success' | 'error' | 'cancelled'>('idle');
    const [runId, setRunId] = useState<number | null>(null);
    const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
    const [jobOutput, setJobOutput] = useState<JobOutput | null>(null);
    const [errorMessage, setErrorMessage] = useState<string>('');
    const [showOutput, setShowOutput] = useState<boolean>(false);
    const [showTasks, setShowTasks] = useState<boolean>(false);

    const pollingIntervalRef = useRef<number | null>(null);

    // Clean up polling on unmount
    useEffect(() => {
        return () => {
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
            }
        };
    }, []);

    // Poll for job status
    const pollJobStatus = async (currentRunId: number) => {
        try {
            const response = await fetch(`/api/jobs/status/${currentRunId}`);
            if (!response.ok) {
                throw new Error(`Failed to get job status: ${response.status}`);
            }

            const statusData: JobStatus = await response.json();
            setJobStatus(statusData);

            // Check if job is complete
            const isTerminal = ['TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'].includes(statusData.life_cycle_state);

            if (isTerminal) {
                // Stop polling
                if (pollingIntervalRef.current) {
                    clearInterval(pollingIntervalRef.current);
                    pollingIntervalRef.current = null;
                }

                // Update status based on result
                if (statusData.result_state === 'SUCCESS') {
                    setStatus('success');
                    // Fetch output
                    fetchJobOutput(currentRunId);
                } else if (statusData.result_state === 'FAILED') {
                    setStatus('error');
                    setErrorMessage(statusData.state_message || 'Job failed');
                    // Fetch output to get error details
                    fetchJobOutput(currentRunId);
                } else if (statusData.result_state === 'CANCELED') {
                    setStatus('cancelled');
                } else {
                    setStatus('error');
                    setErrorMessage(statusData.state_message || 'Job terminated with unknown state');
                }
            }
        } catch (error) {
            console.error('Error polling job status:', error);
            // Don't stop polling on transient errors
        }
    };

    // Fetch job output
    const fetchJobOutput = async (currentRunId: number) => {
        try {
            const response = await fetch(`/api/jobs/output/${currentRunId}`);
            if (!response.ok) {
                throw new Error(`Failed to get job output: ${response.status}`);
            }

            const outputData: JobOutput = await response.json();
            setJobOutput(outputData);
        } catch (error) {
            console.error('Error fetching job output:', error);
        }
    };

    // Trigger job
    const triggerJob = async () => {
        if (!jobId) {
            setErrorMessage('Job ID not configured');
            return;
        }

        setStatus('triggering');
        setErrorMessage('');
        setJobStatus(null);
        setJobOutput(null);
        setShowOutput(false);

        try {
            const response = await fetch('/api/jobs/trigger', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    job_id: jobId,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();
            setRunId(result.run_id);
            setStatus('running');

            // Start polling for status
            pollingIntervalRef.current = window.setInterval(() => {
                pollJobStatus(result.run_id);
            }, 3000); // Poll every 3 seconds

            // Initial status check
            pollJobStatus(result.run_id);
        } catch (error) {
            console.error('Error triggering job:', error);
            setStatus('error');
            setErrorMessage(error instanceof Error ? error.message : 'Unknown error');
        }
    };

    // Cancel job
    const cancelJob = async () => {
        if (!runId) return;

        try {
            const response = await fetch(`/api/jobs/cancel/${runId}`, {
                method: 'DELETE',
            });

            if (!response.ok) {
                throw new Error(`Failed to cancel job: ${response.status}`);
            }

            // Stop polling
            if (pollingIntervalRef.current) {
                window.clearInterval(pollingIntervalRef.current);
                pollingIntervalRef.current = null;
            }

            setStatus('cancelled');
        } catch (error) {
            console.error('Error cancelling job:', error);
            setErrorMessage(error instanceof Error ? error.message : 'Failed to cancel job');
        }
    };

    // Reset to initial state
    const reset = () => {
        if (pollingIntervalRef.current) {
            window.clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
        }
        setStatus('idle');
        setRunId(null);
        setJobStatus(null);
        setJobOutput(null);
        setErrorMessage('');
        setShowOutput(false);
        setShowTasks(false);
    };

    // Format duration in milliseconds to human readable
    const formatDuration = (ms?: number) => {
        if (!ms) return 'N/A';
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);

        if (hours > 0) {
            return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${seconds % 60}s`;
        } else {
            return `${seconds}s`;
        }
    };

    // Format timestamp to human readable
    const formatTimestamp = (ts?: number) => {
        if (!ts) return 'N/A';
        return new Date(ts).toLocaleString();
    };

    // Get status icon and color
    const getStatusDisplay = () => {
        switch (status) {
            case 'triggering':
                return { icon: <Loader2 className="w-5 h-5 animate-spin" />, color: 'text-blue-600', text: 'Triggering...' };
            case 'running':
                return { icon: <Loader2 className="w-5 h-5 animate-spin" />, color: 'text-blue-600', text: 'Running...' };
            case 'success':
                return { icon: <CheckCircle className="w-5 h-5" />, color: 'text-green-600', text: 'Success' };
            case 'error':
                return { icon: <XCircle className="w-5 h-5" />, color: 'text-red-600', text: 'Failed' };
            case 'cancelled':
                return { icon: <StopCircle className="w-5 h-5" />, color: 'text-gray-600', text: 'Cancelled' };
            default:
                return null;
        }
    };

    const statusDisplay = getStatusDisplay();

    return (
        <div className="h-full flex flex-col bg-gray-50/50">
            {/* Header */}
            <div className="p-3 border-b border-gray-200 bg-white">
                <h3 className="text-sm font-semibold text-gray-900">
                    {widgetData?.job_name || 'Databricks Job Runner'}
                </h3>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {/* Run Button - Only show when idle */}
                {status === 'idle' && (
                    <div className="flex items-center justify-center h-full">
                        <button
                            onClick={triggerJob}
                            disabled={!jobId}
                            className="flex items-center justify-center gap-2 px-6 py-3 bg-qualcomm-blue text-white rounded-lg hover:bg-blue-600 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed"
                        >
                            <Play className="w-5 h-5" />
                            Run Job
                        </button>
                    </div>
                )}

                {/* Status Section */}
                {status !== 'idle' && (
                    <div className="space-y-3">
                        {/* Status Header */}
                        <div className="bg-white border border-gray-200 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                    {statusDisplay && (
                                        <>
                                            <span className={statusDisplay.color}>{statusDisplay.icon}</span>
                                            <span className={`text-sm font-semibold ${statusDisplay.color}`}>
                                                {statusDisplay.text}
                                            </span>
                                        </>
                                    )}
                                </div>
                                <button
                                    onClick={reset}
                                    className="text-gray-400 hover:text-gray-600"
                                    title="Reset"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            </div>

                            {runId && (
                                <div className="space-y-1 text-xs text-gray-600">
                                    <div className="flex justify-between">
                                        <span>Run ID:</span>
                                        <span className="font-mono">{runId}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Job ID:</span>
                                        <span className="font-mono">{jobId}</span>
                                    </div>
                                    {jobStatus?.run_page_url && (
                                        <a
                                            href={jobStatus.run_page_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="flex items-center gap-1 text-qualcomm-blue hover:underline"
                                        >
                                            View in Databricks <ExternalLink className="w-3 h-3" />
                                        </a>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Error Message */}
                        {errorMessage && (
                            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                                <div className="flex items-start gap-2">
                                    <AlertCircle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
                                    <div className="text-xs text-red-800">{errorMessage}</div>
                                </div>
                            </div>
                        )}

                        {/* Job Details */}
                        {jobStatus && (
                            <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-2">
                                <div className="text-xs font-semibold text-gray-900 mb-2">Job Details</div>

                                <div className="grid grid-cols-2 gap-2 text-xs">
                                    <div>
                                        <div className="text-gray-500">State</div>
                                        <div className="font-medium">{jobStatus.life_cycle_state}</div>
                                    </div>
                                    {jobStatus.result_state && (
                                        <div>
                                            <div className="text-gray-500">Result</div>
                                            <div className="font-medium">{jobStatus.result_state}</div>
                                        </div>
                                    )}
                                    <div>
                                        <div className="text-gray-500">Start Time</div>
                                        <div className="font-medium">{formatTimestamp(jobStatus.start_time)}</div>
                                    </div>
                                    {jobStatus.end_time && (
                                        <div>
                                            <div className="text-gray-500">End Time</div>
                                            <div className="font-medium">{formatTimestamp(jobStatus.end_time)}</div>
                                        </div>
                                    )}
                                    {jobStatus.run_duration && (
                                        <div>
                                            <div className="text-gray-500">Duration</div>
                                            <div className="font-medium">{formatDuration(jobStatus.run_duration)}</div>
                                        </div>
                                    )}
                                    {jobStatus.execution_duration && (
                                        <div>
                                            <div className="text-gray-500">Execution</div>
                                            <div className="font-medium">{formatDuration(jobStatus.execution_duration)}</div>
                                        </div>
                                    )}
                                </div>

                                {jobStatus.state_message && (
                                    <div className="pt-2 border-t border-gray-200">
                                        <div className="text-gray-500 text-xs mb-1">Message</div>
                                        <div className="text-xs text-gray-700">{jobStatus.state_message}</div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Tasks */}
                        {jobStatus?.tasks && jobStatus.tasks.length > 0 && (
                            <div className="bg-white border border-gray-200 rounded-lg p-3">
                                <button
                                    onClick={() => setShowTasks(!showTasks)}
                                    className="w-full flex items-center justify-between text-xs font-semibold text-gray-900 mb-2"
                                >
                                    <span>Tasks ({jobStatus.tasks.length})</span>
                                    <span>{showTasks ? '▼' : '▶'}</span>
                                </button>

                                {showTasks && (
                                    <div className="space-y-2">
                                        {jobStatus.tasks.map((task, idx) => (
                                            <div key={idx} className="border border-gray-200 rounded p-2 text-xs">
                                                <div className="font-medium mb-1">{task.task_key}</div>
                                                <div className="grid grid-cols-2 gap-1 text-gray-600">
                                                    <div>State: {task.state}</div>
                                                    {task.result_state && <div>Result: {task.result_state}</div>}
                                                </div>
                                                {task.run_page_url && (
                                                    <a
                                                        href={task.run_page_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="flex items-center gap-1 text-qualcomm-blue hover:underline mt-1"
                                                    >
                                                        View Task <ExternalLink className="w-3 h-3" />
                                                    </a>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Output */}
                        {jobOutput && (status === 'success' || status === 'error') && (
                            <div className="bg-white border border-gray-200 rounded-lg p-3">
                                <button
                                    onClick={() => setShowOutput(!showOutput)}
                                    className="w-full flex items-center justify-between text-xs font-semibold text-gray-900 mb-2"
                                >
                                    <span>Output</span>
                                    <span>{showOutput ? '▼' : '▶'}</span>
                                </button>

                                {showOutput && (
                                    <div className="space-y-2">
                                        {jobOutput.notebook_output?.result && (
                                            <div>
                                                <div className="text-xs text-gray-500 mb-1">Notebook Result</div>
                                                <pre className="p-2 bg-gray-900 text-gray-100 text-xs rounded overflow-x-auto max-h-48">
                                                    {jobOutput.notebook_output.result}
                                                </pre>
                                                {jobOutput.notebook_output.truncated && (
                                                    <div className="text-xs text-gray-500 mt-1">Output truncated</div>
                                                )}
                                            </div>
                                        )}

                                        {jobOutput.logs && (
                                            <div>
                                                <div className="text-xs text-gray-500 mb-1">Logs</div>
                                                <pre className="p-2 bg-gray-900 text-gray-100 text-xs rounded overflow-x-auto max-h-48">
                                                    {jobOutput.logs}
                                                </pre>
                                            </div>
                                        )}

                                        {jobOutput.error && (
                                            <div>
                                                <div className="text-xs text-red-600 mb-1">Error</div>
                                                <pre className="p-2 bg-red-50 text-red-900 text-xs rounded overflow-x-auto max-h-48">
                                                    {jobOutput.error}
                                                </pre>
                                            </div>
                                        )}

                                        {jobOutput.error_trace && (
                                            <div>
                                                <div className="text-xs text-red-600 mb-1">Error Trace</div>
                                                <pre className="p-2 bg-red-50 text-red-900 text-xs rounded overflow-x-auto max-h-48">
                                                    {jobOutput.error_trace}
                                                </pre>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Action Buttons */}
                        <div className="flex gap-2">
                            {status === 'running' && (
                                <button
                                    onClick={cancelJob}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors"
                                >
                                    <StopCircle className="w-4 h-4" />
                                    Cancel Job
                                </button>
                            )}

                            {(status === 'success' || status === 'error' || status === 'cancelled') && (
                                <button
                                    onClick={reset}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-qualcomm-blue text-white rounded-md hover:bg-blue-600 transition-colors"
                                >
                                    <Play className="w-4 h-4" />
                                    Run Again
                                </button>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
