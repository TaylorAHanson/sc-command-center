// The sidebar's lists: what `GET /api/apps/` last said (the working set, see
// server/services/working_set.py) merged with what this tab has done since:
// views opened, loaded, starred, dragged, closed, created and deleted. The
// store keeps both and these functions combine them, so a change shows at once
// rather than when the list is next read, and the view catalog's few seconds
// of lag behind a publish or a new star never shows.
//
// No React and no `window` here: `tests/working_set.test.ts` runs this under Node.

export type RowLevel = 'USE' | 'MANAGE';
export type RowState = 'published' | 'published_with_draft' | 'draft_only';
export type RowSharing = 'private' | 'shared' | 'everyone';

/** One view as the sidebar draws it. Never a spec: opening it loads that. */
export interface SidebarRow {
  id: string;
  /** What links name the view by: its claimed name, `<name>-<id>`, or its id. */
  ref: string;
  name: string;
  owner?: string | null;
  domain?: string | null;
  /** 'workspace' or 'standalone'. */
  presentation?: string | null;
  updated_at?: string | null;
  access?: RowLevel | null;
  /** Only on views the caller manages. */
  state?: RowState;
  favorite?: boolean;
  last_opened_at?: string | null;
  sharing?: RowSharing | null;
  /** The caller's own view. Said of views this tab has loaded; the server's own are its `mine`. */
  own?: boolean;
}

/** What `GET /api/apps/` returns. */
export interface WorkingSet {
  favorites: SidebarRow[];
  favorites_total: number;
  recent: SidebarRow[];
  mine: SidebarRow[];
  mine_total: number;
  new_for_you_count: number;
}

export const EMPTY_WORKING_SET: WorkingSet = Object.freeze({
  favorites: [], favorites_total: 0, recent: [], mine: [], mine_total: 0, new_for_you_count: 0,
}) as WorkingSet;

/** What this tab changed since the list was read. */
export interface Changes {
  /** Starred (true) or unstarred (false) here. */
  favored: Record<string, boolean>;
  /** Every favorite in the order this tab last put them, once it has. */
  favoriteOrder: string[] | null;
  /** Opened here, the latest first. */
  opened: string[];
  /** Taken out of Recent here. */
  closed: string[];
  /** Created here. */
  created: string[];
  /** Deleted or archived here. */
  gone: string[];
}

export const NO_CHANGES: Changes = Object.freeze({
  favored: {}, favoriteOrder: null, opened: [], closed: [], created: [], gone: [],
}) as Changes;

/** How many rows each list shows before linking to the rest on Discover. */
export const SHOWN = Object.freeze({ favorites: 15, recent: 5 });

export interface SidebarLists {
  favorites: SidebarRow[];
  /** There are favorites beyond those shown. */
  moreFavorites: boolean;
  /** The latest opened, whoever owns them, less favorites, which have a list of their own. */
  recent: SidebarRow[];
  /** How many views the caller owns, for the My views link. */
  mineTotal: number;
  newForYou: number;
}

const unique = (ids: string[]): string[] => [...new Set(ids)];

/** A time from the server or the browser, in milliseconds. One without a zone is UTC, as Postgres writes them. */
export const timeOf = (value?: string | null): number => {
  if (!value) return 0;
  const t = Date.parse(/(?:Z|[+-]\d\d:?\d\d)$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(t) ? 0 : t;
};

/** `over`'s fields on `base`, except those it leaves undefined. */
const merged = (base: SidebarRow | undefined, over: SidebarRow): SidebarRow => {
  const out: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(over)) if (value !== undefined) out[key] = value;
  return out as unknown as SidebarRow;
};

/** Every row known, by id: the server's, with what this tab loaded since over them. */
const rowsOf = (set: WorkingSet, loaded: SidebarRow[]): Map<string, SidebarRow> => {
  const rows = new Map<string, SidebarRow>();
  for (const r of [...set.mine, ...set.recent, ...set.favorites, ...loaded]) rows.set(r.id, merged(rows.get(r.id), r));
  return rows;
};

/** The caller's own views, the server's and those made or loaded here, the latest changed first. */
const ownRows = (set: WorkingSet, loaded: SidebarRow[], rows: Map<string, SidebarRow>, gone: Set<string>): SidebarRow[] =>
  unique([...set.mine.map(r => r.id), ...loaded.filter(r => r.own).map(r => r.id)])
    .filter(id => rows.has(id) && !gone.has(id))
    .map(id => rows.get(id)!)
    .sort((a, b) => timeOf(b.updated_at) - timeOf(a.updated_at) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));

/** Whether view `id` is a favorite, as far as this tab knows. */
export const isFavorite = (set: WorkingSet, loaded: SidebarRow[], changes: Changes, id: string): boolean =>
  changes.favored[id] ?? rowsOf(set, loaded).get(id)?.favorite ?? set.favorites.some(r => r.id === id);

export const sidebarLists = (set: WorkingSet, loaded: SidebarRow[], changes: Changes): SidebarLists => {
  const rows = rowsOf(set, loaded);
  const gone = new Set(changes.gone);
  const closed = new Set(changes.closed);
  const starred = (id: string) => changes.favored[id] ?? rows.get(id)?.favorite ?? false;
  const known = (id: string) => rows.has(id) && !gone.has(id);
  const row = (id: string): SidebarRow => ({ ...rows.get(id)!, favorite: starred(id) });

  const favoriteIds = unique([...(changes.favoriteOrder ?? []), ...set.favorites.map(r => r.id)])
    .filter(id => known(id) && starred(id));
  let favoritesTotal = set.favorites_total;
  for (const [id, now] of Object.entries(changes.favored)) {
    const was = rows.get(id)?.favorite ?? false;
    if (now !== was) favoritesTotal += now ? 1 : -1;
  }
  const favorites = favoriteIds.slice(0, SHOWN.favorites).map(row);

  const recent = unique([...changes.opened, ...set.recent.map(r => r.id)])
    .filter(id => known(id) && !closed.has(id) && !starred(id))
    .slice(0, SHOWN.recent)
    .map(row);

  const listed = new Set(set.mine.map(r => r.id));
  let mineTotal = set.mine_total;
  for (const id of changes.created) if (!listed.has(id) && !gone.has(id)) mineTotal += 1;
  for (const id of changes.gone) if (listed.has(id)) mineTotal -= 1;

  return {
    favorites,
    moreFavorites: Math.max(favoritesTotal, favoriteIds.length) > favorites.length,
    recent,
    mineTotal: Math.max(mineTotal, ownRows(set, loaded, rows, gone).length),
    newForYou: set.new_for_you_count,
  };
};

/**
 * `changes` less what a freshly read `set` already says, so another tab's
 * later change can show here. Stars and the order are dropped once the server
 * agrees with them; closing, creating and deleting are kept for the session.
 */
export const settled = (changes: Changes, set: WorkingSet): Changes => {
  const listed = new Map<string, boolean>();
  for (const r of [...set.mine, ...set.recent]) listed.set(r.id, !!r.favorite);
  for (const r of set.favorites) listed.set(r.id, true);
  const favored: Record<string, boolean> = {};
  for (const [id, now] of Object.entries(changes.favored)) {
    // A favorite the lists don't mention can't be told from one unstarred.
    const server = listed.get(id) ?? false;
    if (server !== now) favored[id] = now;
  }
  const serverOrder = set.favorites.map(r => r.id);
  // The server shows the first 15, so only those can be compared.
  const order = (changes.favoriteOrder ?? []).filter(id => (favored[id] ?? listed.get(id)) === true);
  const agrees = order.slice(0, serverOrder.length).every((id, i) => serverOrder[i] === id);
  return { ...changes, favored, favoriteOrder: agrees ? null : changes.favoriteOrder };
};

/** The favorites' order once `id` is starred (last) or unstarred (out). */
export const favoriteOrderAfter = (order: string[], id: string, favorite: boolean): string[] =>
  favorite ? [...order.filter(x => x !== id), id] : order.filter(x => x !== id);

/** `ids` with the one at `from` moved to `to`; out-of-range moves change nothing. */
export const moved = (ids: string[], from: number, to: number): string[] => {
  if (from === to || from < 0 || to < 0 || from >= ids.length || to >= ids.length) return ids;
  const next = [...ids];
  const [id] = next.splice(from, 1);
  next.splice(to, 0, id);
  return next;
};

/**
 * Whether a change saved through `discover.ts` (`cc:discover-changed`) can alter
 * what `GET /api/apps/` returns: a star, an order, or a hide, since hidden views
 * leave New for you. A curation can't; the sidebar draws neither featured nor certified.
 */
export const changesSidebar = (change: { favorite?: boolean; hidden?: boolean; order?: string[] }): boolean =>
  change.favorite !== undefined || change.hidden !== undefined || change.order !== undefined;

/** `opened` with `id` the latest. */
export const openedFirst = (opened: string[], id: string): string[] => [id, ...opened.filter(x => x !== id)];

/**
 * What opens when the address names no view: the one opened last, favorites
 * included, else the caller's newest own. Never one taken out of Recent or gone,
 * nor `except` (the view being deleted). Null means the Welcome panel.
 */
export const homeRow = (set: WorkingSet, loaded: SidebarRow[], changes: Changes, except?: string): SidebarRow | null => {
  const rows = rowsOf(set, loaded);
  const skip = new Set([...changes.gone, ...changes.closed, ...(except ? [except] : [])]);
  const last = unique([...changes.opened, ...set.recent.map(r => r.id)]).find(id => rows.has(id) && !skip.has(id));
  if (last) return rows.get(last)!;
  return ownRows(set, loaded, rows, skip)[0] ?? null;
};

/** Where a sidebar row goes. A standalone view is built in the workspace, so its row opens it there. */
export const hrefOf = (row: Pick<SidebarRow, 'ref' | 'presentation'>): string =>
  `${row.presentation === 'standalone' ? '#/workspace' : '#/app'}/${encodeURIComponent(row.ref)}`;
