import React, { useEffect, useState } from 'react';
import { Check, Link2, Pencil } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import { appHash, linkTab, parseAppRoute } from '../store/appRoute';
import { darkBars, isPage, shownTab, themeVariables, type AppTheme } from '../store/appSpec';
import { AssistantDoorContext, useAssistantDoorFor } from '../appApi';
import { useCanvasLook } from '../hooks/useCanvasLook';
import { TabBar } from './TabBar';
import { FilterBar } from './FilterBar';
import { loadAppWidgets } from '../widgetRegistry';
import { useAgentChat } from '../hooks/useAgentChat';
import { getEnvironmentBadge } from '../api';
import { useShell } from '../shell';
import { DashboardGrid } from './DashboardGrid';
import { AgentDrawer } from './AgentDrawer';

const copyText = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand('copy');
    document.body.removeChild(textArea);
  }
};

// The browser tab is the page's, not this component's: whatever it said before
// the app opened is put back when the app closes.
const useTabIdentity = (title: string, favicon: string | null | undefined) => {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;
    return () => { document.title = previousTitle; };
  }, [title]);

  useEffect(() => {
    if (!favicon) return;
    const link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
    if (!link) return;
    const previous = { href: link.getAttribute('href'), type: link.getAttribute('type') };
    link.removeAttribute('type');
    link.setAttribute('href', favicon);
    return () => {
      if (previous.href !== null) link.setAttribute('href', previous.href);
      if (previous.type !== null) link.setAttribute('type', previous.type);
    };
  }, [favicon]);
};

// On the document root rather than this component, so the dialogs and menus
// that widgets portal into <body> take the app's colours too.
const useTheme = (theme: AppTheme | null | undefined) => {
  const primary = theme?.primary;
  const dark = theme?.dark;
  useEffect(() => {
    const root = document.documentElement.style;
    const vars = themeVariables({ primary, dark });
    const previous = Object.keys(vars).map(name => [name, root.getPropertyValue(name)] as const);
    for (const [name, value] of Object.entries(vars)) root.setProperty(name, value);
    return () => {
      for (const [name, value] of previous) {
        if (value) root.setProperty(name, value);
        else root.removeProperty(name);
      }
    };
  }, [primary, dark]);
};

/**
 * One app on its own: its title and logo, its canvas, and its assistant if it
 * offers one. None of the workspace — no sidebar, no widget library, no studios —
 * and nothing here changes the app; its editors build it in the workspace.
 */
export const AppShell: React.FC = () => {
  const { activeApp, activeAppTab, isAdmin, username, canEditApp, generateShareLink, openRoute } = useDashboardStore();
  const shell = useShell();
  const agentChat = useAgentChat();
  const [isAgentOpen, setAgentOpen] = useState(false);
  const assistantDoor = useAssistantDoorFor(agentChat.prefill, setAgentOpen, activeApp?.spec.assistant !== 'off');
  const [badge, setBadge] = useState('');
  const [copied, setCopied] = useState(false);

  const appId = activeApp?.id;
  useEffect(() => {
    if (appId) loadAppWidgets(appId);
  }, [appId]);

  // The address follows the tab on screen, as it does in the workspace, so Back
  // moves between tabs and the address bar is a link to the tab being read.
  useEffect(() => {
    if (!activeApp || !activeAppTab) return;
    const named = parseAppRoute(window.location.hash);
    const showing = named && !named.workspace && named.appId === activeApp.id
      && shownTab(activeApp, named.tabId)?.id === activeAppTab.id;
    if (!showing) window.location.hash = appHash(activeApp.id, linkTab(activeApp, activeAppTab));
  }, [activeApp, activeAppTab]);

  useEffect(() => {
    const onHashChange = () => {
      const route = parseAppRoute(window.location.hash);
      if (route) openRoute(route);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [openRoute]);

  useEffect(() => {
    let cancelled = false;
    getEnvironmentBadge().then(b => { if (!cancelled) setBadge(b); });
    return () => { cancelled = true; };
  }, []);

  const branding = activeApp?.spec.branding;
  const title = branding?.title || activeApp?.name || 'Command Center';
  useTabIdentity(badge ? `${title} - ${badge}` : title, branding?.favicon);
  const look = useCanvasLook(activeApp, activeAppTab);
  useTheme(look.theme);

  if (!activeApp) return null;

  // The same people who get Share in the workspace: an admin for a global app,
  // the owner for a personal one.
  const canShare = activeApp.is_global ? isAdmin : (!activeApp.is_shared && activeApp.username === username);
  const offersAssistant = activeApp.spec.assistant !== 'off';
  const dark = darkBars(activeApp);
  const headerButton = `flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors ${
    dark ? 'text-white/80 hover:text-white hover:bg-white/10' : 'text-gray-600 hover:text-brand-blue hover:bg-gray-100'
  }`;

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden" style={look.fontStack ? { fontFamily: look.fontStack } : undefined}>
      <div className="flex-1 flex flex-col min-w-0">
        <header className={`h-14 border-b flex items-center justify-between px-6 shadow-sm z-10 ${
          dark ? 'bg-brand-navy border-white/10' : 'bg-white border-gray-200'
        }`}>
          <div className="flex items-center gap-3 min-w-0">
            {branding?.logo && (
              <img src={branding.logo} alt="" className="h-8 w-auto max-w-[8rem] object-contain shrink-0" />
            )}
            <h1 className={`text-lg font-semibold truncate ${dark ? 'text-white' : 'text-brand-navy'}`}>{title}</h1>
            {badge && (
              <span
                className="px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide rounded bg-amber-100 text-amber-800 shrink-0"
                title={`This is the ${badge} deployment, not production`}
              >
                {badge}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {canShare && (
              <button
                onClick={async () => {
                  const link = generateShareLink();
                  if (!link) return;
                  await copyText(link);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
                className={headerButton}
                title="Copy a link to this page"
              >
                {copied ? <Check className="w-4 h-4" /> : <Link2 className="w-4 h-4" />}
                <span>{copied ? 'Copied!' : 'Copy link'}</span>
              </button>
            )}
            {canEditApp(activeApp) && (
              <button
                onClick={() => shell.edit(activeApp, linkTab(activeApp, activeAppTab))}
                className={headerButton}
                title="Open this view in Command Center to change it"
              >
                <Pencil className="w-4 h-4" />
                <span>Edit</span>
              </button>
            )}
          </div>
        </header>

        <div className="flex-1 flex flex-col min-h-0" style={look.areaStyle}>
          <TabBar placement="top" />
          <FilterBar />

          <div className="flex-1 flex min-h-0">
            <TabBar placement="side" />
            <main className={`flex-1 min-w-0 overflow-auto relative ${look.hasBackground ? '' : 'bg-gray-50/50'}`}>
              <div className={isPage(activeAppTab) ? 'w-full h-full' : 'w-full h-full px-2'}>
                <AssistantDoorContext.Provider value={assistantDoor}>
                  <DashboardGrid />
                </AssistantDoorContext.Provider>
              </div>
            </main>
          </div>
        </div>
      </div>

      {offersAssistant && (
        <AgentDrawer
          chat={agentChat}
          isOpen={isAgentOpen}
          onOpenChange={setAgentOpen}
          backdrop={look.theme.background}
          dark={dark}
        />
      )}
    </div>
  );
};
