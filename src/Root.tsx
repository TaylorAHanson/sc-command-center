import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import App from './App';
import { AppShell } from './components/AppShell';
import { DashboardProvider } from './store/dashboardStore';
import {
  appHash, isStandalone, parseAppRoute, refersTo, resolvedRoute, routeTab, withoutRouteParams, type AppRoute,
} from './store/appRoute';
import type { App as AppModel } from './store/appSpec';
import { ShellContext, type Shell } from './shell';

type Showing =
  | { kind: 'resolving' }
  | { kind: 'workspace' }
  | { kind: 'standalone'; app: AppModel; route: AppRoute; opened: number; preview?: boolean };

// Whatever isn't a standalone app this person can open goes to the workspace,
// including a link that can't be opened at all: the workspace does with it what
// it always has, subscribing if the app is someone else's and showing nothing
// new if it can't be read. Reading is all this does; subscribing is the
// workspace's or the app page's to do.
const resolve = async (route: AppRoute): Promise<AppModel | null> => {
  try {
    const res = await fetch(`/api/apps/${encodeURIComponent(route.appId)}`);
    if (!res.ok) return null;
    const { app } = await res.json();
    if (!isStandalone(app)) return null;
    return { ...app, locked: app.is_locked || app.is_shared };
  } catch (e) {
    console.error('Failed to read the app a link names', e);
    return null;
  }
};

const linkedRoute = (): AppRoute | null => {
  const route = parseAppRoute(window.location.hash, window.location.search);
  return route && !route.workspace ? route : null;
};

const goTo = (hash: string, replace = false) => {
  const url = window.location.pathname + withoutRouteParams(window.location.search) + hash;
  if (replace) window.history.replaceState(window.history.state, '', url);
  else window.history.pushState(window.history.state, '', url);
};

/**
 * Chooses the page an address is drawn in before anything is drawn, so an app
 * that opens on its own never flashes the workspace's sidebar first.
 */
export const Root = () => {
  const [showing, setShowing] = useState<Showing>(() => (linkedRoute() ? { kind: 'resolving' } : { kind: 'workspace' }));
  // Only the newest navigation lands: a slow read for a link someone has since
  // moved on from must not take the page back to it.
  const navigation = useRef(0);

  const standalone = useCallback((app: AppModel, route: AppRoute, preview = false) => {
    navigation.current += 1;
    setShowing({ kind: 'standalone', app, route, opened: navigation.current, preview });
  }, []);

  const follow = useCallback((route: AppRoute | null) => {
    const ticket = ++navigation.current;
    if (!route) {
      setShowing({ kind: 'workspace' });
      return;
    }
    setShowing({ kind: 'resolving' });
    resolve(route).then(app => {
      if (navigation.current !== ticket) return;
      if (!app) {
        setShowing({ kind: 'workspace' });
        return;
      }
      goTo(appHash(app, routeTab(app, route.tabId)), true);
      standalone(app, resolvedRoute(route, app));
    });
  }, [standalone]);

  useEffect(() => {
    if (showing.kind === 'resolving' && navigation.current === 0) follow(linkedRoute());
    // Only the address the page loaded with; later ones arrive as hash changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The workspace follows its own hash changes, and so does an app on its own
  // moving between its tabs. Otherwise any address but one to a standalone app —
  // Back to the workspace, a pasted page link — leaves for the workspace, which
  // then reads the address as it would on load.
  const shownApp = showing.kind === 'standalone' ? showing.app : null;
  useEffect(() => {
    if (showing.kind === 'workspace') return;
    const onHashChange = () => {
      const route = linkedRoute();
      if (route && shownApp && refersTo(route.appId, shownApp)) return;
      follow(route);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [showing.kind, shownApp, follow]);

  // `pushState` raises no hashchange, so moving between pages here never trips
  // the listener of the page being left. An address already naming the target
  // (the workspace handing over a link it was given) is not pushed again.
  const previewing = showing.kind === 'standalone' && !!showing.preview;
  const shell = useMemo<Shell>(() => ({
    present: (app, tabId = null, widgetId = null, preview = false) => {
      const named = parseAppRoute(window.location.hash);
      if (!(named && !named.workspace && refersTo(named.appId, app))) goTo(appHash(app, tabId));
      standalone(app, { appId: app.id, tabId, widgetId }, preview);
    },
    edit: (app, tabId = null) => {
      navigation.current += 1;
      goTo(appHash(app, tabId, null, true));
      setShowing({ kind: 'workspace' });
    },
    previewing,
  }), [standalone, previewing]);

  return (
    <ShellContext.Provider value={shell}>
      {showing.kind === 'resolving' && <Opening />}
      {showing.kind === 'workspace' && (
        <DashboardProvider key="workspace">
          <App />
        </DashboardProvider>
      )}
      {showing.kind === 'standalone' && (
        <DashboardProvider key={`app-${showing.opened}`} standalone={showing}>
          <AppShell />
        </DashboardProvider>
      )}
    </ShellContext.Provider>
  );
};

const Opening = () => (
  <div className="h-screen flex items-center justify-center bg-gray-50" role="status" aria-label="Opening">
    <div className="w-8 h-8 border-2 border-brand-blue border-t-transparent rounded-full animate-spin" />
  </div>
);
