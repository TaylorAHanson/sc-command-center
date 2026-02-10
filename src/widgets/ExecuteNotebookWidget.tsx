import React, { useState, useEffect } from 'react';
import { Play, FileCode, Loader2, CheckCircle, AlertCircle, RefreshCw, XCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

import { ActionConfirmationModal } from '../components/ActionConfirmationModal';
import { useActionLogger } from '../hooks/useActionLogger';

interface Notebook {
  path: string;
  name: string;
  language?: string;
}

export const ExecuteNotebookWidget: React.FC<WidgetProps> = ({ id, data }) => {
  const widgetData = data as { notebook_path?: string; default_params?: Record<string, string> };

  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebook, setSelectedNotebook] = useState<string>(widgetData?.notebook_path || '');
  const [isLoadingNotebooks, setIsLoadingNotebooks] = useState(true);
  const [notebookError, setNotebookError] = useState<string | null>(null);

  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [runId, setRunId] = useState<number | null>(null);
  const [result, setResult] = useState<{ output?: string; error?: string; executionTime?: number } | null>(null);

  const { isConfirming, initiateAction, confirmAction, cancelAction } = useActionLogger({
    widgetId: id,
    widgetName: 'Execute Notebook'
  });

  // Fetch notebooks on mount
  useEffect(() => {
    const fetchNotebooks = async () => {
      try {
        setIsLoadingNotebooks(true);
        setNotebookError(null);

        // Get current user's path
        const username = 'taylor.hanson@databricks.com'; // TODO: Get from auth context
        const userPath = `/Users/${username}`;

        const response = await fetch(`/api/jobs/notebooks?path=${encodeURIComponent(userPath)}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch notebooks: ${response.status}`);
        }

        const data = await response.json();
        setNotebooks(data.notebooks || []);
      } catch (error) {
        console.error('Error fetching notebooks:', error);
        setNotebookError(error instanceof Error ? error.message : 'Failed to load notebooks');
      } finally {
        setIsLoadingNotebooks(false);
      }
    };

    fetchNotebooks();
  }, []);

  const runNotebook = async () => {
    if (!selectedNotebook) return;

    setStatus('loading');
    setResult(null);
    setRunId(null);

    try {
      // For notebooks, we need to use the Databricks Jobs API
      // This requires creating a one-time job or using the execute endpoint
      // For now, we'll use the workspace.submit API via a simple execution
      const response = await fetch('/api/jobs/execute-notebook', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          notebook_path: selectedNotebook,
          parameters: widgetData?.default_params || {}
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to execute notebook: ${response.status}`);
      }

      const data = await response.json();
      setRunId(data.run_id);

      // Poll for completion
      await pollNotebookExecution(data.run_id);
    } catch (error) {
      console.error('Error executing notebook:', error);
      setStatus('error');
      setResult({
        error: error instanceof Error ? error.message : 'Failed to execute notebook'
      });
    }
  };

  const pollNotebookExecution = async (runId: number) => {
    const maxPolls = 60; // 5 minutes max
    let pollCount = 0;

    const poll = async () => {
      try {
        const response = await fetch(`/api/jobs/status/${runId}`);
        if (!response.ok) {
          throw new Error(`Failed to get status: ${response.status}`);
        }

        const statusData = await response.json();
        const lifecycleState = statusData.life_cycle_state;

        if (lifecycleState === 'TERMINATED' || lifecycleState === 'SKIPPED') {
          // Job completed, fetch output
          const resultState = statusData.result_state;

          if (resultState === 'SUCCESS') {
            // Fetch output
            const outputResponse = await fetch(`/api/jobs/output/${runId}`);
            const outputData = await outputResponse.json();

            setStatus('success');
            setResult({
              output: outputData.notebook_output?.result || 'Notebook executed successfully',
              executionTime: statusData.execution_duration ? Math.floor(statusData.execution_duration / 1000) : undefined
            });
          } else {
            setStatus('error');
            setResult({
              error: statusData.state_message || 'Notebook execution failed',
            });
          }
        } else if (lifecycleState === 'INTERNAL_ERROR') {
          setStatus('error');
          setResult({
            error: 'Internal error during execution'
          });
        } else if (pollCount < maxPolls) {
          // Still running, poll again
          pollCount++;
          setTimeout(poll, 5000); // Poll every 5 seconds
        } else {
          // Timeout
          setStatus('error');
          setResult({
            error: 'Execution timeout - notebook is still running but exceeded wait time'
          });
        }
      } catch (error) {
        setStatus('error');
        setResult({
          error: error instanceof Error ? error.message : 'Failed to get execution status'
        });
      }
    };

    poll();
  };

  const handleRun = () => {
    initiateAction(runNotebook);
  };

  const handleRefresh = () => {
    setStatus('idle');
    setResult(null);
    setRunId(null);
  };

  return (
    <div className="h-full flex flex-col">
      <ActionConfirmationModal
        isOpen={isConfirming}
        onClose={cancelAction}
        onConfirm={confirmAction}
        actionName="Run Notebook"
        widgetName={selectedNotebook ? notebooks.find(n => n.path === selectedNotebook)?.name || 'Notebook' : 'Notebook'}
      />
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Notebook Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Select Notebook
          </label>
          <div className="relative">
            <FileCode className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            {isLoadingNotebooks ? (
              <div className="flex items-center justify-center py-2">
                <Loader2 className="w-4 h-4 animate-spin text-blue-500 mr-2" />
                <span className="text-sm text-gray-500">Loading notebooks...</span>
              </div>
            ) : notebookError ? (
              <div className="text-sm text-red-600 py-2">
                Error: {notebookError}
              </div>
            ) : (
              <select
                value={selectedNotebook}
                onChange={(e) => {
                  setSelectedNotebook(e.target.value);
                  setStatus('idle');
                  setResult(null);
                }}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-transparent bg-white text-sm"
              >
                <option value="">-- Choose a notebook --</option>
                {notebooks.map((notebook) => (
                  <option key={notebook.path} value={notebook.path}>
                    {notebook.name} {notebook.language && `(${notebook.language})`}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Run Button */}
        <button
          onClick={handleRun}
          disabled={!selectedNotebook || status === 'loading'}
          className="w-full flex items-center justify-center space-x-2 px-4 py-2.5 bg-qualcomm-blue text-white rounded-md hover:bg-qualcomm-blue-light disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {status === 'loading' ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Executing Notebook...</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              <span>Run Notebook</span>
            </>
          )}
        </button>

        {/* Run ID Display */}
        {runId && (
          <div className="text-xs text-gray-500">
            Run ID: {runId}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-medium text-gray-700">Result</h4>
              <button
                onClick={handleRefresh}
                className="text-xs text-blue-600 hover:text-blue-800 flex items-center space-x-1"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Clear</span>
              </button>
            </div>

            {status === 'success' && (
              <div className="bg-green-50 border border-green-200 rounded-md p-3">
                <div className="flex items-center space-x-2 mb-2">
                  <CheckCircle className="w-4 h-4 text-green-600" />
                  <span className="text-sm font-medium text-green-800">
                    Execution Successful
                  </span>
                  {result.executionTime && (
                    <span className="text-xs text-green-600">
                      ({result.executionTime}s)
                    </span>
                  )}
                </div>
                {result.output && (
                  <pre className="mt-2 text-xs text-gray-700 bg-white p-2 rounded border border-green-200 overflow-auto max-h-64">
                    {result.output}
                  </pre>
                )}
              </div>
            )}

            {status === 'error' && (
              <div className="bg-red-50 border border-red-200 rounded-md p-3">
                <div className="flex items-center space-x-2 mb-2">
                  <XCircle className="w-4 h-4 text-red-600" />
                  <span className="text-sm font-medium text-red-800">
                    Execution Failed
                  </span>
                </div>
                <p className="text-xs text-red-700 mt-1">
                  {result.error || 'Unknown error occurred'}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Help Text */}
        {!result && status === 'idle' && selectedNotebook && (
          <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
            <div className="flex items-start space-x-2">
              <AlertCircle className="w-4 h-4 text-blue-600 mt-0.5" />
              <div className="text-xs text-blue-700">
                <p className="font-medium">Ready to execute</p>
                <p className="mt-1">
                  This will run the selected notebook using your Databricks workspace credentials.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
