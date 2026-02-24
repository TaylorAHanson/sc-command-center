import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Code, Eye, RefreshCw, Send, Save, AlertCircle, Settings } from 'lucide-react';
import { loadCustomWidgets } from '../widgetRegistry';
import { useScript } from '../hooks/useScript';

interface WidgetStudioProps {
    editWidgetId?: string | null;
    onClose?: () => void;
}

class WidgetErrorBoundary extends React.Component<
    { children: React.ReactNode; onReset?: () => void; onError?: (error: Error) => void },
    { hasError: boolean; error: Error | null }
> {
    constructor(props: any) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error) {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('Widget preview error:', error, errorInfo);
        this.props.onError?.(error);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="w-full h-full p-6 flex flex-col items-center justify-center bg-rose-50 border-4 border-dashed border-rose-200 text-center">
                    <AlertCircle className="text-rose-500 mb-4" size={48} />
                    <h3 className="text-lg font-bold text-rose-800 mb-2">Build Succeeded, Render Failed</h3>
                    <p className="text-sm text-rose-600 mb-4 max-w-md">The widget code compiled successfully but crashed when React tried to render it.</p>
                    <pre className="text-xs text-left bg-white p-4 rounded-lg shadow-inner border border-rose-100 text-rose-900 max-w-lg w-full overflow-x-auto whitespace-pre-wrap">
                        {this.state.error?.message}
                    </pre>
                    <button
                        onClick={() => {
                            this.setState({ hasError: false, error: null });
                            this.props.onReset?.();
                        }}
                        className="mt-6 px-4 py-2 bg-rose-600 text-white rounded-md hover:bg-rose-700 font-medium text-sm transition-colors"
                    >
                        Try Again
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

// Basic skeleton for the page
export const WidgetStudio: React.FC<WidgetStudioProps> = ({ editWidgetId, onClose }) => {
    const [messages, setMessages] = useState<{ role: 'user' | 'assistant' | 'system', content: string }[]>([{
        role: 'assistant',
        content: "Welcome to the Widget Studio! Briefly describe the widget you want to build."
    }]);

    const [prompt, setPrompt] = useState("");
    const [isGenerating, setIsGenerating] = useState(false);
    const [code, setCode] = useState<string>("export default function MyWidget() {\n  return (\n    <div className=\"p-4 bg-white rounded-lg shadow h-full flex items-center justify-center\">\n      <h3 className=\"text-xl font-bold text-slate-800\">Hello Widget</h3>\n    </div>\n  );\n}");
    const [viewMode, setViewMode] = useState<'preview' | 'code' | 'config'>('preview');
    const [previewComponent, setPreviewComponent] = useState<React.ComponentType | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);

    // Widget Settings State
    const [widgetName, setWidgetName] = useState("New Custom Widget");
    const [widgetDescription, setWidgetDescription] = useState("");
    const [widgetCategory, setWidgetCategory] = useState("Custom");
    const [widgetDomain, setWidgetDomain] = useState("General");
    const [isExecutable, setIsExecutable] = useState(false);
    const [dataSourceType, setDataSourceType] = useState<"none" | "api" | "sql">("none");
    const [dataSource, setDataSource] = useState("");
    const [dataSourceSchema, setDataSourceSchema] = useState<any>(null);
    const [isTestingDataSource, setIsTestingDataSource] = useState(false);
    const [dataSourceTestError, setDataSourceTestError] = useState<string | null>(null);
    const [defaultW, setDefaultW] = useState(6);
    const [defaultH, setDefaultH] = useState(6);
    const [editingId, setEditingId] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Load existing widget data when editWidgetId is provided
    useEffect(() => {
        if (!editWidgetId) return;
        fetch('/api/widgets/custom')
            .then(r => r.json())
            .then(data => {
                const w = data.widgets?.find((x: any) => x.id === editWidgetId);
                if (!w) return;
                setEditingId(w.id);
                setWidgetName(w.name);
                setWidgetDescription(w.description || '');
                setWidgetCategory(w.category || 'Custom');
                setWidgetDomain(w.domain || 'General');
                setCode(w.tsx_code);
                setDataSourceType((w.data_source_type as any) || 'none');
                setDataSource(w.data_source || '');
                setDefaultW(w.default_w || 6);
                setDefaultH(w.default_h || 6);
                setMessages([{ role: 'assistant', content: `Loaded "${w.name}" for editing. Describe what you'd like to change.` }]);
            })
            .catch(console.error);
    }, [editWidgetId]);

    useEffect(() => {
        const timeoutId = setTimeout(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
        return () => clearTimeout(timeoutId);
    }, [messages, isGenerating]);

    useEffect(() => {
        // Attempt to evaluate code whenever it changes
        const evaluateCode = () => {
            try {
                setPreviewError(null);
                // @ts-ignore
                if (!window.Babel) {
                    throw new Error("Babel compiler missing. Please ensure babel-standalone CDN is loaded.");
                }

                if (!code || code.trim() === '') {
                    setPreviewComponent(() => () => (
                        <div className="w-full h-full flex items-center justify-center text-slate-500">
                            <p>Provide a prompt to generate a widget preview</p>
                        </div>
                    ));
                    return;
                }

                // Use Babel to transpile TSX to JS
                // @ts-ignore
                const transpiled = window.Babel.transform(code, {
                    filename: 'widget.tsx',
                    presets: ['react', 'typescript']
                }).code;

                // We evaluate the code in a closure providing React
                // We replace "export default" to be able to extract the component
                const executableCode = transpiled.replace(/export\s+default\s+(function|class|identifier)/, 'return $1').replace(/export\s+default\s+/, 'return ');

                // Fallback to window object if globals aren't directly available in module scope
                // @ts-ignore
                const HC = typeof Highcharts !== 'undefined' ? Highcharts : window.Highcharts;

                // eslint-disable-next-line no-new-func
                const createComponent = new Function('React', 'useScript', 'Highcharts', executableCode);
                const Component = createComponent(React, useScript, HC);
                setPreviewComponent(() => Component);
            } catch (err: any) {
                const errorMsg = err.message || String(err);
                if (previewError !== errorMsg) {
                    setPreviewError(errorMsg);
                    setPreviewComponent(null);

                    // Trigger auto-retry after a small delay to let state settle
                    if (!isGenerating) {
                        setTimeout(() => handleGenerate(errorMsg), 1000);
                    }
                }
            }
        };

        // add small debounce
        const timeoutid = setTimeout(evaluateCode, 500);
        return () => clearTimeout(timeoutid);
    }, [code]);

    const handleGenerate = async (autoRetryError?: string) => {
        if (!prompt && !autoRetryError) return;

        let newMessages = [...messages];
        if (autoRetryError) {
            setMessages(prev => [...prev, { role: 'system', content: `Auto-retrying due to compilation error: ${autoRetryError}` }]);
            newMessages.push({ role: 'system', content: `Auto-retrying due to compilation error: ${autoRetryError}` });
        } else {
            newMessages.push({ role: 'user' as const, content: prompt });
            setMessages(newMessages);
            setPrompt("");
            // Clear any old preview errors on a fresh prompt
            setPreviewError(null);
        }

        setIsGenerating(true);

        try {
            const resp = await fetch('/api/agent/widget/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: prompt || "Please fix the compilation error in the code.",
                    history: messages.filter(m => m.role !== 'system'),
                    error_log: autoRetryError || previewError,
                    current_code: code,
                    data_source_schema: dataSourceSchema,
                    data_source: dataSourceType !== 'none' ? dataSource : null,
                    data_source_type: dataSourceType !== 'none' ? dataSourceType : null
                })
            });

            const data = await resp.json();

            if (!resp.ok) {
                setMessages([...newMessages, { role: 'system', content: `Server Error: ${data.detail || resp.statusText}` }]);
                setIsGenerating(false);
                return;
            }

            if (data.code) {
                setCode(data.code);
            }

            if (!autoRetryError) {
                setMessages([...newMessages, { role: 'assistant', content: data.explanation || "Widget code generated." }]);
            } else {
                setMessages([...newMessages, { role: 'assistant', content: data.explanation || "I've attempted to fix the compilation error." }]);
            }
        } catch (e) {
            setMessages([...newMessages, { role: 'system', content: `Network Error: ${e}` }]);
        } finally {
            setIsGenerating(false);
        }
    };

    const handlePublish = async () => {
        const isEditing = !!editingId;
        const url = isEditing ? `/api/widgets/custom/${editingId}` : '/api/widgets/custom';
        const method = isEditing ? 'PUT' : 'POST';
        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: widgetName,
                    description: widgetDescription,
                    category: widgetCategory,
                    domain: widgetDomain,
                    tsx_code: code,
                    isExecutable: isExecutable,
                    data_source_type: dataSourceType,
                    data_source: dataSource,
                    default_w: defaultW,
                    default_h: defaultH
                })
            });
            if (res.ok) {
                await loadCustomWidgets();
                alert(isEditing
                    ? `"${widgetName}" updated! Changes are live in the Widget Library.`
                    : `"${widgetName}" published! Open the Widget Library (press W) to find it.`
                );
                if (isEditing) onClose?.();
            } else {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                alert(`Failed to ${isEditing ? 'update' : 'publish'} widget: ${err.detail || res.statusText}`);
            }
        } catch (err) {
            alert(`Error: ${err}`);
        }
    };

    const handleTestDataSource = async () => {
        if (dataSourceType === "none" || !dataSource) return;
        setIsTestingDataSource(true);
        setDataSourceTestError(null);
        setDataSourceSchema(null);
        try {
            const res = await fetch('/api/agent/widget/datasource/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    data_source_type: dataSourceType,
                    data_source: dataSource
                })
            });
            const data = await res.json();
            if (res.ok) {
                setDataSourceSchema(data.schema);
            } else {
                setDataSourceTestError(data.detail || "Error testing data source");
            }
        } catch (err: any) {
            setDataSourceTestError(err.message || String(err));
        } finally {
            setIsTestingDataSource(false);
        }
    };

    return (
        <div className="flex h-full w-full bg-slate-900 text-slate-100 overflow-hidden font-sans">
            {/* LEFT PANE: Chat Interface (1/3 width) */}
            <div className="w-1/3 flex flex-col border-r border-slate-700 bg-slate-800">
                <div className="p-4 border-b border-slate-700 bg-slate-900 flex justify-between items-center h-14">
                    <div className="flex items-center gap-2 text-indigo-400 font-semibold tracking-wide">
                        <Terminal size={18} />
                        <span>Widget Studio</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handlePublish}
                            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 rounded-md transition-colors font-medium">
                            <Save size={14} />
                            {editingId ? 'Update' : 'Publish'}
                        </button>
                    </div>
                </div>

                {/* Chat History */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {messages.map((m, i) => (
                        <div key={i} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className={`max-w-[85%] rounded-lg p-3 text-sm shadow-sm whitespace-pre-wrap ${m.role === 'user' ? 'bg-indigo-600 text-white rounded-br-none' :
                                m.role === 'system' ? 'bg-slate-700/50 text-slate-300 border border-slate-600/50 rounded-bl-none' :
                                    'bg-slate-700 text-slate-200 rounded-bl-none border border-slate-600'
                                }`}>
                                {m.content}
                            </div>
                        </div>
                    ))}
                    {isGenerating && (
                        <div className="flex items-start">
                            <div className="bg-slate-700 text-slate-400 rounded-lg p-3 rounded-bl-none text-sm border border-slate-600 flex items-center gap-2">
                                <RefreshCw size={14} className="animate-spin" />
                                Generating widget...
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                <div className="p-4 border-t border-slate-700 bg-slate-800/50">
                    {/* Data source context pill */}
                    {dataSourceType !== 'none' && dataSource && (
                        <div className="mb-2 flex items-center gap-2 px-3 py-1.5 bg-slate-700/60 border border-slate-600 rounded-md text-xs text-slate-300">
                            <span className={`px-1.5 py-0.5 rounded font-mono font-bold text-[10px] ${dataSourceType === 'sql' ? 'bg-indigo-900 text-indigo-300' : 'bg-emerald-900 text-emerald-300'}`}>
                                {dataSourceType.toUpperCase()}
                            </span>
                            <span className="truncate text-slate-400 font-mono">{dataSource.replace(/\s+/g, ' ').slice(0, 80)}{dataSource.length > 80 ? '…' : ''}</span>
                        </div>
                    )}
                    <div className="flex border border-slate-600 rounded-md bg-slate-900 focus-within:border-indigo-500 ring-1 focus-within:ring-indigo-500 overflow-hidden transition-all shadow-inner items-end">
                        <textarea
                            className="flex-1 bg-transparent border-none px-4 py-3 text-sm focus:outline-none text-slate-200 placeholder-slate-500 resize-none min-h-[44px] max-h-32"
                            placeholder="E.g., A bar chart showing total completed units..."
                            value={prompt}
                            onChange={e => {
                                setPrompt(e.target.value);
                                e.target.style.height = 'auto';
                                e.target.style.height = `${e.target.scrollHeight}px`;
                            }}
                            onKeyDown={e => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleGenerate();
                                    // Reset height on submit
                                    e.currentTarget.style.height = 'auto';
                                }
                            }}
                            rows={1}
                        />
                        <button
                            onClick={() => {
                                handleGenerate();
                                // We can't easily reset height here without a ref, so we rely on prompt clearing (it might not resize until manual edit, but good enough for now - or we could use a ref).
                            }}
                            disabled={isGenerating || !prompt}
                            className="px-4 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition-colors flex items-center justify-center self-stretch"
                        >
                            <Send size={16} />
                        </button>
                    </div>
                </div>
            </div>

            {/* RIGHT PANE: Workspace (2/3 width) */}
            <div className="w-2/3 flex flex-col bg-slate-900">
                <div className="flex border-b border-slate-800 bg-slate-900/50 px-4 pt-2 gap-2 h-14 items-end">
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'preview' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('preview')}
                    >
                        <Eye size={14} /> Live Preview
                    </button>
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'code' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('code')}
                    >
                        <Code size={14} /> TSX Editor
                    </button>
                    <button
                        className={`px-4 py-2 border-b-2 font-medium text-sm flex items-center gap-2 transition-colors ${viewMode === 'config' ? 'border-indigo-500 text-indigo-400 bg-slate-800/50' : 'border-transparent text-slate-400 hover:text-slate-300'}`}
                        onClick={() => setViewMode('config')}
                    >
                        <Settings size={14} /> Configuration
                    </button>
                </div>

                <div className="flex-1 relative overflow-hidden bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCI+CjxjaXJjbGUgY3g9IjIiIGN5PSIyIiByPSIxIiBmaWxsPSJyZ2JhKDI1NSwyNTUsMjU1LDAuMDMpIi8+Cjwvc3ZnPg==')]">
                    {viewMode === 'preview' ? (
                        <div className="absolute inset-0 p-8 overflow-auto w-full h-full flex items-start justify-center">
                            <div className="min-w-min min-h-min pb-16">
                                {previewError ? (
                                    <div className="w-full max-w-2xl bg-rose-950/40 border border-rose-900/50 rounded-xl p-6 text-rose-200">
                                        <div className="flex items-center gap-2 mb-4">
                                            <AlertCircle className="text-rose-500" size={24} />
                                            <h3 className="font-semibold text-lg">Compilation Error</h3>
                                        </div>
                                        <pre className="text-sm overflow-x-auto whitespace-pre-wrap p-4 bg-black/30 rounded-lg border border-rose-900/20">{previewError}</pre>
                                    </div>
                                ) : previewComponent ? (
                                    <div className="min-w-min min-h-min">
                                        <div
                                            className="bg-gray-100 rounded-xl shadow-2xl overflow-hidden flex flex-col border border-gray-300 pb-1 pr-1"
                                            style={{
                                                // Assume ~80px width per grid column, ~60px height per row to give a rough feel for Grid layout.
                                                width: `${Math.max(300, defaultW * 80)}px`,
                                                height: `${Math.max(200, defaultH * 60)}px`,
                                                resize: 'both',
                                                overflow: 'auto'
                                            }}
                                        >
                                            <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center min-h-[40px] flex-shrink-0">
                                                <h3 className="font-semibold text-gray-800 text-sm truncate">{widgetName}</h3>
                                            </div>
                                            <div className="p-4 flex-1 h-full w-full overflow-auto bg-white">
                                                <WidgetErrorBoundary
                                                    onReset={() => setPreviewComponent(null)}
                                                    onError={(err) => {
                                                        if (!isGenerating) {
                                                            setTimeout(() => handleGenerate(err.message || String(err)), 1000);
                                                        }
                                                    }}
                                                >
                                                    {React.createElement(previewComponent as any, {
                                                        id: "preview-widget",
                                                        data: {
                                                            dataSource: dataSource,
                                                            dataSourceType: dataSourceType
                                                        }
                                                    })}
                                                </WidgetErrorBoundary>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="w-full max-w-2xl bg-slate-800 rounded-xl border border-slate-700 p-8 shadow-2xl flex flex-col items-center justify-center gap-4 text-center">
                                        <RefreshCw size={32} className="text-indigo-500 mb-2 animate-spin" />
                                        <h3 className="text-lg font-medium text-slate-200">Evaluating Component...</h3>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : viewMode === 'code' ? (
                        <div className="absolute inset-0 flex flex-col bg-[#1e1e1e] p-4">
                            <textarea
                                className="w-full h-full bg-transparent text-slate-300 font-mono text-sm resize-none focus:outline-none !border-none !ring-0"
                                value={code}
                                onChange={(e) => setCode(e.target.value)}
                                spellCheck={false}
                            />
                        </div>
                    ) : (
                        <div className="absolute inset-0 flex items-start justify-center p-8 overflow-y-auto w-full h-full">
                            <div className="w-full max-w-3xl bg-slate-800 border border-slate-700 rounded-xl p-8 shadow-xl space-y-6">
                                <h2 className="text-xl font-semibold text-slate-100 border-b border-slate-700 pb-4">Widget Configuration</h2>

                                <div className="grid grid-cols-2 gap-6">
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Widget Name</label>
                                        <input
                                            value={widgetName} onChange={e => setWidgetName(e.target.value)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Description</label>
                                        <textarea
                                            value={widgetDescription} onChange={e => setWidgetDescription(e.target.value)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-none h-24"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Category</label>
                                        <input
                                            value={widgetCategory} onChange={e => setWidgetCategory(e.target.value)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                            placeholder="e.g. Analytics"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Domain</label>
                                        <input
                                            value={widgetDomain} onChange={e => setWidgetDomain(e.target.value)}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                            placeholder="e.g. Logistics"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Default Width (cols)</label>
                                        <input
                                            type="number" min="1" max="12"
                                            value={defaultW} onChange={e => setDefaultW(parseInt(e.target.value))}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                        <p className="text-xs text-slate-500 mt-1">Grid width representation (1-12)</p>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Default Height (rows)</label>
                                        <input
                                            type="number" min="1" max="12"
                                            value={defaultH} onChange={e => setDefaultH(parseInt(e.target.value))}
                                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                        />
                                        <p className="text-xs text-slate-500 mt-1">Grid height representation (1-12)</p>
                                    </div>
                                    <div className="col-span-2">
                                        <label className="block text-sm font-medium text-slate-300 mb-1.5">Data Source</label>
                                        <div className="flex gap-4 mb-4">
                                            {["none", "api", "sql"].map(type => (
                                                <label key={type} className="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
                                                    <input
                                                        type="radio"
                                                        checked={dataSourceType === type}
                                                        onChange={() => {
                                                            setDataSourceType(type as any);
                                                            setDataSource("");
                                                            setDataSourceSchema(null);
                                                            setDataSourceTestError(null);
                                                        }}
                                                        className="text-indigo-600 focus:ring-indigo-500 bg-slate-900 border-slate-600"
                                                    />
                                                    {type.toUpperCase()}
                                                </label>
                                            ))}
                                        </div>

                                        {dataSourceType !== "none" && (
                                            <div className="space-y-4 p-4 border border-slate-600 rounded-lg bg-slate-800/50">
                                                <label className="block text-sm font-medium text-slate-300 mb-1.5">
                                                    {dataSourceType === 'api' ? 'API Endpoint URL' : 'SQL Query'}
                                                </label>
                                                {dataSourceType === 'api' ? (
                                                    <input
                                                        value={dataSource} onChange={e => setDataSource(e.target.value)}
                                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                                                        placeholder="https://api.example.com/data"
                                                    />
                                                ) : (
                                                    <textarea
                                                        value={dataSource} onChange={e => setDataSource(e.target.value)}
                                                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 resize-none h-24 font-mono"
                                                        placeholder="SELECT * FROM table_name LIMIT 10"
                                                    />
                                                )}

                                                <button
                                                    onClick={handleTestDataSource}
                                                    disabled={isTestingDataSource || !dataSource}
                                                    className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors w-max"
                                                >
                                                    {isTestingDataSource ? <RefreshCw size={14} className="animate-spin" /> : <Code size={14} />}
                                                    Test & Extract Schema
                                                </button>

                                                {dataSourceTestError && (
                                                    <div className="p-3 bg-rose-900/30 border border-rose-800/50 rounded-lg text-rose-300 text-xs">
                                                        {dataSourceTestError}
                                                    </div>
                                                )}

                                                {dataSourceSchema && (
                                                    <div className="space-y-2">
                                                        <div className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
                                                            Schema Extracted Successfully!
                                                        </div>
                                                        <pre className="p-3 bg-slate-900 border border-slate-700 rounded-lg text-slate-300 text-xs overflow-x-auto">
                                                            {JSON.stringify(dataSourceSchema, null, 2)}
                                                        </pre>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div className="col-span-2">
                                        <label className="flex items-center gap-3 cursor-pointer p-3 bg-slate-900 border border-slate-600 rounded-lg hover:border-indigo-500 transition-colors">
                                            <input
                                                type="checkbox"
                                                checked={isExecutable}
                                                onChange={e => setIsExecutable(e.target.checked)}
                                                className="w-5 h-5 rounded border-slate-500 bg-slate-800 text-indigo-600 focus:ring-indigo-500 focus:ring-opacity-25"
                                            />
                                            <div>
                                                <div className="text-sm font-medium text-slate-200">Is Executable Action</div>
                                                <div className="text-xs text-slate-400">Enable if this widget submits forms, triggers pipelines, or executes server actions.</div>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
