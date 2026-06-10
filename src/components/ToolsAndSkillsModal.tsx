import React, { useState, useEffect } from 'react';
import { X, Search, Wrench, BookOpen, FileText, Info, ChevronDown, Pencil } from 'lucide-react';
import type { AvailableTool } from '../hooks/useAgentChat';
import { UserSkillsManager } from './UserSkillsManager';

interface ToolsAndSkillsModalProps {
    onClose: () => void;
    availableTools: AvailableTool[];
    availableSkills: string[];
    selectedTools: string[];
    selectedSkills: string[];
    onToolsChange: (tools: string[]) => void;
    onSkillsChange: (skills: string[]) => void;
    customInstructions: string;
    onCustomInstructionsChange: (value: string) => void;
    isLoading: boolean;
}

export const ToolsAndSkillsModal: React.FC<ToolsAndSkillsModalProps> = ({
    onClose,
    availableTools,
    availableSkills,
    selectedTools,
    selectedSkills,
    onToolsChange,
    onSkillsChange,
    customInstructions,
    onCustomInstructionsChange,
    isLoading,
}) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [showExplanation, setShowExplanation] = useState(false);

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [onClose]);

    const q = searchQuery.toLowerCase();
    const filteredTools = availableTools.filter(t =>
        t.name.toLowerCase().includes(q) || t.type.toLowerCase().includes(q)
    );
    const filteredSkills = availableSkills.filter(s => s.toLowerCase().includes(q));

    const toggleTool = (tool: string) => {
        onToolsChange(selectedTools.includes(tool)
            ? selectedTools.filter(t => t !== tool)
            : [...selectedTools, tool]);
    };
    const toggleSkill = (skill: string) => {
        onSkillsChange(selectedSkills.includes(skill)
            ? selectedSkills.filter(s => s !== skill)
            : [...selectedSkills, skill]);
    };

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-qualcomm-navy/70 backdrop-blur-sm p-4 sm:p-8 animate-in fade-in duration-200">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl h-[88vh] flex flex-col overflow-hidden border border-gray-200">
                {/* Header */}
                <div className="bg-white border-b border-gray-200 px-8 py-5 flex justify-between items-center shrink-0">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-qualcomm-blue/10 rounded-lg">
                            <Wrench className="w-5 h-5 text-qualcomm-blue" />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold text-qualcomm-navy tracking-tight">Tools &amp; Skills</h2>
                            <p className="text-sm text-gray-500 mt-0.5">Dynamically loaded based on your Unity Catalog permissions</p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-rose-500 bg-gray-50 hover:bg-rose-50 rounded-md p-2 transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-8 bg-gray-50/40 flex flex-col">
                    {/* Search */}
                    <div className="mb-6 relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                        <input
                            type="text"
                            placeholder="Search tools and skills..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-transparent shadow-sm text-sm"
                        />
                    </div>

                    {/* Custom instructions */}
                    <div className="mb-6 bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                        <div className="flex items-center mb-3">
                            <div className="w-9 h-9 bg-qualcomm-blue/10 text-qualcomm-blue rounded-md flex items-center justify-center mr-3 border border-qualcomm-blue/20">
                                <Pencil className="w-4 h-4" />
                            </div>
                            <div>
                                <h3 className="font-bold text-qualcomm-navy">Custom Instructions</h3>
                                <p className="text-xs text-gray-500">Appended to the agent's prompt on every message</p>
                            </div>
                            {customInstructions.trim() && (
                                <button
                                    onClick={() => onCustomInstructionsChange('')}
                                    className="ml-auto text-xs text-gray-400 hover:text-rose-500 font-medium"
                                >
                                    Clear
                                </button>
                            )}
                        </div>
                        <textarea
                            value={customInstructions}
                            onChange={(e) => onCustomInstructionsChange(e.target.value)}
                            rows={3}
                            placeholder="e.g. Always answer concisely. Default to the prod_analytics catalog. Format currency as USD."
                            className="w-full px-3 py-2 border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-transparent shadow-sm text-sm resize-y font-mono"
                        />
                        <p className="text-[11px] text-gray-400 mt-2">Saved in this browser. Takes precedence over default instructions, but cannot override safety rules.</p>
                    </div>

                    {isLoading ? (
                        <div className="flex-1 flex items-center justify-center py-16">
                            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-qualcomm-blue" />
                        </div>
                    ) : (
                        <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-6 min-h-0">
                            {/* Tools */}
                            <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm flex flex-col min-h-0">
                                <div className="flex items-center mb-4 border-b border-gray-100 pb-3">
                                    <div className="w-9 h-9 bg-qualcomm-blue/10 text-qualcomm-blue rounded-md flex items-center justify-center mr-3 border border-qualcomm-blue/20">
                                        <Wrench className="w-4 h-4" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-qualcomm-navy">Unity Catalog Tools</h3>
                                        <p className="text-xs text-gray-500">Functions you have EXECUTE permission on</p>
                                    </div>
                                    <span className="ml-auto bg-gray-100 text-gray-600 font-bold px-2 py-0.5 rounded text-xs">{filteredTools.length}</span>
                                </div>
                                <div className="flex-1 overflow-y-auto pr-1 space-y-2">
                                    {filteredTools.length > 0 ? filteredTools.map((tool, idx) => (
                                        <label
                                            key={idx}
                                            className={`flex items-start border rounded-md p-3 transition-colors ${tool.always_on ? 'bg-qualcomm-blue/5 border-qualcomm-blue/20 cursor-default' : 'bg-gray-50 border-gray-100 hover:border-qualcomm-blue/40 cursor-pointer'}`}
                                        >
                                            <input
                                                type="checkbox"
                                                className="w-4 h-4 mt-0.5 mr-3 text-qualcomm-blue bg-white border-gray-300 rounded focus:ring-qualcomm-blue focus:ring-2 disabled:opacity-60"
                                                checked={tool.always_on ? true : selectedTools.includes(tool.name)}
                                                disabled={tool.always_on}
                                                onChange={() => !tool.always_on && toggleTool(tool.name)}
                                            />
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="font-mono text-xs text-gray-800 break-all pr-2">{tool.name}</span>
                                                    <div className="flex items-center gap-1 shrink-0">
                                                        {tool.always_on && (
                                                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-200">always on</span>
                                                        )}
                                                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-qualcomm-blue/5 text-qualcomm-blue border border-qualcomm-blue/20">{tool.type}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        </label>
                                    )) : (
                                        <p className="text-gray-400 text-sm text-center py-8">No tools found.</p>
                                    )}
                                </div>
                            </div>

                            {/* Skills */}
                            <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm flex flex-col min-h-0">
                                <div className="flex items-center mb-4 border-b border-gray-100 pb-3">
                                    <div className="w-9 h-9 bg-qualcomm-blue/10 text-qualcomm-blue rounded-md flex items-center justify-center mr-3 border border-qualcomm-blue/20">
                                        <BookOpen className="w-4 h-4" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-qualcomm-navy">Agent Skills</h3>
                                        <p className="text-xs text-gray-500">SOPs loaded from 'skills' volumes</p>
                                    </div>
                                    <span className="ml-auto bg-gray-100 text-gray-600 font-bold px-2 py-0.5 rounded text-xs">{filteredSkills.length}</span>
                                </div>
                                <div className="flex-1 overflow-y-auto pr-1 space-y-2">
                                    {filteredSkills.length > 0 ? filteredSkills.map((skill, idx) => (
                                        <label key={idx} className="flex items-center bg-gray-50 border border-gray-100 rounded-md p-3 hover:border-qualcomm-blue/40 transition-colors cursor-pointer">
                                            <input
                                                type="checkbox"
                                                className="w-4 h-4 mr-3 text-qualcomm-blue bg-white border-gray-300 rounded focus:ring-qualcomm-blue focus:ring-2"
                                                checked={selectedSkills.includes(skill)}
                                                onChange={() => toggleSkill(skill)}
                                            />
                                            <FileText className="w-4 h-4 text-qualcomm-blue mr-2 shrink-0" />
                                            <span className="font-medium text-sm text-gray-800">{skill}</span>
                                        </label>
                                    )) : (
                                        <p className="text-gray-400 text-sm text-center py-8">No skills found.</p>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Personal (user-scoped) skills */}
                    <UserSkillsManager />

                    {/* Explanation */}
                    <div className="mt-6 border border-gray-200 rounded-lg bg-white overflow-hidden shadow-sm shrink-0">
                        <button
                            onClick={() => setShowExplanation(!showExplanation)}
                            className="w-full px-5 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors"
                        >
                            <div className="flex items-center gap-2">
                                <Info className="w-4 h-4 text-qualcomm-blue" />
                                <span className="font-bold text-qualcomm-navy text-sm">What is this?</span>
                            </div>
                            <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${showExplanation ? 'rotate-180' : ''}`} />
                        </button>
                        {showExplanation && (
                            <div className="p-5 border-t border-gray-200 text-sm text-gray-600 leading-relaxed space-y-3">
                                <p>
                                    The agent discovers its capabilities based on <strong>your specific permissions</strong> in Unity Catalog,
                                    using the On-Behalf-Of (OBO) token forwarded from your session.
                                </p>
                                <p className="text-xs bg-amber-50 text-amber-800 p-3 rounded-md border border-amber-200">
                                    <strong>Note:</strong> Two different users may see completely different tools and skills here — enforcing strict data governance.
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
