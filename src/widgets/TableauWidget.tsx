import React, { useEffect, useRef, useState } from 'react';
import { BarChart3, Loader, AlertCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

interface TableauWidgetConfig {
    dashboardId?: string;
    dashboardUrl?: string;
    name?: string;
    toolbar?: boolean;
    tabs?: boolean;
    device?: string;
}

declare global {
    interface Window {
        tableau: any;
    }
}

export const TableauWidget: React.FC<WidgetProps> = ({ data }) => {
    const config = (data as TableauWidgetConfig) || {};
    const dashboardId = config.dashboardId;
    const providedUrl = config.dashboardUrl;

    const vizRef = useRef<HTMLDivElement>(null);
    const [vizUrl, setVizUrl] = useState<string | null>(providedUrl || null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [tableauLoaded, setTableauLoaded] = useState(false);
    const vizInstance = useRef<any>(null);

    // Load Tableau Embedding API
    useEffect(() => {
        if (window.tableau) {
            setTableauLoaded(true);
            return;
        }

        const script = document.createElement('script');
        script.src = 'https://public.tableau.com/javascripts/api/tableau.embedding.3.latest.min.js';
        script.type = 'module';
        script.onload = () => setTableauLoaded(true);
        script.onerror = () => setError('Failed to load Tableau Embedding API');
        document.head.appendChild(script);

        return () => {
            if (script.parentNode) {
                script.parentNode.removeChild(script);
            }
        };
    }, []);

    // Fetch dashboard configuration if dashboardId is provided
    useEffect(() => {
        if (dashboardId && !providedUrl) {
            const fetchDashboardConfig = async () => {
                try {
                    const response = await fetch(`/api/tableau/config/${dashboardId}`);
                    const configData = await response.json();
                    setVizUrl(configData.dashboard_url);
                } catch (err) {
                    setError('Failed to load dashboard configuration');
                }
            };
            fetchDashboardConfig();
        }
    }, [dashboardId, providedUrl]);

    // Initialize Tableau viz
    useEffect(() => {
        if (!tableauLoaded || !vizUrl || !vizRef.current) return;

        const initViz = () => {
            if (vizInstance.current) {
                vizInstance.current.dispose();
            }

            try {
                setIsLoading(true);
                setError(null);

                const viz = document.createElement('tableau-viz');
                viz.id = 'tableau-viz-' + Math.random().toString(36).substr(2, 9);
                viz.setAttribute('src', vizUrl);

                // Set options from config
                if (config.toolbar !== undefined) {
                    viz.setAttribute('toolbar', config.toolbar ? 'top' : 'hidden');
                }
                if (config.tabs !== undefined) {
                    viz.setAttribute('hide-tabs', (!config.tabs).toString());
                }
                if (config.device) {
                    viz.setAttribute('device', config.device);
                }

                // Set default dimensions
                viz.style.width = '100%';
                viz.style.height = '100%';

                // Clear and append
                if (vizRef.current) {
                    vizRef.current.innerHTML = '';
                    vizRef.current.appendChild(viz);
                }

                // Listen for load event
                viz.addEventListener('firstinteractive', () => {
                    setIsLoading(false);
                });

                viz.addEventListener('error', (event: any) => {
                    setError(event.detail?.message || 'Failed to load dashboard');
                    setIsLoading(false);
                });

                vizInstance.current = viz;
            } catch (err: any) {
                setError(err.message || 'Failed to initialize Tableau visualization');
                setIsLoading(false);
            }
        };

        initViz();

        return () => {
            if (vizInstance.current) {
                vizInstance.current.dispose?.();
            }
        };
    }, [tableauLoaded, vizUrl, config.toolbar, config.tabs, config.device]);

    // Show configuration message if no dashboard is configured
    if (!dashboardId && !providedUrl) {
        return (
            <div className="h-full flex items-center justify-center p-4">
                <div className="text-center text-gray-500">
                    <BarChart3 className="w-12 h-12 mx-auto mb-2 text-gray-400" />
                    <p className="font-semibold">No Dashboard Configured</p>
                    <p className="text-sm mt-1">Please configure this widget to select a Tableau dashboard.</p>
                </div>
            </div>
        );
    }

    const dashboardName = config.name || 'Tableau Dashboard';

    return (
        <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg overflow-hidden">
            {/* Header */}
            <div className="bg-gradient-to-r from-blue-600 to-teal-600 text-white px-4 py-3 flex items-center justify-between">
                <div className="flex items-center space-x-2">
                    <BarChart3 className="w-5 h-5" />
                    <h3 className="font-semibold">{dashboardName}</h3>
                </div>
                {isLoading && (
                    <Loader className="w-4 h-4 animate-spin" />
                )}
            </div>

            {/* Viz Container */}
            <div className="flex-1 relative">
                {error ? (
                    <div className="absolute inset-0 flex items-center justify-center p-4">
                        <div className="text-center">
                            <AlertCircle className="w-12 h-12 mx-auto mb-2 text-red-500" />
                            <p className="font-semibold text-gray-900 dark:text-gray-100">Error Loading Dashboard</p>
                            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{error}</p>
                        </div>
                    </div>
                ) : (
                    <>
                        {isLoading && (
                            <div className="absolute inset-0 flex items-center justify-center bg-white dark:bg-gray-900">
                                <div className="text-center">
                                    <Loader className="w-12 h-12 mx-auto mb-2 text-blue-500 animate-spin" />
                                    <p className="text-sm text-gray-600 dark:text-gray-400">Loading dashboard...</p>
                                </div>
                            </div>
                        )}
                        <div ref={vizRef} className="w-full h-full" />
                    </>
                )}
            </div>
        </div>
    );
};
