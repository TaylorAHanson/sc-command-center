import React from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import { useRef, useEffect } from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const CostBreakdownWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: {
      type: 'pie',
      height: undefined,
      reflow: true
    },
    title: { text: '' },
    tooltip: {
      pointFormat: '{series.name}: <b>${point.y:,.0f}M</b> ({point.percentage:.1f}%)'
    },
    plotOptions: {
      pie: {
        allowPointSelect: true,
        cursor: 'pointer',
        dataLabels: {
          enabled: true,
          format: '<b>{point.name}</b>: {point.percentage:.1f} %'
        },
        showInLegend: true
      }
    },
    series: [{
      type: 'pie',
      name: 'Cost',
      data: [
        { name: 'Raw Materials', y: 45, color: '#007BFF' },
        { name: 'Manufacturing', y: 28, color: '#10B981' },
        { name: 'Logistics', y: 15, color: '#F59E0B' },
        { name: 'Quality Control', y: 8, color: '#8B5CF6' },
        { name: 'Overhead', y: 4, color: '#EF4444' }
      ]
    }],
    credits: { enabled: false }
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

