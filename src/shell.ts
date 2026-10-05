import { createContext, useContext } from 'react';
import type { App } from './store/appSpec';

/**
 * Which page an app is drawn in. The workspace is Command Center itself:
 * sidebar, widget library and studios. An app whose presentation is standalone
 * is shown on its own to people who open its link, and is built in the
 * workspace by its editors.
 */
export interface Shell {
  /** Show an app on its own, the way people with its link see it. */
  present: (app: App, tabId?: string | null, widgetId?: string | null) => void;
  /** Open an app in the workspace, where its editors build it. */
  edit: (app: App, tabId?: string | null) => void;
}

export const ShellContext = createContext<Shell>({ present: () => {}, edit: () => {} });

export const useShell = () => useContext(ShellContext);
