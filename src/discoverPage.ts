/**
 * The Discover page's decisions, as plain functions: what its address means as a
 * search, what each rail's "See all" opens, what a filter change keeps, and how
 * further pages and changes made elsewhere fold into what is on screen.
 * Only types are imported, so `tests/discover_page.test.ts` loads this straight
 * from src/ under Node, as `discoverRoute.ts` is.
 */
import type { DiscoverChange, FacetValue, Rails, ViewRow } from './discover';
import type { DiscoverRoute, RailName, SearchMode, SearchParams, SearchScope, SearchSort } from './discoverRoute';

/** A page of results; divides evenly into grids of 2, 3 and 4 columns. */
export const PAGE_SIZE = 24;

export const RAIL_ORDER: readonly RailName[] = ['featured', 'certified', 'popular', 'trending', 'updated', 'new_for_you'];

/** Rails whose "See all" is the rail on its own, because no search narrows to exactly them. */
export const RAILS_ALONE: readonly RailName[] = ['featured', 'new_for_you'];

/** The most views the server returns in one rail (`RAIL_LIMIT` in view_catalog.py), so also the most a rail on its own can show. */
export const RAIL_LIMIT = 12;

export const RAIL_LABELS: Record<RailName, { title: string; blurb: string }> = {
    featured: { title: 'Featured', blurb: 'Picked by your administrators.' },
    certified: { title: 'Certified', blurb: 'Checked and vouched for by your administrators.' },
    popular: { title: 'Popular this month', blurb: 'Opened by the most people in the last 30 days.' },
    trending: { title: 'Trending', blurb: 'Gaining viewers this week.' },
    updated: { title: 'Recently updated', blurb: 'Published most recently.' },
    new_for_you: { title: 'New for you', blurb: 'Shared with you or your groups in the last 14 days, and not opened yet.' },
};

export const SCOPE_LABELS: Record<SearchScope, string> = {
    all: 'All I can open',
    mine: 'Mine',
    shared: 'Shared with me',
    favorites: 'Favorites',
    everything: 'Everything in this deployment',
};

export const SORT_LABELS: Record<SearchSort, string> = {
    relevance: 'Relevance',
    popular: 'Popular',
    trending: 'Trending',
    updated: 'Recently updated',
    name: 'Name',
    favorites: 'Most favorited',
};

/** Searching every view skips the access filter, which only administrators may. */
export const scopesFor = (isAdmin: boolean): SearchScope[] =>
    isAdmin ? ['all', 'mine', 'shared', 'favorites', 'everything'] : ['all', 'mine', 'shared', 'favorites'];

/** Relevance needs words to be relevant to; without them the server sorts by popularity. */
export const sortsFor = (hasQuery: boolean): SearchSort[] =>
    hasQuery ? ['relevance', 'popular', 'trending', 'updated', 'name', 'favorites'] : ['popular', 'trending', 'updated', 'name', 'favorites'];

/** What a rail's "See all" opens. */
export const seeAllRoute = (rail: RailName): DiscoverRoute => {
    switch (rail) {
        case 'certified': return { certified: true };
        case 'popular': return { sort: 'popular' };
        case 'trending': return { sort: 'trending' };
        case 'updated': return { sort: 'updated' };
        default: return { rail };
    }
};

/** An address naming a rail that a search stands in for opens that search; a rail shown alone shows only itself. */
export const normalizeRoute = (route: DiscoverRoute): DiscoverRoute => {
    if (!route.rail) return route;
    if (RAILS_ALONE.includes(route.rail)) return { rail: route.rail };
    const rest: DiscoverRoute = { ...route };
    delete rest.rail;
    return { ...rest, ...seeAllRoute(route.rail) };
};

const FILTERS = ['domain', 'owner', 'certified', 'standalone', 'status', 'opened'] as const;

export const hasFilters = (route: DiscoverRoute): boolean =>
    FILTERS.some(key => {
        const value = route[key];
        return Array.isArray(value) ? value.length > 0 : value !== undefined;
    });

export type PageMode = 'home' | 'rail' | 'results';

/** Rails when there's nothing to search for; a rail on its own; otherwise results. */
export const pageMode = (route: DiscoverRoute): PageMode => {
    if (route.rail && RAILS_ALONE.includes(route.rail)) return 'rail';
    if (route.q?.trim() || route.sort || (route.scope && route.scope !== 'all') || hasFilters(route)) return 'results';
    return 'home';
};

export const effectiveSort = (route: DiscoverRoute): SearchSort => {
    if (route.q?.trim()) return route.sort ?? 'relevance';
    return route.sort && route.sort !== 'relevance' ? route.sort : 'popular';
};

/** A link carrying `everything` opens as an ordinary search for someone who isn't an administrator. */
export const effectiveScope = (route: DiscoverRoute, isAdmin: boolean): SearchScope =>
    route.scope === 'everything' && !isAdmin ? 'all' : route.scope ?? 'all';

/** The first page's request for what the address shows. */
export const searchParamsOf = (route: DiscoverRoute, isAdmin: boolean): SearchParams => {
    const p: SearchParams = { scope: effectiveScope(route, isAdmin), sort: effectiveSort(route), limit: PAGE_SIZE };
    const q = route.q?.trim();
    if (q) p.q = q;
    if (route.domain?.length) p.domain = [...route.domain];
    if (route.owner?.length) p.owner = [...route.owner];
    if (route.certified !== undefined) p.certified = route.certified;
    if (route.standalone !== undefined) p.standalone = route.standalone;
    if (route.status) p.status = route.status;
    if (route.opened) p.opened = route.opened;
    return p;
};

/**
 * The route with `patch` applied. Unset and empty values are dropped, `all` is
 * the default scope, relevance is the default sort (with words; without them it
 * means nothing), and a rail shown alone is left behind unless the patch names one.
 */
export const withChanges = (route: DiscoverRoute, patch: Partial<DiscoverRoute>): DiscoverRoute => {
    const merged: DiscoverRoute = { ...route, ...patch };
    if (!('rail' in patch)) delete merged.rail;
    const out: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(merged)) {
        const value = key === 'q' && typeof raw === 'string' ? raw.trim() : raw;
        if (value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) continue;
        out[key] = value;
    }
    const next = out as DiscoverRoute;
    if (next.scope === 'all') delete next.scope;
    if (next.sort === 'relevance') delete next.sort;
    return next;
};

/** A search typed and run keeps the scope, sort and filters around it. */
export const withQuery = (route: DiscoverRoute, text: string): DiscoverRoute => withChanges(route, { q: text });

export const clearFilters = (route: DiscoverRoute): DiscoverRoute =>
    withChanges(route, { domain: undefined, owner: undefined, certified: undefined, standalone: undefined, status: undefined, opened: undefined });

export const toggled = (list: string[] | undefined, value: string): string[] =>
    list?.includes(value) ? list.filter(v => v !== value) : [...(list ?? []), value];

/** The administrators' way to find views to archive: every view, none opened by anyone in 90 days. */
export const GOVERNANCE_ROUTE: DiscoverRoute = { scope: 'everything', opened: '90d', sort: 'name' };

export const isGovernance = (route: DiscoverRoute): boolean => route.scope === 'everything' && route.opened === '90d';

export const resultsTitle = (route: DiscoverRoute): string => {
    const q = route.q?.trim();
    if (q) return `Results for “${q}”`;
    if (isGovernance(route)) return 'Not opened in 90 days';
    switch (route.scope) {
        case 'mine': return 'Your views';
        case 'shared': return 'Shared with you';
        case 'favorites': return 'Your favorites';
        case 'everything': return 'Every view in this deployment';
    }
    if (route.certified) return 'Certified views';
    switch (effectiveSort(route)) {
        case 'popular': return 'Popular this month';
        case 'trending': return 'Trending';
        case 'updated': return 'Recently updated';
        case 'name': return 'All views, A to Z';
        case 'favorites': return 'Most favorited';
        default: return 'Views';
    }
};

/** What to say when a list comes back empty. */
export const emptyMessage = (route: DiscoverRoute): { title: string; hint: string } => {
    const q = route.q?.trim();
    if (q) {
        return {
            title: `No views match “${q}”`,
            hint: hasFilters(route) || (route.scope && route.scope !== 'all')
                ? 'Try fewer words, or clear the filters and search everything you can open.'
                : 'Try fewer or different words. Search reads names, descriptions, tab names, owners, domains and widget names.',
        };
    }
    if (isGovernance(route)) return { title: 'Every view has been opened in the last 90 days', hint: 'Nothing here needs archiving.' };
    if (hasFilters(route)) return { title: 'No views match these filters', hint: 'Clear a filter or two to see more.' };
    switch (route.scope) {
        case 'favorites': return { title: 'No favorites yet', hint: 'Press the star on a view to keep it here and at the top of your sidebar.' };
        case 'mine': return { title: 'You haven’t published a view yet', hint: 'Views you build appear here once published. Until then, open them from My views in the sidebar.' };
        case 'shared': return { title: 'Nothing shared with you yet', hint: 'Views other people share with you appear here once they publish them.' };
    }
    return { title: 'No views to show yet', hint: 'Views appear here once someone publishes one and shares it with you, or you can build your own.' };
};

export interface FacetOption {
    value: string;
    label: string;
    /** Null for a value that is ticked but not among the top counts. */
    count: number | null;
    selected: boolean;
}

/**
 * A facet's choices: the server's counts, without the blank value (views with no
 * domain or owner can't be filtered on), plus anything ticked that fell out of
 * the top counts, so it can still be unticked.
 */
export const facetOptions = (values: FacetValue[] | undefined, selected: string[] | undefined): FacetOption[] => {
    const chosen = new Set(selected ?? []);
    const out: FacetOption[] = [];
    for (const v of values ?? []) {
        if (!v.value) continue;
        out.push({ value: v.value, label: v.label || v.value, count: v.count, selected: chosen.has(v.value) });
    }
    for (const value of chosen) {
        if (!out.some(o => o.value === value)) out.push({ value, label: value, count: null, selected: true });
    }
    return out;
};

/**
 * The next page appended to what is shown. A view already on screen keeps its
 * place: keyset pages can overlap when a view's numbers change between requests.
 */
export const mergePages = (shown: ViewRow[], next: ViewRow[]): ViewRow[] => {
    const seen = new Set(shown.map(r => r.id));
    const out = [...shown];
    for (const row of next) {
        if (seen.has(row.id)) continue;
        seen.add(row.id);
        out.push(row);
    }
    return out;
};

export const applyChange = (row: ViewRow, c: DiscoverChange): ViewRow => {
    if (row.id !== c.id) return row;
    switch (c.change) {
        case 'favorite': return row.favorite === c.favorite ? row : { ...row, favorite: c.favorite };
        case 'hidden': return row.hidden === c.hidden ? row : { ...row, hidden: c.hidden };
        case 'curation': return { ...row, featured_position: c.featured_position, featured: c.featured_position !== null, certified: c.certified };
    }
};

export const applyToRows = (rows: ViewRow[], c: DiscoverChange): ViewRow[] =>
    rows.some(r => r.id === c.id) ? rows.map(r => applyChange(r, c)) : rows;

const byFeaturedPosition = (a: ViewRow, b: ViewRow) =>
    (a.featured_position ?? Infinity) - (b.featured_position ?? Infinity) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/**
 * The rails after a change. A hidden view leaves every rail, as the server
 * leaves it out; curation moves a view into or out of Featured and Certified.
 * `row` is the view as the caller last saw it, for a rail it isn't in yet. An
 * unhidden view comes back with the next fetch: only the server knows where.
 */
export const applyToRails = (rails: Rails, c: DiscoverChange, row?: ViewRow): Rails => {
    const out = {} as Rails;
    for (const name of RAIL_ORDER) {
        const rows = applyToRows(rails[name] ?? [], c);
        out[name] = c.change === 'hidden' && c.hidden ? rows.filter(r => r.id !== c.id) : rows;
    }
    if (c.change !== 'curation') return out;
    const known = RAIL_ORDER.map(name => out[name].find(r => r.id === c.id)).find(Boolean)
        ?? (row && row.id === c.id ? applyChange(row, c) : undefined);
    const addable = known && !known.hidden ? known : undefined;
    if (c.featured_position === null) out.featured = out.featured.filter(r => r.id !== c.id);
    else if (addable && !out.featured.some(r => r.id === c.id)) out.featured = [...out.featured, addable].sort(byFeaturedPosition);
    else out.featured = [...out.featured].sort(byFeaturedPosition);
    if (!c.certified) out.certified = out.certified.filter(r => r.id !== c.id);
    else if (addable && !out.certified.some(r => r.id === c.id)) out.certified = [...out.certified, addable];
    return out;
};

export const MAX_FEATURED_POSITION = 10_000;

/** A newly featured view goes after the ones already featured. */
export const nextFeaturedPosition = (featured: ViewRow[]): number =>
    Math.min(MAX_FEATURED_POSITION, Math.max(-1, ...featured.map(r => r.featured_position ?? -1)) + 1);

const MODE_RANK: Record<SearchMode, number> = { basic: 0, keyword: 1, hybrid: 2 };

export interface ModeNote {
    label: string;
    detail: string;
    /** The app could search by meaning once an administrator turns hybrid search on. */
    setup: boolean;
}

/**
 * What to say about how a search was answered, or null with nothing to say (no
 * words searched, or answered by meaning). `configured` is the best mode the
 * app runs (the `search` capability), null when unknown; one search can be
 * answered lower, by a sort other than relevance or an embedding that was slow.
 */
export const modeNote = (q: string | undefined, answered: SearchMode, configured: SearchMode | null, sort: SearchSort): ModeNote | null => {
    if (!q?.trim() || answered === 'hybrid') return null;
    const label = answered === 'keyword' ? 'Showing keyword matches' : 'Showing word matches';
    const best = configured ?? answered;
    if (MODE_RANK[best] > MODE_RANK[answered]) {
        const fuller = best === 'hybrid' ? 'match by meaning too' : 'rank by keyword';
        if (sort !== 'relevance') {
            return { label, detail: `Sorting by ${SORT_LABELS[sort].toLowerCase()} matches the words typed. Sort by relevance to ${fuller}.`, setup: false };
        }
        return {
            label,
            detail: best === 'hybrid'
                ? 'Matching by meaning took too long this time, so these match the words typed. Searching again usually helps.'
                : 'Keyword ranking wasn’t available for this search, so these match the words typed.',
            setup: false,
        };
    }
    return {
        label,
        detail: answered === 'keyword' ? 'This app ranks views by keyword; it doesn’t match by meaning yet.' : 'This app matches the words you type, not their meaning.',
        setup: configured !== null,
    };
};

/** The most views Combine views takes: every view gives at least one tab, and a view has at most 50 (`MAX_TABS`). */
export const MAX_COMBINED = 50;

/** `row` added to the end of what Combine views will copy, once, up to the limit. */
export const addPick = (picked: ViewRow[], row: ViewRow): ViewRow[] =>
    picked.some(r => r.id === row.id) || picked.length >= MAX_COMBINED ? picked : [...picked, row];

/** The picks with `id` moved one place earlier (-1) or later (1); the order is the new view's tab order. */
export const movePick = (picked: ViewRow[], id: string, by: -1 | 1): ViewRow[] => {
    const from = picked.findIndex(r => r.id === id);
    const to = from + by;
    if (from < 0 || to < 0 || to >= picked.length) return picked;
    const out = [...picked];
    [out[from], out[to]] = [out[to], out[from]];
    return out;
};

export const countText = (total: number, capped: boolean): string =>
    capped ? `Top ${total.toLocaleString()} matches` : `${total.toLocaleString()} view${total === 1 ? '' : 's'}`;
