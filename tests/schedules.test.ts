// The scheduling helpers (src/schedules.ts), standalone like every test here:
//
//   node --experimental-strip-types tests/schedules.test.ts
//
// Only the pure helpers: the requests need a server, and the dialog and page
// need a browser.
import assert from 'node:assert/strict';
import {
  bannerReason,
  connectUrl,
  createPayload,
  describeRecurrence,
  expiresIn,
  expiresWithin,
  formProblem,
  listJoin,
  looksLikeEmail,
  normalizeRecurrence,
  normalizeScheduleRequest,
  oauthErrorMessage,
  OAUTH_ERRORS,
  ordinal,
  parseRecipients,
  parseUtc,
  patchPayload,
  readOAuthOutcome,
  recurrenceProblem,
  relativeTime,
  returnPath,
  statusLabel,
  withFrequency,
  withoutOAuthOutcome,
  type ConnectionStatus,
  type Recurrence,
  type ScheduleForm,
} from '../src/schedules.ts';

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

const LA = 'America/Los_Angeles';
const r = (freq: Recurrence['freq'], days: number[] = [], time = '08:00', tz = LA): Recurrence => ({ freq, days, time, tz });

const NOW = Date.parse('2026-11-12T12:00:00Z');
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const iso = (ms: number) => new Date(ms).toISOString();

const connection = (patch: Partial<ConnectionStatus> = {}): ConnectionStatus => ({
  connected: true,
  connected_at: iso(NOW - 20 * DAY),
  expires_at: iso(NOW + 10 * DAY),
  needs_reconnect: false,
  reason: null,
  ...patch,
});

const form = (patch: Partial<ScheduleForm> = {}): ScheduleForm => ({
  name: 'Open orders',
  kind: 'email_report',
  recipients: ['me@example.com'],
  subject: 'Open orders',
  message: 'Hello',
  sendWhen: 'has_rows',
  attachCsv: true,
  recurrence: r('daily'),
  ...patch,
});

// ------------------------------------------------------------ recurrence

test('describes each frequency the way the contract examples read', () => {
  assert.equal(describeRecurrence(r('weekly', [1, 2, 3, 4, 5])), 'Every weekday at 08:00 (America/Los_Angeles)');
  assert.equal(describeRecurrence(r('hourly', [], '08:15')), 'Hourly at :15');
  assert.equal(describeRecurrence(r('monthly', [1, 15], '09:00')), 'Monthly on the 1st and 15th at 09:00 (America/Los_Angeles)');
  assert.equal(describeRecurrence(r('daily', [], '17:30', 'UTC')), 'Every day at 17:30 (UTC)');
});

test('weekly names its days in week order, and all seven read as every day', () => {
  assert.equal(describeRecurrence(r('weekly', [5, 1, 3])), 'Every Monday, Wednesday and Friday at 08:00 (America/Los_Angeles)');
  assert.equal(describeRecurrence(r('weekly', [7])), 'Every Sunday at 08:00 (America/Los_Angeles)');
  assert.equal(describeRecurrence(r('weekly', [1, 2, 3, 4, 5, 6, 7])), 'Every day at 08:00 (America/Los_Angeles)');
  assert.equal(describeRecurrence(r('weekly', [1, 1, 9, 0])), 'Every Monday at 08:00 (America/Los_Angeles)');
});

test('a recurrence with no day chosen says so instead of reading as never', () => {
  assert.match(describeRecurrence(r('weekly', [])), /no day chosen/);
  assert.match(describeRecurrence(r('monthly', [])), /no day chosen/);
});

test('ordinals, including the teens', () => {
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31].map(ordinal),
    ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '31st']);
});

test('lists join with commas and a final and', () => {
  assert.equal(listJoin([]), '');
  assert.equal(listJoin(['a']), 'a');
  assert.equal(listJoin(['a', 'b']), 'a and b');
  assert.equal(listJoin(['a', 'b', 'c']), 'a, b and c');
});

test('recurrence problems name what to fix', () => {
  assert.equal(recurrenceProblem(r('daily')), null);
  assert.equal(recurrenceProblem(r('weekly', [])), 'Choose at least one day of the week.');
  assert.equal(recurrenceProblem(r('monthly', [])), 'Choose at least one day of the month.');
  assert.equal(recurrenceProblem(r('daily', [], '8:00')), 'Choose a time.');
  assert.equal(recurrenceProblem(r('daily', [], '24:00')), 'Choose a time.');
  assert.equal(recurrenceProblem(r('daily', [], '08:00', '')), 'Choose a time zone.');
});

test('a widget\'s recurrence is cleaned, with the person\'s zone filling a missing or unknown one', () => {
  assert.deepEqual(normalizeRecurrence(undefined, LA), r('daily'));
  assert.deepEqual(normalizeRecurrence({ freq: 'weekly', days: [3, 1, 3], time: '9:05' }, LA), r('weekly', [1, 3], '09:05'));
  assert.deepEqual(normalizeRecurrence({ freq: 'weekly', days: [8] }, LA), r('weekly', [1]));
  assert.deepEqual(normalizeRecurrence({ freq: 'monthly', days: [31, 15] }, LA), r('monthly', [15, 31]));
  assert.deepEqual(normalizeRecurrence({ freq: 'daily', days: [1, 2], time: '25:00' }, LA), r('daily'));
  assert.deepEqual(normalizeRecurrence({ freq: 'yearly', tz: 'Mars/Olympus' }, LA), r('daily'));
  assert.equal(normalizeRecurrence({ tz: 'Europe/Berlin' }, LA).tz, 'Europe/Berlin');
});

test('changing frequency keeps the time and zone and restarts the days', () => {
  const weekly = r('weekly', [2, 4], '07:45');
  assert.deepEqual(withFrequency(weekly, 'monthly'), r('monthly', [1], '07:45'));
  assert.deepEqual(withFrequency(weekly, 'daily'), r('daily', [], '07:45'));
  assert.equal(withFrequency(weekly, 'weekly'), weekly);
});

// ------------------------------------------------------------ the request

test('recipients split on commas, semicolons and spaces, repeats once', () => {
  assert.deepEqual(parseRecipients('a@x.com, b@x.com;c@x.com  A@X.com'), ['a@x.com', 'b@x.com', 'c@x.com']);
  assert.deepEqual(parseRecipients(['a@x.com', ' ', 7, 'b@x.com']), ['a@x.com', 'b@x.com']);
  assert.deepEqual(parseRecipients(undefined), []);
  assert.equal(looksLikeEmail('a@x.com'), true);
  assert.equal(looksLikeEmail('team'), false);
});

test('a widget\'s request becomes what the dialog shows', () => {
  const n = normalizeScheduleRequest({
    name: '  West orders ', sql: ' SELECT 1 ', sendWhen: 'no_rows', attachCsv: true,
    recipients: 'a@x.com, b@x.com', recurrence: { freq: 'hourly', time: '00:30' },
  }, { tz: LA, executable: false });
  assert.equal(n.name, 'West orders');
  assert.equal(n.sql, 'SELECT 1');
  assert.equal(n.kind, 'email_report');
  assert.equal(n.statementRefused, false);
  assert.equal(n.sendWhen, 'no_rows');
  assert.equal(n.attachCsv, true);
  assert.deepEqual(n.recipients, ['a@x.com', 'b@x.com']);
  assert.deepEqual(n.recurrence, r('hourly', [], '00:30'));
});

test('a request that names nobody starts with the person themselves; defaults are safe', () => {
  const n = normalizeScheduleRequest({ sql: 'SELECT 1', sendWhen: 'sometimes', attachCsv: 'yes' }, { tz: LA, executable: true });
  assert.equal(n.recipients, null);
  assert.equal(n.sendWhen, 'always');
  assert.equal(n.attachCsv, false);
  assert.equal(n.kind, 'email_report');
  assert.deepEqual(normalizeScheduleRequest(null, { tz: LA, executable: false }).sql, '');
});

test('a statement run is offered only from an executable widget', () => {
  const asked = { sql: 'DELETE FROM t', kind: 'run_statement' };
  const fromExecutable = normalizeScheduleRequest(asked, { tz: LA, executable: true });
  assert.equal(fromExecutable.kind, 'run_statement');
  assert.equal(fromExecutable.statementRefused, false);
  const fromViewer = normalizeScheduleRequest(asked, { tz: LA, executable: false });
  assert.equal(fromViewer.kind, 'email_report');
  assert.equal(fromViewer.statementRefused, true);
});

test('the form says what stops it saving', () => {
  assert.equal(formProblem(form(), 'SELECT 1'), null);
  assert.equal(formProblem(form({ name: '  ' }), 'SELECT 1'), 'Give the schedule a name.');
  assert.match(formProblem(form(), '  ') || '', /no query/);
  assert.equal(formProblem(form({ recipients: [] }), 'SELECT 1'), 'Add at least one recipient.');
  assert.equal(formProblem(form({ kind: 'run_statement', recipients: [] }), 'SELECT 1'), null);
  assert.equal(formProblem(form({ recurrence: r('weekly', []) }), 'SELECT 1'), 'Choose at least one day of the week.');
});

test('create and patch bodies carry the contract\'s field names', () => {
  const source = {
    source_app_id: 'app-1', source_widget_instance: 'w-1', source_widget_id: 'orders',
    view_name: 'Ops – Orders', view_link: 'https://app.example.com/?v.region=West#/app/ops',
  };
  assert.deepEqual(createPayload(form({ name: ' Open orders ' }), 'SELECT 1', source), {
    name: 'Open orders', recipients: ['me@example.com'], subject: 'Open orders', message: 'Hello',
    send_when: 'has_rows', attach_csv: true, recurrence: r('daily'),
    kind: 'email_report', sql: 'SELECT 1', ...source,
  });
  const patch = patchPayload(form());
  assert.equal('sql' in patch || 'kind' in patch || 'owner' in patch || 'id' in patch, false);
});

test('a statement run sends no email fields', () => {
  assert.deepEqual(patchPayload(form({ kind: 'run_statement' })), {
    name: 'Open orders', recipients: [], subject: '', message: '', send_when: 'always', attach_csv: false,
    recurrence: r('daily'),
  });
});

// --------------------------------------------------------------- labels

test('status labels', () => {
  assert.equal(statusLabel({ status: 'active', paused_reason: null }), 'Active');
  assert.equal(statusLabel({ status: 'paused', paused_reason: 'owner' }), 'Paused');
  assert.equal(statusLabel({ status: 'paused', paused_reason: null }), 'Paused');
  assert.equal(statusLabel({ status: 'paused', paused_reason: 'failures' }), 'Paused after failures');
  assert.equal(statusLabel({ status: 'needs_reconnect', paused_reason: null }), 'Needs reconnect');
});

// ---------------------------------------------------------------- dates

test('timestamps without a zone are UTC', () => {
  assert.equal(parseUtc('2026-11-12T12:00:00')?.toISOString(), '2026-11-12T12:00:00.000Z');
  assert.equal(parseUtc('2026-11-12 12:00:00')?.toISOString(), '2026-11-12T12:00:00.000Z');
  assert.equal(parseUtc('2026-11-12T12:00:00+02:00')?.toISOString(), '2026-11-12T10:00:00.000Z');
  assert.equal(parseUtc('2026-11-12T12:00:00Z')?.toISOString(), '2026-11-12T12:00:00.000Z');
  assert.equal(parseUtc(null), null);
  assert.equal(parseUtc('soon'), null);
});

test('expiry counts down in days, then hours', () => {
  assert.equal(expiresIn(iso(NOW + 6 * DAY + 2 * HOUR), NOW), 'expires in 6 days');
  assert.equal(expiresIn(iso(NOW + 1 * DAY), NOW), 'expires in 1 day');
  assert.equal(expiresIn(iso(NOW + 5 * HOUR), NOW), 'expires in 5 hours');
  assert.equal(expiresIn(iso(NOW + 1 * HOUR), NOW), 'expires in 1 hour');
  assert.equal(expiresIn(iso(NOW + 10 * 60_000), NOW), 'expires in less than an hour');
  assert.equal(expiresIn(iso(NOW - 1), NOW), 'expired');
  assert.equal(expiresIn(null, NOW), null);
});

test('expires within a week, lapsed included', () => {
  assert.equal(expiresWithin(iso(NOW + 6 * DAY), 7, NOW), true);
  assert.equal(expiresWithin(iso(NOW + 8 * DAY), 7, NOW), false);
  assert.equal(expiresWithin(iso(NOW - DAY), 7, NOW), true);
  assert.equal(expiresWithin(null, 7, NOW), false);
});

test('relative times', () => {
  assert.equal(relativeTime(iso(NOW + 3 * HOUR), NOW), 'in 3 hours');
  assert.equal(relativeTime(iso(NOW - 5 * 60_000), NOW), '5 minutes ago');
  assert.equal(relativeTime(iso(NOW + 2 * DAY), NOW), 'in 2 days');
  assert.equal(relativeTime(iso(NOW + 10_000), NOW), 'just now');
  assert.equal(relativeTime(null, NOW), '');
});

// ---------------------------------------------------------- connecting

test('the return from a connect reads as connected, or as an error with a sentence', () => {
  assert.deepEqual(readOAuthOutcome('?oauth=connected'), { connected: true });
  assert.deepEqual(readOAuthOutcome('?v.region=West&oauth_error=identity_mismatch'), {
    connected: false, reason: 'identity_mismatch', message: OAUTH_ERRORS.identity_mismatch,
  });
  assert.equal(readOAuthOutcome('?v.region=West'), null);
  assert.equal(readOAuthOutcome('?oauth=maybe'), null);
  assert.equal(readOAuthOutcome(''), null);
});

test('every reason the vault sends has its own sentence, and identity mismatch names the problem', () => {
  const reasons = ['not_set_up', 'denied', 'idp_error', 'invalid_state', 'exchange_failed', 'identity_mismatch',
    'no_refresh_token', 'storage_failed', 'not_signed_in', 'invalid_id_token', 'no_id_token'];
  for (const reason of reasons) {
    assert.ok(OAUTH_ERRORS[reason], reason);
    assert.match(OAUTH_ERRORS[reason], /\.$/, reason);
  }
  assert.equal(new Set(reasons.map(oauthErrorMessage)).size, reasons.length);
  assert.match(oauthErrorMessage('identity_mismatch'), /you signed in to Databricks as a different user/i);
  assert.match(oauthErrorMessage('something_new'), /wasn’t connected/);
});

test('stripping the outcome keeps every other param exactly as written', () => {
  assert.equal(withoutOAuthOutcome('?oauth=connected'), '');
  assert.equal(withoutOAuthOutcome('?v.region=West%20Coast&oauth=connected&w.3f2a.q=a+b'), '?v.region=West%20Coast&w.3f2a.q=a+b');
  assert.equal(withoutOAuthOutcome('?oauth_error=denied&v.x=1'), '?v.x=1');
  assert.equal(withoutOAuthOutcome('?oauthy=1&oauth=connected'), '?oauthy=1');
  assert.equal(withoutOAuthOutcome(''), '');
});

test('return_to is a path on this app the vault accepts', () => {
  assert.equal(returnPath('/', '?v.region=West', '#/app/ops'), '/?v.region=West#/app/ops');
  assert.equal(returnPath('/', '?oauth_error=denied', '#/schedules'), '/#/schedules');
  assert.equal(returnPath('//evil.example', '', '#/x'), '/#/x');
  assert.equal(returnPath('/', '?q=a b\\c', '#/app/ops caf\u00e9'), '/?q=a%20b%5Cc#/app/ops%20caf%C3%A9');
  const long = `?v.q=${'x'.repeat(3000)}`;
  assert.equal(returnPath('/', long, '#/app/ops'), '/#/app/ops');
  for (const out of [returnPath('/', long, '#/a'), returnPath('/', '?q=\u0001', '#/a b')]) {
    assert.ok(out.startsWith('/') && !out.startsWith('//') && !out.includes('\\'), out);
    assert.ok([...out].every(ch => ch.charCodeAt(0) >= 0x21 && ch.charCodeAt(0) <= 0x7e), out);
  }
});

test('the connect url carries return_to encoded', () => {
  assert.equal(connectUrl('/?v.a=1#/schedules'), '/api/oauth/connect?return_to=%2F%3Fv.a%3D1%23%2Fschedules');
});

// --------------------------------------------------------------- banner

test('the banner shows for a reconnect or an expiry within a week, and only with schedules that should run', () => {
  const active = [{ status: 'active' as const }];
  assert.equal(bannerReason(connection({ expires_at: iso(NOW + 6 * DAY) }), active, NOW), 'expiring');
  assert.equal(bannerReason(connection({ expires_at: iso(NOW + 8 * DAY) }), active, NOW), null);
  assert.equal(bannerReason(connection({ connected: false, needs_reconnect: true, reason: 'expired' }), active, NOW), 'reconnect');
  assert.equal(bannerReason(null, [{ status: 'needs_reconnect' }], NOW), 'reconnect');
  assert.equal(bannerReason(connection({ expires_at: iso(NOW + DAY) }), [{ status: 'paused' }], NOW), null);
  assert.equal(bannerReason(connection({ needs_reconnect: true }), [], NOW), null);
  assert.equal(bannerReason(connection({ connected: false, expires_at: null }), active, NOW), null);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
