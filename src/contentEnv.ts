/**
 * Legacy-compatible remains of the Dev / Test / Prod workspace switcher.
 *
 * There is one content store now (`content_env()` on the server); a draft is
 * what Dev and Test used to be. The server still accepts an `env` and ignores
 * it, so nothing here stamps requests any more. What is left:
 *
 * - `stripLegacyEnvParam`, because links copied before the change carry
 *   `?env=dev|test|prod` and would otherwise keep it in the address forever.
 * - Fixed-value shims for modules that still import the old names. They answer
 *   `'prod'` (the content store's default name) and never change; drop the
 *   import rather than building anything new on them.
 *
 * This is not `APP_ENVIRONMENT` (which Databricks App this is, the amber
 * badge); that still comes from `/api/health`.
 */

/** @deprecated There are no workspaces; kept so old imports compile. */
export type ContentEnv = 'dev' | 'test' | 'prod';

/** @deprecated */
export const CONTENT_ENVS: readonly ContentEnv[] = ['prod'];

/** @deprecated */
export const CONTENT_ENV_LABELS: Record<ContentEnv, string> = { dev: 'Dev', test: 'Test', prod: 'Prod' };

/** The query parameter old links used for the workspace. */
export const CONTENT_ENV_PARAM = 'env';

/** Removes a legacy `?env=` from the address, so a reload or a copied link drops it. */
export const stripLegacyEnvParam = () => {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has(CONTENT_ENV_PARAM)) return;
    url.searchParams.delete(CONTENT_ENV_PARAM);
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
  } catch {
    /* file: or test */
  }
};

/** @deprecated Always `'prod'`. */
export const getContentEnv = (): ContentEnv => 'prod';

/** @deprecated No-op. */
export const setContentEnv: (env: ContentEnv) => void = () => {};

/** @deprecated Nothing ever changes, so nothing is ever notified. */
export const subscribeContentEnv: (fn: () => void) => () => void = () => () => {};

/** @deprecated */
export interface WorkspaceAccess {
  resolved: boolean;
  canSwitch: boolean;
  refused: ContentEnv | null;
}

const SETTLED: WorkspaceAccess = { resolved: true, canSwitch: false, refused: null };

/** @deprecated Always settled, never switchable. */
export const getWorkspaceAccess = (): WorkspaceAccess => SETTLED;
