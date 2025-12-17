import React, { useRef, useEffect } from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import type { WidgetProps } from '../widgetRegistry';

export const InventoryWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: { 
      type: 'line', 
      style: { fontFamily: 'inherit' },
      height: undefined, // Let container control height
      reflow: true // Enable automatic reflow
    },
    title: { text: '' },
    xAxis: { categories: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] },
    yAxis: { title: { text: 'Units (Thousands)' } },
    series: [
      { 
        type: 'line', 
        name: 'Snapdragon 8 Gen 2', 
        data: [120, 132, 101, 134, 90, 230, 210],
        color: '#007BFF' 
      },
      { 
        type: 'line', 
        name: 'Snapdragon 8 Gen 3', 
        data: [220, 182, 191, 234, 290, 330, 310],
        color: '#001E3C'
      }
    ],
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
        options={options} 
        containerProps={{ style: { height: '100%', width: '100%' } }} 
      />
    </div>
  );
};

