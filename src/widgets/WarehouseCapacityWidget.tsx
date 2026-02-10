import React from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import { useRef, useEffect } from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const WarehouseCapacityWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: {
      type: 'bar',
      height: undefined,
      reflow: true
    },
    title: { text: '' },
    xAxis: {
      categories: ['San Diego', 'Austin', 'Munich', 'Singapore', 'Taipei'],
      title: { text: 'Warehouse Locations' }
    },
    yAxis: {
      title: { text: 'Capacity Utilization (%)' },
      max: 100
    },
    series: [{
      type: 'bar',
      name: 'Current',
      data: [78, 65, 82, 91, 72],
      color: '#007BFF'
    }, {
      type: 'bar',
      name: 'Threshold',
      data: [85, 85, 85, 85, 85],
      color: '#F59E0B',
      dashStyle: 'Dash'
    }],
    credits: { enabled: false },
    plotOptions: {
      bar: {
        dataLabels: {
          enabled: true,
          format: '{y}%'
        }
      }
    },
    legend: {
      enabled: true
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

