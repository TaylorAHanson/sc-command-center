// The link-state codec (src/linkState.ts), standalone like every test here:
//
//   node --experimental-strip-types tests/link_state.test.ts
//
// Node 22.6 or newer runs TypeScript by stripping its types, so this needs no
// test runner and no dependency. The codec imports nothing, which is what lets
// Node load it straight from src/.
import assert from 'node:assert/strict';
import {
  MAX_LINK_STATE,
  createLinkStateStore,
  decodeValue,
  encodeValue,
  instanceScope,
  linkStatePart,
  readLinkState,
  writeLinkState,
  type LinkState,
} from '../src/linkState.ts';

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

const write = (state: Partial<LinkState>, search = '', options = {}) =>
  writeLinkState(search, { variables: {}, widgets: {}, ...state }, options);

const roundTrip = (state: LinkState, textKeys?: Set<string>) =>
  readLinkState(write(state, '', { textKeys }).search, textKeys);

test('round trip of every kind of value', () => {
  const state: LinkState = {
    variables: { region: 'West', year: 2025, all: '', none: null, tags: ['a', 'b'] },
    widgets: {
      '3f2a91c0': { sort: { column: 'revenue', desc: true }, page: 3, open: false },
      '9b1d0e77': { q: 'north & south = 100%', range: { from: '2026-01-01', to: '2026-03-31' } },
    },
  };
  assert.deepEqual(roundTrip(state), state);
});

test('a string that reads as JSON stays a string', () => {
  for (const text of ['2025', 'true', 'null', '{"a":1}', '[1]', ' 12', '"quoted"']) {
    const back = roundTrip({ variables: { k: text }, widgets: {} });
    assert.equal(back.variables.k, text, `"${text}" came back as ${JSON.stringify(back.variables.k)}`);
  }
});

test('plain strings are written as they are', () => {
  const { search } = write({ variables: { region: 'West', day: '2026-01-01', label: '{oops' } });
  assert.equal(search, '?v.day=2026-01-01&v.label=%7Boops&v.region=West');
  assert.equal(decodeValue('{oops'), '{oops');
});

test('non-string values are JSON', () => {
  assert.equal(encodeValue(3), '3');
  assert.equal(encodeValue(true), 'true');
  assert.equal(encodeValue(null), 'null');
  assert.equal(encodeValue(['x', 1]), '["x",1]');
  assert.equal(encodeValue({ b: 1, a: { d: 2, c: 3 } }), '{"a":{"c":3,"d":2},"b":1}');
  assert.equal(encodeValue({ a: 1, b: 2 }), encodeValue({ b: 2, a: 1 }));
  assert.equal(write({ variables: { n: 3 } }).search, '?v.n=3');
});

test('values a link cannot hold are left out', () => {
  assert.equal(encodeValue(undefined), undefined);
  assert.equal(encodeValue(() => 1), undefined);
  assert.equal(encodeValue(BigInt(1)), undefined);
  assert.equal(write({ variables: { gone: undefined, fn: () => 1, kept: 'x' } }).search, '?v.kept=x');
});

test('a variable at its default is left out', () => {
  const defaults = { region: 'West', year: '2025' };
  const textKeys = new Set(['region', 'year']);
  assert.equal(write({ variables: { region: 'West', year: '2025' } }, '', { defaults, textKeys }).search, '');
  assert.equal(write({ variables: { region: 'East', year: '2025' } }, '', { defaults, textKeys }).search, '?v.region=East');
});

test('All (an empty string) is a choice, not the default', () => {
  const { search } = write({ variables: { region: '' } }, '', { defaults: { region: 'West' } });
  assert.equal(search, '?v.region=');
  assert.equal(readLinkState(search).variables.region, '');
});

test('filter keys are plain text both ways', () => {
  const textKeys = new Set(['year']);
  const { search } = write({ variables: { year: '2025', count: '2025' } }, '', { textKeys });
  assert.equal(search, '?v.count=%222025%22&v.year=2025');
  const back = readLinkState(search, textKeys);
  assert.equal(back.variables.year, '2025');
  assert.equal(back.variables.count, '2025');
  assert.equal(readLinkState('?v.year=2025').variables.year, 2025);
});

test('the state is capped, dropping the largest first', () => {
  const big = 'x'.repeat(900);
  const state: LinkState = {
    variables: { region: 'West', huge: big, medium: 'm'.repeat(700) },
    widgets: { '3f2a91c0': { sort: 'revenue' } },
  };
  const { search, dropped } = write(state);
  assert.ok(linkStatePart(search).length <= MAX_LINK_STATE, `state is ${linkStatePart(search).length} long`);
  assert.deepEqual(dropped, ['v.huge']);
  const back = readLinkState(search);
  assert.equal(back.variables.region, 'West');
  assert.equal(back.variables.medium, 'm'.repeat(700));
  assert.equal(back.widgets['3f2a91c0'].sort, 'revenue');
});

test('the cap is deterministic whatever order the state was built in', () => {
  const values: Array<[string, string]> = Array.from({ length: 40 }, (_, i) => [`k${i}`, 'v'.repeat(30 + (i % 7))]);
  const forward = write({ variables: Object.fromEntries(values) }, '', { max: 400 });
  const backward = write({ variables: Object.fromEntries([...values].reverse()) }, '', { max: 400 });
  assert.equal(forward.search, backward.search);
  assert.deepEqual(forward.dropped, backward.dropped);
  assert.ok(linkStatePart(forward.search).length <= 400);
  assert.ok(forward.dropped.length > 0);
  // The longest go first (k13, k20, k27 and k34 are equal), ties broken by name.
  assert.deepEqual(forward.dropped.slice(0, 3), ['v.k13', 'v.k20', 'v.k27']);
});

test('a single value over the cap is dropped and the rest kept', () => {
  const { search, dropped } = write({ variables: { a: 'x' }, widgets: { abcdefgh: { list: 'z'.repeat(5000) } } });
  assert.deepEqual(dropped, ['w.abcdefgh.list']);
  assert.equal(search, '?v.a=x');
});

test('widget settings are scoped by the first 8 characters of the instance id', () => {
  assert.equal(instanceScope('3f2a91c0-1b2c-4d5e-8f90-0123456789ab'), '3f2a91c0');
  assert.equal(instanceScope('w1'), 'w1');
  assert.equal(instanceScope('a.b.c.d.e'), 'a-b-c-d-');
  const state: LinkState = {
    variables: {},
    widgets: {
      [instanceScope('3f2a91c0-1b2c-4d5e-8f90-0123456789ab')]: { sort: 'name' },
      [instanceScope('9b1d0e77-0000-4000-8000-000000000000')]: { sort: 'revenue' },
    },
  };
  const { search } = write(state);
  assert.equal(search, '?w.3f2a91c0.sort=name&w.9b1d0e77.sort=revenue');
  assert.deepEqual(readLinkState(search).widgets, state.widgets);
});

test('a widget key may contain dots; malformed widget params are ignored', () => {
  const back = readLinkState('?w.abcdefgh.chart.type=bar&w.nodot=1&w..x=1&w.abc.=1&w.=1');
  assert.deepEqual(back.widgets, { abcdefgh: { 'chart.type': 'bar' } });
});

test('unrelated params are kept exactly, and old state replaced', () => {
  const before = '?shared_view=abc&v.region=West&q=a%20b&w.3f2a91c0.sort=name&flag';
  const { search } = write({ variables: { region: 'East' } }, before);
  assert.equal(search, '?shared_view=abc&q=a%20b&flag&v.region=East');
  assert.equal(write({}, before).search, '?shared_view=abc&q=a%20b&flag');
  assert.equal(write({}, '?v.a=1').search, '');
  assert.equal(write({}, '').search, '');
});

test('linkStatePart is only the state, as written', () => {
  assert.equal(linkStatePart('?env=prod&v.region=West&w.abcdefgh.page=2&x=1'), 'v.region=West&w.abcdefgh.page=2');
  assert.equal(linkStatePart('?env=prod'), '');
  assert.equal(linkStatePart(''), '');
});

test('a link cannot reach a prototype', () => {
  const back = readLinkState('?v.__proto__=1&w.__proto__.x=1&w.constructor.polluted=yes&w.abcdefgh.__proto__=1&v.constructor=2');
  assert.equal(({} as Record<string, unknown>).polluted, undefined);
  assert.equal((Object as unknown as Record<string, unknown>).polluted, undefined);
  assert.deepEqual(Object.keys(back.variables), ['constructor']);
  assert.deepEqual(Object.keys(back.widgets), ['constructor']);
  assert.ok(Object.prototype.hasOwnProperty.call(back.widgets, 'constructor'));
  assert.equal(back.widgets.constructor.polluted, 'yes');
});

test('the store holds what differs from the default and says when it changes', () => {
  const store = createLinkStateStore({ abcdefgh: { sort: 'name' } });
  let calls = 0;
  const unsubscribe = store.subscribe(() => { calls += 1; });
  assert.equal(store.get('abcdefgh', 'sort'), 'name');
  assert.equal(store.get('abcdefgh', 'toString'), undefined);
  store.set('abcdefgh', 'sort', 'revenue', 'name');
  assert.equal(store.get('abcdefgh', 'sort'), 'revenue');
  store.set('abcdefgh', 'sort', 'revenue', 'name');
  assert.equal(calls, 1, 'setting the same value again notified');
  store.set('abcdefgh', 'sort', 'name', 'name');
  assert.equal(store.get('abcdefgh', 'sort'), undefined);
  assert.deepEqual(store.snapshot(), {});
  store.set('abcdefgh', 'range', { to: 2, from: 1 }, null);
  store.set('abcdefgh', 'range', { from: 1, to: 2 }, null);
  assert.equal(calls, 3);
  store.set('abcdefgh', 'range', undefined, null);
  assert.deepEqual(store.snapshot(), {});
  store.replace({ zzzzzzzz: { page: 2 } });
  assert.deepEqual(store.snapshot(), { zzzzzzzz: { page: 2 } });
  assert.equal(calls, 5);
  unsubscribe();
  store.replace({});
  assert.equal(calls, 5);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
