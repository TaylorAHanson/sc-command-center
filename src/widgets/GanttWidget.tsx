import React, { useRef, useEffect } from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import highchartsGantt from 'highcharts/modules/gantt';
import type { WidgetProps } from '../widgetRegistry';

// Initialize Gantt module
if (typeof highchartsGantt === 'function') {
    (highchartsGantt as any)(Highcharts);
}

export const GanttWidget: React.FC<WidgetProps> = () => {
    const chartRef = useRef<HighchartsReact.RefObject>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Basic Gantt Chart Options
    const options: Highcharts.Options = {
        title: { text: '' },
        chart: { 
            height: undefined, // Let container control height
            reflow: true // Enable automatic reflow
        },
        xAxis: {
            currentDateIndicator: true,
            min: Date.UTC(2023, 10, 1),
            max: Date.UTC(2023, 11, 30),
        },
        yAxis: {
             uniqueNames: true
        },
        series: [{
            type: 'gantt',
            name: 'Production Phases',
            data: [
                {
                    name: 'Wafer Fab',
                    start: Date.UTC(2023, 10, 1),
                    end: Date.UTC(2023, 10, 15),
                    completed: 0.85
                },
                {
                    name: 'Testing',
                    start: Date.UTC(2023, 10, 10),
                    end: Date.UTC(2023, 10, 20),
                    completed: 0.5
                },
                {
                    name: 'Packaging',
                    start: Date.UTC(2023, 10, 18),
                    end: Date.UTC(2023, 10, 25)
                },
                {
                    name: 'Distribution',
                    start: Date.UTC(2023, 10, 24),
                    end: Date.UTC(2023, 11, 5)
                }
            ]
        }],
        credits: { enabled: false }
    };

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

    return (
        <div ref={containerRef} className="h-full w-full">
            <HighchartsReact 
                ref={chartRef}
                highcharts={Highcharts} 
                constructorType={'ganttChart'} 
                options={options} 
                containerProps={{ style: { height: '100%', width: '100%' } }} 
            />
        </div>
    );
};

