import React, { useState } from 'react';
import { X, AlertTriangle } from 'lucide-react';

interface ActionConfirmationModalProps {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: (explanation: string) => void;
    actionName: string;
    widgetName: string;
}

export const ActionConfirmationModal: React.FC<ActionConfirmationModalProps> = ({
    isOpen,
    onClose,
    onConfirm,
    actionName,
    widgetName
}) => {
    const [explanation, setExplanation] = useState('');

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/50 z-[70] flex items-center justify-center p-4">
            <div className="bg-white rounded-lg shadow-xl w-full max-w-md flex flex-col">
                <div className="flex items-center justify-between p-4 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <div className="p-1.5 bg-amber-100 rounded-md">
                            <AlertTriangle className="w-5 h-5 text-amber-600" />
                        </div>
                        <h2 className="text-lg font-semibold text-gray-900">Confirm Action</h2>
                    </div>
                    <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6">
                    <p className="text-gray-700 mb-4">
                        You are about to <strong>{actionName}</strong> on <strong>{widgetName}</strong>.
                    </p>
                    <p className="text-sm text-gray-500 mb-4">
                        Please provide a brief explanation for this action. This will be logged for auditing and training purposes.
                    </p>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Reason for Action
                        </label>
                        <textarea
                            value={explanation}
                            onChange={(e) => setExplanation(e.target.value)}
                            className="w-full h-24 px-3 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                            placeholder="e.g., Yields are low in Fab 2..."
                            autoFocus
                        />
                    </div>
                </div>

                <div className="p-4 border-t border-gray-200 flex justify-between gap-3 bg-gray-50 rounded-b-lg">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                    >
                        Cancel
                    </button>
                    <div className="flex gap-3">
                        <button
                            onClick={() => onConfirm("(Skipped)")}
                            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                        >
                            Skip and run
                        </button>
                        <button
                            onClick={() => {
                                if (explanation.trim()) {
                                    onConfirm(explanation);
                                } else {
                                    alert("Please provide an explanation.");
                                }
                            }}
                            disabled={!explanation.trim()}
                            className="px-4 py-2 text-sm font-medium text-white bg-qualcomm-blue rounded-md hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Confirm & Run
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
