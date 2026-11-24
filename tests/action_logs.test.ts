// Admin Panel → Action Logs: the requests the tab sends (src/actionLogs.ts):
//
//   node --experimental-strip-types tests/action_logs.test.ts
//
// The module imports nothing, which is what lets Node load it straight from src/.
import assert from 'node:assert/strict';
import {
  DEFAULT_QUERY, dateRange, isFiltered, nextSort, pageInfo, rangeIsBackwards, readSavedQuery, searchUrl,
} from '../src/actionLogs.ts';

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

const paramsOf = (url: string) => new URLSearchParams(url.split('?')[1]);

test('an unfiltered first page asks for the newest rows and nothing else', () => {
  const url = searchUrl(DEFAULT_QUERY);
  assert.ok(url.startsWith('/api/actions/search?'));
  const qs = paramsOf(url);
  assert.deepEqual([...qs.keys()].sort(), ['dir', 'limit', 'offset', 'sort']);
  assert.equal(qs.get('sort'), 'timestamp');
  assert.equal(qs.get('dir'), 'desc');
  assert.equal(qs.get('limit'), '50');
  assert.equal(qs.get('offset'), '0');
});

test('every filter is sent under the server\'s name, and the search trimmed', () => {
  const qs = paramsOf(searchUrl({
    ...DEFAULT_QUERY, q: '  50% off ', widgetId: 'w1', actionName: 'approve', username: 'a@x.com',
    domain: 'Sales', sort: 'username', dir: 'asc', page: 3, pageSize: 25,
  }));
  assert.equal(qs.get('q'), '50% off');
  assert.equal(qs.get('widget_id'), 'w1');
  assert.equal(qs.get('action_name'), 'approve');
  assert.equal(qs.get('username'), 'a@x.com');
  assert.equal(qs.get('domain'), 'Sales');
  assert.equal(qs.get('offset'), '75');
  assert.equal(qs.get('limit'), '25');
});

test('the date range covers whole local days, the last one included', () => {
  const { since, until } = dateRange('2026-11-01', '2026-11-01');
  assert.equal(since, new Date(2026, 10, 1).toISOString());
  assert.equal(until, new Date(2026, 10, 2).toISOString());
  assert.deepEqual(dateRange('', ''), {});
  assert.deepEqual(dateRange('2026-02-30', 'soon'), {}, 'a day that does not exist is no bound');
  const open = dateRange('', '2026-12-31');
  assert.equal(open.since, undefined);
  assert.equal(open.until, new Date(2027, 0, 1).toISOString());
});

test('a range that ends before it starts is caught before it is sent', () => {
  assert.equal(rangeIsBackwards('2026-11-02', '2026-11-01'), true);
  assert.equal(rangeIsBackwards('2026-11-01', '2026-11-01'), false);
  assert.equal(rangeIsBackwards('', '2026-11-01'), false);
});

test('clicking a header flips its direction, and a new column starts where expected', () => {
  assert.deepEqual(nextSort({ sort: 'timestamp', dir: 'desc' }, 'timestamp'), { sort: 'timestamp', dir: 'asc' });
  assert.deepEqual(nextSort({ sort: 'timestamp', dir: 'desc' }, 'username'), { sort: 'username', dir: 'asc' });
  assert.deepEqual(nextSort({ sort: 'username', dir: 'asc' }, 'id'), { sort: 'id', dir: 'desc' });
});

test('page numbers and the paging buttons follow the total', () => {
  assert.deepEqual(pageInfo(120, 0, 50, 50), { first: 1, last: 50, pages: 3, hasPrev: false, hasNext: true });
  assert.deepEqual(pageInfo(120, 2, 50, 20), { first: 101, last: 120, pages: 3, hasPrev: true, hasNext: false });
  assert.deepEqual(pageInfo(0, 0, 50, 0), { first: 0, last: 0, pages: 1, hasPrev: false, hasNext: false });
});

test('only a search or a filter counts as filtered, not the sort or the page', () => {
  assert.equal(isFiltered(DEFAULT_QUERY), false);
  assert.equal(isFiltered({ ...DEFAULT_QUERY, sort: 'username', page: 4 }), false);
  assert.equal(isFiltered({ ...DEFAULT_QUERY, q: '   ' }), false);
  assert.equal(isFiltered({ ...DEFAULT_QUERY, from: '2026-11-01' }), true);
  assert.equal(isFiltered({ ...DEFAULT_QUERY, actionName: 'approve' }), true);
});

test('saved state comes back as it was left', () => {
  const left = { ...DEFAULT_QUERY, q: 'refund', domain: 'Sales', from: '2026-11-01', sort: 'domain' as const,
    dir: 'asc' as const, page: 2, pageSize: 100 };
  assert.deepEqual(readSavedQuery(JSON.stringify(left)), left);
});

test('saved state that is missing, broken or tampered with falls back field by field', () => {
  assert.deepEqual(readSavedQuery(null), DEFAULT_QUERY);
  assert.deepEqual(readSavedQuery('{not json'), DEFAULT_QUERY);
  assert.deepEqual(readSavedQuery('[]'), { ...DEFAULT_QUERY });
  const odd = readSavedQuery(JSON.stringify({
    q: 42, sort: 'dashboard_context', dir: 'sideways', page: -1, pageSize: 7, from: 'yesterday', username: 'me',
  }));
  assert.deepEqual(odd, { ...DEFAULT_QUERY, username: 'me' });
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
