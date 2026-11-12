import { createContext, useContext, useEffect, useMemo, useRef } from 'react';
import { useDashboardStore } from './store/dashboardStore';
import { colourProblem, DEFAULT_THEME, effectiveTheme, isTabLink, tabLabel, webAddress, type TabLayout } from './store/appSpec';
import { fontById } from './fonts';
import { isAvailable, useCapabilities } from './capabilities';
import type { ScheduleOutcome, ScheduleRequest } from './schedules';

export type { ScheduleOutcome, ScheduleRequest } from './schedules';

export interface AssistantRequest {
  agentId?: string;
  prompt?: string;
}

/** A table to send: column names, then rows as arrays in that order or objects keyed by column. */
export interface EmailTable {
  columns?: string[];
  rows: unknown[];
}

export interface EmailRequest {
  subject?: string;
  /** Markdown. The server renders and escapes it; HTML arrives as text. */
  message?: string;
  /** Who it is for to start with. The person can change it before sending. */
  to?: string | string[];
  /** Drawn under the message, its first 50 rows. */
  table?: EmailTable;
  /** Attach the table as a CSV file too. */
  attachCsv?: boolean;
}

export interface EmailOutcome {
  /** True once it went out, or in a local run was written to the server log. */
  sent: boolean;
  status: 'sent' | 'logged' | 'cancelled' | 'unavailable';
  recipients: string[];
}

/**
 * What widget code may do with the app around it, handed to every widget as
 * `props.app`. It reads nothing beyond the app's own tab names and colours, moves
 * only between this app's tabs, and fills in the assistant without sending:
 * pressing Send stays the user's act, since that is what runs tools as them.
 * Email follows the same rule: `sendEmail` opens a Send dialog, never sends,
 * and `schedule` opens the Schedule dialog, never creates.
 */
export interface AppApi {
  tabs: { id: string; name: string; layout: TabLayout }[];
  activeTabId: string;
  goToTab: (idOrName: string) => void;
  /**
   * A `link` setting (`props.data[key]`) made followable: the tab's current name
   * or the address, and how to open it. Null until someone sets it, or once its
   * tab is deleted. An address opens in a new browser tab, never this one.
   */
  link: (value: unknown) => ResolvedLink | null;
  openAssistant: (request?: AssistantRequest) => void;
  /** The view's colors, and its font as a CSS font-family (null: Command Center's). */
  theme: { primary: string; dark: string; font: string | null };
  /**
   * Opens the platform's Send dialog with this email filled in: the person
   * edits the recipients, sees the email as it will arrive and presses Send,
   * which is logged like `executeAction`. Resolves when the dialog closes.
   */
  sendEmail: (request: EmailRequest) => Promise<EmailOutcome>;
  /** False until email is set up in this app; a widget disables its email button then. */
  emailAvailable: boolean;
  /**
   * Opens the platform's Schedule dialog with this schedule filled in: the
   * person chooses when it runs and who gets it, and saves, which is logged
   * like `executeAction`. Resolves when the dialog closes.
   */
  schedule: (request: ScheduleRequest) => Promise<ScheduleOutcome>;
  /** False until scheduling is set up in this app. A scheduled report is emailed, so it needs `emailAvailable` too. */
  scheduleAvailable: boolean;
}

export interface ResolvedLink {
  label: string;
  external: boolean;
  open: () => void;
}

/** Resolves a link setting against a list of tabs, so the preview can use it too. */
export const resolveLink = (
  value: unknown,
  tabs: AppApi['tabs'],
  goToTab: (id: string) => void,
): ResolvedLink | null => {
  if (isTabLink(value)) {
    const tab = tabs.find(t => t.id === value.tab);
    return tab ? { label: tab.name, external: false, open: () => goToTab(tab.id) } : null;
  }
  const href = value && typeof value === 'object' ? webAddress((value as { url?: unknown }).url) : null;
  if (!href) return null;
  return {
    label: new URL(href).host,
    external: true,
    open: () => { window.open(href, '_blank', 'noopener,noreferrer'); },
  };
};

/** How a shell opens its assistant. Absent where the app has none. */
export interface AssistantDoor {
  open: (request: AssistantRequest) => void;
}

export const AssistantDoorContext = createContext<AssistantDoor | null>(null);

/** A shell's door: open its drawer, then hand the request to its chat. */
export const useAssistantDoorFor = (
  prefill: (request: AssistantRequest) => unknown,
  setOpen: (open: boolean) => void,
  enabled: boolean,
): AssistantDoor | null => {
  const latest = useRef(prefill);
  useEffect(() => { latest.current = prefill; }, [prefill]);
  return useMemo(
    () => (enabled ? { open: (request: AssistantRequest) => { setOpen(true); void latest.current(request); } } : null),
    [enabled, setOpen],
  );
};

export const useAppApi = (): AppApi | undefined => {
  const { activeApp, activeAppTab, selectTab } = useDashboardStore();
  const door = useContext(AssistantDoorContext);

  const tabs = useMemo(
    () => (activeApp ? activeApp.spec.tabs.map((t, i) => ({ id: t.id, name: tabLabel(activeApp, t, i), layout: t.layout || 'canvas' as TabLayout })) : []),
    [activeApp],
  );
  // Keyed on what widgets can see, so a save that changes none of it hands them
  // the same object and their effects don't re-run.
  const tabsKey = JSON.stringify(tabs);
  const activeTabId = activeAppTab?.id || '';
  const theme = effectiveTheme(activeApp);
  const primary = theme.primary && !colourProblem(theme.primary) ? theme.primary : DEFAULT_THEME.primary;
  const dark = theme.dark && !colourProblem(theme.dark) ? theme.dark : DEFAULT_THEME.dark;
  const font = fontById(theme.font)?.stack || null;
  const capabilities = useCapabilities();
  const emailAvailable = isAvailable(capabilities, 'email');
  const scheduleAvailable = isAvailable(capabilities, 'scheduling');

  const hasApp = !!activeApp;

  return useMemo(() => {
    if (!hasApp) return undefined;
    const list: AppApi['tabs'] = JSON.parse(tabsKey);
    return {
      tabs: list,
      activeTabId,
      goToTab: (idOrName: string) => {
        if (typeof idOrName !== 'string') return;
        const wanted = idOrName.trim().toLowerCase();
        const tab = list.find(t => t.id === idOrName) || list.find(t => t.name.trim().toLowerCase() === wanted);
        if (tab && tab.id !== activeTabId) selectTab(tab.id);
      },
      link: (value: unknown) => resolveLink(value, list, id => { if (id !== activeTabId) selectTab(id); }),
      openAssistant: (request?: AssistantRequest) => {
        door?.open({ agentId: request?.agentId, prompt: request?.prompt });
      },
      theme: { primary, dark, font },
      // ExecuteActionPropInjector replaces these for each widget whose actions
      // are logged; anywhere else a Send or a Save would leave no audit row, so
      // no dialog opens.
      sendEmail: () => Promise.resolve<EmailOutcome>({ sent: false, status: 'unavailable', recipients: [] }),
      emailAvailable,
      schedule: () => Promise.resolve<ScheduleOutcome>({ scheduled: false, status: 'unavailable' }),
      scheduleAvailable,
    };
  }, [hasApp, tabsKey, activeTabId, primary, dark, font, door, selectTab, emailAvailable, scheduleAvailable]);
};
