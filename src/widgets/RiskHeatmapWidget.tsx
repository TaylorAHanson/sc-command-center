import React from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import highchartsHeatmap from 'highcharts/modules/heatmap';
import { useRef, useEffect } from 'react';
import type { WidgetProps } from '../widgetRegistry';

// Initialize Heatmap module
if (typeof highchartsHeatmap === 'function') {
    (highchartsHeatmap as any)(Highcharts);
}

export const RiskHeatmapWidget: React.FC<WidgetProps> = () => {
  const chartRef = useRef<HighchartsReact.RefObject>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: Highcharts.Options = {
    chart: {
      type: 'heatmap',
      height: undefined,
      reflow: true
    },
    title: { text: '' },
    colorAxis: {
      min: 0,
      minColor: '#10B981',
      maxColor: '#EF4444',
      stops: [
        [0, '#10B981'],
        [0.5, '#F59E0B'],
        [1, '#EF4444']
      ]
    },
    xAxis: {
      categories: ['Q1', 'Q2', 'Q3', 'Q4']
    },
    yAxis: {
      categories: ['Geopolitical', 'Logistics', 'Supplier', 'Quality', 'Demand'],
      title: { text: '' }
    },
    series: [{
      type: 'heatmap',
      name: 'Risk Level',
      data: [
        [0, 0, 65], [0, 1, 45], [0, 2, 75], [0, 3, 35],
        [1, 0, 70], [1, 1, 50], [1, 2, 80], [1, 3, 40],
        [2, 0, 85], [2, 1, 55], [2, 2, 60], [2, 3, 50],
        [3, 0, 90], [3, 1, 60], [3, 2, 70], [3, 3, 45],
        [4, 0, 55], [4, 1, 40], [4, 2, 50], [4, 3, 30]
      ],
      dataLabels: {
        enabled: true,
        color: '#000000',
        format: '{point.value}'
      }
    }],
    credits: { enabled: false },
    tooltip: {
      formatter: function(this: any) {
        const point = this.point;
        const yAxis = this.series.yAxis;
        const xAxis = this.series.xAxis;
        return `<b>${(yAxis.categories as string[])[point.y as number]}</b><br/>
                ${(xAxis.categories as string[])[point.x as number]}: <b>${point.value}</b>`;
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

