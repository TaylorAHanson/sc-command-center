import { createContext, useContext } from 'react';

/**
 * What Command Center's own chrome offers the canvas: its widget library and
 * Widget Studio. A view opened on its own has neither, so it provides nothing.
 */
export interface WorkspaceTools {
  openLibrary: () => void;
  editWidget: (widgetId: string) => void;
}

export const WorkspaceToolsContext = createContext<WorkspaceTools | null>(null);

export const useWorkspaceTools = () => useContext(WorkspaceToolsContext);
