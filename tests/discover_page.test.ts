// The Discover page's own logic (src/discoverPage.ts):
//
//   node --experimental-strip-types tests/discover_page.test.ts
//
// The module imports only types, which is what lets Node load it straight from src/.
import assert from 'node:assert/strict';
import {
  addPick, applyToRails, applyToRows, clearFilters, countText, effectiveScope, effectiveSort, emptyMessage, facetOptions,
  GOVERNANCE_ROUTE, isGovernance, MAX_COMBINED, mergePages, modeNote, movePick, nextFeaturedPosition, normalizeRoute,
  pageMode, RAIL_ORDER, resultsTitle, searchParamsOf, seeAllRoute, showsUnpublished, sortsFor, scopesFor, toggled,
  unpublishedOf, withChanges, withQuery,
} from '../src/discoverPage.ts';
import { discoverHref, parseDiscoverHref } from '../src/discoverRoute.ts';
import type { Rails, ViewRow } from '../src/discover.ts';

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

const row = (id: string, extra: Partial<ViewRow> = {}): ViewRow => ({
  id, link: `#/app/${id}`, ref: id, name: id, description: '', owner: 'a@x.com', domain: null, presentation: 'workspace',
  updated_at: null, published_at: null, viewers_30d: 0, trend: 0, favorites: 0, featured: false, featured_position: null,
  certified: false, access: 'USE', favorite: false, hidden: false, last_opened_at: null, ...extra,
});

const rails = (over: Partial<Rails> = {}): Rails => ({
  featured: [], certified: [], popular: [], trending: [], updated: [], new_for_you: [], ...over,
});

// The links the sidebar hands out, read as the page reads its address.
const opened = (href: string) => normalizeRoute(parseDiscoverHref(href));

test('every sidebar link lands on a sensible state', () => {
  assert.equal(pageMode(opened(discoverHref())), 'home');

  const search = opened(discoverHref({ q: 'revenue' }));
  assert.equal(pageMode(search), 'results');
  assert.deepEqual(searchParamsOf(search, false), { scope: 'all', sort: 'relevance', limit: 24, q: 'revenue' });

  const favorites = opened(discoverHref({ scope: 'favorites', sort: 'favorites' }));
  assert.equal(pageMode(favorites), 'results');
  assert.equal(resultsTitle(favorites), 'Your favorites');
  assert.deepEqual(searchParamsOf(favorites, false), { scope: 'favorites', sort: 'favorites', limit: 24 });

  const mine = opened(discoverHref({ scope: 'mine', sort: 'updated' }));
  assert.equal(resultsTitle(mine), 'Your views');
  assert.deepEqual(searchParamsOf(mine, false), { scope: 'mine', sort: 'updated', limit: 24 });

  const fresh = opened(discoverHref({ rail: 'new_for_you' }));
  assert.equal(pageMode(fresh), 'rail');
  assert.deepEqual(fresh, { rail: 'new_for_you' });
});

test('each rail’s See all opens its sort or filter, or the rail alone', () => {
  assert.deepEqual(seeAllRoute('popular'), { sort: 'popular' });
  assert.deepEqual(seeAllRoute('trending'), { sort: 'trending' });
  assert.deepEqual(seeAllRoute('updated'), { sort: 'updated' });
  assert.deepEqual(seeAllRoute('certified'), { certified: true });
  assert.deepEqual(seeAllRoute('featured'), { rail: 'featured' });
  assert.deepEqual(seeAllRoute('new_for_you'), { rail: 'new_for_you' });
  for (const rail of RAIL_ORDER) {
    const route = opened(discoverHref(seeAllRoute(rail)));
    assert.notEqual(pageMode(route), 'home', `${rail} See all stayed on the rails`);
  }
  // Certified's See all keeps the rail's own order.
  assert.equal(searchParamsOf(seeAllRoute('certified'), false).sort, 'popular');
});

test('an address naming a searchable rail opens that search', () => {
  assert.deepEqual(normalizeRoute({ rail: 'popular', scope: 'mine' }), { scope: 'mine', sort: 'popular' });
  assert.deepEqual(normalizeRoute({ rail: 'certified' }), { certified: true });
  assert.deepEqual(normalizeRoute({ rail: 'featured', q: 'x', sort: 'name' }), { rail: 'featured' });
  const plain = { q: 'x' };
  assert.equal(normalizeRoute(plain), plain);
});

test('relevance needs a query; without one the sort is popular', () => {
  assert.equal(effectiveSort({}), 'popular');
  assert.equal(effectiveSort({ sort: 'relevance' }), 'popular');
  assert.equal(effectiveSort({ q: 'a' }), 'relevance');
  assert.equal(effectiveSort({ q: '  ' }), 'popular');
  assert.equal(effectiveSort({ q: 'a', sort: 'name' }), 'name');
  assert.deepEqual(sortsFor(false).includes('relevance'), false);
  assert.equal(sortsFor(true)[0], 'relevance');
});

test('everything is for administrators; a link carrying it searches what you can open', () => {
  assert.equal(effectiveScope({ scope: 'everything' }, false), 'all');
  assert.equal(effectiveScope({ scope: 'everything' }, true), 'everything');
  assert.equal(scopesFor(false).includes('everything'), false);
  assert.equal(scopesFor(true).at(-1), 'everything');
  assert.equal(searchParamsOf(GOVERNANCE_ROUTE, false).scope, 'all');
});

test('filters become search parameters, and back through the address', () => {
  const route = {
    q: ' late shipments ', scope: 'shared' as const, sort: 'trending' as const, domain: ['Ops', 'Finance'],
    owner: ['b@x.com'], certified: true, standalone: false, status: 'draft' as const, opened: 'never' as const,
  };
  assert.deepEqual(searchParamsOf(route, false), {
    scope: 'shared', sort: 'trending', limit: 24, q: 'late shipments', domain: ['Ops', 'Finance'], owner: ['b@x.com'],
    certified: true, standalone: false, status: 'draft', opened: 'never',
  });
  assert.deepEqual(parseDiscoverHref(discoverHref(route)), { ...route });
  assert.equal(pageMode({ domain: ['Ops'] }), 'results');
  assert.equal(pageMode({ scope: 'all' }), 'home');
});

test('a change drops empty values, defaults and a rail shown alone', () => {
  assert.deepEqual(withChanges({ rail: 'new_for_you' }, { scope: 'mine' }), { scope: 'mine' });
  assert.deepEqual(withChanges({ scope: 'mine', domain: ['Ops'] }, { scope: 'all', domain: [] }), {});
  assert.deepEqual(withChanges({ q: 'a', sort: 'relevance' }, { q: '' }), {});
  assert.deepEqual(withChanges({ q: 'a', sort: 'name' }, { q: '' }), { sort: 'name' });
  assert.deepEqual(withChanges({ q: 'a', sort: 'name' }, { sort: 'relevance' }), { q: 'a' });
  assert.deepEqual(withChanges({}, { rail: 'featured' }), { rail: 'featured' });
  assert.deepEqual(withQuery({ scope: 'mine', certified: true, rail: 'featured' }, '  sales  '), { scope: 'mine', certified: true, q: 'sales' });
  assert.deepEqual(clearFilters({ q: 'a', sort: 'name', domain: ['x'], owner: ['y'], certified: false, opened: '90d', status: 'published', standalone: true }), { q: 'a', sort: 'name' });
  assert.deepEqual(toggled(undefined, 'a'), ['a']);
  assert.deepEqual(toggled(['a', 'b'], 'a'), ['b']);
});

test('the governance filter is every view, none opened in 90 days', () => {
  assert.equal(isGovernance(GOVERNANCE_ROUTE), true);
  assert.equal(isGovernance({ opened: '90d' }), false);
  assert.deepEqual(searchParamsOf(GOVERNANCE_ROUTE, true), { scope: 'everything', sort: 'name', limit: 24, opened: '90d' });
  assert.equal(resultsTitle(GOVERNANCE_ROUTE), 'Not opened in 90 days');
  assert.equal(emptyMessage(GOVERNANCE_ROUTE).title, 'Every view has been opened in the last 90 days');
});

test('facets leave out blanks and keep a ticked value that fell out of the counts', () => {
  const options = facetOptions(
    [{ value: '', count: 9 }, { value: 'a@x.com', label: 'A@x.com', count: 4 }, { value: 'b@x.com', count: 2 }],
    ['b@x.com', 'c@x.com'],
  );
  assert.deepEqual(options, [
    { value: 'a@x.com', label: 'A@x.com', count: 4, selected: false },
    { value: 'b@x.com', label: 'b@x.com', count: 2, selected: true },
    { value: 'c@x.com', label: 'c@x.com', count: null, selected: true },
  ]);
  assert.deepEqual(facetOptions(undefined, undefined), []);
});

test('pages merge without repeating a view', () => {
  const first = [row('a'), row('b')];
  const merged = mergePages(first, [row('b', { name: 'newer' }), row('c'), row('c')]);
  assert.deepEqual(merged.map(r => r.id), ['a', 'b', 'c']);
  assert.equal(merged[1].name, 'b');
  assert.deepEqual(first.map(r => r.id), ['a', 'b']);
});

test('a change patches only its own row, and leaves a list alone when absent', () => {
  const rows = [row('a'), row('b')];
  const starred = applyToRows(rows, { id: 'b', favorite: true });
  assert.equal(starred[1].favorite, true);
  assert.equal(starred[0], rows[0]);
  assert.equal(applyToRows(rows, { id: 'z', hidden: true }), rows);
  const curated = applyToRows(rows, { id: 'a', featured_position: 3, certified: true });
  assert.deepEqual([curated[0].featured, curated[0].featured_position, curated[0].certified], [true, 3, true]);
  // The page's own optimistic star, then the client's event with the same value: nothing new to draw.
  assert.equal(applyToRows(starred, { id: 'b', favorite: true }), starred);
});

test('a change sets only the fields it carries; a new favorites order changes no row', () => {
  const rows = [row('a', { favorite: true, featured: true, featured_position: 2, certified: true })];
  const certifiedOnly = applyToRows(rows, { id: 'a', certified: false });
  assert.deepEqual(
    [certifiedOnly[0].certified, certifiedOnly[0].featured_position, certifiedOnly[0].featured, certifiedOnly[0].favorite],
    [false, 2, true, true],
  );
  assert.equal(applyToRows(rows, { order: ['a'] }), rows);
  const start = rails({ popular: rows, featured: rows });
  assert.equal(applyToRails(start, { order: ['a'] }), start);
  assert.equal(applyToRails(start, { id: 'a', favorite: true }), start);
});

test('hiding takes a view off every rail; curation moves it in and out', () => {
  const start = rails({ popular: [row('a'), row('b')], updated: [row('a')], featured: [row('f', { featured: true, featured_position: 0 })] });
  const hidden = applyToRails(start, { id: 'a', hidden: true });
  assert.deepEqual(hidden.popular.map(r => r.id), ['b']);
  assert.deepEqual(hidden.updated, []);

  const featured = applyToRails(start, { id: 'b', featured_position: 1, certified: true });
  assert.deepEqual(featured.featured.map(r => r.id), ['f', 'b']);
  assert.deepEqual(featured.certified.map(r => r.id), ['b']);
  assert.equal(featured.popular[1].certified, true);

  const off = applyToRails(featured, { id: 'b', featured_position: null, certified: false });
  assert.deepEqual(off.featured.map(r => r.id), ['f']);
  assert.deepEqual(off.certified, []);

  // Certifying alone leaves Featured as it was.
  const certifiedOnly = applyToRails(featured, { id: 'b', certified: false });
  assert.deepEqual(certifiedOnly.featured.map(r => r.id), ['f', 'b']);
  assert.deepEqual(certifiedOnly.certified, []);

  // A view on no rail yet joins Featured from the card it was featured on, in position order.
  const later = rails({ featured: [row('f', { featured: true, featured_position: 2 })] });
  const outside = applyToRails(later, { id: 'n', featured_position: 1, certified: false }, row('n'));
  assert.deepEqual(outside.featured.map(r => r.id), ['n', 'f']);
  assert.deepEqual(outside.certified, []);
  // Without the card (the event alone), it waits for the next fetch.
  assert.equal(applyToRails(later, { id: 'n', featured_position: 1, certified: false }), later);
  // The event first, then the page's own patch with the card: one copy, in order.
  const twice = applyToRails(outside, { id: 'n', featured_position: 1, certified: false }, row('n'));
  assert.deepEqual(twice.featured.map(r => r.id), ['n', 'f']);
  const hiddenRow = applyToRails(start, { id: 'h', featured_position: 5, certified: true }, row('h', { hidden: true }));
  assert.deepEqual(hiddenRow.featured.map(r => r.id), ['f']);
  assert.deepEqual(hiddenRow.certified, []);
});

test('a newly featured view goes last, within the server’s range', () => {
  assert.equal(nextFeaturedPosition([]), 0);
  assert.equal(nextFeaturedPosition([row('a', { featured_position: 4 }), row('b', { featured_position: 1 })]), 5);
  assert.equal(nextFeaturedPosition([row('a', { featured_position: 10_000 })]), 10_000);
});

test('the mode note says how a search was answered, and only when it matters', () => {
  assert.equal(modeNote(undefined, 'basic', 'basic', 'popular'), null);
  assert.equal(modeNote('a', 'hybrid', 'hybrid', 'relevance'), null);

  const local = modeNote('a', 'basic', 'basic', 'relevance');
  assert.equal(local?.label, 'Showing word matches');
  assert.equal(local?.setup, true);

  const slow = modeNote('a', 'keyword', 'hybrid', 'relevance');
  assert.equal(slow?.label, 'Showing keyword matches');
  assert.equal(slow?.setup, false);
  assert.match(slow?.detail ?? '', /too long/);

  const sorted = modeNote('a', 'basic', 'hybrid', 'name');
  assert.match(sorted?.detail ?? '', /Sort by relevance to match by meaning too/);

  assert.equal(modeNote('a', 'keyword', null, 'relevance')?.setup, false);
});

test('counts and empty states read naturally', () => {
  assert.equal(countText(1, false), '1 view');
  assert.equal(countText(12, false), '12 views');
  assert.equal(countText(500, true), 'Top 500 matches');
  assert.match(emptyMessage({ q: 'zz' }).title, /No views match “zz”/);
  assert.match(emptyMessage({ q: 'zz', scope: 'mine' }).hint, /clear the filters/);
  assert.equal(emptyMessage({ scope: 'favorites' }).title, 'No favorites yet');
  assert.equal(emptyMessage({ domain: ['Ops'] }).title, 'No views match these filters');
});

test('Mine lists never-published views above its results, unless a search or filter is set', () => {
  // The sidebar's My views See all link.
  assert.equal(showsUnpublished(opened(discoverHref({ scope: 'mine', sort: 'updated' }))), true);
  assert.equal(showsUnpublished({ scope: 'mine', status: 'draft' }), true);
  assert.equal(showsUnpublished({ scope: 'mine', status: 'published' }), false);
  assert.equal(showsUnpublished({ scope: 'mine', q: 'revenue' }), false);
  assert.equal(showsUnpublished({ scope: 'mine', domain: ['Ops'] }), false);
  assert.equal(showsUnpublished({ scope: 'mine', status: 'draft', certified: true }), false);
  assert.equal(showsUnpublished({ scope: 'shared' }), false);
  assert.equal(showsUnpublished({}), false);

  const mine = [row('p', { state: 'published' }), row('d', { state: 'draft_only' }), row('w', { state: 'published_with_draft' }), row('n')];
  assert.deepEqual(unpublishedOf(mine).map(r => r.id), ['d']);

  assert.equal(emptyMessage({ scope: 'mine' }, 2).title, 'None of your views is published yet');
  assert.match(emptyMessage({ scope: 'mine', status: 'draft' }, 2).title, /unpublished changes/);
  assert.equal(emptyMessage({ scope: 'mine' }, 0).title, 'You haven’t published a view yet');
  assert.equal(emptyMessage({ scope: 'mine', q: 'zz' }, 2).title, 'No views match “zz”');
});

test('combine views takes each view once, up to the tab limit, in the order arranged', () => {
  const a = row('a');
  const b = row('b');
  const c = row('c');
  let picked = addPick(addPick(addPick([], a), b), a);
  assert.deepEqual(picked.map(r => r.id), ['a', 'b']);
  picked = addPick(picked, c);
  assert.deepEqual(movePick(picked, 'c', -1).map(r => r.id), ['a', 'c', 'b']);
  assert.deepEqual(movePick(picked, 'a', -1).map(r => r.id), ['a', 'b', 'c']);
  assert.deepEqual(movePick(picked, 'c', 1).map(r => r.id), ['a', 'b', 'c']);
  assert.equal(movePick(picked, 'zz', 1), picked);

  const full = Array.from({ length: MAX_COMBINED }, (_, i) => row(`v${i}`));
  assert.equal(addPick(full, row('extra')), full);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
