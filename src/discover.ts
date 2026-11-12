/**
 * The browser side of `/api/discover` (server/routes/discover.py), shared by the
 * sidebar and the Discover page so neither holds the full catalog.
 *
 * Every list is light rows, never a spec. A row is opened through its `link`
 * (`#/app/<ref>`), which loads the full view on demand. The search parameters and
 * the page's own address live in `discoverRoute.ts`, re-exported here.
 */
import { requestJson, type Level, type PublishState } from './sharing';
import { searchQuery, shouldCountVisit, type RailName, type SearchMode, type SearchParams } from './discoverRoute';

export * from './discoverRoute';

const BASE = '/api/discover';

/** One view as every Discover list returns it. */
export interface ViewRow {
    id: string;
    /** `#/app/<ref>`. */
    link: string;
    ref: string;
    name: string;
    /** Cut to 240 characters. */
    description: string;
    owner: string | null;
    domain: string | null;
    /** `workspace` or `standalone`. */
    presentation: string;
    updated_at: string | null;
    published_at: string | null;
    viewers_30d: number;
    trend: number;
    favorites: number;
    featured: boolean;
    featured_position: number | null;
    certified: boolean;
    /** From the per-page access re-check. */
    access: Level;
    /** The caller's own star, hide and last open. */
    favorite: boolean;
    hidden: boolean;
    last_opened_at: string | null;
    /** Only on rows the caller manages. */
    state?: PublishState;
}

export interface FacetValue {
    value: string;
    label?: string;
    count: number;
}

export interface SearchResponse {
    results: ViewRow[];
    next_cursor: string | null;
    total: number;
    /** The mode that actually answered, which can be lower than the one configured. */
    mode: SearchMode;
    /** Relevance results stop at 500. */
    capped: boolean;
    facets?: { domain: FacetValue[]; owner: FacetValue[] };
}

export type Rails = Record<RailName, ViewRow[]>;

/** The sidebar's working set. `mine` includes never-published drafts (`state: 'draft_only'`). */
export interface Home {
    favorites: ViewRow[];
    recent: ViewRow[];
    mine: ViewRow[];
    mine_total: number;
    new_for_you_count: number;
}

export interface DiscoverStatus {
    ready: boolean;
    mode: SearchMode;
    indexed: number;
    total: number;
    building: boolean;
}

export interface Curation {
    app_id: string;
    featured_position: number | null;
    featured_by: string | null;
    featured_at: string | null;
    certified: boolean;
    certified_by: string | null;
    certified_at: string | null;
}

const item = (path: string, id: string) => `${BASE}/${path}/${encodeURIComponent(id)}`;

/** Each of these throws an Error carrying the server's reason. */
export const searchViews = (p: SearchParams, init?: RequestInit) =>
    requestJson<SearchResponse>(`${BASE}/search?${searchQuery(p)}`, init);

export const suggestViews = (q: string, init?: RequestInit) =>
    requestJson<{ results: ViewRow[]; mode: SearchMode }>(`${BASE}/suggest?q=${encodeURIComponent(q)}`, init);

export const fetchRails = () => requestJson<Rails>(`${BASE}/rails`);
export const fetchHome = () => requestJson<Home>(`${BASE}/home`);
export const fetchDiscoverStatus = () => requestJson<DiscoverStatus>(`${BASE}/status`);

export const fetchFavorites = async () => (await requestJson<{ favorites: ViewRow[] }>(`${BASE}/favorites`)).favorites;

export const setFavorite = (id: string, favorite: boolean) =>
    requestJson<{ id: string; favorite: boolean }>(item('favorites', id), { method: favorite ? 'PUT' : 'DELETE' });

/** `ids` go first in that order; favorites not named keep their order after them. */
export const orderFavorites = async (ids: string[]) =>
    (await requestJson<{ ids: string[] }>(`${BASE}/favorites/order`, { method: 'PUT', body: JSON.stringify({ ids }) })).ids;

/** Hidden views leave the rails; search still finds them. */
export const setHidden = (id: string, hidden: boolean) =>
    requestJson<{ id: string; hidden: boolean }>(item('hidden', id), { method: hidden ? 'PUT' : 'DELETE' });

/** Administrators only. Omit a field to leave it alone; `featured_position: null` unfeatures. */
export const curateView = (id: string, changes: { featured_position?: number | null; certified?: boolean }) =>
    requestJson<Curation>(item('curation', id), { method: 'PUT', body: JSON.stringify(changes) });

const counted = new Map<string, number>();

/**
 * Counts an open of view `id` toward Recent and popularity, at most once an hour
 * per view per tab. Never awaited and never throws: a lost count costs nothing.
 */
export const recordVisit = (id: string): void => {
    if (!shouldCountVisit(counted, id, Date.now())) return;
    fetch(item('visit', id), { method: 'POST' }).catch(() => undefined);
};
