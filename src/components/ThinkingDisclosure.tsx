import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';

/**
 * A collapsible account of what an agent did before it answered.
 *
 * Shared by the assistant drawer and Widget Studio, which sit on opposite
 * backgrounds — hence `variant`, the same split `ModelSelect` makes. It opens
 * itself while work is in flight (the caller passes `defaultOpen`) and can be
 * pinned open or shut from then on, so a long run is readable without leaving a
 * wall of text behind once it settles.
 */
export const ThinkingDisclosure: React.FC<{
    text: string;
    label: string;
    defaultOpen: boolean;
    variant?: 'light' | 'dark';
}> = ({ text, label, defaultOpen, variant = 'light' }) => {
    const [openOverride, setOpenOverride] = useState<boolean | null>(null);
    const open = openOverride === null ? defaultOpen : openOverride;
    const trimmed = text.replace(/\n{3,}/g, '\n\n').trim();
    const dark = variant === 'dark';
    return (
        <div className="mb-2">
            <button
                type="button"
                onClick={() => setOpenOverride(!open)}
                className={`flex items-center gap-1.5 text-[11px] font-medium transition-colors ${
                    dark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-400 hover:text-gray-600'
                }`}
            >
                <ChevronRight className={`w-3 h-3 transition-transform duration-150 ${open ? 'rotate-90' : ''}`} />
                <span>{label}</span>
            </button>
            {open && (
                <div className={`mt-1.5 max-h-64 overflow-y-auto rounded-md border px-3 py-2 text-[12px] whitespace-pre-wrap leading-relaxed ${
                    dark
                        ? 'bg-slate-900/60 border-slate-700 text-slate-400'
                        : 'bg-gray-50 border-gray-100 text-gray-500'
                }`}>
                    {trimmed}
                </div>
            )}
        </div>
    );
};

export default ThinkingDisclosure;
