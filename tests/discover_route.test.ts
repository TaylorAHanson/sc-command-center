// Discover's search parameters and page address (src/discoverRoute.ts):
//
//   node --experimental-strip-types tests/discover_route.test.ts
//
// The module imports nothing, which is what lets Node load it straight from src/.
import assert from 'node:assert/strict';
import { discoverHref, parseDiscoverHref, searchQuery, shouldCountVisit } from '../src/discoverRoute.ts';

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

test('search query repeats list filters and leaves out unset ones', () => {
  const qs = new URLSearchParams(searchQuery({
    q: 'supply chain', scope: 'mine', sort: 'updated', domain: ['Ops', 'Finance'], owner: ['a@x.com'],
    certified: false, limit: 10, facets: true,
  }));
  assert.equal(qs.get('q'), 'supply chain');
  assert.deepEqual(qs.getAll('domain'), ['Ops', 'Finance']);
  assert.equal(qs.get('certified'), 'false');
  assert.equal(qs.get('facets'), '1');
  assert.equal(qs.has('standalone'), false);
  assert.equal(qs.has('cursor'), false);
  assert.equal(searchQuery({}), '');
});

test('a bare Discover address has no query', () => {
  assert.equal(discoverHref(), '#/discover');
  assert.equal(discoverHref({}), '#/discover');
});

test('the address round-trips what it carries', () => {
  const route = { q: 'regional revenue & margin', scope: 'favorites' as const, sort: 'favorites' as const, certified: true, opened: '90d' as const };
  const href = discoverHref(route);
  assert.ok(href.startsWith('#/discover?'));
  assert.deepEqual(parseDiscoverHref(href), route);
  assert.deepEqual(parseDiscoverHref(discoverHref({ rail: 'new_for_you' })), { rail: 'new_for_you' });
});

test('the address carries facet filters, deduplicated and bounded', () => {
  const route = { domain: ['Ops', 'Sales & Marketing'], owner: ['a@x.com'], standalone: true, status: 'published' as const };
  assert.deepEqual(parseDiscoverHref(discoverHref(route)), route);
  const many = Array.from({ length: 30 }, (_, i) => `d${i}`);
  assert.equal(parseDiscoverHref(discoverHref({ domain: many })).domain?.length, 20);
  assert.deepEqual(parseDiscoverHref('#/discover?domain=a&domain=a&domain=&standalone=maybe&status=x'), { domain: ['a'] });
});

test('unknown values in the address are dropped, not trusted', () => {
  assert.deepEqual(parseDiscoverHref('#/discover?scope=root&sort=random&rail=x&certified=yes&opened=1y'), {});
  assert.deepEqual(parseDiscoverHref('#/discover'), {});
  assert.equal(parseDiscoverHref(`#/discover?q=${'a'.repeat(500)}`).q?.length, 200);
});

test('a view is counted at most once an hour per tab', () => {
  const seen = new Map<string, number>();
  const hour = 60 * 60 * 1000;
  assert.equal(shouldCountVisit(seen, 'v1', 1_000), true);
  assert.equal(shouldCountVisit(seen, 'v1', 1_000 + hour - 1), false);
  assert.equal(shouldCountVisit(seen, 'v2', 1_000 + 5), true);
  assert.equal(shouldCountVisit(seen, 'v1', 1_000 + hour), true);
  assert.equal(shouldCountVisit(seen, '', 0), false);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
