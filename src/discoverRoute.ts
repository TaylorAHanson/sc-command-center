/**
 * Discover's search parameters and page address, as plain functions over strings.
 * Imports nothing, so `tests/discover_route.test.ts` can load it straight from
 * src/ under Node; `src/discover.ts` re-exports all of it.
 */

export type SearchMode = 'basic' | 'keyword' | 'hybrid';
export type SearchScope = 'all' | 'mine' | 'shared' | 'favorites' | 'everything';
export type SearchSort = 'relevance' | 'popular' | 'trending' | 'updated' | 'name' | 'favorites';
export type RailName = 'featured' | 'certified' | 'popular' | 'trending' | 'updated' | 'new_for_you';

export interface SearchParams {
    q?: string;
    scope?: SearchScope;
    sort?: SearchSort;
    domain?: string[];
    owner?: string[];
    certified?: boolean;
    standalone?: boolean;
    /** Narrows to views the caller manages. */
    status?: 'draft' | 'published';
    /** The view's last open by anyone, for finding stale views. */
    opened?: 'never' | '90d';
    cursor?: string | null;
    /** 1 to 50; the server defaults to 24. */
    limit?: number;
    facets?: boolean;
}

/** The query string for `GET /api/discover/search`. */
export const searchQuery = (p: SearchParams): string => {
    const qs = new URLSearchParams();
    if (p.q) qs.set('q', p.q);
    if (p.scope) qs.set('scope', p.scope);
    if (p.sort) qs.set('sort', p.sort);
    for (const d of p.domain ?? []) qs.append('domain', d);
    for (const o of p.owner ?? []) qs.append('owner', o);
    if (p.certified !== undefined) qs.set('certified', String(p.certified));
    if (p.standalone !== undefined) qs.set('standalone', String(p.standalone));
    if (p.status) qs.set('status', p.status);
    if (p.opened) qs.set('opened', p.opened);
    if (p.cursor) qs.set('cursor', p.cursor);
    if (p.limit) qs.set('limit', String(p.limit));
    if (p.facets) qs.set('facets', '1');
    return qs.toString();
};

/** What the Discover page's address can carry, so the sidebar and links can open it set up. */
export interface DiscoverRoute {
    q?: string;
    scope?: SearchScope;
    sort?: SearchSort;
    /** A rail shown on its own, e.g. "New for you (N)" from the sidebar. */
    rail?: RailName;
    certified?: boolean;
    opened?: 'never' | '90d';
}

const SCOPES: readonly string[] = ['all', 'mine', 'shared', 'favorites', 'everything'];
const SORTS: readonly string[] = ['relevance', 'popular', 'trending', 'updated', 'name', 'favorites'];
const RAILS: readonly string[] = ['featured', 'certified', 'popular', 'trending', 'updated', 'new_for_you'];

/** `#/discover`, with `?…` when there is anything to carry. */
export const discoverHref = (route: DiscoverRoute = {}): string => {
    const qs = new URLSearchParams();
    if (route.q) qs.set('q', route.q);
    if (route.scope) qs.set('scope', route.scope);
    if (route.sort) qs.set('sort', route.sort);
    if (route.rail) qs.set('rail', route.rail);
    if (route.certified !== undefined) qs.set('certified', String(route.certified));
    if (route.opened) qs.set('opened', route.opened);
    const s = qs.toString();
    return s ? `#/discover?${s}` : '#/discover';
};

/** The inverse of `discoverHref`; anything unrecognized is dropped rather than trusted. */
export const parseDiscoverHref = (hash: string): DiscoverRoute => {
    const at = hash.indexOf('?');
    const qs = new URLSearchParams(at >= 0 ? hash.slice(at + 1) : '');
    const route: DiscoverRoute = {};
    const q = qs.get('q');
    if (q) route.q = q.slice(0, 200);
    const scope = qs.get('scope');
    if (scope && SCOPES.includes(scope)) route.scope = scope as SearchScope;
    const sort = qs.get('sort');
    if (sort && SORTS.includes(sort)) route.sort = sort as SearchSort;
    const rail = qs.get('rail');
    if (rail && RAILS.includes(rail)) route.rail = rail as RailName;
    const certified = qs.get('certified');
    if (certified === 'true' || certified === 'false') route.certified = certified === 'true';
    const opened = qs.get('opened');
    if (opened === 'never' || opened === '90d') route.opened = opened;
    return route;
};

const VISIT_EVERY_MS = 60 * 60 * 1000;

/**
 * Whether an open of view `id` at `now` should be counted, given when each view
 * was last counted in this tab: at most once an hour per view. Records `now` when
 * it says yes.
 */
export const shouldCountVisit = (seen: Map<string, number>, id: string, now: number): boolean => {
    if (!id) return false;
    const last = seen.get(id);
    if (last !== undefined && now - last < VISIT_EVERY_MS) return false;
    seen.set(id, now);
    return true;
};
