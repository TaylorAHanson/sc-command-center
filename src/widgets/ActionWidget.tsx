import React, { useState } from 'react';
import { Play, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

import { ActionConfirmationModal } from '../components/ActionConfirmationModal';
import { useActionLogger } from '../hooks/useActionLogger';

export const ActionWidget: React.FC<WidgetProps> = ({ id }) => {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const { isConfirming, initiateAction, confirmAction, cancelAction } = useActionLogger({
    widgetId: id,
    widgetName: 'Job Trigger'
  });

  const performTrigger = async () => {
    setStatus('loading');
    setMessage('');
    try {
      const res = await fetch('http://localhost:8000/api/jobs/trigger/1234', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setStatus('success');
        setMessage(`Job triggered. ID: ${data.run_id || 'Mock-Run'}`);
      } else {
        setStatus('error');
        setMessage(data.error || 'Failed to trigger job');
      }
    } catch (e) {
      setStatus('error');
      setMessage('Network error');
    }
  };

  const handleTrigger = () => {
    initiateAction(performTrigger);
  };

  return (
    <div className="h-full flex flex-col items-center justify-center p-4 text-center">
      <ActionConfirmationModal
        isOpen={isConfirming}
        onClose={cancelAction}
        onConfirm={confirmAction}
        actionName="Trigger Job"
        widgetName="Inventory Sync"
      />
      <h3 className="text-lg font-semibold mb-2">Inventory Sync Job</h3>
      <p className="text-sm text-gray-500 mb-6">Trigger the Databricks job to update global inventory levels from SAP.</p>

      <button
        onClick={handleTrigger}
        disabled={status === 'loading'}
        className="flex items-center gap-2 px-6 py-3 bg-qualcomm-blue text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors"
      >
        {status === 'loading' ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
        Run Synchronization
      </button>

      {status === 'success' && (
        <div className="mt-4 flex items-center gap-2 text-green-600 text-sm font-medium">
          <CheckCircle className="w-4 h-4" /> {message}
        </div>
      )}

      {status === 'error' && (
        <div className="mt-4 flex items-center gap-2 text-red-600 text-sm font-medium">
          <AlertCircle className="w-4 h-4" /> {message}
        </div>
      )}
    </div>
  );
};

