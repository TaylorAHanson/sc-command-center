import type { AppFilter } from './appSpec';

// Per browser, per person, per view: a shared computer keeps each person's own.
const storageKey = (user: string, appId: string) => `sccc-filter-choices:${user}:${appId}`;

const usable = (filter: AppFilter, value: unknown): value is string =>
  typeof value === 'string' && (value === '' || filter.options.includes(value));

const read = (user: string, appId: string): Record<string, unknown> => {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(user, appId)) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

/**
 * The filter choices this person last left the view on. A choice the filter no
 * longer offers is dropped, so editing a filter's options can't strand anyone
 * on a value they can't pick.
 */
export const rememberedFilters = (user: string | null, appId: string, filters?: AppFilter[] | null): Record<string, string> => {
  if (!user || !appId || !filters?.length) return {};
  const saved = read(user, appId);
  const out: Record<string, string> = {};
  for (const f of filters) if (usable(f, saved[f.key])) out[f.key] = saved[f.key] as string;
  return out;
};

/** Keeps the filter keys among `values`; other dashboard variables are never stored. */
export const rememberFilters = (user: string | null, appId: string, filters: AppFilter[] | null | undefined, values: Record<string, unknown>) => {
  if (!user || !appId || !filters?.length) return;
  const picked: Record<string, string> = {};
  for (const f of filters) {
    const value = values[f.key] == null ? undefined : String(values[f.key]);
    if (f.key in values && usable(f, value)) picked[f.key] = value;
  }
  if (!Object.keys(picked).length) return;
  try {
    localStorage.setItem(storageKey(user, appId), JSON.stringify({ ...read(user, appId), ...picked }));
  } catch { /* private browsing */ }
};
