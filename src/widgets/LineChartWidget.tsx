import React, { useRef, useEffect, useState } from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import { RefreshCw, AlertCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';
import { executeSqlQuery } from '../services/sqlQueryService';

// Widget configuration interface
interface LineChartWidgetConfig {
    queryId: string;
    title?: string;
    xColumn: string;
    yColumn: string;
    seriesColumn?: string; // Optional: column to group by for multiple series
    xAxisType?: 'category' | 'datetime' | 'linear'; // Type of x-axis
    yAxisTitle?: string;
    parameters?: Record<string, any>;
    refreshInterval?: number; // in seconds
    chartType?: 'line' | 'spline' | 'area' | 'areaspline'; // Chart type
    showLegend?: boolean;
    showDataLabels?: boolean;
}

export const LineChartWidget: React.FC<WidgetProps> = ({ data }) => {
    // Extract configuration from widget data with defaults
    const config = {
        queryId: 'inventory_trends', // Default query
        xAxisType: 'category',
        chartType: 'line',
        showLegend: true,
        showDataLabels: false,
        xColumn: 'date',
        yColumn: 'inventory_level',
        ...data,
    } as LineChartWidgetConfig;

    const chartRef = useRef<HighchartsReact.RefObject>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // State for data fetching
    const [chartData, setChartData] = useState<Record<string, any>[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

    // Fetch data from SQL API
    const fetchData = React.useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await executeSqlQuery({
                query_id: config.queryId,
                parameters: config.parameters,
            });
            setChartData(response.rows);
            setLastRefresh(new Date());
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch data');
            console.error('Error fetching chart data:', err);
        } finally {
            setIsLoading(false);
        }
    }, [config.queryId, config.parameters]);

    // Initial data fetch
    useEffect(() => {
        fetchData();
    }, [fetchData]);

    // Auto-refresh if configured
    useEffect(() => {
        if (config.refreshInterval && config.refreshInterval > 0) {
            const interval = setInterval(fetchData, config.refreshInterval * 1000);
            return () => clearInterval(interval);
        }
    }, [config.refreshInterval, fetchData]);

    // Handle resize
    useEffect(() => {
        if (!containerRef.current || !chartRef.current?.chart) return;

        const resizeObserver = new ResizeObserver(() => {
            if (chartRef.current?.chart) {
                chartRef.current.chart.reflow();
            }
        });

        resizeObserver.observe(containerRef.current);

        return () => {
            resizeObserver.disconnect();
        };
    }, []);

    // Process data into Highcharts format
    const processChartData = (): { categories?: string[]; series: Highcharts.SeriesOptionsType[] } => {
        if (chartData.length === 0) {
            return { series: [] };
        }

        const { xColumn, yColumn, seriesColumn, xAxisType } = config;

        // If no series column, create a single series
        if (!seriesColumn) {
            const data: Array<[number | string, number]> = chartData.map((row) => {
                const xValue = row[xColumn];
                const yValue = Number(row[yColumn]) || 0;

                // Handle datetime x-axis
                if (xAxisType === 'datetime') {
                    const timestamp = new Date(String(xValue)).getTime();
                    return [timestamp, yValue];
                }

                return [xValue, yValue];
            });

            // For category axis, extract categories
            if (xAxisType === 'category') {
                const categories = chartData.map((row) => String(row[xColumn]));
                const values = chartData.map((row) => Number(row[yColumn]) || 0);

                return {
                    categories,
                    series: [
                        {
                            type: config.chartType,
                            name: config.yAxisTitle || yColumn,
                            data: values,
                            color: '#007BFF',
                        } as Highcharts.SeriesOptionsType,
                    ],
                };
            }

            return {
                series: [
                    {
                        type: config.chartType,
                        name: config.yAxisTitle || yColumn,
                        data,
                        color: '#007BFF',
                    } as Highcharts.SeriesOptionsType,
                ],
            };
        }

        // Multiple series based on seriesColumn
        const seriesMap = new Map<string, Array<[number | string, number]>>();
        const categoriesSet = new Set<string>();

        chartData.forEach((row) => {
            const seriesName = String(row[seriesColumn]);
            const xValue = row[xColumn];
            const yValue = Number(row[yColumn]) || 0;

            if (!seriesMap.has(seriesName)) {
                seriesMap.set(seriesName, []);
            }

            if (xAxisType === 'datetime') {
                const timestamp = new Date(String(xValue)).getTime();
                seriesMap.get(seriesName)!.push([timestamp, yValue]);
            } else if (xAxisType === 'category') {
                categoriesSet.add(String(xValue));
                seriesMap.get(seriesName)!.push([String(xValue), yValue]);
            } else {
                seriesMap.get(seriesName)!.push([xValue, yValue]);
            }
        });

        // Color palette
        const colors = [
            '#007BFF', '#001E3C', '#10B981', '#F59E0B', '#EF4444',
            '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16', '#F97316',
        ];

        const series: Highcharts.SeriesOptionsType[] = Array.from(seriesMap.entries()).map(
            ([name, data], index) => ({
                type: config.chartType,
                name,
                data,
                color: colors[index % colors.length],
            } as Highcharts.SeriesOptionsType)
        );

        if (xAxisType === 'category') {
            return {
                categories: Array.from(categoriesSet),
                series,
            };
        }

        return { series };
    };

    const { categories, series } = processChartData();

    // Build Highcharts options
    const options: Highcharts.Options = {
        chart: {
            type: config.chartType,
            style: { fontFamily: 'inherit' },
            height: undefined,
            reflow: true,
        },
        title: { text: config.title || '' },
        xAxis: {
            type: config.xAxisType,
            categories: config.xAxisType === 'category' ? categories : undefined,
            title: {
                text: config.xColumn
                    ? config.xColumn
                        .split('_')
                        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                        .join(' ')
                    : 'X Axis',
            },
        },
        yAxis: {
            title: {
                text: config.yAxisTitle || (config.yColumn
                    ? config.yColumn
                        .split('_')
                        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                        .join(' ')
                    : 'Y Axis'),
            },
        },
        series,
        credits: { enabled: false },
        legend: {
            enabled: config.showLegend && series.length > 1,
        },
        plotOptions: {
            series: {
                dataLabels: {
                    enabled: config.showDataLabels,
                },
            },
            area: {
                fillOpacity: 0.3,
            },
            areaspline: {
                fillOpacity: 0.3,
            },
        },
        tooltip: {
            shared: true,
        },
    };

    // Loading state
    if (isLoading && chartData.length === 0) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <RefreshCw className="w-8 h-8 text-qualcomm-blue animate-spin mx-auto mb-2" />
                    <p className="text-gray-600">Loading chart data...</p>
                </div>
            </div>
        );
    }

    // Error state
    if (error && chartData.length === 0) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
                    <p className="text-gray-900 font-medium mb-1">Failed to load chart</p>
                    <p className="text-gray-600 text-sm mb-4">{error}</p>
                    <button
                        onClick={fetchData}
                        className="px-4 py-2 bg-qualcomm-blue text-white rounded-md hover:bg-qualcomm-navy transition-colors"
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    // No data state
    if (chartData.length === 0) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="text-center">
                    <p className="text-gray-600">No data available</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full w-full flex flex-col">
            {/* Header with title and refresh */}
            <div className="flex items-center justify-between mb-2 px-2">
                {config.title && (
                    <h3 className="text-lg font-semibold text-qualcomm-navy">{config.title}</h3>
                )}
                <div className="flex items-center gap-2 ml-auto">
                    {lastRefresh && (
                        <span className="text-xs text-gray-500">
                            Updated {lastRefresh.toLocaleTimeString()}
                        </span>
                    )}
                    <button
                        onClick={fetchData}
                        disabled={isLoading}
                        className="p-1 text-gray-600 hover:text-qualcomm-blue hover:bg-gray-50 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Refresh data"
                    >
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                    </button>
                </div>
            </div>

            {/* Chart */}
            <div ref={containerRef} className="flex-1 w-full">
                <HighchartsReact
                    key={`${config.chartType}-${config.title}`}
                    ref={chartRef}
                    highcharts={Highcharts}
                    options={options}
                    immutable={true}
                    containerProps={{ style: { height: '100%', width: '100%' } }}
                />
            </div>
        </div>
    );
};
