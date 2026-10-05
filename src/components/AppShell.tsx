import React, { useEffect, useState } from 'react';
import { Check, Link2, Pencil } from 'lucide-react';
import { useDashboardStore } from '../store/dashboardStore';
import { appHash, linkTab, parseAppRoute } from '../store/appRoute';
import { shownTab } from '../store/appSpec';
import { TabBar } from './TabBar';
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

  if (!activeApp) return null;

  // The same people who get Share in the workspace: an admin for a global app,
  // the owner for a personal one.
  const canShare = activeApp.is_global ? isAdmin : (!activeApp.is_shared && activeApp.username === username);
  const offersAssistant = activeApp.spec.assistant !== 'off';

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 shadow-sm z-10">
          <div className="flex items-center gap-3 min-w-0">
            {branding?.logo && (
              <img src={branding.logo} alt="" className="h-8 w-auto max-w-[8rem] object-contain shrink-0" />
            )}
            <h1 className="text-lg font-semibold text-brand-navy truncate">{title}</h1>
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
                className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                title="Copy a link to this page"
              >
                {copied ? <Check className="w-4 h-4" /> : <Link2 className="w-4 h-4" />}
                <span>{copied ? 'Copied!' : 'Copy link'}</span>
              </button>
            )}
            {canEditApp(activeApp) && (
              <button
                onClick={() => shell.edit(activeApp, linkTab(activeApp, activeAppTab))}
                className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-brand-blue hover:bg-gray-100 rounded-md transition-colors"
                title="Open this view in Command Center to change it"
              >
                <Pencil className="w-4 h-4" />
                <span>Edit</span>
              </button>
            )}
          </div>
        </header>

        <TabBar />

        <main className="flex-1 overflow-auto bg-gray-50/50 relative">
          <div className="w-full h-full px-2">
            <DashboardGrid />
          </div>
        </main>
      </div>

      {offersAssistant && (
        <AgentDrawer
          chat={agentChat}
          isOpen={isAgentOpen}
          onOpenChange={setAgentOpen}
          name={branding?.assistant_name || undefined}
        />
      )}
    </div>
  );
};
