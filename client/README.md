# Supply Chain Command Center - Widget Development Guide

Welcome! This guide will help you add new widgets to the dashboard. It's designed for developers who are new to the codebase.

## Quick Start: Adding a New Widget

Adding a widget is simple - just follow these 3 steps:

### Step 1: Create Your Widget Component

Create a new file in `src/widgets/` with your widget name, e.g., `MyNewWidget.tsx`:

```tsx
import React from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const MyNewWidget: React.FC<WidgetProps> = ({ id, data }) => {
  return (
    <div className="h-full p-4">
      <h3 className="text-lg font-semibold mb-4">My New Widget</h3>
      <p>Your widget content goes here!</p>
    </div>
  );
};
```

**Key Points:**
- Always import `WidgetProps` from `../widgetRegistry`
- Your component receives `id` (unique widget instance ID) and optional `data` (widget-specific props)
- Use `className="h-full"` on your root div so the widget fills its container
- Use Tailwind CSS classes for styling (we use the Qualcomm color scheme)

### Step 2: Import and Register Your Widget

Open `src/widgetRegistry.ts` and:

1. **Import your widget** at the top:
```tsx
import { MyNewWidget } from './widgets/MyNewWidget';
```

2. **Register it** using `registerWidget()`:
```tsx
registerWidget({
  id: 'my_new_widget',           // Unique ID (use snake_case)
  name: 'My New Widget',          // Display name
  component: MyNewWidget,         // Your component
  defaultW: 4,                    // Default width (grid units, 1-12)
  defaultH: 4,                    // Default height (grid units)
  description: 'A brief description of what this widget does.',
  category: 'Analytics'            // Category: 'Monitoring', 'Analytics', 'Planning', 'AI & Automation', or 'Actions'
});
```

**Grid Sizing Guide:**
- The dashboard uses a 12-column grid
- `defaultW: 4` = 1/3 of the width
- `defaultW: 6` = 1/2 of the width
- `defaultW: 12` = full width
- Height is in grid rows (each row is ~60px)

**Available Categories:**
- `Monitoring` - Real-time status, alerts, KPIs
- `Analytics` - Charts, data visualization, reports
- `Planning` - Schedules, forecasts, timelines
- `AI & Automation` - AI assistants, automated actions
- `Actions` - Buttons, forms, external links

### Step 3: That's It! 🎉

Your widget will automatically appear in the Widget Library under its category. Users can drag it onto their dashboards.

## Widget Examples

### Simple Text Widget
```tsx
import React from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const SimpleWidget: React.FC<WidgetProps> = () => {
  return (
    <div className="h-full p-4">
      <h2 className="text-xl font-bold text-qualcomm-navy mb-2">Title</h2>
      <p className="text-gray-600">Your content here</p>
    </div>
  );
};
```

### Widget with Data/Props
```tsx
import React from 'react';
import type { WidgetProps } from '../widgetRegistry';

export const DataWidget: React.FC<WidgetProps> = ({ data }) => {
  const title = data?.title || 'Default Title';
  const items = data?.items || [];
  
  return (
    <div className="h-full p-4">
      <h2 className="text-xl font-bold mb-4">{title}</h2>
      <ul className="space-y-2">
        {items.map((item: string, i: number) => (
          <li key={i} className="text-gray-700">{item}</li>
        ))}
      </ul>
    </div>
  );
};
```

### Widget with Charts (Highcharts)
```tsx
import React, { useRef, useEffect } from 'react';
import Highcharts from 'highcharts';
import HighchartsReact from 'highcharts-react-official';
import type { WidgetProps } from '../widgetRegistry';

export const ChartWidget: React.FC<WidgetProps> = () => {
  const chartComponentRef = useRef<HighchartsReact.RefObject>(null);

  // Make chart responsive to container resizing
  useEffect(() => {
    const chart = chartComponentRef.current?.chart;
    if (!chart) return;

    const resizeObserver = new ResizeObserver(() => {
      chart.reflow();
    });

    const container = chart.container.parentNode as HTMLElement;
    if (container) {
      resizeObserver.observe(container);
    }

    return () => {
      if (container) {
        resizeObserver.disconnect();
      }
    };
  }, []);

  const options: Highcharts.Options = {
    chart: {
      type: 'line',
      height: '100%',
      reflow: true,
    },
    title: { text: 'My Chart' },
    series: [{
      type: 'line',
      data: [1, 2, 3, 4, 5]
    }],
    credits: { enabled: false }
  };

  return (
    <div className="h-full">
      <HighchartsReact
        highcharts={Highcharts}
        options={options}
        containerProps={{ style: { height: '100%' } }}
        ref={chartComponentRef}
      />
    </div>
  );
};
```

## Design Guidelines

### Colors (Qualcomm Brand)
- **Primary Navy**: `text-qualcomm-navy` or `#001E3C`
- **Primary Blue**: `text-qualcomm-blue` or `#007BFF`
- **Background**: `bg-white` or `bg-gray-50`
- **Text**: `text-gray-700` for body, `text-gray-600` for secondary

### Spacing
- Use Tailwind spacing: `p-4`, `mb-4`, `gap-2`, etc.
- Keep padding consistent: `p-4` for widget content

### Typography
- Headings: `text-lg font-semibold` or `text-xl font-bold`
- Body: `text-sm` or `text-base`
- Use `text-qualcomm-navy` for headings

## Common Patterns

### Making Widgets Responsive
Widgets automatically resize with the grid. For charts, use `ResizeObserver` (see Chart Widget example above).

### Handling User Interactions
```tsx
const [count, setCount] = useState(0);

return (
  <div className="h-full p-4">
    <button 
      onClick={() => setCount(count + 1)}
      className="px-4 py-2 bg-qualcomm-blue text-white rounded hover:bg-blue-600"
    >
      Clicked {count} times
    </button>
  </div>
);
```

### Fetching Data (Future)
When backend APIs are ready, you'll fetch data like this:
```tsx
useEffect(() => {
  fetch('/api/my-endpoint')
    .then(res => res.json())
    .then(data => setData(data));
}, []);
```

## File Structure

```
client/src/
├── widgets/              # All widget components go here
│   ├── MyNewWidget.tsx   # Your new widget
│   └── ...
├── widgetRegistry.ts     # Register your widget here
└── components/
    └── BaseWidget.tsx    # Wrapper that adds header, drag handle, etc.
```

## Tips for Junior Developers

1. **Start Simple**: Create a basic text widget first, then add complexity
2. **Copy & Modify**: Look at existing widgets (`AlertsWidget.tsx` is a good simple example)
3. **Test Often**: After registering, open the Widget Library and drag your widget to a dashboard
4. **Use Tailwind**: We use Tailwind CSS - check [tailwindcss.com](https://tailwindcss.com) for classes
5. **Ask Questions**: The widget system is designed to be simple - if something feels complicated, ask!

## Troubleshooting

**Widget doesn't appear in library?**
- Check that you imported it in `widgetRegistry.ts`
- Check that you called `registerWidget()` with all required fields
- Check the browser console for errors

**Widget looks broken?**
- Make sure your root div has `className="h-full"`
- Check that you're using valid Tailwind classes
- Look at similar widgets for reference

**Widget doesn't resize properly?**
- For charts, make sure you added the `ResizeObserver` pattern
- Check that chart options have `height: '100%'` and `reflow: true`

## Next Steps

Once you're comfortable:
- Add data fetching from the backend
- Create more complex visualizations
- Add interactive features
- Explore the full widget API in `widgetRegistry.ts`

Happy coding! 🚀
