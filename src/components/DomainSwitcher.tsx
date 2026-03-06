import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Layers, Building2, Globe } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';

// Mock list of Domains
const MOCK_DOMAINS = [
    { id: 'all', name: 'All Domains', icon: Globe },
    { id: 'supply_chain', name: 'Supply Chain', icon: Layers },
    { id: 'manufacturing', name: 'Manufacturing', icon: Building2 },
    { id: 'hr', name: 'Human Resources', icon: Layers },
];

export const DomainSwitcher: React.FC = () => {
    const { activeDomain, setActiveDomain } = useDashboardStore();
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const currentDomain = MOCK_DOMAINS.find(d => d.id === activeDomain) || MOCK_DOMAINS[0];
    const CurrentIcon = currentDomain.icon;

    // Close on outside click
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [isOpen]);

    // Close on Escape
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setIsOpen(false);
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, [isOpen]);

    return (
        <div ref={containerRef} className="relative z-50">
            {/* Trigger button */}
            <button
                onClick={() => setIsOpen((prev) => !prev)}
                className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-md transition-colors"
                title="Switch Domain"
            >
                <CurrentIcon className="w-4 h-4 text-qualcomm-blue" />
                <span className="text-sm font-medium text-gray-700 whitespace-nowrap">
                    {currentDomain.name}
                </span>
                <ChevronDown className={clsx("w-4 h-4 text-gray-400 transition-transform", isOpen && "rotate-180")} />
            </button>

            {/* Dropdown panel */}
            {isOpen && (
                <div className="absolute right-0 top-full mt-2 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 origin-top-right animate-in fade-in zoom-in-95 duration-150">
                    <div className="px-3 py-2 border-b border-gray-100 mb-1">
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                            Select Domain
                        </p>
                    </div>

                    <div className="flex flex-col">
                        {MOCK_DOMAINS.map((domain) => {
                            const Icon = domain.icon;
                            const isSelected = activeDomain === domain.id || (!activeDomain && domain.id === 'all');

                            return (
                                <button
                                    key={domain.id}
                                    onClick={() => {
                                        setActiveDomain(domain.id === 'all' ? null : domain.id);
                                        setIsOpen(false);
                                    }}
                                    className={clsx(
                                        "w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors text-left",
                                        isSelected
                                            ? "bg-blue-50 text-qualcomm-blue font-medium"
                                            : "text-gray-700 hover:bg-gray-50"
                                    )}
                                >
                                    <Icon className={clsx("w-4 h-4", isSelected ? "text-qualcomm-blue" : "text-gray-400")} />
                                    {domain.name}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};
