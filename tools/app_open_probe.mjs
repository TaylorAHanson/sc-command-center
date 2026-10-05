// What does opening an app cost in the browser?
//
// Runs the production build with every /api call answered from a synthetic,
// realistically sized deployment (a library with version history, a sidebar of
// views), so it needs no backend and no credentials. Reports what a user feels:
// first paint, when the widgets on screen are real rather than "Loading…", and
// how long the main thread is blocked. The longest single task is the number
// that matters: over a second is jank, several seconds is Chrome offering to
// kill the page.
//
//   npm run build && npx vite preview --port 4173 &
//   npm i --no-save playwright          # once; not a project dependency
//   node tools/app_open_probe.mjs
//
// Knobs (env): BASE, WIDGETS, VERSIONS, PER_TAB, TABS, VIEWS, CPU, CHROMIUM
// (path to a browser binary if Playwright's own isn't installed), SHOTS (dir).
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch {
  console.error('Playwright is not installed: run `npm i --no-save playwright` (or set NODE_PATH to a copy).');
  process.exit(1);
}

const BASE = process.env.BASE || 'http://localhost:4173/';
const WIDGETS = Number(process.env.WIDGETS || 30);
const VERSIONS = Number(process.env.VERSIONS || 8);
const PER_TAB = Number(process.env.PER_TAB || 6);
const TABS = Number(process.env.TABS || 5);
const VIEWS = Number(process.env.VIEWS || 60);
// A corporate laptop, not an M-series.
const CPU = Number(process.env.CPU || 4);
const SHOTS = process.env.SHOTS || '';
const ME = 'ana@example.com';

const widgetCode = (name, lines = 160) => `
import React, { useState, useEffect, useMemo } from 'react';
interface Row { label: string; value: number; }
export default function ${name}({ data }: { data?: Record<string, unknown> }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/sql/execute-raw', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: 'SELECT 1' }) })
      .then(r => r.json()).then(p => { if (!cancelled) { setRows(p.rows || []); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [data]);
${Array.from({ length: lines }, (_, i) => `  const v${i} = useMemo(() => rows.filter(r => r.value > ${i}).length, [rows]);`).join('\n')}
  if (loading) return <div className="p-4 text-gray-500">Fetching…</div>;
  return <div className="w-full h-full p-4 text-slate-800"><h3 className="font-semibold">${name}</h3>{rows.length}</div>;
}
`;

// The library as `/api/widgets/custom` sends it: every version's metadata, and
// source only on the latest.
const library = () => {
  const rows = [];
  for (let i = 0; i < WIDGETS; i++) {
    for (let v = VERSIONS; v >= 1; v--) {
      rows.push({
        id: `widget-${i}`, version: v, name: `Widget ${i}`, description: `Reports on subject ${i}`,
        category: ['Ops', 'Finance', 'Quality'][i % 3], domain: 'General', default_w: 4, default_h: 4,
        is_latest: v === VERSIONS, has_snapshot: true, tsx_code: v === VERSIONS ? widgetCode(`Widget${i}`) : null,
        configuration_mode: 'none', config_schema: '[]', data_source_type: 'sql', data_source: 'SELECT 1',
        help_text: null, open_in_new_tab_link: null, is_executable: 0, is_certified: i % 4 === 0, is_deprecated: 0,
        created_by: `person${i % 5}@example.com`, timestamp: '2026-08-01T00:00:00Z',
      });
    }
  }
  return rows;
};

const app = (id, tabs, presentation) => ({
  id, name: `Board ${id}`, domain: 'General', username: ME, is_global: false, is_shared: false, is_locked: false,
  pinned_agent_id: null, version: 3, timestamp: '2026-10-01T00:00:00Z',
  spec: {
    schema: 1, presentation, assistant: 'on', branding: null, nav: null, theme: null, filters: [],
    tabs: Array.from({ length: tabs }, (_, t) => ({
      id: t === 0 ? id : `${id}-t${t}`, name: t === 0 ? '' : `Tab ${t + 1}`, pinned_agent_id: null,
      widgets: Array.from({ length: PER_TAB }, (_, k) => {
        const n = (t * PER_TAB + k) % WIDGETS;
        return { i: `${id}-${t}-${k}`, type: `widget-${n}`, x: (k % 3) * 4, y: Math.floor(k / 3) * 4, w: 4, h: 4, props: {} };
      }),
    })),
  },
});

const fmt = ms => (ms == null ? 'never' : `${(ms / 1000).toFixed(2)}s`);

// Real widgets on screen and none still compiling or fetching.
const usableAt = () => {
  const items = document.querySelectorAll('.react-grid-item');
  const real = document.querySelectorAll('.react-grid-item h3').length;
  const waiting = document.querySelectorAll('.react-grid-item .animate-pulse').length;
  return items.length > 0 && real > 0 && waiting === 0 ? performance.now() : null;
};

async function waitUsable(page, since = 0) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const at = await page.evaluate(usableAt).catch(() => null);
    if (at !== null) return at - since;
    await page.waitForTimeout(100);
  }
  return null;
}

const longTasks = async (page, from = 0) => {
  const tasks = (await page.evaluate(() => window.__long)).filter(t => t.start >= from);
  return {
    count: tasks.length,
    worst: tasks.reduce((m, t) => Math.max(m, t.ms), 0),
    blocked: tasks.reduce((s, t) => s + Math.max(0, t.ms - 50), 0),
  };
};

async function scenario(browser, { label, tabs, presentation }) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
  await page.addInitScript(() => {
    window.__long = [];
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) window.__long.push({ start: e.startTime, ms: e.duration });
    }).observe({ entryTypes: ['longtask'] });
  });

  const target = app('target', tabs, presentation);
  const others = Array.from({ length: VIEWS - 1 }, (_, n) => app(`v${n}`, 1, 'workspace'));
  const libraryBody = JSON.stringify({ widgets: library() });
  const placed = new Set(target.spec.tabs.flatMap(t => t.widgets.map(w => w.type)));
  const appWidgetsBody = JSON.stringify({ widgets: library().filter(r => placed.has(r.id)) });
  const bytes = { total: 0 };
  page.on('response', async r => {
    if (!r.url().includes('/api/')) return;
    try { bytes.total += (await r.body()).length; } catch { /* aborted */ }
  });

  // Registered first = matched last: specific routes below override this.
  await page.route('**/api/**', r => r.fulfill({ json: {} }));
  await page.route('**/api/health', r => r.fulfill({ json: { environment: 'dev', brand: 'brand' } }));
  await page.route('**/api/roles/my-permissions', r => r.fulfill({ json: { username: ME, is_admin: false, domain_permissions: { General: 'editor' } } }));
  await page.route('**/api/roles/my-domains', r => r.fulfill({ json: { domains: ['General'] } }));
  await page.route('**/api/taxonomy/**', r => r.fulfill({ json: { categories: ['Ops', 'Finance', 'Quality'], domains: ['General'] } }));
  await page.route('**/api/apps/', r => r.fulfill({ json: { apps: [target, ...others] } }));
  await page.route('**/api/apps/target', r => r.fulfill({ json: { app: target } }));
  await page.route('**/api/apps/target/widgets', r => r.fulfill({ contentType: 'application/json', body: appWidgetsBody }));
  await page.route('**/api/widgets/custom', r => r.fulfill({ contentType: 'application/json', body: libraryBody }));
  await page.route('**/api/sql/**', r => r.fulfill({ json: { rows: [{ label: 'a', value: 3 }] } }));

  const started = Date.now();
  await page.goto(`${BASE}#/app/target`, { waitUntil: 'commit' });
  const usable = await waitUsable(page);
  const paint = await page.evaluate(() => performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null);
  const open = await longTasks(page);
  const wall = Date.now() - started;
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/open-${label.replace(/\W+/g, '-')}.png` });

  let switching = null;
  if (tabs > 1) {
    const before = await page.evaluate(() => performance.now());
    await page.getByRole('navigation', { name: 'Tabs' }).getByText('Tab 2', { exact: true }).click();
    await page.waitForFunction(() => location.hash.endsWith('-t1'));
    const ready = await waitUsable(page, before);
    switching = { ready, ...(await longTasks(page, before)) };
  }
  await page.close();
  return { label, tabs, paint, usable, wall, kb: bytes.total / 1024, open, switching };
}

const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
const runs = [
  { label: 'workspace, one tab', tabs: 1, presentation: 'workspace' },
  { label: `workspace, ${TABS} tabs`, tabs: TABS, presentation: 'workspace' },
  { label: 'on its own, one tab', tabs: 1, presentation: 'standalone' },
  { label: `on its own, ${TABS} tabs`, tabs: TABS, presentation: 'standalone' },
];
console.log(`\n  ${WIDGETS} widgets × ${VERSIONS} versions, ${VIEWS} views in the sidebar, ${PER_TAB} widgets a tab, CPU ×${CPU}\n`);
console.log(`  ${'app'.padEnd(24)}${'API KB'.padStart(8)}${'paint'.padStart(8)}${'usable'.padStart(8)}${'longest'.padStart(9)}${'blocked'.padStart(9)}   switch tab: usable / longest`);
for (const run of runs) {
  const r = await scenario(browser, run);
  const sw = r.switching ? `${fmt(r.switching.ready)} / ${fmt(r.switching.worst)}` : '—';
  console.log(`  ${r.label.padEnd(24)}${r.kb.toFixed(0).padStart(8)}${fmt(r.paint).padStart(8)}${fmt(r.usable).padStart(8)}${fmt(r.open.worst).padStart(9)}${fmt(r.open.blocked).padStart(9)}   ${sw}`);
}
console.log('');
await browser.close();
