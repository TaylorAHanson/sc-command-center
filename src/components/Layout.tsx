import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useDashboardStore, type App, type AppVersion, type ArchivedApp } from '../store/dashboardStore';
import { Plus, Menu, LayoutGrid, Copy, Share2, Lock, Unlock, Shield, Code, BookOpen, Bot, ScrollText, Settings2, AppWindow, Compass, Archive, ChevronRight, RotateCcw, Trash2, X, Loader2, FileText, History, Undo2, CalendarClock, Search, Star } from 'lucide-react';
import clsx from 'clsx';
import { ConfirmModal } from './ConfirmModal';
import { DraftBar, PublishDialog, ShareDialog } from './sharing';
import { StatePill } from './sharing/DraftBar';
import { HeaderMenu } from './HeaderMenu';
import { SidebarViews } from './SidebarViews';
import { discoverHref } from '../discover';
import { hrefOf, type SidebarRow } from '../workingSet';
import { WidgetTray } from './WidgetTray';
import { AgentDrawer } from './AgentDrawer';
import { WelcomeOverlay, type WelcomeSpot } from './WelcomeOverlay';
import { AppSettingsModal } from './AppSettingsModal';
import { AddTabMenu, TabBar } from './TabBar';
import { FilterBar } from './FilterBar';
import { assistantLabel, useAgentChat } from '../hooks/useAgentChat';
import { ConfigModal } from './ConfigModal';
import { widgetRegistry } from '../widgetRegistry';
import { darkBars, isPage, layoutSwitch, showsHeader, shownTab, themeVariables } from '../store/appSpec';
import { WorkspaceToolsContext, type WorkspaceTools } from '../contexts/WorkspaceTools';
import { AssistantDoorContext, useAssistantDoorFor } from '../appApi';
import { useCanvasLook } from '../hooks/useCanvasLook';
import { appHash, appRef, isStandalone, linkTab, parseAppRoute, tabIdOf } from '../store/appRoute';
import { useShell } from '../shell';
import { isAvailable, useCapabilities } from '../capabilities';
import { OAuthOutcomeToast, ScheduleBanner } from './ScheduleNotices';

// The full-page screens load when they are opened. Together they are most of the
// app's code — the editor, the markdown renderer, the admin tables — and a session
// that only looks at a dashboard should not wait for any of it. They are fetched
// again once the browser goes idle, so opening one still feels immediate.
const pageImports = {
  admin: () => import('../pages/AdminPage'),
  settings: () => import('../pages/SettingsPage'),
  help: () => import('../pages/HelpPage'),
  about: () => import('../pages/AboutPage'),
  studio: () => import('../pages/WidgetStudio'),
  'agent-studio': () => import('../pages/AgentStudio'),
  'user-guide': () => import('../pages/UserGuidePage'),
  'release-notes': () => import('../pages/ReleaseNotesPage'),
  schedules: () => import('../pages/SchedulesPage'),
};

const AdminPage = React.lazy(() => pageImports.admin().then(m => ({ default: m.AdminPage })));
const SettingsPage = React.lazy(() => pageImports.settings().then(m => ({ default: m.SettingsPage })));
const HelpPage = React.lazy(() => pageImports.help().then(m => ({ default: m.HelpPage })));
const AboutPage = React.lazy(() => pageImports.about().then(m => ({ default: m.AboutPage })));
const WidgetStudio = React.lazy(() => pageImports.studio().then(m => ({ default: m.WidgetStudio })));
const AgentStudio = React.lazy(() => pageImports['agent-studio']().then(m => ({ default: m.AgentStudio })));
const UserGuidePage = React.lazy(() => pageImports['user-guide']().then(m => ({ default: m.UserGuidePage })));
const ReleaseNotesPage = React.lazy(() => pageImports['release-notes']().then(m => ({ default: m.ReleaseNotesPage })));
const SchedulesPage = React.lazy(() => pageImports.schedules().then(m => ({ default: m.SchedulesPage })));

const PageLoading: React.FC = () => (
  <div className="flex items-center justify-center h-full w-full text-gray-400">
    <div className="w-6 h-6 border-2 border-brand-blue border-t-transparent rounded-full animate-spin" />
  </div>
);

// Every full-page screen `currentPage` can name. Reload and Back/Forward both
// read this list, so a page missing from it is one the browser can't return to.
const PAGES = ['admin', 'studio', 'agent-studio', 'settings', 'help', 'about', 'user-guide', 'release-notes', 'schedules'];
// `#/user-guide/<section>` is still the guide: a page may carry a path of its own
// after its name, which that page reads itself (the guide's sections, for one).
const pageOf = (hash: string): string | null =>
  PAGES.find(p => hash === `#/${p}` || hash.startsWith(`#/${p}/`) || hash.startsWith(`#/${p}?`)) ?? null;

const when = (value?: string | null) => (value ? new Date(value).toLocaleString() : '');

/** A view's published versions, newest first; a manager can make any of them the draft again. */
const ViewHistoryDialog: React.FC<{
  app: App;
  load: (appId: string) => Promise<AppVersion[]>;
  revert: (appId: string, version: number) => Promise<void>;
  onClose: () => void;
}> = ({ app, load, revert, onClose }) => {
  const [versions, setVersions] = useState<AppVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    load(app.id)
      .then(v => { if (live) setVersions(v); })
      .catch(e => { if (live) setError(e?.message || String(e)); });
    return () => { live = false; };
  }, [app.id, load]);

  const choose = async (version: number) => {
    setBusy(version);
    setError(null);
    try {
      await revert(app.id, version);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label={`History of ${app.name}`}
        className="w-full max-w-lg rounded-xl bg-white shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <h2 className="text-base font-semibold text-gray-900">Published versions of ‘{app.name}’</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto px-5 py-3">
          {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
          {!versions && !error && <p className="text-sm text-gray-500">Loading…</p>}
          {versions && versions.length === 0 && <p className="text-sm text-gray-500">This view hasn’t been published yet.</p>}
          <ul className="divide-y divide-gray-100">
            {versions?.map((v, i) => (
              <li key={v.version} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800">
                    Version {v.version}{i === 0 && <span className="ml-2 text-xs font-normal text-emerald-700">Published now</span>}
                  </p>
                  <p className="truncate text-xs text-gray-500">
                    {[v.name, v.published_by, when(v.published_at || v.timestamp)].filter(Boolean).join(' · ')}
                  </p>
                </div>
                {app.access === 'MANAGE' && (
                  <button
                    onClick={() => choose(v.version)}
                    disabled={busy !== null}
                    className="flex shrink-0 items-center gap-1.5 rounded-md border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    title="Make this version the draft. Nothing changes for anyone else until you publish."
                  >
                    {busy === v.version ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                    Revert to this
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>,
    document.body,
  );
};

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentPage, setCurrentPage] = useState<string | null>(() => pageOf(window.location.hash));
  // Pages that take over the full screen (no header, no agent drawer).
  const isFullScreenStudio = currentPage === 'studio' || currentPage === 'agent-studio';
  const schedulingOn = isAvailable(useCapabilities(), 'scheduling');
  const {
    apps, sidebar, sidebarStatus, isFavorite, toggleFavorite, opening, openHome,
    activeAppId, activeApp, activeAppTab, openRoute, addApp, deleteApp, archiveApp, restoreApp, fetchArchived,
    duplicateApp, generateShareLink, toggleLock, configModal, closeConfigModal, isAdmin, username,
    canEditApp, canEditLayout, addTab, setTabLayout, isLoading, modeOf, setAppMode, loadPreflight, publishApp, discardDraft, fetchHistory, revertApp, sharingChanged,
  } = useDashboardStore();
  const shell = useShell();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const canAccessAdmin = isAdmin;
  const [sharingOpen, setSharingOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  // A view to delete or archive, waiting on the person's confirmation.
  const [removing, setRemoving] = useState<{ app: { id: string; name: string }; archive: boolean } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [archived, setArchived] = useState<ArchivedApp[] | null>(null);
  // The loaded view behind what's on screen: in Published mode `activeApp` is
  // the published copy, but where the draft stands is the loaded view's to say.
  const activeRow = apps.find(a => a.id === activeApp?.id) ?? activeApp;
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  // From the collapsed sidebar: the box exists once the click's render is done.
  const openSearch = () => {
    setSidebarOpen(true);
    window.setTimeout(() => searchRef.current?.focus(), 0);
  };
  // Persist the assistant drawer's open/closed state so it reopens if the user
  // left it open last session.
  const [isAgentOpen, setAgentOpen] = useState(() => {
    try { return localStorage.getItem('sccc-agent-open') === 'true'; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem('sccc-agent-open', String(isAgentOpen)); } catch { /* ignore */ }
  }, [isAgentOpen]);
  const [isTrayOpen, setTrayOpen] = useState(false);
  // The welcome panel opens by itself once, for someone with no views of their
  // own, and on request from Resources after that. Not for a link, though: whoever
  // sent it meant the view it names to be the first thing seen.
  const [welcomeSeen, setWelcomeSeen] = useState(() => {
    try { return localStorage.getItem('sccc-welcome-seen') === 'true'; } catch { return false; }
  });
  const [welcomeRequested, setWelcomeRequested] = useState(false);
  const [openedWithLink] = useState(() => parseAppRoute(window.location.hash, window.location.search) !== null);
  const [welcomeSpot, setWelcomeSpot] = useState<WelcomeSpot | null>(null);
  const [editWidgetId, setEditWidgetId] = useState<string | null>(null);
  const [cloneWidgetId, setCloneWidgetId] = useState<string | null>(null);
  const workspaceTools = React.useMemo<WorkspaceTools>(() => ({
    openLibrary: () => setTrayOpen(true),
    editWidget: (id: string) => {
      setEditWidgetId(id);
      setCloneWidgetId(null);
      setCurrentPage('studio');
    },
  }), []);

  // Held at the Layout level so the conversation survives collapsing the panel.
  const agentChat = useAgentChat();
  // A view set to "No agent" has no assistant while it is the page on screen.
  const viewHasNoAssistant = currentPage === null && activeApp?.spec.assistant === 'off';
  const assistantDoor = useAssistantDoorFor(agentChat.prefill, setAgentOpen, !viewHasNoAssistant);
  const look = useCanvasLook(activeApp, activeAppTab);
  const viewLook = { ...themeVariables(look.theme), ...(look.fontStack ? { fontFamily: look.fontStack } : {}) } as React.CSSProperties;
  // The header is drawn as the view's own when the view is what's on screen, so
  // editing it looks like Preview. Title, logo and "No header" are branding,
  // which only a view that opens on its own has; the header color is its Look.
  const viewOnScreen = currentPage === null && activeApp ? activeApp : null;
  const branded = viewOnScreen && isStandalone(viewOnScreen) ? viewOnScreen.spec.branding || {} : null;
  const viewHeader = !branded || showsHeader(viewOnScreen);
  const darkHeader = Boolean(viewOnScreen && viewHeader && darkBars(viewOnScreen));
  const headerButton = clsx(
    'flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors',
    darkHeader ? 'text-white/80 hover:text-white hover:bg-white/10' : 'text-gray-600 hover:text-brand-blue hover:bg-gray-100',
  );

  // Fetch the pages behind the sidebar buttons once the dashboard has settled.
  // Splitting them out of the bundle is what makes the first load quick; pulling
  // them in during idle time is what stops that showing up as a wait later. Only
  // the ones this person can actually open.
  useEffect(() => {
    const prefetch = () => {
      pageImports.studio();
      pageImports['agent-studio']();
      pageImports.settings();
      if (canAccessAdmin) pageImports.admin();
    };
    const idle = (window as any).requestIdleCallback;
    const handle = idle ? idle(prefetch, { timeout: 8000 }) : window.setTimeout(prefetch, 4000);
    return () => {
      if (idle && (window as any).cancelIdleCallback) (window as any).cancelIdleCallback(handle);
      else window.clearTimeout(handle);
    };
  }, [canAccessAdmin]);

  // Sync state changes to URL hash. A hash that already names what is on screen
  // is left as it is, so a link spelling out the first tab isn't rewritten into
  // a second history entry for the same place. A standalone app's own link would
  // show it on its own, so here, where it is being built, its address is the
  // workspace one: reloading keeps its editor in the workspace. While a view is
  // being read to be opened, the address already names it and the view on
  // screen is the one before, so the address is left alone.
  useEffect(() => {
    if (opening) return;
    let newHash = '';
    if (currentPage) {
      newHash = `#/${currentPage}`;
    } else if (activeApp && activeAppTab) {
      const named = parseAppRoute(window.location.hash);
      const standalone = isStandalone(activeApp);
      // By the name links use now, not merely one that reaches the app, so the
      // address catches up when the view or the tab is renamed.
      const showing = named?.appId === appRef(activeApp)
        && (named.workspace || !standalone)
        && shownTab(activeApp, tabIdOf(activeApp, named.tabId))?.id === activeAppTab.id;
      if (!showing) newHash = appHash(activeApp, linkTab(activeApp, activeAppTab), null, standalone);
    }

    // A page's own path ("#/user-guide/promotion") or query ("#/discover?q=…") is that page's to keep.
    const insidePage = !!currentPage
      && (window.location.hash.startsWith(`#/${currentPage}/`) || window.location.hash.startsWith(`#/${currentPage}?`));
    if (newHash && !insidePage && window.location.hash !== newHash) {
      window.location.hash = newHash;
    }
  }, [currentPage, activeApp, activeAppTab, opening]);

  // Auto-collapse the sidebar only in Agent Studio (it needs the full viewport),
  // and restore the user's previous sidebar state when they leave. Widget Studio
  // deliberately does NOT auto-collapse — users found that jarring.
  const autoCollapseSidebar = currentPage === 'agent-studio';
  const prevSidebarOpen = useRef<boolean | null>(null);
  useEffect(() => {
    if (autoCollapseSidebar) {
      if (prevSidebarOpen.current === null) {
        prevSidebarOpen.current = isSidebarOpen;
      }
      if (isSidebarOpen) setSidebarOpen(false);
    } else if (prevSidebarOpen.current !== null) {
      setSidebarOpen(prevSidebarOpen.current);
      prevSidebarOpen.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage]);

  // Handle browser back/forward buttons (hash changes)
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash;
      const page = pageOf(hash);
      const route = page ? null : parseAppRoute(hash);
      if (page) {
        setCurrentPage(page);
      } else if (route) {
        setCurrentPage(null);
        openRoute(route);
      } else if (hash === '' || hash === '#/') {
        setCurrentPage(null);
        openHome();
      }
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [openHome, openRoute]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Toggle widget tray on 'w' key press
      if (event.key.toLowerCase() === 'w' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        // Check if the user is typing in an input or textarea
        const activeElement = document.activeElement;
        const isTyping =
          activeElement instanceof HTMLInputElement ||
          activeElement instanceof HTMLTextAreaElement ||
          (activeElement as HTMLElement)?.isContentEditable;

        // Only open widget tray if there is no full screen page open, and not typing
        if (!isTyping && !currentPage) {
          setTrayOpen(true);
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [currentPage]);

  const loadArchived = React.useCallback(() => { fetchArchived().then(setArchived); }, [fetchArchived]);
  useEffect(() => { if (archivedOpen) loadArchived(); }, [archivedOpen, loadArchived]);

  // Closing one of your own views deletes it, as it always has, unless other
  // people can open it: then it is archived first, where a manager can restore it.
  const closeOwnView = (row: SidebarRow) => setRemoving({
    app: { id: row.id, name: row.name }, archive: (row.sharing ?? 'private') !== 'private',
  });
  const confirmRemoval = async () => {
    if (!removing) return;
    const { app, archive } = removing;
    setRemoving(null);
    const fromArchive = archived?.some(a => a.id === app.id);
    const refusal = archive ? await archiveApp(app.id) : await deleteApp(app.id);
    if (refusal) setNotice(refusal);
    else if (fromArchive || archivedOpen) loadArchived();
  };

  // With no view open there is nothing under the panel, so it stays as the page
  // until one is: someone new, or someone who has opened nothing yet and made nothing.
  const welcomeFirstRun = !welcomeSeen && !openedWithLink && sidebarStatus === 'ready' && sidebar.mineTotal === 0;
  const showWelcome = currentPage === null && !isLoading && (welcomeRequested || welcomeFirstRun || (!activeApp && !opening));
  // The assistant is the first thing the panel offers, so it is open beside it.
  // Once: closing the drawer while the panel is still up keeps it closed.
  const welcomeOpenedAgent = useRef(false);
  useEffect(() => {
    if (!showWelcome || !welcomeFirstRun || viewHasNoAssistant || welcomeOpenedAgent.current) return;
    welcomeOpenedAgent.current = true;
    setAgentOpen(true);
  }, [showWelcome, welcomeFirstRun, viewHasNoAssistant]);
  const dismissWelcome = () => {
    setWelcomeRequested(false);
    setWelcomeSpot(null);
    setWelcomeSeen(true);
    try { localStorage.setItem('sccc-welcome-seen', 'true'); } catch { /* ignore */ }
  };
  const spot = (target: WelcomeSpot) => welcomeSpot === target && 'ring-2 ring-brand-blue ring-offset-2 ring-offset-brand-navy rounded-md bg-brand-blue/15';
  // Other people's views opened lately, for the Welcome panel's Browse views card.
  const sharedRecent = [...sidebar.favorites, ...sidebar.recent]
    .filter(r => !!r.owner && r.owner.toLowerCase() !== username.toLowerCase());

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Sidebar */}
      <div className={clsx(
        "bg-brand-navy text-white transition-all duration-300 flex flex-col border-r border-gray-800",
        isSidebarOpen ? "w-64" : "w-16"
      )}>
        <div className={clsx("border-b border-gray-700 bg-opacity-50", isSidebarOpen ? "h-14 flex items-center px-4" : "px-1 py-2 flex flex-col items-center gap-2")}>
          {isSidebarOpen ? (
            <>
              <div className="flex items-center gap-2 font-bold text-lg truncate">
                <span>Command Center</span>
              </div>
              <button onClick={() => setSidebarOpen(!isSidebarOpen)} className="ml-auto text-gray-400 hover:text-white">
                <Menu className="w-5 h-5" />
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setSidebarOpen(!isSidebarOpen)} className="text-gray-400 hover:text-white" aria-label="Open the sidebar">
                <Menu className="w-5 h-5" />
              </button>
              <button onClick={openSearch} className="p-1 text-gray-400 hover:text-white" aria-label="Search views" title="Search views">
                <Search className="w-5 h-5" />
              </button>
            </>
          )}
        </div>

        <div className="flex-1 overflow-y-auto flex flex-col">
          {isSidebarOpen ? (
            <>
              <SidebarViews
                selectedId={currentPage === null ? activeAppId || null : null}
                onOpen={() => setWelcomeRequested(false)}
                onNewView={() => { setCurrentPage(null); setWelcomeRequested(false); addApp(`View ${sidebar.mineTotal + 1}`); }}
                onRemove={closeOwnView}
                onNotice={setNotice}
                searchRef={searchRef}
                browseSpot={spot('global-views')}
              />

              {/* Archived: views this person manages, out of everyone's sidebar until restored */}
              <div className="px-3 py-2 border-b border-gray-700">
                <button
                  onClick={() => setArchivedOpen(o => !o)}
                  className="w-full text-xs font-semibold text-gray-400 uppercase px-1 flex items-center gap-2 hover:text-white"
                  aria-expanded={archivedOpen}
                >
                  <ChevronRight className={clsx('w-3 h-3 transition-transform', archivedOpen && 'rotate-90')} />
                  <Archive className="w-3 h-3" />
                  Archived
                </button>
                {archivedOpen && (
                  <div className="mt-2 space-y-1">
                    {archived === null && <p className="text-xs text-gray-500 px-1">Loading…</p>}
                    {archived?.length === 0 && <p className="text-xs text-gray-500 px-1">Nothing archived.</p>}
                    {archived?.map(a => (
                      <div key={a.id} className="group flex items-center gap-1 px-3 py-1.5 rounded-md text-sm text-gray-400 hover:bg-gray-800">
                        <span className="truncate flex-1" title={a.archived_at ? `Archived ${when(a.archived_at)}` : undefined}>{a.name}</span>
                        <button
                          onClick={async () => {
                            const refusal = await restoreApp(a.id);
                            if (refusal) setNotice(refusal);
                            loadArchived();
                          }}
                          className="p-1 rounded hover:bg-brand-blue/20 hover:text-white"
                          title="Restore: back on the sidebar of everyone it is shared with"
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => setRemoving({ app: a, archive: false })}
                          className="p-1 rounded hover:bg-red-500/20 hover:text-red-400"
                          title="Delete permanently"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Widget Library Button */}
              <div className="p-3">
                <button
                  onClick={() => setTrayOpen(true)}
                  className={clsx("w-full px-3 py-2 border border-gray-600 hover:border-brand-blue hover:text-brand-blue rounded-md text-sm text-gray-400 transition-colors flex items-center justify-center gap-2 group", spot('library'))}
                >
                  <LayoutGrid className="w-4 h-4 group-hover:text-brand-blue" />
                  Widget Library (w)
                </button>
                <button
                  onClick={() => setCurrentPage('studio')}
                  className={clsx("w-full mt-2 px-3 py-2 border rounded-md text-sm transition-colors flex items-center justify-center gap-2 group", currentPage === 'studio' ? "bg-brand-blue border-transparent text-white" : "border-gray-600 hover:border-brand-blue hover:text-brand-blue text-gray-400", spot('studio'))}
                >
                  <Code className="w-4 h-4 group-hover:text-brand-blue" />
                  Widget Studio
                </button>
                <button
                  onClick={() => setCurrentPage('agent-studio')}
                  className={clsx("w-full mt-2 px-3 py-2 border rounded-md text-sm transition-colors flex items-center justify-center gap-2 group", currentPage === 'agent-studio' ? "bg-brand-blue border-transparent text-white" : "border-gray-600 hover:border-brand-blue hover:text-brand-blue text-gray-400", spot('agent-studio'))}
                >
                  <Bot className="w-4 h-4 group-hover:text-brand-blue" />
                  Agent Studio
                </button>
              </div>

              {/* Resources */}
              <div className="p-3 border-t border-gray-700 mt-auto">
                <div className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1">
                  Resources
                </div>
                <div className="space-y-1">
                  <button onClick={() => { setCurrentPage(null); setWelcomeRequested(true); }} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", showWelcome ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <Compass className="w-4 h-4" />
                    <span>Getting Started</span>
                  </button>
                  <button onClick={() => setCurrentPage('user-guide')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'user-guide' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <BookOpen className="w-4 h-4" />
                    <span>User Guide</span>
                  </button>
                  <button onClick={() => setCurrentPage('release-notes')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'release-notes' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                    <ScrollText className="w-4 h-4" />
                    <span>Release Notes</span>
                  </button>
                  {schedulingOn && (
                    <button onClick={() => setCurrentPage('schedules')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'schedules' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                      <CalendarClock className="w-4 h-4" />
                      <span>My schedules</span>
                    </button>
                  )}
                  {canAccessAdmin && (
                    <button onClick={() => setCurrentPage('admin')} className={clsx("flex items-center gap-2 px-3 py-2 text-sm w-full text-left rounded-md transition-colors", currentPage === 'admin' ? "bg-brand-blue text-white" : "text-gray-400 hover:text-white hover:bg-gray-800")}>
                      <Shield className="w-4 h-4" />
                      <span>Admin Panel</span>
                    </button>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        <ScheduleBanner hidden={isFullScreenStudio || currentPage === 'schedules'} />
        {/* Top Header */}
        {!isFullScreenStudio && (() => {
          const name = branded?.title || activeApp?.name;
          // These pages are not views, so the header must not keep showing the last view's name.
          const pageTitle = currentPage ? ({ admin: 'Admin Panel', 'user-guide': 'User Guide', 'release-notes': 'Release Notes', help: 'Getting Started', schedules: 'My schedules' } as Record<string, string>)[currentPage] : undefined;
          const title = pageTitle ? pageTitle : name || 'Command Center';
          const manages = !currentPage && activeRow?.access === 'MANAGE';
          const tab = !currentPage && activeApp && activeAppTab && canEditLayout(activeApp) ? activeAppTab : null;
          const swap = tab ? layoutSwitch(tab) : null;
          const canAddTab = Boolean(tab && activeApp && activeApp.spec.tabs.length === 1);
          const editable = !currentPage && activeApp && canEditApp(activeApp) ? activeApp : null;
          const menu = (openAddTab?: (from: { currentTarget: HTMLElement }) => void) => (
            <HeaderMenu
              dark={darkHeader}
              label="More view options"
              sections={[
                {
                  label: activeApp && activeApp.spec.tabs.length > 1 ? 'This tab' : 'Layout',
                  items: tab && swap && activeApp ? [
                    ...(['canvas', 'page'] as const).map(layout => {
                      const on = (isPage(tab) ? 'page' : 'canvas') === layout;
                      return {
                        key: layout,
                        label: layout === 'canvas' ? 'Cards on a grid' : 'Full page',
                        icon: layout === 'canvas' ? LayoutGrid : FileText,
                        checked: on,
                        disabled: !on && swap.blocked,
                        title: on ? undefined : swap.title,
                        onSelect: () => { if (!on) setTabLayout(activeApp.id, tab.id, layout); },
                      };
                    }),
                    ...(canAddTab && openAddTab ? [{
                      key: 'add-tab', label: 'Add a tab…', icon: Plus, title: 'Give this view a second tab',
                      onSelect: (trigger: HTMLElement) => openAddTab({ currentTarget: trigger }),
                    }] : []),
                  ] : [],
                },
                {
                  label: 'View',
                  items: [
                    ...(!currentPage && activeApp ? [{
                      key: 'copy', label: 'Make a copy', icon: Copy,
                      title: 'A copy of your own in My views, to change as you like',
                      onSelect: () => { duplicateApp(activeApp.id); },
                    }] : []),
                    ...(!currentPage && activeApp && isStandalone(activeApp) ? [{
                      key: 'preview', label: 'Preview as a viewer', icon: AppWindow,
                      title: 'See this view on its own, as people with its link do',
                      onSelect: () => shell.present(activeApp, linkTab(activeApp, activeAppTab), null, true),
                    }] : []),
                    ...(editable ? [
                      {
                        key: 'settings', label: 'View settings…', icon: Settings2,
                        title: 'How this view opens from its link, its title and logo, and its assistant',
                        onSelect: () => setSettingsOpen(true),
                      },
                      {
                        key: 'lock', label: editable.locked ? 'Unlock layout' : 'Lock layout', icon: editable.locked ? Unlock : Lock,
                        title: editable.locked ? 'Allow widgets to be moved, resized and removed again' : 'Stop widgets being moved, resized or removed by accident',
                        onSelect: () => toggleLock(editable.id),
                      },
                    ] : []),
                  ],
                },
                {
                  label: 'Versions',
                  items: manages && activeRow ? [
                    ...(activeRow.published_version ? [{
                      key: 'history', label: 'Version history…', icon: History, title: 'Published versions, and going back to one',
                      onSelect: () => setHistoryOpen(true),
                    }] : []),
                    ...(activeRow.state === 'published_with_draft' ? [{
                      key: 'discard', label: 'Discard draft…', icon: Undo2, danger: true,
                      title: 'Throw away your changes and go back to the published version',
                      onSelect: () => setDiscarding(true),
                    }] : []),
                  ] : [],
                },
              ]}
            />
          );
          const more = canAddTab && activeApp && activeAppTab ? (
            <AddTabMenu
              align="right"
              naming={{ suggested: 'Tab 2', first: activeAppTab.name ? undefined : 'Overview' }}
              onChoose={(layout, names) => addTab(activeApp.id, names?.name || 'Tab 2', layout, names?.first)}
              button={open => menu(open)}
            />
          ) : menu();
          const share = !currentPage && activeRow?.access ? (
            <button
              onClick={() => setSharingOpen(true)}
              className={headerButton}
              title={activeRow.access === 'MANAGE' ? 'Choose who can use or manage this view, and copy its link' : 'See who this view is shared with, and copy its link'}
            >
              <Share2 className="w-4 h-4" />
              <span>Share</span>
            </button>
          ) : null;
          const pill = manages && activeRow ? <StatePill state={activeRow.state} variant={darkHeader ? 'dark' : 'light'} /> : null;
          // Favorites are listed from the catalog, which only holds published views.
          const starrable = !currentPage && activeRow?.access && activeRow.state !== 'draft_only' ? activeRow : null;
          const starred = starrable ? isFavorite(starrable.id) : false;
          const star = starrable ? (
            <button
              type="button"
              onClick={async () => {
                const refusal = await toggleFavorite(starrable.id);
                if (refusal) setNotice(refusal);
              }}
              aria-pressed={starred}
              aria-label={starred ? 'Remove from favorites' : 'Add to favorites'}
              title={starred ? 'Remove from favorites' : 'Add to favorites: it stays at the top of your sidebar'}
              className={clsx(
                'rounded-md p-1.5 transition-colors shrink-0',
                darkHeader ? 'text-white/70 hover:text-white hover:bg-white/10' : 'text-gray-400 hover:text-amber-500 hover:bg-gray-100',
              )}
            >
              <Star className={clsx('w-4 h-4', starred && 'fill-current text-amber-400')} />
            </button>
          ) : null;
          // Publish is last and the only filled button: it is what a manager came
          // to the header for. Everything rarely needed sits in the "⋯" menu.
          const actions = manages && activeRow ? (
            <DraftBar
              state={activeRow.state}
              mode={modeOf(activeRow)}
              onModeChange={m => setAppMode(activeRow.id, m)}
              onPublish={() => setPublishOpen(true)}
              busy={draftBusy}
              variant={darkHeader ? 'dark' : 'light'}
              showState={!viewHeader}
            >
              {more}
              {share}
            </DraftBar>
          ) : (
            <>
              {more}
              {share}
            </>
          );
          return viewHeader ? (
            <header
              className={clsx(
                'h-14 border-b flex items-center justify-between px-6 shadow-sm z-10',
                darkHeader ? 'bg-brand-navy border-white/10' : 'bg-white border-gray-200',
              )}
              style={viewOnScreen ? viewLook : undefined}
            >
              <div className="flex items-center gap-3 min-w-0">
                {branded?.logo && (
                  <img src={branded.logo} alt="" className="h-8 w-auto max-w-[8rem] object-contain shrink-0" />
                )}
                <h1 className={clsx('text-lg font-semibold truncate', darkHeader ? 'text-white' : 'text-brand-navy')}>{title}</h1>
                {star}
                {pill}
              </div>
              <div className="flex items-center gap-2 shrink-0">{actions}</div>
            </header>
          ) : (
            // The view draws its own title bar, as it does on its own, so the
            // editing controls sit bottom left, clear of the assistant's button.
            <div
              role="toolbar"
              aria-label="View controls"
              className="absolute bottom-4 left-4 z-30 flex items-center gap-1 px-1 py-1 bg-white/95 backdrop-blur-sm border border-gray-200 rounded-lg shadow-md"
              style={viewLook}
            >
              {star}
              {actions}
            </div>
          );
        })()}

        {/* Dashboard Canvas or Page */}
        {currentPage ? (
          <main className="flex-1 overflow-hidden bg-gray-50">
            <React.Suspense fallback={<PageLoading />}>
            {currentPage === 'user-guide' && <UserGuidePage />}
            {currentPage === 'release-notes' && <ReleaseNotesPage />}
            {currentPage === 'schedules' && <SchedulesPage />}
            {currentPage === 'settings' && <SettingsPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'help' && <HelpPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'about' && <AboutPage onNavigate={(page) => setCurrentPage(page)} />}
            {currentPage === 'admin' && (
              <WorkspaceToolsContext.Provider value={workspaceTools}>
                <AdminPage onNavigate={(page) => setCurrentPage(page)} />
              </WorkspaceToolsContext.Provider>
            )}
            {currentPage === 'studio' && <WidgetStudio editWidgetId={editWidgetId} cloneWidgetId={cloneWidgetId} onClose={() => { setCurrentPage(null); setEditWidgetId(null); setCloneWidgetId(null); }} />}
            {currentPage === 'agent-studio' && <AgentStudio />}
            </React.Suspense>
          </main>
        ) : (
          // The view's theme covers its own tabs, filters and canvas, and the header
          // above them; the sidebar is Command Center's, so switching views doesn't
          // repaint it.
          <div className="flex-1 flex flex-col min-h-0 relative" style={{ ...viewLook, ...look.areaStyle }}>
            <TabBar placement="top" />
            <FilterBar />
            <div className="flex-1 flex min-h-0">
              <TabBar placement="side" />
              <main
                className={`flex-1 min-w-0 overflow-auto relative ${look.hasBackground ? '' : 'bg-gray-50/50'}`}
                onDragOver={(e) => {
                  // Allow drops on main content area
                  if (e.dataTransfer.types.includes('application/widget-type')) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.dataTransfer.dropEffect = 'copy';
                  }
                }}
                onDrop={(e) => {
                  // Prevent main from intercepting - let it bubble to children
                  if (e.dataTransfer.types.includes('application/widget-type')) {
                    e.stopPropagation();
                  }
                }}
              >
                <div className={isPage(activeAppTab) ? 'w-full h-full' : 'w-full h-full px-2'}>
                  <WorkspaceToolsContext.Provider value={workspaceTools}>
                    <AssistantDoorContext.Provider value={assistantDoor}>
                      {children}
                    </AssistantDoorContext.Provider>
                  </WorkspaceToolsContext.Provider>
                </div>
              </main>
            </div>
            {showWelcome && (
              <WelcomeOverlay
                agentName={assistantDoor ? assistantLabel(agentChat) : null}
                onAsk={prompt => { dismissWelcome(); assistantDoor?.open({ prompt }); }}
                sharedViews={sharedRecent}
                onOpenView={id => {
                  dismissWelcome();
                  const row = sharedRecent.find(r => r.id === id);
                  if (row) window.location.hash = hrefOf(row);
                }}
                onBrowse={() => { dismissWelcome(); window.location.hash = discoverHref(); }}
                onOpenLibrary={() => { dismissWelcome(); setTrayOpen(true); }}
                onOpenStudio={page => { dismissWelcome(); setEditWidgetId(null); setCloneWidgetId(null); setCurrentPage(page); }}
                onBlankView={() => { dismissWelcome(); addApp(`View ${sidebar.mineTotal + 1}`); }}
                onSpot={setWelcomeSpot}
                onDismiss={activeApp ? dismissWelcome : undefined}
              />
            )}
          </div>
        )}
      </div>

      {/* Agent Assistant (hidden in Studios, which need the full viewport) */}
      {/* It answers about the view on screen, so it wears that view's look, as it
          does when the view is opened on its own; elsewhere, Command Center's. */}
      {!isFullScreenStudio && !viewHasNoAssistant && (
        <div className="contents" style={currentPage === null ? viewLook : undefined}>
          <AgentDrawer
            chat={agentChat}
            isOpen={isAgentOpen}
            onOpenChange={setAgentOpen}
            backdrop={currentPage === null ? look.theme.background : undefined}
            dark={Boolean(viewOnScreen && darkBars(viewOnScreen))}
            spotlight={showWelcome && welcomeSpot === 'assistant'}
          />
        </div>
      )}

      <OAuthOutcomeToast />

      {/* Widget Tray */}
      <WidgetTray
        isOpen={isTrayOpen}
        onClose={() => setTrayOpen(false)}
        onEditWidget={(id) => {
          setEditWidgetId(id);
          setCloneWidgetId(null);
          setCurrentPage('studio');
        }}
        onCloneWidget={(id) => {
          setCloneWidgetId(id);
          setEditWidgetId(null);
          setCurrentPage('studio');
        }}
      />

      {/* Config Modal */}
      <ConfigModal
        isOpen={configModal.isOpen}
        onClose={closeConfigModal}
        onSave={(config) => {
          if (configModal.onSave) {
            configModal.onSave(config);
          }
          closeConfigModal();
        }}
        widget={configModal.widgetId ? widgetRegistry[configModal.widgetId] : null}
        initialConfig={configModal.initialConfig}
        editing={configModal.editing}
      />

      {settingsOpen && activeApp && (
        <AppSettingsModal
          app={activeApp}
          agents={agentChat.availableProfiles}
          loadAgents={agentChat.loadProfilesOnce}
          selectAgent={id => { if (!agentChat.isLoading) agentChat.setSelectedProfileId(id); }}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {sharingOpen && activeRow?.access && (
        <ShareDialog
          objectType="app"
          objectId={activeRow.id}
          name={activeRow.name}
          published={Boolean(activeRow.published_version)}
          link={generateShareLink()}
          onClose={() => setSharingOpen(false)}
          onChanged={acl => sharingChanged(activeRow.id, acl)}
        />
      )}

      {publishOpen && activeRow && (
        <PublishDialog
          title={activeRow.name}
          loadPreflight={() => loadPreflight(activeRow.id)}
          onConfirm={include => publishApp(activeRow.id, include)}
          onClose={() => setPublishOpen(false)}
        />
      )}

      {historyOpen && activeRow && (
        <ViewHistoryDialog
          app={activeRow}
          load={fetchHistory}
          revert={revertApp}
          onClose={() => setHistoryOpen(false)}
        />
      )}

      {discarding && activeRow && createPortal(
        <ConfirmModal
          title="Discard draft?"
          message="Your unpublished changes will be deleted. The published version stays as it is."
          confirmLabel="Discard draft"
          variant="danger"
          onCancel={() => setDiscarding(false)}
          onConfirm={async () => {
            setDiscarding(false);
            setDraftBusy(true);
            const refusal = await discardDraft(activeRow.id);
            setDraftBusy(false);
            if (refusal) setNotice(refusal);
          }}
        />,
        document.body,
      )}

      {removing && createPortal(
        <ConfirmModal
          title={removing.archive ? `Archive ‘${removing.app.name}’?` : `Delete ‘${removing.app.name}’?`}
          message={removing.archive
            ? 'It leaves the sidebar of everyone it is shared with, and its link stops opening it. You can restore it from Archived.'
            : 'The view and all its published versions are deleted for good.'}
          confirmLabel={removing.archive ? 'Archive' : 'Delete'}
          variant={removing.archive ? 'warning' : 'danger'}
          onCancel={() => setRemoving(null)}
          onConfirm={confirmRemoval}
        />,
        document.body,
      )}

      {notice && createPortal(
        <ConfirmModal
          title="That didn’t work"
          message={notice}
          confirmLabel="OK"
          variant="primary"
          onCancel={() => setNotice(null)}
          onConfirm={() => setNotice(null)}
        />,
        document.body,
      )}
    </div >
  );
};
