import React from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import { useRef, useEffect } from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const DemandForecastWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: {
      type: 'areaspline',
      height: undefined,
      reflow: true
    },
    title: { text: '' },
    xAxis: {
      categories: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    },
    yAxis: {
      title: { text: 'Units (Millions)' }
    },
    series: [
      {
        type: 'areaspline',
        name: 'Forecast',
        data: [2.5, 2.8, 3.1, 3.4, 3.6, 3.9, 4.2, 4.0, 3.8, 3.5, 3.2, 2.9],
        color: '#007BFF',
        fillOpacity: 0.3
      },
      {
        type: 'line',
        name: 'Actual',
        data: [2.4, 2.7, 3.0, null, null, null, null, null, null, null, null, null],
        color: '#10B981',
        marker: {
          enabled: true,
          radius: 4
        }
      }
    ],
    credits: { enabled: false },
    legend: {
      enabled: true
    },
    plotOptions: {
      areaspline: {
        fillOpacity: 0.3
      }
    }
  };

  useEffect(() => {
    if (!containerRef.current || !chartRef.current?.chart) return;
    const resizeObserver = new ResizeObserver(() => {
      if (chartRef.current?.chart) {
        chartRef.current.chart.reflow();
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="h-full w-full">
      <HighchartsReact ref={chartRef} highcharts={Highcharts} options={options} containerProps={{ style: { height: '100%', width: '100%' } }} />
    </div>
  );
};

