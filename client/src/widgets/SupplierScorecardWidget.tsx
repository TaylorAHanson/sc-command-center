import React from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import { useRef, useEffect } from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const SupplierScorecardWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: {
      type: 'column',
      height: undefined,
      reflow: true
    },
    title: { text: '' },
    xAxis: {
      categories: ['TSMC', 'Samsung', 'Foxconn', 'ASE', 'Amkor'],
      title: { text: 'Suppliers' }
    },
    yAxis: {
      title: { text: 'Score' },
      max: 100
    },
    series: [{
      type: 'column',
      name: 'Performance Score',
      data: [92, 88, 85, 79, 76],
      colorByPoint: true,
      colors: ['#10B981', '#3B82F6', '#F59E0B', '#EF4444', '#EF4444']
    }],
    credits: { enabled: false },
    plotOptions: {
      column: {
        dataLabels: {
          enabled: true,
          format: '{y}%'
        }
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

