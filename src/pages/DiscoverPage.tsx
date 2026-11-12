import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertCircle, Archive, ArrowLeft, ChevronLeft, ChevronRight, Compass, Info, Layers, LayoutGrid, List, Loader2, RefreshCw, SlidersHorizontal, X,
} from 'lucide-react';
import clsx from 'clsx';
import { findCapability, useCapabilities } from '../capabilities';
import { fetchMe } from '../sharing';
import {
    announceDiscoverChange, curateView, DISCOVER_CHANGED, discoverHref, fetchDiscoverStatus, fetchRails, parseDiscoverHref,
    searchQuery, searchViews, setFavorite, setHidden,
    type DiscoverChange, type DiscoverRoute, type DiscoverStatus, type RailName, type Rails, type SearchMode, type SearchResponse, type ViewRow,
} from '../discover';
import {
    applyToRails, applyToRows, clearFilters, countText, effectiveScope, effectiveSort, emptyMessage, GOVERNANCE_ROUTE, isGovernance,
    mergePages, modeNote, nextFeaturedPosition, normalizeRoute, pageMode, RAIL_LABELS, RAIL_LIMIT, RAIL_ORDER, resultsTitle, SCOPE_LABELS,
    scopesFor, searchParamsOf, seeAllRoute, SORT_LABELS, sortsFor, withChanges, withQuery,
} from '../discoverPage';
import { ShareDialog } from '../components/sharing';
import { ComposeDialog } from '../components/discover/ComposeDialog';
import { DiscoverFilters } from '../components/discover/DiscoverFilters';
import { ViewCard, ViewListHeader, ViewListRow, type ViewActions } from '../components/discover/ViewCard';
import { ViewSearchBox } from '../components/discover/ViewSearchBox';

const PRIMARY = 'flex items-center gap-1.5 rounded-lg bg-brand-blue px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50';
const SECONDARY = 'flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';

const LAYOUT_KEY = 'sccc-discover-layout';
type Layout = 'grid' | 'list';

const readLayout = (): Layout => {
    try {
        return localStorage.getItem(LAYOUT_KEY) === 'list' ? 'list' : 'grid';
    } catch {
        return 'grid';
    }
};

/** The catalog's first build can take minutes on a large deployment; asking more often than this tells nobody anything sooner. */
const STATUS_POLL_MS = 4000;
const STATUS_POLL_MAX_MS = 20_000;
const MODES: readonly SearchMode[] = ['basic', 'keyword', 'hybrid'];
const GRID = 'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4';
const HYBRID_GUIDE = '#/user-guide/settings/hybrid-search';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const onDiscover = () => window.location.hash === '#/discover' || window.location.hash.startsWith('#/discover?');
const readRoute = () => normalizeRoute(parseDiscoverHref(window.location.hash));
const addressFor = (route: DiscoverRoute) => `${window.location.pathname}${window.location.search}${discoverHref(route)}`;

interface ResultsPage {
    /** `searchQuery` of the first page's request; a different key is a different search. */
    key: string;
    rows: ViewRow[];
    next_cursor: string | null;
    total: number;
    mode: SearchMode;
    capped: boolean;
    facets?: SearchResponse['facets'];
    error: string | null;
    moreError: string | null;
}

/**
 * Discover: every view the caller can open, found by searching rather than
 * listed, because a deployment can hold tens of thousands. With nothing to
 * search for it shows rails (Featured, Popular, …); with words, a scope other
 * than "All I can open", a sort or a filter, it shows results.
 *
 * The address is the page's state (`#/discover?q=&scope=…`), so Back, reload
 * and a copied link all land where the reader was. Typing rewrites the current
 * entry; running a search, picking a scope or changing a filter adds one.
 */
export const DiscoverPage: React.FC = () => {
    const [asked, setRoute] = useState<DiscoverRoute>(readRoute);
    const [text, setText] = useState(() => readRoute().q ?? '');
    const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
    const [status, setStatus] = useState<DiscoverStatus | null>(null);
    const [refresh, setRefresh] = useState(0);
    const [rails, setRails] = useState<{ data: Rails | null; error: string | null } | null>(null);
    const [page, setPage] = useState<ResultsPage | null>(null);
    const [moreFor, setMoreFor] = useState<string | null>(null);
    const [layout, setLayout] = useState<Layout>(readLayout);
    const [notice, setNotice] = useState<string | null>(null);
    const [sharing, setSharing] = useState<ViewRow | null>(null);
    const [composing, setComposing] = useState<ViewRow[] | null>(null);
    const [managesSome, setManagesSome] = useState(false);
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null);
    const more = useRef<AbortController | null>(null);
    const capabilities = useCapabilities();

    const admin = isAdmin === true;
    // A link carrying `everything` reads as an ordinary search for someone who isn't an administrator.
    const route = useMemo(
        () => (asked.scope === 'everything' && isAdmin === false ? withChanges(asked, { scope: undefined }) : asked),
        [asked, isAdmin],
    );
    const mode = pageMode(route);
    const configured = useMemo(() => {
        const m = findCapability(capabilities, 'search')?.mode;
        return MODES.find(x => x === m) ?? null;
    }, [capabilities]);

    const noteManaged = useCallback((rows: ViewRow[]) => {
        if (rows.some(r => r.access === 'MANAGE')) setManagesSome(true);
    }, []);

    useEffect(() => {
        let live = true;
        fetchMe()
            .then(me => { if (live) setIsAdmin(me.is_admin); })
            .catch(() => { if (live) setIsAdmin(false); });
        return () => { live = false; };
    }, []);

    // A link naming a rail that a search stands in for (`?rail=popular`) reads as that search.
    useEffect(() => {
        if (onDiscover() && window.location.hash !== discoverHref(readRoute())) {
            window.history.replaceState(window.history.state, '', addressFor(readRoute()));
        }
    }, []);

    // Back, Forward and links into Discover (the sidebar's) change the address under the page.
    useEffect(() => {
        const follow = () => {
            if (!onDiscover()) return;
            const next = readRoute();
            const href = discoverHref(next);
            if (window.location.hash !== href) window.history.replaceState(window.history.state, '', addressFor(next));
            setRoute(prev => (discoverHref(prev) === href ? prev : next));
            setText(next.q ?? '');
        };
        window.addEventListener('hashchange', follow);
        window.addEventListener('popstate', follow);
        return () => {
            window.removeEventListener('hashchange', follow);
            window.removeEventListener('popstate', follow);
        };
    }, []);

    // Until the catalog's first build finishes, say so; when it does, reload what's shown.
    useEffect(() => {
        let live = true;
        let timer: number | undefined;
        let delay = STATUS_POLL_MS;
        let waited = false;
        const poll = () => {
            fetchDiscoverStatus()
                .then(s => {
                    if (!live) return;
                    setStatus(s);
                    if (s.ready) {
                        if (waited) setRefresh(n => n + 1);
                        return;
                    }
                    waited = true;
                    timer = window.setTimeout(poll, delay);
                    delay = Math.min(delay * 1.5, STATUS_POLL_MAX_MS);
                })
                // Search answers for itself; status only adds the banner.
                .catch(() => undefined);
        };
        poll();
        return () => { live = false; window.clearTimeout(timer); };
    }, []);

    const wantsRails = mode !== 'results';
    useEffect(() => {
        if (!wantsRails) return;
        let live = true;
        fetchRails()
            .then(data => {
                if (!live) return;
                setRails({ data, error: null });
                noteManaged(RAIL_ORDER.flatMap(name => data[name] ?? []));
            })
            .catch(e => { if (live) setRails(prev => ({ data: prev?.data ?? null, error: message(e) })); });
        return () => { live = false; };
    }, [wantsRails, refresh, noteManaged]);

    // Only `everything` depends on being an administrator, so knowing it late
    // doesn't repeat any other search; that one waits until it's known.
    const adminScope = route.scope === 'everything' ? admin : false;
    const params = useMemo(() => searchParamsOf(route, adminScope), [route, adminScope]);
    const key = searchQuery(params);
    const holding = route.scope === 'everything' && isAdmin === null;
    const searching = mode === 'results' && !holding;

    useEffect(() => {
        if (!searching) return;
        const ctrl = new AbortController();
        const k = searchQuery(params);
        searchViews({ ...params, facets: true }, { signal: ctrl.signal })
            .then(res => {
                setPage({
                    key: k, rows: res.results, next_cursor: res.next_cursor, total: res.total, mode: res.mode,
                    capped: res.capped, facets: res.facets, error: null, moreError: null,
                });
                noteManaged(res.results);
            })
            .catch(e => {
                if (ctrl.signal.aborted) return;
                setPage({ key: k, rows: [], next_cursor: null, total: 0, mode: 'basic', capped: false, error: message(e), moreError: null });
            });
        return () => ctrl.abort();
    }, [searching, params, refresh, noteManaged]);

    useEffect(() => {
        const box = more;
        return () => box.current?.abort();
    }, [key]);

    const current = !holding && page && page.key === key ? page : null;
    const loading = mode === 'results' && !current;

    const loadMore = useCallback(() => {
        if (!current?.next_cursor || current.moreError || moreFor === key) return;
        const k = key;
        const cursor = current.next_cursor;
        const ctrl = new AbortController();
        more.current?.abort();
        more.current = ctrl;
        setMoreFor(k);
        searchViews({ ...params, cursor }, { signal: ctrl.signal })
            .then(res => {
                setPage(p => (p && p.key === k && p.next_cursor === cursor
                    ? { ...p, rows: mergePages(p.rows, res.results), next_cursor: res.next_cursor }
                    : p));
                noteManaged(res.results);
            })
            .catch(e => {
                if (ctrl.signal.aborted) return;
                setPage(p => (p && p.key === k ? { ...p, moreError: message(e) } : p));
            })
            .finally(() => setMoreFor(m => (m === k ? null : m)));
    }, [current, key, moreFor, params, noteManaged]);

    useEffect(() => {
        if (!sentinel) return;
        const io = new IntersectionObserver(entries => {
            if (entries.some(e => e.isIntersecting)) loadMore();
        }, { rootMargin: '600px 0px' });
        io.observe(sentinel);
        return () => io.disconnect();
    }, [sentinel, loadMore]);

    useEffect(() => {
        if (!notice) return;
        const timer = window.setTimeout(() => setNotice(null), 8000);
        return () => window.clearTimeout(timer);
    }, [notice]);

    const patch = useCallback((c: DiscoverChange, row?: ViewRow) => {
        setPage(p => {
            if (!p) return p;
            const rows = applyToRows(p.rows, c);
            return rows === p.rows ? p : { ...p, rows };
        });
        setRails(r => (r?.data ? { ...r, data: applyToRails(r.data, c, row) } : r));
    }, []);

    // The sidebar stars and hides too; its changes land here without a refetch.
    useEffect(() => {
        const onChange = (e: Event) => {
            const c = (e as CustomEvent<DiscoverChange>).detail;
            if (c?.id) patch(c);
        };
        window.addEventListener(DISCOVER_CHANGED, onChange);
        return () => window.removeEventListener(DISCOVER_CHANGED, onChange);
    }, [patch]);

    // ------------------------------------------------------------- navigation

    /** Shows `next` as a new history entry, after putting back what typing had rewritten. */
    const go = (next: DiscoverRoute) => {
        const href = discoverHref(next);
        if (discoverHref(route) !== href) {
            window.history.replaceState(window.history.state, '', addressFor(route));
            window.history.pushState(window.history.state, '', addressFor(next));
        } else if (window.location.hash !== href) {
            window.history.replaceState(window.history.state, '', addressFor(next));
        }
        setRoute(prev => (discoverHref(prev) === href ? prev : next));
        setText(next.q ?? '');
        setFiltersOpen(false);
    };

    const change = (patchRoute: Partial<DiscoverRoute>) => go(withChanges(route, patchRoute));

    const type = (value: string) => {
        setText(value);
        window.history.replaceState(window.history.state, '', addressFor(withQuery(route, value)));
    };

    const toggleGovernance = () => go(isGovernance(route) ? withChanges(route, { scope: undefined, opened: undefined }) : GOVERNANCE_ROUTE);

    // ---------------------------------------------------------------- actions

    const toggleFavorite = (row: ViewRow) => {
        const favorite = !row.favorite;
        patch({ id: row.id, change: 'favorite', favorite });
        setFavorite(row.id, favorite)
            .then(() => announceDiscoverChange({ id: row.id, change: 'favorite', favorite }))
            .catch(e => {
                patch({ id: row.id, change: 'favorite', favorite: !favorite });
                setNotice(`Couldn’t ${favorite ? 'star' : 'unstar'} “${row.name}”: ${message(e)}`);
            });
    };

    const toggleHidden = (row: ViewRow) => {
        const hidden = !row.hidden;
        patch({ id: row.id, change: 'hidden', hidden });
        setHidden(row.id, hidden)
            .then(() => {
                announceDiscoverChange({ id: row.id, change: 'hidden', hidden });
                // Only the server knows where an unhidden view goes back in the rails.
                if (!hidden && wantsRails) setRefresh(n => n + 1);
            })
            .catch(e => {
                patch({ id: row.id, change: 'hidden', hidden: !hidden });
                if (hidden) setRefresh(n => n + 1);
                setNotice(`Couldn’t ${hidden ? 'hide' : 'unhide'} “${row.name}”: ${message(e)}`);
            });
    };

    const curate = async (row: ViewRow, changes: { featured_position?: number | null; certified?: boolean }, verb: string) => {
        try {
            const saved = await curateView(row.id, changes);
            const c: DiscoverChange = { id: row.id, change: 'curation', featured_position: saved.featured_position, certified: saved.certified };
            patch(c, row);
            announceDiscoverChange(c);
        } catch (e) {
            setNotice(`Couldn’t ${verb} “${row.name}”: ${message(e)}`);
        }
    };

    const toggleFeatured = async (row: ViewRow) => {
        if (row.featured) {
            await curate(row, { featured_position: null }, 'unfeature');
            return;
        }
        try {
            const featured = rails?.data?.featured ?? (await fetchRails()).featured;
            await curate(row, { featured_position: nextFeaturedPosition(featured) }, 'feature');
        } catch (e) {
            setNotice(`Couldn’t feature “${row.name}”: ${message(e)}`);
        }
    };

    const actions: ViewActions = {
        isAdmin: admin,
        onFavorite: toggleFavorite,
        onHide: toggleHidden,
        onFeature: row => { void toggleFeatured(row); },
        onCertify: row => { void curate(row, { certified: !row.certified }, row.certified ? 'uncertify' : 'certify'); },
        onShare: setSharing,
        onCombine: row => setComposing([row]),
    };

    const setLayoutChoice = (next: Layout) => {
        setLayout(next);
        try {
            localStorage.setItem(LAYOUT_KEY, next);
        } catch {
            /* private mode: the choice lasts this visit */
        }
    };

    // ----------------------------------------------------------------- render

    const scope = effectiveScope(route, admin);
    const offersStatus = admin || managesSome || !!route.status;

    return (
        <div className="h-full overflow-y-auto bg-gray-50">
            <header className="border-b border-gray-200 bg-white">
                <div className="mx-auto max-w-7xl px-6 py-5">
                    <div className="flex items-center gap-3">
                        <Compass className="hidden h-7 w-7 shrink-0 text-brand-blue sm:block" aria-hidden="true" />
                        <ViewSearchBox
                            size="lg"
                            label="Search views"
                            placeholder="Search views by name, description, owner, domain or widget"
                            value={text}
                            onChange={type}
                            onSubmit={value => go(withQuery(route, value))}
                            onPick={row => { window.location.hash = row.link; }}
                            autoFocus={!route.q}
                            className="min-w-0 flex-1"
                        />
                        <button
                            type="button"
                            onClick={() => setComposing([])}
                            title="Make one view with a tab for each view you pick"
                            className={clsx(SECONDARY, 'hidden shrink-0 py-2.5 sm:flex')}
                        >
                            <Layers className="h-4 w-4" aria-hidden="true" /> Combine views…
                        </button>
                    </div>
                    <nav aria-label="Which views" className="mt-3 flex flex-wrap items-center gap-2">
                        {scopesFor(admin).map(s => (
                            <button
                                key={s}
                                type="button"
                                aria-pressed={scope === s && !isGovernance(route)}
                                onClick={() => change({ scope: s })}
                                className={clsx(
                                    'rounded-full border px-3 py-1 text-sm font-medium transition-colors',
                                    scope === s && !isGovernance(route)
                                        ? 'border-brand-blue bg-brand-blue text-white'
                                        : 'border-gray-300 bg-white text-gray-700 hover:border-brand-blue hover:text-brand-blue',
                                )}
                            >
                                {SCOPE_LABELS[s]}
                            </button>
                        ))}
                        {admin && (
                            <>
                                <span className="mx-1 h-5 w-px bg-gray-200" aria-hidden="true" />
                                <button
                                    type="button"
                                    aria-pressed={isGovernance(route)}
                                    onClick={toggleGovernance}
                                    title="Every view in this deployment that nobody has opened in 90 days, to review for archiving"
                                    className={clsx(
                                        'flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors',
                                        isGovernance(route)
                                            ? 'border-amber-500 bg-amber-500 text-white'
                                            : 'border-amber-300 bg-amber-50 text-amber-800 hover:border-amber-500',
                                    )}
                                >
                                    <Archive className="h-3.5 w-3.5" aria-hidden="true" />
                                    Not opened in 90 days
                                </button>
                            </>
                        )}
                    </nav>
                </div>
            </header>

            <div className="mx-auto max-w-7xl space-y-6 px-6 py-6">
                {status && !status.ready && (
                    <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900" role="status">
                        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
                        <p>
                            <span className="font-medium">Indexing views…</span>{' '}
                            {status.total > 0
                                ? `${status.indexed.toLocaleString()} of ${status.total.toLocaleString()} so far. `
                                : ''}
                            What’s indexed can already be found, and this page refreshes when it’s done.
                        </p>
                    </div>
                )}

                {notice && (
                    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                        <p className="flex-1">{notice}</p>
                        <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)} className="rounded p-0.5 hover:bg-red-100">
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                )}

                {mode === 'home' && (
                    <Home rails={rails} actions={actions} onSeeAll={name => go(seeAllRoute(name))} onRetry={() => setRefresh(n => n + 1)} />
                )}

                {mode === 'rail' && route.rail && (
                    <RailAlone
                        name={route.rail}
                        rails={rails}
                        layout={layout}
                        onLayout={setLayoutChoice}
                        actions={actions}
                        isAdmin={admin}
                        onBack={() => go({})}
                        onRetry={() => setRefresh(n => n + 1)}
                    />
                )}

                {mode === 'results' && (
                    <div className="flex gap-6">
                        <aside className="hidden w-56 shrink-0 lg:block">
                            <DiscoverFilters
                                route={route}
                                facets={current?.facets}
                                offersStatus={offersStatus}
                                isAdmin={admin}
                                onChange={change}
                                onClear={() => go(clearFilters(route))}
                            />
                        </aside>
                        <section className="min-w-0 flex-1 space-y-4" aria-labelledby="discover-results-title">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                                <h1 id="discover-results-title" className="min-w-0 truncate text-lg font-semibold text-gray-900">{resultsTitle(route)}</h1>
                                {current && !current.error && (
                                    <span className="text-sm text-gray-500" title={current.capped ? 'Searches by relevance stop at the 500 best matches' : undefined}>
                                        {countText(current.total, current.capped)}
                                    </span>
                                )}
                                {loading && <Loader2 className="h-4 w-4 animate-spin text-gray-400" aria-label="Loading" />}
                                <div className="ml-auto flex items-center gap-2">
                                    <button type="button" onClick={() => setFiltersOpen(o => !o)} aria-expanded={filtersOpen} className={clsx(SECONDARY, 'lg:hidden')}>
                                        <SlidersHorizontal className="h-4 w-4" aria-hidden="true" /> Filters
                                    </button>
                                    <label className="flex items-center gap-1.5 text-sm text-gray-600">
                                        <span className="hidden sm:inline">Sort</span>
                                        <select
                                            value={effectiveSort(route)}
                                            onChange={e => change({ sort: e.target.value as DiscoverRoute['sort'] })}
                                            className="rounded-lg border border-gray-300 bg-white py-1.5 pl-2 pr-7 text-sm text-gray-800 focus:border-brand-blue focus:outline-none focus:ring-2 focus:ring-brand-blue/20"
                                        >
                                            {sortsFor(!!route.q?.trim()).map(s => <option key={s} value={s}>{SORT_LABELS[s]}</option>)}
                                        </select>
                                    </label>
                                    <LayoutToggle layout={layout} onChange={setLayoutChoice} />
                                </div>
                            </div>

                            {filtersOpen && (
                                <div className="rounded-xl border border-gray-200 bg-white p-4 lg:hidden">
                                    <DiscoverFilters
                                        route={route}
                                        facets={current?.facets}
                                        offersStatus={offersStatus}
                                        isAdmin={admin}
                                        onChange={change}
                                        onClear={() => go(clearFilters(route))}
                                    />
                                </div>
                            )}

                            <ResultNotes route={route} page={current} configured={configured} isAdmin={admin} />

                            {current?.error ? (
                                <ErrorState text={current.error} onRetry={() => setRefresh(n => n + 1)} />
                            ) : loading ? (
                                <Skeleton layout={layout} />
                            ) : current && current.rows.length === 0 ? (
                                <Empty route={route} onClear={() => go(clearFilters(route))} onHome={() => go({})} />
                            ) : current && (
                                <>
                                    <Rows rows={current.rows} layout={layout} actions={actions} />
                                    {current.next_cursor && !current.moreError && <div ref={setSentinel} aria-hidden="true" className="h-px" />}
                                    {moreFor === key && (
                                        <div className="flex justify-center py-4 text-gray-400"><Loader2 className="h-5 w-5 animate-spin" aria-label="Loading more" /></div>
                                    )}
                                    {current.moreError && (
                                        <div className="flex items-center justify-center gap-3 py-4 text-sm text-red-700">
                                            <span>Couldn’t load more: {current.moreError}</span>
                                            <button type="button" className={SECONDARY} onClick={() => setPage(p => (p ? { ...p, moreError: null } : p))}>
                                                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Try again
                                            </button>
                                        </div>
                                    )}
                                    {!current.next_cursor && current.capped && (
                                        <p className="py-4 text-center text-sm text-gray-500">
                                            Searches by relevance stop at the top 500 matches. Add words or a filter to narrow it down.
                                        </p>
                                    )}
                                </>
                            )}
                        </section>
                    </div>
                )}
            </div>

            {sharing && (
                <ShareDialog
                    objectType="app"
                    objectId={sharing.id}
                    name={sharing.name}
                    published
                    link={`${window.location.origin}${window.location.pathname}${sharing.link}`}
                    onClose={() => setSharing(null)}
                />
            )}
            {composing && <ComposeDialog initial={composing} onClose={() => setComposing(null)} />}
        </div>
    );
};

// ------------------------------------------------------------------- pieces

const LayoutToggle: React.FC<{ layout: Layout; onChange: (layout: Layout) => void }> = ({ layout, onChange }) => (
    <div className="flex rounded-lg border border-gray-300 bg-white p-0.5" role="group" aria-label="Layout">
        {([['grid', LayoutGrid, 'Cards'], ['list', List, 'List']] as const).map(([value, Icon, label]) => (
            <button
                key={value}
                type="button"
                aria-pressed={layout === value}
                aria-label={label}
                title={label}
                onClick={() => onChange(value)}
                className={clsx('rounded-md p-1.5 transition-colors', layout === value ? 'bg-brand-blue/10 text-brand-blue' : 'text-gray-500 hover:text-gray-800')}
            >
                <Icon className="h-4 w-4" />
            </button>
        ))}
    </div>
);

const Rows: React.FC<{ rows: ViewRow[]; layout: Layout; actions: ViewActions }> = ({ rows, layout, actions }) =>
    layout === 'grid' ? (
        <div className={GRID}>
            {rows.map(row => <ViewCard key={row.id} row={row} actions={actions} />)}
        </div>
    ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <ViewListHeader />
            {rows.map(row => <ViewListRow key={row.id} row={row} actions={actions} />)}
        </div>
    );

const Skeleton: React.FC<{ layout: Layout }> = ({ layout }) => (
    <div className={layout === 'grid' ? GRID : 'space-y-2'} aria-hidden="true">
        {Array.from({ length: layout === 'grid' ? 8 : 6 }, (_, i) => (
            <div key={i} className={clsx('animate-pulse rounded-xl border border-gray-200 bg-white', layout === 'grid' ? 'h-36' : 'h-12')} />
        ))}
    </div>
);

const ErrorState: React.FC<{ text: string; onRetry: () => void }> = ({ text, onRetry }) => (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-red-200 bg-white px-6 py-10 text-center">
        <AlertCircle className="h-6 w-6 text-red-500" aria-hidden="true" />
        <div>
            <p className="font-medium text-gray-900">Couldn’t load views</p>
            <p className="mt-1 text-sm text-gray-500">{text}</p>
        </div>
        <button type="button" className={SECONDARY} onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Try again</button>
    </div>
);

const EmptyBox: React.FC<{ title: string; hint: string; children?: React.ReactNode }> = ({ title, hint, children }) => (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
        <Compass className="h-7 w-7 text-gray-300" aria-hidden="true" />
        <div>
            <p className="font-medium text-gray-900">{title}</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-gray-500">{hint}</p>
        </div>
        {children && <div className="flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
);

const Empty: React.FC<{ route: DiscoverRoute; onClear: () => void; onHome: () => void }> = ({ route, onClear, onHome }) => {
    const { title, hint } = emptyMessage(route);
    const filtered = clearFilters(route);
    const canClear = discoverHref(filtered) !== discoverHref(route);
    return (
        <EmptyBox title={title} hint={hint}>
            {canClear && <button type="button" className={PRIMARY} onClick={onClear}>Clear filters</button>}
            <button type="button" className={SECONDARY} onClick={onHome}>Back to Discover</button>
        </EmptyBox>
    );
};

/** How the search was answered, when that changes what someone should expect. */
const ResultNotes: React.FC<{ route: DiscoverRoute; page: ResultsPage | null; configured: SearchMode | null; isAdmin: boolean }> = ({ route, page, configured, isAdmin }) => {
    const note = page && !page.error ? modeNote(route.q, page.mode, configured, effectiveSort(route)) : null;
    const mine = route.scope === 'mine';
    if (!note && !mine) return null;
    return (
        <div className="space-y-2">
            {note && (
                <div className="flex items-start gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600">
                    <Info className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
                    <p>
                        <span className="font-medium text-gray-800">{note.label}.</span> {note.detail}
                        {note.setup && isAdmin && (
                            <> <a href={HYBRID_GUIDE} className="font-medium text-brand-blue hover:underline">Turn on hybrid search</a></>
                        )}
                    </p>
                </div>
            )}
            {mine && (
                <p className="text-xs text-gray-500">
                    Only published views are searchable. Views you haven’t published yet are under My views in the sidebar.
                </p>
            )}
        </div>
    );
};

const RailsLoading: React.FC = () => (
    <div className="space-y-8" aria-hidden="true">
        {[0, 1, 2].map(i => (
            <div key={i} className="space-y-3">
                <div className="h-5 w-40 animate-pulse rounded bg-gray-200" />
                <div className="flex gap-4 overflow-hidden">
                    {[0, 1, 2, 3].map(j => <div key={j} className="h-36 w-72 shrink-0 animate-pulse rounded-xl border border-gray-200 bg-white" />)}
                </div>
            </div>
        ))}
    </div>
);

const Rail: React.FC<{ name: RailName; rows: ViewRow[]; actions: ViewActions; onSeeAll: () => void }> = ({ name, rows, actions, onSeeAll }) => {
    const scroller = useRef<HTMLDivElement>(null);
    const nudge = (direction: 1 | -1) => {
        const el = scroller.current;
        if (el) el.scrollBy({ left: direction * Math.max(el.clientWidth * 0.8, 300), behavior: 'smooth' });
    };
    const { title, blurb } = RAIL_LABELS[name];
    return (
        <section aria-labelledby={`rail-${name}`}>
            <div className="flex items-end justify-between gap-3">
                <div className="min-w-0">
                    <h2 id={`rail-${name}`} className="text-base font-semibold text-gray-900">{title}</h2>
                    <p className="text-xs text-gray-500">{blurb}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <button type="button" aria-label={`Scroll ${title} left`} onClick={() => nudge(-1)} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                        <ChevronLeft className="h-4 w-4" />
                    </button>
                    <button type="button" aria-label={`Scroll ${title} right`} onClick={() => nudge(1)} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                        <ChevronRight className="h-4 w-4" />
                    </button>
                    <a
                        href={discoverHref(seeAllRoute(name))}
                        onClick={e => { e.preventDefault(); onSeeAll(); }}
                        className="ml-2 text-sm font-medium text-brand-blue hover:underline"
                    >
                        See all
                    </a>
                </div>
            </div>
            <div ref={scroller} className="-mx-1 mt-3 flex snap-x gap-4 overflow-x-auto px-1 pb-2">
                {rows.map(row => (
                    <div key={row.id} className="w-72 shrink-0 snap-start">
                        <ViewCard row={row} actions={actions} />
                    </div>
                ))}
            </div>
        </section>
    );
};

const Home: React.FC<{
    rails: { data: Rails | null; error: string | null } | null;
    actions: ViewActions;
    onSeeAll: (name: RailName) => void;
    onRetry: () => void;
}> = ({ rails, actions, onSeeAll, onRetry }) => {
    if (!rails) return <RailsLoading />;
    if (!rails.data) return <ErrorState text={rails.error ?? 'Unknown error'} onRetry={onRetry} />;
    const data = rails.data;
    const shown = RAIL_ORDER.filter(name => (data[name] ?? []).length > 0);
    if (shown.length === 0) {
        return (
            <EmptyBox
                title="Nothing to discover yet"
                hint="Views appear here once someone publishes one and shares it with you. Search above finds any view you can already open, or build your own from the sidebar."
            />
        );
    }
    return (
        <div className="space-y-8">
            {shown.map(name => <Rail key={name} name={name} rows={data[name]} actions={actions} onSeeAll={() => onSeeAll(name)} />)}
        </div>
    );
};

const ALONE_EMPTY: Partial<Record<RailName, (isAdmin: boolean) => { title: string; hint: string }>> = {
    featured: isAdmin => ({
        title: 'Nothing is featured yet',
        hint: isAdmin
            ? 'Feature a view from its ⋯ menu to put it here for everyone who can open it.'
            : 'Your administrators haven’t featured any views yet.',
    }),
    new_for_you: () => ({
        title: 'Nothing new for you',
        hint: 'Views shared with you or your groups in the last 14 days show here until you open them.',
    }),
};

const RailAlone: React.FC<{
    name: RailName;
    rails: { data: Rails | null; error: string | null } | null;
    layout: Layout;
    onLayout: (layout: Layout) => void;
    actions: ViewActions;
    isAdmin: boolean;
    onBack: () => void;
    onRetry: () => void;
}> = ({ name, rails, layout, onLayout, actions, isAdmin, onBack, onRetry }) => {
    const { title, blurb } = RAIL_LABELS[name];
    const rows = rails?.data?.[name] ?? [];
    const empty = ALONE_EMPTY[name]?.(isAdmin) ?? { title: `No ${title.toLowerCase()} views`, hint: '' };
    return (
        <section className="space-y-4" aria-labelledby="discover-rail-title">
            <button type="button" onClick={onBack} className="flex items-center gap-1 text-sm font-medium text-brand-blue hover:underline">
                <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Discover
            </button>
            <div className="flex items-end gap-3">
                <div className="min-w-0 flex-1">
                    <h1 id="discover-rail-title" className="text-lg font-semibold text-gray-900">{title}</h1>
                    <p className="text-sm text-gray-500">{blurb}</p>
                </div>
                <LayoutToggle layout={layout} onChange={onLayout} />
            </div>
            {!rails ? (
                <Skeleton layout={layout} />
            ) : !rails.data ? (
                <ErrorState text={rails.error ?? 'Unknown error'} onRetry={onRetry} />
            ) : rows.length === 0 ? (
                <EmptyBox title={empty.title} hint={empty.hint} />
            ) : (
                <>
                    <Rows rows={rows} layout={layout} actions={actions} />
                    {rows.length >= RAIL_LIMIT && (
                        <p className="text-center text-sm text-gray-500">
                            {name === 'new_for_you' ? `Showing the ${RAIL_LIMIT} most recent.` : `Showing the first ${RAIL_LIMIT}.`} Search above to find any other view.
                        </p>
                    )}
                </>
            )}
        </section>
    );
};
