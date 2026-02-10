import React, { useState } from 'react';
import { Play, FileCode, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

import { ActionConfirmationModal } from '../components/ActionConfirmationModal';
import { useActionLogger } from '../hooks/useActionLogger';

// Mock notebook list
const MOCK_NOTEBOOKS = [
  { id: 'notebook-1', name: 'Inventory Analysis', path: '/Workspace/Notebooks/inventory_analysis' },
  { id: 'notebook-2', name: 'Demand Forecasting', path: '/Workspace/Notebooks/demand_forecast' },
  { id: 'notebook-3', name: 'Supplier Performance', path: '/Workspace/Notebooks/supplier_perf' },
  { id: 'notebook-4', name: 'Cost Optimization', path: '/Workspace/Notebooks/cost_optimization' },
  { id: 'notebook-5', name: 'Risk Assessment', path: '/Workspace/Notebooks/risk_assessment' },
];

// Mock execution results
const MOCK_RESULTS: Record<string, { status: 'success' | 'error'; output: string; executionTime: number }> = {
  'notebook-1': {
    status: 'success',
    output: `Execution completed successfully.

Results:
- Total inventory value: $2,450,000
- Low stock items: 12
- High stock items: 3
- Average turnover rate: 4.2x

Recommendations:
- Reorder items: SKU-1234, SKU-5678, SKU-9012
- Consider reducing stock for: SKU-3456, SKU-7890`,
    executionTime: 45
  },
  'notebook-2': {
    status: 'success',
    output: `Demand forecast generated for Q1 2024.

Forecast Summary:
- Expected demand: 15,000 units
- Confidence interval: ±5%
- Peak demand period: Week 8-12

Key Insights:
- 23% increase from previous quarter
- Strong demand in North America region
- Seasonal patterns detected`,
    executionTime: 120
  },
  'notebook-3': {
    status: 'success',
    output: `Supplier performance analysis complete.

Top Performers:
1. Supplier A - Score: 95/100
2. Supplier B - Score: 92/100
3. Supplier C - Score: 88/100

Areas for Improvement:
- On-time delivery: 3 suppliers below target
- Quality metrics: 2 suppliers need attention`,
    executionTime: 67
  },
  'notebook-4': {
    status: 'success',
    output: `Cost optimization analysis finished.

Potential Savings:
- Transportation: $45,000/year
- Inventory holding: $28,000/year
- Supplier consolidation: $12,000/year

Total potential savings: $85,000/year`,
    executionTime: 89
  },
  'notebook-5': {
    status: 'error',
    output: `Execution failed.

Error: Data source connection timeout
- Unable to connect to risk database
- Please check network connectivity
- Retry in 30 seconds`,
    executionTime: 15
  },
};

export const ExecuteNotebookWidget: React.FC<WidgetProps> = ({ id }) => {
  const [selectedNotebook, setSelectedNotebook] = useState<string>('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<{ status: 'success' | 'error'; output: string; executionTime: number } | null>(null);

  const { isConfirming, initiateAction, confirmAction, cancelAction } = useActionLogger({
    widgetId: id,
    widgetName: 'Execute Notebook'
  });

  const runNotebook = () => {
    if (!selectedNotebook) return;

    setStatus('loading');
    setResult(null);

    // Simulate notebook execution
    setTimeout(() => {
      const mockResult = MOCK_RESULTS[selectedNotebook] || {
        status: 'success' as const,
        output: 'Notebook executed successfully.\n\nNo specific output available.',
        executionTime: 30
      };
      setResult(mockResult);
      setStatus(mockResult.status);
    }, 2000); // 2 second delay to simulate execution
  };

  const handleRun = () => {
    initiateAction(runNotebook);
  };

  return (
    <div className="h-full flex flex-col">
      <ActionConfirmationModal
        isOpen={isConfirming}
        onClose={cancelAction}
        onConfirm={confirmAction}
        actionName="Run Notebook"
        widgetName={selectedNotebook ? MOCK_NOTEBOOKS.find(n => n.id === selectedNotebook)?.name || 'Notebook' : 'Notebook'}
      />
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Notebook Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Select Notebook
          </label>
          <div className="relative">
            <FileCode className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
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
              {MOCK_NOTEBOOKS.map((notebook) => (
                <option key={notebook.id} value={notebook.id}>
                  {notebook.name}
                </option>
              ))}
            </select>
          </div>
          {selectedNotebook && (
            <p className="mt-1 text-xs text-gray-500">
              {MOCK_NOTEBOOKS.find(n => n.id === selectedNotebook)?.path}
            </p>
          )}
        </div>

        {/* Run Button */}
        <button
          onClick={handleRun}
          disabled={!selectedNotebook || status === 'loading'}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-qualcomm-blue text-white rounded-md hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
        >
          {status === 'loading' ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Running...
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Run Notebook
            </>
          )}
        </button>

        {/* Results */}
        {result && (
          <div className="mt-4 border rounded-lg overflow-hidden">
            <div className={`px-4 py-2 flex items-center justify-between ${result.status === 'success' ? 'bg-green-50 border-b border-green-200' : 'bg-red-50 border-b border-red-200'
              }`}>
              <div className="flex items-center gap-2">
                {result.status === 'success' ? (
                  <CheckCircle className="w-4 h-4 text-green-600" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-red-600" />
                )}
                <span className={`text-sm font-semibold ${result.status === 'success' ? 'text-green-700' : 'text-red-700'
                  }`}>
                  {result.status === 'success' ? 'Execution Successful' : 'Execution Failed'}
                </span>
              </div>
              <span className="text-xs text-gray-500">
                {result.executionTime}s
              </span>
            </div>
            <div className="p-4 bg-gray-50">
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
                {result.output}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

