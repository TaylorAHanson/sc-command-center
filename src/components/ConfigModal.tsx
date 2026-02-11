import React, { useState } from 'react';
import { X, Settings } from 'lucide-react';
import type { WidgetDefinition } from '../widgetRegistry';

interface ConfigModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (config: any) => void;
    widget: WidgetDefinition | null;
    initialConfig?: any;
}

export const ConfigModal: React.FC<ConfigModalProps> = ({ isOpen, onClose, onSave, widget, initialConfig }) => {
    // For structured forms
    const [formData, setFormData] = useState<Record<string, any>>({});
    // For JSON fallback
    const [jsonConfig, setJsonConfig] = useState(JSON.stringify(initialConfig || {}, null, 2));

    React.useEffect(() => {
        if (isOpen) {
            if (widget?.configSchema) {
                // Initialize form data from initialConfig or defaults
                const data: Record<string, any> = {};
                widget.configSchema.forEach(field => {
                    // Use initialConfig value if it exists, otherwise use defaultValue
                    const hasInitialValue = initialConfig && field.key in initialConfig;
                    data[field.key] = hasInitialValue
                        ? initialConfig[field.key]
                        : (field.defaultValue !== undefined ? field.defaultValue : '');
                });
                setFormData(data);
            } else {
                setJsonConfig(JSON.stringify(initialConfig || {}, null, 2));
            }
        }
    }, [isOpen, initialConfig, widget]);

    if (!isOpen || !widget) return null;

    const hasSchema = widget.configSchema && widget.configSchema.length > 0;

    const handleFormChange = (key: string, value: any) => {
        setFormData(prev => ({ ...prev, [key]: value }));
    };

    const handleSave = () => {
        if (hasSchema) {
            // Validate required fields
            const missingFields = widget.configSchema!
                .filter(field => field.required && !formData[field.key])
                .map(field => field.label);

            if (missingFields.length > 0) {
                alert(`Please fill in required fields: ${missingFields.join(', ')}`);
                return;
            }

            // Convert number fields to actual numbers
            const processedData = { ...formData };
            widget.configSchema!.forEach(field => {
                if (field.type === 'number' && processedData[field.key]) {
                    processedData[field.key] = Number(processedData[field.key]);
                }
            });

            onSave(processedData);
        } else {
            // JSON fallback
            let parsed;
            try {
                parsed = jsonConfig ? JSON.parse(jsonConfig) : {};
            } catch (e) {
                alert("Invalid JSON format. Please check your syntax.");
                return;
            }

            try {
                onSave(parsed);
            } catch (e) {
                console.error("Error saving widget config:", e);
                alert("Failed to save widget configuration.");
            }
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4">
            <div className="bg-white rounded-lg shadow-xl w-full max-w-md flex flex-col max-h-[90vh]">
                <div className="flex items-center justify-between p-4 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <div className="p-1.5 bg-qualcomm-blue/10 rounded-md">
                            <Settings className="w-5 h-5 text-qualcomm-blue" />
                        </div>
                        <h2 className="text-lg font-semibold text-gray-900">Configure Widget</h2>
                    </div>
                    <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6 overflow-y-auto">
                    <h3 className="font-medium text-gray-900 mb-2">{widget.name}</h3>
                    <p className="text-sm text-gray-500 mb-4">{widget.description}</p>

                    {hasSchema ? (
                        <div className="space-y-4">
                            {widget.configSchema!.map(field => (
                                <div key={field.key}>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        {field.label}
                                        {field.required && <span className="text-red-500 ml-1">*</span>}
                                    </label>

                                    {field.type === 'select' ? (
                                        <select
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                                        >
                                            <option value="">-- Select --</option>
                                            {field.options?.map(opt => (
                                                <option key={opt.value} value={opt.value}>
                                                    {opt.label}
                                                </option>
                                            ))}
                                        </select>
                                    ) : field.type === 'textarea' ? (
                                        <textarea
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            placeholder={field.placeholder}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                                            rows={3}
                                        />
                                    ) : (
                                        <input
                                            type={field.type}
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            placeholder={field.placeholder}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm"
                                        />
                                    )}

                                    {field.helpText && (
                                        <p className="text-xs text-gray-500 mt-1">{field.helpText}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Configuration (JSON)
                                </label>
                                <textarea
                                    value={jsonConfig}
                                    onChange={(e) => setJsonConfig(e.target.value)}
                                    className="w-full h-32 px-3 py-2 border border-gray-300 rounded-md focus:ring-qualcomm-blue focus:border-qualcomm-blue text-sm font-mono"
                                    placeholder='{"key": "value"}'
                                />
                                <p className="text-xs text-gray-500 mt-1">
                                    Enter configuration parameters for this widget.
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-gray-200 flex justify-end gap-3 bg-gray-50 rounded-b-lg">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        className="px-4 py-2 text-sm font-medium text-white bg-qualcomm-blue rounded-md hover:bg-blue-600"
                    >
                        Add Widget
                    </button>
                </div>
            </div>
        </div>
    );
};
