import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { resolveLink, type AppApi } from '../appApi';
import { DEFAULT_THEME } from '../store/appSpec';
import { isAvailable, useCapabilities } from '../capabilities';
import { normalizeEmailRequest, recipientsText, tablesOf } from '../email';
import { describeRecurrence, normalizeScheduleRequest } from '../schedules';

export type PageWidth = 'laptop' | 'wide' | 'narrow';

export const PAGE_WIDTHS: { id: PageWidth; label: string; px: number }[] = [
  { id: 'laptop', label: 'Laptop', px: 1280 },
  { id: 'wide', label: 'Wide', px: 1680 },
  { id: 'narrow', label: 'Narrow', px: 820 },
];

/** The tab area of a laptop screen once the header and tab bar are drawn. */
export const PAGE_HEIGHT = 720;

const STAND_IN_TABS: AppApi['tabs'] = [
  { id: 'home', name: 'Home', layout: 'page' },
  { id: 'overview', name: 'Overview', layout: 'canvas' },
  { id: 'details', name: 'Details', layout: 'canvas' },
];

/** What the preview hands a `link` setting: the stand-in tabs after Home, in turn. */
export const standInLink = (index: number) => ({ tab: STAND_IN_TABS[1 + (index % (STAND_IN_TABS.length - 1))].id });

/**
 * A `props.app` for the studio's preview. It has no view to move around, so each
 * call says what it would do instead of doing it.
 */
export const usePreviewApp = () => {
  const [note, setNote] = useState<string | null>(null);
  const [activeTabId, setActiveTabId] = useState('home');
  const timer = useRef<number | undefined>(undefined);
  const say = useCallback((text: string) => {
    setNote(text);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(null), 5000);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const capabilities = useCapabilities();
  const emailAvailable = isAvailable(capabilities, 'email');
  const scheduleAvailable = isAvailable(capabilities, 'scheduling');

  const app = useMemo<AppApi>(() => ({
    tabs: STAND_IN_TABS,
    activeTabId,
    goToTab: (idOrName: string) => {
      const tab = STAND_IN_TABS.find(t => t.id === idOrName)
        || STAND_IN_TABS.find(t => t.name.toLowerCase() === String(idOrName).trim().toLowerCase());
      if (tab) setActiveTabId(tab.id);
      say(tab
        ? `In a view this opens the “${tab.name}” tab.`
        : `In a view this opens the “${idOrName}” tab, if the view has one. The preview’s stand-in tabs are ${STAND_IN_TABS.map(t => t.name).join(', ')}.`);
    },
    link: (value: unknown) => {
      const link = resolveLink(value, STAND_IN_TABS, id => setActiveTabId(id));
      if (!link) return null;
      return {
        ...link,
        open: () => {
          if (!link.external) link.open();
          say(link.external
            ? `In a view this opens ${link.label} in a new browser tab.`
            : `In a view this opens the “${link.label}” tab.`);
        },
      };
    },
    openAssistant: (request = {}) => {
      const agent = typeof request.agentId === 'string' && request.agentId ? ` with agent “${request.agentId}”` : '';
      const prompt = typeof request.prompt === 'string' && request.prompt ? `, its message box filled with “${request.prompt.slice(0, 160)}”` : '';
      say(`In a view this opens the assistant${agent}${prompt}. The user presses Send.`);
    },
    theme: { primary: DEFAULT_THEME.primary, dark: DEFAULT_THEME.dark, font: null },
    sendEmail: (request) => {
      const asked = normalizeEmailRequest(request);
      const who = recipientsText(asked.to);
      const tables = tablesOf(asked);
      const parts = [
        asked.html ? 'its HTML' : '',
        tables.length === 1 ? `a ${tables[0].rows.length.toLocaleString()}-row table${asked.attachCsv ? ' and its CSV' : ''}`
          : tables.length > 1 ? `${tables.length} tables${asked.attachCsv ? ' and their CSVs' : ''}` : '',
        asked.attachments?.length ? `${asked.attachments.length} attached file${asked.attachments.length === 1 ? '' : 's'}` : '',
      ].filter(Boolean);
      const what = parts.length ? ` with ${parts.join(', ')}` : '';
      say(`In a view this opens the Send dialog for “${(asked.subject || 'an email').slice(0, 120)}”${who ? ` to ${who.slice(0, 160)}` : ''}${what}. The user checks the recipients and the preview, then presses Send.`);
      return Promise.resolve({ sent: false, status: 'cancelled' as const, recipients: [] });
    },
    emailAvailable,
    schedule: (request) => {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const asked = normalizeScheduleRequest(request, { tz, executable: true });
      const what = asked.kind === 'run_statement' ? 'run its statement' : `email “${(asked.subject || asked.name || 'its results').slice(0, 120)}”`;
      const who = asked.kind === 'email_report' && asked.recipients?.length ? ` to ${asked.recipients.join(', ').slice(0, 160)}` : '';
      const noQuery = asked.sql ? '' : ' The widget passed no `sql`, so the dialog would have nothing to schedule.';
      const when = describeRecurrence(asked.recurrence);
      say(`In a view this opens the Schedule dialog to ${what}${who}, ${when.charAt(0).toLowerCase()}${when.slice(1)}. The user adjusts it and presses Save.${noQuery}`);
      return Promise.resolve({ scheduled: false, status: 'cancelled' });
    },
    scheduleAvailable,
  }), [activeTabId, say, emailAvailable, scheduleAvailable]);

  return { app, note, showHome: () => setActiveTabId('home') };
};
