import { useSyncExternalStore } from 'react';
import { getContentEnv, getWorkspaceAccess, setContentEnv, subscribeContentEnv, type ContentEnv, type WorkspaceAccess } from '../contentEnv';

export const useContentEnv = (): [ContentEnv, (env: ContentEnv) => void] => [
  useSyncExternalStore(subscribeContentEnv, getContentEnv),
  setContentEnv,
];

export const useWorkspaceAccess = (): WorkspaceAccess => useSyncExternalStore(subscribeContentEnv, getWorkspaceAccess);
