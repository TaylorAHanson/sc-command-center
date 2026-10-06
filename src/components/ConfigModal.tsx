import React, { useState } from 'react';
import { X, Settings } from 'lucide-react';
import type { ConfigField, WidgetDefinition } from '../widgetRegistry';
import { useDashboardStore } from '../store/dashboardStore';
import { tabLabel } from '../store/appSpec';

interface ConfigModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (config: any) => void;
    widget: WidgetDefinition | null;
    initialConfig?: any;
    /** Changing a placed widget rather than placing one. */
    editing?: boolean;
}

/**
 * A `tabs` field: every other tab (the default, which takes in tabs added later)
 * or a pick of them. Kept as tab ids, so renaming a tab doesn't lose it.
 */
const TabsField: React.FC<{ field: ConfigField; value: unknown; onChange: (ids: string[]) => void; picking: boolean; setPicking: (on: boolean) => void }> = ({
    field, value, onChange, picking, setPicking,
}) => {
    const { activeApp, activeAppTab } = useDashboardStore();
    const tabs = activeApp ? activeApp.spec.tabs.map((t, i) => ({ id: t.id, name: tabLabel(activeApp, t, i) })) : [];
    const others = tabs.filter(t => t.id !== activeAppTab?.id);
    const chosen = Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
    const toggle = (id: string) => onChange(chosen.includes(id) ? chosen.filter(c => c !== id) : [...chosen, id]);

    return (
        <fieldset className="space-y-2">
            <legend className="block text-sm font-medium text-gray-700 mb-1">{field.label}</legend>
            <label className="flex items-start gap-2 text-sm text-gray-700">
                <input type="radio" className="mt-0.5" checked={!picking} onChange={() => { setPicking(false); onChange([]); }} />
                <span>
                    Every other tab
                    <span className="block text-xs text-gray-500">Tabs added later show up on their own.</span>
                </span>
            </label>
            <label className="flex items-start gap-2 text-sm text-gray-700">
                <input type="radio" className="mt-0.5" checked={picking} onChange={() => setPicking(true)} />
                <span>Only the tabs I pick</span>
            </label>
            {picking && (
                <div className="ml-6 space-y-1.5" role="group" aria-label="Tabs to link to">
                    {tabs.length < 2 && <p className="text-xs text-gray-500">This view has one tab. Add another and come back to pick it.</p>}
                    {tabs.map(t => (
                        <label key={t.id} className="flex items-center gap-2 text-sm text-gray-700">
                            <input type="checkbox" checked={chosen.includes(t.id)} onChange={() => toggle(t.id)} />
                            <span className="truncate">{t.name}</span>
                            {t.id === activeAppTab?.id && <span className="text-xs text-gray-400">(this tab)</span>}
                        </label>
                    ))}
                </div>
            )}
            {!picking && !others.length && (
                <p className="text-xs text-gray-500">This view has no other tabs yet, so the card will say how to add one.</p>
            )}
        </fieldset>
    );
};

export const ConfigModal: React.FC<ConfigModalProps> = ({ isOpen, onClose, onSave, widget, initialConfig, editing }) => {
    // For structured forms
    const [formData, setFormData] = useState<Record<string, any>>({});
    const [picking, setPicking] = useState<Record<string, boolean>>({});
    const [problem, setProblem] = useState<string | null>(null);
    // For JSON fallback
    const [jsonConfig, setJsonConfig] = useState(JSON.stringify(initialConfig || {}, null, 2));

    React.useEffect(() => {
        if (isOpen) {
            setProblem(null);
            if (widget?.configSchema) {
                // Initialize form data from initialConfig or defaults
                const data: Record<string, any> = {};
                const pick: Record<string, boolean> = {};
                widget.configSchema.forEach(field => {
                    // Use initialConfig value if it exists, otherwise use defaultValue
                    const hasInitialValue = initialConfig && field.key in initialConfig;
                    data[field.key] = hasInitialValue
                        ? initialConfig[field.key]
                        : (field.defaultValue !== undefined ? field.defaultValue : '');
                    if (field.type === 'tabs') pick[field.key] = Array.isArray(data[field.key]) && data[field.key].length > 0;
                });
                setFormData(data);
                setPicking(pick);
            } else {
                setJsonConfig(JSON.stringify(initialConfig || {}, null, 2));
            }
        }
    }, [isOpen, initialConfig, widget]);

    if (!isOpen || !widget) return null;

    const hasSchema = widget.configSchema && widget.configSchema.length > 0;

    const handleFormChange = (key: string, value: any) => {
        setProblem(null);
        setFormData(prev => ({ ...prev, [key]: value }));
    };

    const handleSave = () => {
        if (hasSchema) {
            const missingFields = widget.configSchema!
                .filter(field => field.required && !formData[field.key])
                .map(field => field.label);
            if (missingFields.length > 0) {
                setProblem(`Fill in ${missingFields.join(', ')}.`);
                return;
            }
            const unpicked = widget.configSchema!.find(field =>
                field.type === 'tabs' && picking[field.key] && !(Array.isArray(formData[field.key]) && formData[field.key].length));
            if (unpicked) {
                setProblem(`${unpicked.label}: tick at least one tab, or choose Every other tab.`);
                return;
            }

            // Convert number fields to actual numbers
            const processedData = { ...formData };
            widget.configSchema!.forEach(field => {
                if (field.type === 'number' && processedData[field.key]) {
                    processedData[field.key] = Number(processedData[field.key]);
                }
            });

            // Props the form doesn't show, such as a pinned version, stay as they were.
            onSave(editing ? { ...(initialConfig || {}), ...processedData } : processedData);
        } else {
            let parsed;
            try {
                parsed = jsonConfig ? JSON.parse(jsonConfig) : {};
            } catch {
                setProblem('That isn’t valid JSON. Check the brackets and quotes.');
                return;
            }

            try {
                onSave(parsed);
            } catch (e) {
                console.error("Error saving widget config:", e);
                setProblem('The settings couldn’t be saved.');
            }
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4">
            <div role="dialog" aria-label={`${widget.name} settings`} className="bg-white rounded-lg shadow-xl w-full max-w-md flex flex-col max-h-[90vh]">
                <div className="flex items-center justify-between p-4 border-b border-gray-200">
                    <div className="flex items-center gap-2">
                        <div className="p-1.5 bg-brand-blue/10 rounded-md">
                            <Settings className="w-5 h-5 text-brand-blue" />
                        </div>
                        <h2 className="text-lg font-semibold text-gray-900">Widget settings</h2>
                    </div>
                    <button onClick={onClose} className="text-gray-500 hover:text-gray-700" title="Close">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6 overflow-y-auto">
                    <h3 className="font-medium text-gray-900 mb-2">{widget.name}</h3>
                    <p className="text-sm text-gray-500 mb-4">{widget.description}</p>

                    {hasSchema ? (
                        <div className="space-y-4">
                            {widget.configSchema!.map(field => field.type === 'tabs' ? (
                                <TabsField
                                    key={field.key}
                                    field={field}
                                    value={formData[field.key]}
                                    onChange={ids => handleFormChange(field.key, ids)}
                                    picking={!!picking[field.key]}
                                    setPicking={on => { setProblem(null); setPicking(prev => ({ ...prev, [field.key]: on })); }}
                                />
                            ) : (
                                <div key={field.key}>
                                    <label htmlFor={`config-${field.key}`} className="block text-sm font-medium text-gray-700 mb-1">
                                        {field.label}
                                        {field.required && <span className="text-red-500 ml-1">*</span>}
                                    </label>

                                    {field.type === 'select' ? (
                                        <select
                                            id={`config-${field.key}`}
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-brand-blue focus:border-brand-blue text-sm"
                                        >
                                            {field.defaultValue === undefined && <option value="">-- Select --</option>}
                                            {field.options?.map(opt => (
                                                <option key={opt.value} value={opt.value}>
                                                    {opt.label}
                                                </option>
                                            ))}
                                        </select>
                                    ) : field.type === 'textarea' ? (
                                        <textarea
                                            id={`config-${field.key}`}
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            placeholder={field.placeholder}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-brand-blue focus:border-brand-blue text-sm"
                                            rows={3}
                                        />
                                    ) : (
                                        <input
                                            id={`config-${field.key}`}
                                            type={field.type}
                                            value={formData[field.key] || ''}
                                            onChange={(e) => handleFormChange(field.key, e.target.value)}
                                            placeholder={field.placeholder}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-brand-blue focus:border-brand-blue text-sm"
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
                                    onChange={(e) => { setProblem(null); setJsonConfig(e.target.value); }}
                                    className="w-full h-32 px-3 py-2 border border-gray-300 rounded-md focus:ring-brand-blue focus:border-brand-blue text-sm font-mono"
                                    placeholder='{"key": "value"}'
                                />
                                <p className="text-xs text-gray-500 mt-1">
                                    Enter configuration parameters for this widget.
                                </p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-gray-200 flex items-center justify-end gap-3 bg-gray-50 rounded-b-lg">
                    {problem && <p className="mr-auto text-sm text-red-600">{problem}</p>}
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        className="px-4 py-2 text-sm font-medium text-white bg-brand-blue rounded-md hover:bg-blue-600"
                    >
                        {editing ? 'Save' : 'Add widget'}
                    </button>
                </div>
            </div>
        </div>
    );
};
