import React from 'react';
import { AlertTriangle, Info } from 'lucide-react';

interface ConfirmModalProps {
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    /** 'danger' = red confirm button, 'warning' = amber, 'primary' = blue (default) */
    variant?: 'danger' | 'warning' | 'primary';
    detail?: string; // optional extra detail line in smaller text
    onConfirm: () => void;
    onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
    title,
    message,
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    variant = 'primary',
    detail,
    onConfirm,
    onCancel,
}) => {
    const btnCls = {
        primary: 'bg-qualcomm-blue hover:bg-blue-700 text-white',
        warning: 'bg-amber-500 hover:bg-amber-600 text-white',
        danger: 'bg-red-600 hover:bg-red-700 text-white',
    }[variant];

    const iconCls = {
        primary: 'text-qualcomm-blue bg-blue-50',
        warning: 'text-amber-500 bg-amber-50',
        danger: 'text-red-500 bg-red-50',
    }[variant];

    const Icon = variant === 'danger' ? AlertTriangle : Info;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
                <div className="p-6">
                    <div className="flex items-start gap-4">
                        <div className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full ${iconCls}`}>
                            <Icon size={20} />
                        </div>
                        <div className="flex-1 min-w-0">
                            <h3 className="text-base font-bold text-gray-900 mb-1">{title}</h3>
                            <p className="text-sm text-gray-600 leading-relaxed">{message}</p>
                            {detail && (
                                <p className="text-xs text-gray-400 mt-2 leading-relaxed">{detail}</p>
                            )}
                        </div>
                    </div>
                </div>
                <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
                    <button
                        onClick={onCancel}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                        {cancelLabel}
                    </button>
                    <button
                        onClick={onConfirm}
                        className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${btnCls}`}
                    >
                        {confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
};
