import { useEffect } from 'react';
import { Layout } from './components/Layout';
import { DashboardGrid } from './components/DashboardGrid';
import { ThumbnailCaptureHost } from './components/ThumbnailCapture';
import { loadCustomWidgets } from './widgetRegistry';
import { getEnvironmentBadge } from './api';
import { brandReady } from './brand';

function App() {
  useEffect(() => {
    loadCustomWidgets();
    // Widget Studio and the admin preview compile synchronously, so the brand has
    // to be known before either opens rather than fetched when they do.
    brandReady();
  }, []);

  useEffect(() => {
    let cancelled = false;
    getEnvironmentBadge().then((badge) => {
      if (cancelled) return;
      document.title = badge ? `Command Center - ${badge}` : 'Command Center';
    });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <Layout>
        <DashboardGrid />
      </Layout>
      {/* Mounted as a SIBLING of Layout — not as one of its children — because
          Layout only renders its `children` when no full-page (admin/studio/
          settings/etc.) is active. Putting the host inside `children` made it
          unmount the moment the user navigated to the Admin page, which is
          exactly where backfill is invoked. Sitting outside Layout keeps it
          alive across all routes while remaining inside the DashboardProvider
          tree set up in main.tsx (so BaseWidget's hooks still work). */}
      <ThumbnailCaptureHost />
    </>
  );
}

export default App;
