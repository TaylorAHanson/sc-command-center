// The sidebar's lists, from the working set and this tab's changes (src/workingSet.ts):
//
//   node --experimental-strip-types tests/working_set.test.ts
//
// The module imports nothing, which is what lets Node load it straight from src/.
import assert from 'node:assert/strict';
import {
  EMPTY_WORKING_SET, NO_CHANGES, SHOWN, changesSidebar, favoriteOrderAfter, homeRow, hrefOf, isFavorite, moved,
  openedFirst, settled, sidebarLists, timeOf, type Changes, type SidebarRow, type WorkingSet,
} from '../src/workingSet.ts';

let passed = 0;
let failed = 0;

const test = (name: string, fn: () => void) => {
  try {
    fn();
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`FAIL ${name}\n  ${(err as Error).message.split('\n').join('\n  ')}`);
  }
};

const row = (id: string, extra: Partial<SidebarRow> = {}): SidebarRow => ({ id, ref: id, name: `View ${id}`, ...extra });
const day = (n: number) => `2026-10-${String(n).padStart(2, '0')}T00:00:00Z`;
const set = (extra: Partial<WorkingSet> = {}): WorkingSet => ({ ...EMPTY_WORKING_SET, ...extra });
const changes = (extra: Partial<Changes> = {}): Changes => ({ ...NO_CHANGES, ...extra });
const ids = (rows: SidebarRow[]) => rows.map(r => r.id);

test('each list stops at what the sidebar shows', () => {
  const many = (prefix: string, n: number, extra: Partial<SidebarRow> = {}) =>
    Array.from({ length: n }, (_, i) => row(`${prefix}${i}`, { updated_at: day(1 + (i % 28)), ...extra }));
  const lists = sidebarLists(set({
    favorites: many('f', 15, { favorite: true }), favorites_total: 40,
    recent: many('r', 20), mine: many('m', 50), mine_total: 120, new_for_you_count: 3,
  }), [], NO_CHANGES);
  assert.equal(lists.favorites.length, SHOWN.favorites);
  assert.equal(lists.recent.length, SHOWN.recent);
  assert.equal(lists.moreFavorites, true);
  assert.equal(lists.mineTotal, 120);
  assert.equal(lists.newForYou, 3);
});

test('favorites keep the saved order, and say when there are more', () => {
  const lists = sidebarLists(set({
    favorites: [row('b', { favorite: true }), row('a', { favorite: true })], favorites_total: 2,
  }), [], NO_CHANGES);
  assert.deepEqual(ids(lists.favorites), ['b', 'a']);
  assert.equal(lists.moreFavorites, false);
});

test('recent leaves out favorites, the latest opened here first', () => {
  const lists = sidebarLists(set({
    favorites: [row('f', { favorite: true })],
    recent: [row('f', { favorite: true }), row('r1'), row('r2')],
  }), [row('new')], changes({ opened: ['new', 'r2'] }));
  assert.deepEqual(ids(lists.recent), ['new', 'r2', 'r1']);
});

test('your own views are in Recent like anyone else’s, so no view is listed twice', () => {
  const lists = sidebarLists(set({
    favorites: [row('f', { favorite: true })], favorites_total: 1,
    recent: [row('own'), row('theirs'), row('f', { favorite: true })], mine: [row('own'), row('f', { favorite: true })], mine_total: 2,
  }), [], NO_CHANGES);
  assert.deepEqual(ids(lists.recent), ['own', 'theirs']);
  assert.deepEqual(ids(lists.favorites), ['f']);
});

test('a view starred here leaves Recent for Favorites at once, last in line', () => {
  const lists = sidebarLists(set({
    favorites: [row('f', { favorite: true })], favorites_total: 1, recent: [row('r1'), row('r2')],
  }), [], changes({ favored: { r1: true }, favoriteOrder: favoriteOrderAfter(['f'], 'r1', true) }));
  assert.deepEqual(ids(lists.favorites), ['f', 'r1']);
  assert.deepEqual(ids(lists.recent), ['r2']);
  assert.equal(lists.favorites[1].favorite, true);
});

test('a view unstarred here leaves Favorites and comes back to Recent', () => {
  const lists = sidebarLists(set({
    favorites: [row('f', { favorite: true }), row('g', { favorite: true })], favorites_total: 16,
    recent: [row('f', { favorite: true })],
  }), [], changes({ favored: { f: false } }));
  assert.deepEqual(ids(lists.favorites), ['g']);
  assert.deepEqual(ids(lists.recent), ['f']);
  // 16 less the one unstarred is 15, and one of those is shown.
  assert.equal(lists.moreFavorites, true);
});

test('the order dragged here wins over the one last read', () => {
  const favorites = ['a', 'b', 'c'].map(id => row(id, { favorite: true }));
  const lists = sidebarLists(set({ favorites, favorites_total: 3 }), [], changes({ favoriteOrder: ['c', 'a', 'b'] }));
  assert.deepEqual(ids(lists.favorites), ['c', 'a', 'b']);
});

test('views made here count as yours, and other people’s loaded here do not', () => {
  const lists = sidebarLists(set({
    mine: [row('old', { updated_at: day(1) }), row('mid', { updated_at: day(5) })], mine_total: 2,
  }), [row('made', { own: true, updated_at: day(9) }), row('theirs', { own: false, updated_at: day(10) })],
  changes({ created: ['made'] }));
  assert.equal(lists.mineTotal, 3);
});

test('deleting or archiving a view takes it out of every list and the count', () => {
  const lists = sidebarLists(set({
    favorites: [row('x', { favorite: true })], favorites_total: 1,
    recent: [row('x', { favorite: true }), row('y')], mine: [row('x'), row('y')], mine_total: 9,
  }), [], changes({ gone: ['x'] }));
  assert.deepEqual(ids(lists.favorites), []);
  assert.deepEqual(ids(lists.recent), ['y']);
  assert.equal(lists.mineTotal, 8);
});

test('a view made and deleted here leaves the count where it was', () => {
  const lists = sidebarLists(set({ mine: [row('a')], mine_total: 1 }), [row('t', { own: true })],
    changes({ created: ['t'], gone: ['t'] }));
  assert.equal(lists.mineTotal, 1);
});

test('the count never says fewer than the rows it has', () => {
  const lists = sidebarLists(set({ mine: [row('a'), row('b')], mine_total: 0 }), [], NO_CHANGES);
  assert.equal(lists.mineTotal, 2);
});

test('whether a view is a favorite: this tab, then the row, then the list', () => {
  const ws = set({ favorites: [row('f')], recent: [row('r', { favorite: false })] });
  assert.equal(isFavorite(ws, [], NO_CHANGES, 'f'), true);
  assert.equal(isFavorite(ws, [], NO_CHANGES, 'r'), false);
  assert.equal(isFavorite(ws, [row('r', { favorite: true })], NO_CHANGES, 'r'), true);
  assert.equal(isFavorite(ws, [], changes({ favored: { f: false } }), 'f'), false);
  assert.equal(isFavorite(ws, [], NO_CHANGES, 'unknown'), false);
});

test('settled drops a star once the server has it, and keeps one it has not', () => {
  const ws = set({ favorites: [row('a', { favorite: true })], recent: [row('b', { favorite: false })] });
  const after = settled(changes({ favored: { a: true, b: true }, opened: ['b'], gone: ['z'] }), ws);
  assert.deepEqual(after.favored, { b: true });
  assert.deepEqual(after.opened, ['b']);
  assert.deepEqual(after.gone, ['z']);
});

test('settled keeps an unstar until the server stops listing it', () => {
  const ws = set({ favorites: [row('a', { favorite: true })] });
  assert.deepEqual(settled(changes({ favored: { a: false } }), ws).favored, { a: false });
  assert.deepEqual(settled(changes({ favored: { a: false } }), set()).favored, {});
});

test('settled drops the order once the first rows agree', () => {
  const ws = set({ favorites: ['c', 'a'].map(id => row(id, { favorite: true })) });
  assert.equal(settled(changes({ favoriteOrder: ['c', 'a', 'b'] }), ws).favoriteOrder, null);
  assert.deepEqual(settled(changes({ favoriteOrder: ['a', 'c'] }), ws).favoriteOrder, ['a', 'c']);
});

test('the favorites order after starring and unstarring', () => {
  assert.deepEqual(favoriteOrderAfter(['a', 'b'], 'c', true), ['a', 'b', 'c']);
  assert.deepEqual(favoriteOrderAfter(['a', 'b', 'c'], 'a', true), ['b', 'c', 'a']);
  assert.deepEqual(favoriteOrderAfter(['a', 'b'], 'a', false), ['b']);
});

test('moving a row, and moves that go nowhere', () => {
  assert.deepEqual(moved(['a', 'b', 'c'], 0, 2), ['b', 'c', 'a']);
  assert.deepEqual(moved(['a', 'b', 'c'], 2, 0), ['c', 'a', 'b']);
  const same = ['a', 'b'];
  assert.equal(moved(same, 1, 1), same);
  assert.equal(moved(same, -1, 0), same);
  assert.equal(moved(same, 0, 2), same);
});

test('stars, orders and hides from Discover reach the sidebar; curation does not', () => {
  assert.equal(changesSidebar({ id: 'a', favorite: false }), true);
  assert.equal(changesSidebar({ order: [] }), true);
  assert.equal(changesSidebar({ id: 'a', hidden: true }), true);
  // What curateView announces: nothing the sidebar draws.
  const curation = { id: 'a', featured_position: null, certified: true };
  assert.equal(changesSidebar(curation), false);
  assert.equal(changesSidebar({}), false);
});

test('opened puts the view first, once', () => {
  assert.deepEqual(openedFirst(['a', 'b'], 'b'), ['b', 'a']);
  assert.deepEqual(openedFirst([], 'a'), ['a']);
});

test('with no link the view opened last opens, favorites included', () => {
  const ws = set({
    favorites: [row('f', { favorite: true })], recent: [row('f', { favorite: true }), row('r')], mine: [row('m')],
  });
  assert.equal(homeRow(ws, [], NO_CHANGES)?.id, 'f');
  assert.equal(homeRow(ws, [row('n')], changes({ opened: ['n'] }))?.id, 'n');
});

test('home skips a view deleted, taken out of Recent, or being deleted', () => {
  const ws = set({ recent: [row('a'), row('b'), row('c')], mine: [row('m', { updated_at: day(1) })] });
  assert.equal(homeRow(ws, [], changes({ gone: ['a'], closed: ['b'] }))?.id, 'c');
  assert.equal(homeRow(ws, [], NO_CHANGES, 'a')?.id, 'b');
});

test('with nothing opened yet, home is the newest own view, else nothing', () => {
  const ws = set({ mine: [row('old', { updated_at: day(1) }), row('new', { updated_at: day(3) })], mine_total: 2 });
  assert.equal(homeRow(ws, [], NO_CHANGES)?.id, 'new');
  assert.equal(homeRow(ws, [], NO_CHANGES, 'new')?.id, 'old');
  assert.equal(homeRow(set(), [], NO_CHANGES), null);
});

test('home counts a view made or saved here as your newest, as it is now', () => {
  const ws = set({ mine: [row('a', { updated_at: day(5) }), row('b', { updated_at: day(1), sharing: 'shared' })], mine_total: 2 });
  const home = homeRow(ws, [row('b', { name: 'Renamed', own: true, updated_at: day(8), sharing: undefined })], NO_CHANGES);
  assert.equal(home?.id, 'b');
  assert.equal(home?.name, 'Renamed');
  assert.equal(home?.sharing, 'shared', 'a row loaded here keeps what the server said about what it leaves out');
  assert.equal(homeRow(ws, [row('made', { own: true, updated_at: day(9) })], changes({ created: ['made'] }))?.id, 'made');
});

test('a row links to the app page, or the workspace for a standalone view', () => {
  assert.equal(hrefOf({ ref: 'ops-board', presentation: 'workspace' }), '#/app/ops-board');
  assert.equal(hrefOf({ ref: 'kiosk', presentation: 'standalone' }), '#/workspace/kiosk');
  assert.equal(hrefOf({ ref: 'a b/c' }), '#/app/a%20b%2Fc');
});

test('times without a zone are UTC, and nonsense is the start of time', () => {
  assert.equal(timeOf('2026-10-01T00:00:00'), Date.UTC(2026, 9, 1));
  assert.equal(timeOf('2026-10-01T00:00:00Z'), Date.UTC(2026, 9, 1));
  assert.equal(timeOf('2026-10-01T02:00:00+02:00'), Date.UTC(2026, 9, 1));
  assert.equal(timeOf(null), 0);
  assert.equal(timeOf('soon'), 0);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exitCode = 1;
