# ADR-001 — Apps as the top-level artifact (Views become Tabs)

| Field | Value |
| --- | --- |
| Status | Proposed |
| Date | 2026-10-05 |
| Branch | `feature/apps-as-top-level-artifact` |
| Scope | Application only: data model, API, shell, builder, promotion |
| Out of scope | Signals/pipelines/new intelligence; presets/"modes"; a spec-authoring agent; iframe isolation for widgets; a responsive grid; public/anonymous links; iframe embedding in other sites |

This document is the working ADR and implementation spec for folding today's
**views** into **apps**. The brief that seeded it is advisory; open questions and
verify-before-building items are called out explicitly so implementation can
challenge them.

---

## 1. Context

Command Center is a configurable single-canvas dashboard. Users compose a canvas
from widgets (Widget Studio), agents (Agent Studio), and data (OBO / Unity
Catalog). The canvas is stored as a **view** (`dashboard_views`).

We want users to compose a multi-tab, designed experience — an **app** — from
those same building blocks. Examples: an executive-facing multi-tab experience,
a team hub, or a simple one-canvas dashboard that behaves exactly as a view does
today.

Separately, an app must be **linkable** and able to render **without Command
Center chrome**, so a shared link feels like its own product while Command
Center remains the authoring and management surface.

### 1.1 Design stance

**One concept, not two.** A view is just a simple app. The model becomes
**App → Tabs**, where each tab is what we call a view today. An app with one tab
must look and behave exactly like a view does today. Do not build a parallel
"apps" system next to views; fold views into apps.

### 1.2 Facts about the current code (verified at brief time)

- A view is a row in `dashboard_views`, PK `(id, version)`, with
  `name, domain, username, is_global, widgets_json, is_locked, pinned_agent_id`.
  Every save (`PUT /api/views/{id}`, `server/routes/views.py::update_view`)
  **inserts a new version row**, and the client PUTs on every drag/resize
  (`dashboardStore.apiSyncView`).
- The store already calls views "tabs" (`src/store/dashboardStore.tsx`: `Tab`,
  `tabs`, `activeTabId`). The sidebar lists them (`Layout.tsx`).
- `DashboardGrid` in `src/App.tsx` is hard-wired to `activeTabId`. It also has
  an orphan-cleanup effect meant to **write to the view** when a widget no longer
  exists. *Found in slice 2:* it never does — it calls `updateLayout`, which saves
  only a move or resize — and orphans are merely hidden by the grid's filter.
- Grid is a single 12-col `react-grid-layout` layout (`breakpoints={{ lg: 0 }}`).
- `variables` (emitter/receiver state) is one provider-wide map, never reset on
  view change.
- Routing is hash-based in `Layout.tsx`: `#/view/<id>`, `#/template/<id>`. The
  `hashchange` handler omits `#/agent-studio`, `#/user-guide`, `#/release-notes`
  (existing bug; fixed in slice 3).
- Version numbers are **per environment** (`promotion.py`: Dev v5 and Test v5
  are unrelated rows). Never reference a version number across envs.
- Widgets and global views are domain-filtered server-side today
  (`custom_widgets.py::_visible`, `views.py::get_views`).
- Opening `?shared_view=` calls `POST /api/views/shared/{id}`, which only
  checks the row exists and then **subscribes the caller**. Anyone holding a
  view id can read any view, including personal ones.
- `Layout.tsx` always renders the sidebar, header, floating agent launcher,
  `WidgetTray`, `w` shortcut, and studio/admin entry points. Shell decision must
  be made before first paint (Layout reads hash synchronously in `useState`) or
  users see a sidebar flash.
- `DashboardProvider` eagerly calls `fetchPermissions()` and `fetchViews()` on
  mount; the app also loads the full widget library. Layout prefetches studio /
  admin chunks at idle — none of that is wanted in a standalone context.
- CSP already has `frame-ancestors 'self'` (`server/main.py`); iframe embedding
  elsewhere stays out of scope. `img-src` already allows logos from data URLs or
  https.

### 1.3 Blast radius (files that touch views today)

| Area | Files |
| --- | --- |
| Backend | `routes/views.py`, `routes/promotion.py` (`transfer_view`), `database.py`, `services/data_migration.py`, `services/creator_stats.py` |
| Tests | `tests/test_view_archive.py`, `tests/test_view_pins.py` (+ any new apps tests) |
| Frontend | `dashboardStore.tsx`, `Layout.tsx`, `App.tsx`, `pages/admin/ViewManager.tsx`, `AdminPage.tsx`, `AgentPanel.tsx`, `useAgentChat.ts`, `useDashboardContext.ts`, `useActionLogger.ts`, `WidgetTray.tsx`, `WidgetStudio.tsx`, `WidgetPromotionPanel.tsx`, `ThumbnailCapture.tsx` |

`data_migration.py` table specs must stay current; a test fails if a table isn't
listed.

---

## 2. Decision

### 2.1 Target model

```json
App {
  "id": "...", "version": 1, "name": "...", "domain": "...", "username": "...",
  "is_global": false, "is_locked": false,
  "spec": {
    "schema": 1,
    "presentation": "workspace" | "standalone",
    "assistant": "on" | "off",
    "branding": {
      "title": "...",
      "logo": "data-url-or-https",
      "favicon": "..."
    },
    "tabs": [
      {
        "id": "...",
        "name": "...",
        "layout": "canvas" | "page",
        "widgets": ["WidgetLayout"],
        "pinned_agent_id": null
      }
    ],
    "default_agent_id": null,
    "nav": null,
    "theme": null,
    "filters": []
  }
}
```

- **As built (slice 1):** the app-level agent stays in the existing
  `pinned_agent_id` column, exposed as `pinned_agent_id` on the app, rather than
  moving into `spec.default_agent_id`. One place to store it, `pin_value`
  semantics unchanged, and the legacy API keeps working. Tabs carry their own
  `pinned_agent_id` in the spec; resolution is tab → app → built-in default.
  Name, domain, owner, global and lock likewise stay columns.
- **As built:** a missing `presentation` reads as `workspace`. "New apps default
  to standalone" is a client default for the *New app* flow (slice 4), not a
  storage default, so that no row can lose the sidebar by omission.
- Rename the store's current `Tab` to `App` and introduce `AppTab`. Do not leave
  two meanings of "tab" in the code.
- Tabs live **inside** the app (embedded in `spec`), not as separate rows
  referenced by id. One versioned artifact, promoted atomically.
- The only promotion dependencies left are widgets and pinned agents.
- Optional later fields (`nav`, `theme`, `filters`) are reserved; do not block
  early slices on them. (Slice 7 gave them meaning; see §4.3f.)

### 2.2 Storage and compatibility (evolve in place)

Recommended path — challenge if a cleaner cutover appears during slice 1:

- Keep table `dashboard_views` for now. Add `spec_json TEXT` via
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (idempotent DDL, advisory-lock
  block in `database.py`).
- A row with no `spec_json` is read as a one-tab app
  (`tab.id = app.id`, widgets from `widgets_json`). No data move.
- Writes always write `spec_json`; optionally dual-write `widgets_json`
  (= first tab) for a couple of releases for rollback safety.
- **Preserve ids.** App id = old view id, so `shared_views`, `archived_views`,
  `?shared_view=` links, `#/view/<id>`, `?widget=<id>` deep links and
  action-log references keep working.
- A later, optional step can rename the physical table.

### 2.2a Existing deployments (many views, many widgets, every env)

The deployment this lands on already has every version of every view anyone saved,
in dev, test and prod, plus subscriptions, archives, shared links and action-log
references to view ids. The design is that **none of it is touched**:

| Concern | How it's handled |
| --- | --- |
| Migrating rows | Not done. `spec_json` is added nullable and never backfilled; a NULL reads as the one-tab app (tab id = app id). A backfill would mint a version of every view in every env. |
| Promotion after a lazy upgrade | `same_view_content` compares the *read* spec, not columns, so a view re-saved in Dev still matches its untouched copy in Test and isn't re-promoted for nothing. A change on tab 2+ still counts as a change. |
| Old clients during and after deploy | ~~A browser still on the old bundle, and `/api/views` generally, can only see one canvas. Their saves change **tab one only** (`with_first_tab_widgets`).~~ **Slice 6 removed `/api/views`.** A tab still running the pre-apps bundle when this deploys gets 404s from it, so it can't load or save until reloaded. It can no longer write at all, rather than writing tab one only. |
| Rollback to pre-apps code | `widgets_json` is always written equal to tab one, so old code shows each app's first tab. Caveat: an old-code save then writes no `spec_json`, so that app reads as one tab again. Tabs 2+ survive in version history, not in the head. Don't roll back past slice 5 without restoring those heads. |
| Ids and links | App id = view id, so `shared_views`, `archived_views`, `#/view/<id>`, `?shared_view=`, `?widget=` and action logs are unaffected. |
| Junk in old rows | `read_spec` never raises and keeps widget entries verbatim (including `y: null` from `Infinity`). Strict validation applies only to new writes, and a widget id repeated *within* one tab is still allowed, as it always was. |
| Folding many views into apps | `POST /api/apps/compose` copies chosen views (or apps) into a new personal app, one tab each, in order. Sources are copied, not moved, so their links, subscriptions and history keep working; the author archives them afterwards if they want. Tabs get new ids; widget instance ids are kept unless two sources share one (e.g. a duplicated view), in which case the later copy is re-keyed. Every source must be one the caller could open. |
| Data migration snapshots | The column travels automatically ("only columns both sides have"). Importing into an app older than slice 1 drops `spec_json` and keeps tab one. |

### 2.3 Access: unchanged from views (decided 2026-10-05)

**Everything that was true for views is true for apps. Introducing apps does not
change the security model.** The brief proposed several changes here; all of them
are dropped:

| Brief proposed | Decision |
| --- | --- |
| Viewers render an app's widgets without a role in the widgets' domains (bypass `_visible`) | **Dropped.** The app-scoped widget bundle (`GET /api/apps/{id}/widgets`, slice 3) must apply the same domain filter `/api/widgets/custom` applies today. |
| `link_access: restricted \| workspace` | **Dropped.** No such field. |
| Opening a link must not subscribe; subscribing becomes an explicit button | **Dropped as a security change.** The `?shared_view=` flow keeps auto-subscribing. `POST /api/apps/{id}/subscribe` is the same handler as `POST /api/views/shared/{id}`. |
| 404 for no-access on read | Kept where views already denied access (a global app outside your domains); it grants and removes nothing. |

What that means concretely, as built in `app_spec.can_read` and
`app_store.require_may_edit`:

- **Read:** a global app needs a role in its domain, or global admin, as
  `GET /api/views` filters global views. A personal app opens for anyone holding
  its id, because `?shared_view=<id>` has always subscribed any caller to any id
  that exists. Archived apps read as missing, as they drop out of the views list.
- **Write:** personal apps by their owner, global apps by an editor of their
  domain, as `PUT /api/views/{id}`.
- **Data:** every query still runs as the viewer (OBO), and Unity Catalog decides
  what it returns.
- **One tightening, flagged for review:** making an app global, or moving a
  global app to another domain, now needs editor rights on the domain it lands
  in. The old update path checked only the starting domain, so an owner could
  publish a personal view as global into any domain, which the create path already
  refused. Revert by removing the `new_global and (...)` check in
  `app_store.save_version` if this is unwanted.

Still worth auditing before rollout, though it is not a change: any widget with
side effects that are not UC-governed (n8n, Tableau, custom_widgets APIs,
executable actions) must run as the viewer (OBO) and write `action_logs`, and
none should run as the SP.

### 2.4 Presentation and shell

- Canonical link: `#/app/<appId>[/<tabId>]`, optional widget deep link
  `#/app/<appId>/<tabId>/w/<widgetId>`.
- `#/view/<id>` and `?shared_view=` remain permanent aliases that resolve to the
  same app.
- **The shell is a property of the app, not the URL.** Spec field
  `presentation: "workspace" | "standalone"`:
  - Migrated legacy views default to `workspace` (analysts keep the sidebar).
  - ~~Newly created apps default to `standalone`.~~ New View still makes a
    workspace app; standalone is chosen in View settings (Q9).
- Standalone = no Command Center chrome (no sidebar, no "Command Center"
  header/title, no widget tray, no studio/admin entry points). Render
  `AppShell` with **no Layout at all** — do not hide Layout with CSS.
- Links still require normal sign-in to this Databricks App (OBO identity). Never
  public/anonymous.
- Keep an environment badge in dev/test/stage even in standalone.

### 2.5 Behavior to preserve or define

| Concern | Rule |
| --- | --- |
| Single-tab app | No tab bar; sidebar (workspace) opens straight to the canvas |
| Multi-tab | Tab bar inside the app; sidebar lists apps, not tabs |
| Lock / share / archive | App-level (tab-level lock later if needed) |
| Agent pin | App-level default with tab-level override (tab → app → default). Keep `pin_value` semantics (absent = keep, `""` = clear); covered by `tests/test_view_pins.py` |
| Variables | Scope to the active app. Reset on app change; shared across its tabs. Fixes a cross-view leak — verify nothing relies on cross-view persistence (§5 #2, still open) |
| Orphan widgets | Do not write to an app from orphan-cleanup for non-editors; show a visible "widget unavailable" placeholder instead of silently hiding |
| Version churn | Debounce client autosave; update the head row in place when the same user saves within a short window and only layout changed. Promotion must still see a stable head |
| Branding | Applied by `AppShell`; set `document.title` / favicon while mounted; restore Command Center's on exit. Validate and size-limit logo/favicon server-side |
| Assistant | `assistant: "on" \| "off"`. When on, reuse `AgentPanel` with app default or per-tab pin; conversation held above tabs. Branding replaces "EDH Agent" |
| Viewer vs editor (standalone) | Viewers: no tray, no `w`, no drag/resize, no lock/share, no orphan writes. Editors: one unobtrusive "Edit app" → workspace builder. "Copy link" for anyone allowed to share |

---

## 3. Consequences

### 3.1 Positive

- One mental model and one promotion unit for single-canvas and multi-tab
  experiences.
- Shared links can look like a product without forking the runtime.
- No change to who can see or change what (§2.3), so nothing to re-review or
  re-communicate about access.
- App-scoped widget bundle is smaller/faster than loading the full library,
  which matters most for standalone apps opened from a link.

### 3.2 Trade-offs / risks

- Embedding tabs multiplies row size; version-per-drag already churns rows —
  coalescing is required, not optional, for multi-tab to stay healthy.
- Dual-write / legacy read path adds temporary complexity; delete the
  `/api/views` shim once the frontend is flipped.
- Standalone load path must be route-aware from the first paint; any eager
  `fetchViews` / full library / studio prefetch will regress link open cost and
  flash chrome.
- `presentation` defaults differ for migrated vs new apps — document clearly in
  user guide and release notes so creators are not surprised.

### 3.3 Non-goals (restate)

- Public anonymous apps, cross-site iframe embeds, responsive grid redesign,
  widget iframe isolation, intelligence/presets, authoring agent for the app
  spec.

---

## 4. Implementation plan

### 4.1 Backend

1. `database.py`: add `spec_json`; keep idempotent DDL + advisory lock.
2. New `routes/apps.py` (or rename `views.py`) reading legacy and new rows.
   Register by hand in `main.py`. Accept `env` on every route.
3. API surface: `/api/apps` (CRUD, history, shared, archive/restore). Keep
   `/api/views` as a thin shim until the frontend is flipped, then delete it.
4. `GET /api/apps/{id}/widgets`: source for widgets the app's tabs use (honor
   placed `props._version`), for users who can read the app, with the **same
   domain filter** `/api/widgets/custom` applies (§2.3).
5. `_require_certified_widgets`: run over **all tabs'** widgets on create and
   update.
6. `promotion.py`: `transfer_view` → `transfer_app`, with a **preflight** that
   lists widgets and pinned agents missing in the target env (resolve by id to
   target env's head). Fixes the existing "view references a widget not in the
   target" gap.
7. `creator_stats.py`: count placements across every tab.
8. `data_migration.py`: keep table spec current.
9. Share-link helpers (`generateShareLink` / `generateWidgetShareLink`): emit
   canonical `#/app/...` links.

### 4.2 Frontend

1. `dashboardStore.tsx`: `App` / `AppTab`, active app + active tab, app-scoped
   variables. Make `DashboardProvider` route-aware (standalone skips
   `fetchViews`, full library, studio/admin prefetch).
2. Parameterize `DashboardGrid` by app/tab id and read-only flag.
3. Route-level shell split: resolve `#/app/<id>` before Layout; standalone →
   `AppShell`, else existing Layout.
4. `Layout.tsx`: sidebar lists apps; header lock/share act on the app; hash
   routing for `#/app/<id>[/<tabId>]`; fix missing `hashchange` entries.
5. Tab bar (reorder, add, rename, delete) for editors; part of `AppShell` for
   standalone.
6. Admin / promotion screens: app terminology, new API.
7. `useDashboardContext` / `useActionLogger`: include app name and active tab.
8. Add-widget flows target the active tab.
9. Later slices: nav style, theme tokens (if generators learn about them, update
   `agent_instructions.md`, `widgetLint.ts`, and the runtime together),
   app-scoped filters into `variables`.

### 4.3 Ship slices (independently shippable; behavior-preserving first)

| # | Slice | Notes |
| --- | --- | --- |
| 1 | Storage + `/api/apps` + legacy read path + tests | No UI change. **Built**, plus `compose` |
| 2 | Store/type rename; flip frontend to `/api/apps` | Workspace behavior identical. **Built** (§4.3a) |
| 3 | App-scoped widget bundle + canonical links/aliases | Access unchanged (§2.3). **Built** (§4.3b) |
| 4 | `AppShell` standalone: route-level split, branding, env badge, viewer/editor, route-aware provider | Critical path for shareable apps. **Built** (§4.3c) |
| 5 | Multi-tab bar and editing; app-scoped variables | **Built** (§4.3d) |
| 6 | `transfer_app` with preflight; delete `/api/views` shim | **Built** (§4.3e) |
| 7 | Nav styles, theme tokens, filters | **Built** (§4.3f) |

### 4.3a Slice 2 as built

- **Store.** `Tab` is now `App` (in `src/store/appSpec.ts`, beside `AppTab`,
  `AppSpec`, `WidgetLayout`), and the store's `tabs`/`activeTabId`/`addTab`/... are
  `apps`/`activeAppId`/`addApp`/.... It also exposes `activeApp` and
  `activeAppTab`. "Tab" now means only a canvas inside an app.
- **Shown tab = first tab** (`shownTab`), until slice 5's tab bar. An app with
  more tabs (only `compose` can make one today) shows tab one, as `/api/views`
  always did, and keeps the rest.
- **Saves send the whole spec**, built from what `GET /api/apps` returned with one
  tab's widgets changed. Widget operations take `(appId, tabId)`. The server
  accepts every spec its read path returns; the route tests round-trip legacy
  rows (null `y`, a widget id repeated within a tab, a view id over the 64-char
  tab-id cap, which is now accepted when it is the app's own id).
- **Saves to one app are queued.** Each save claims version + 1 off the newest
  row, so overlapping saves hit `dashboard_views_pkey` and one is refused. That
  predates apps (StrictMode doubled every save in dev; in production it took two
  edits close together). The store now chains saves per app. Q3's
  debounce/coalescing can sit on the same queue.
- **Pins.** The drawer resolves tab → app → built-in (`pinnedAgentOf`). The pin
  button changes the pin in force: the tab's if it has one, else the app's. A
  view's tab never has one, so for views nothing changed. The apply-on-arrival
  effect is keyed `appId/tabId`.
- **Telemetry.** `action_logs.context.tabId`/`tabName` keep meaning the
  view's (app's) id and name, so the audit trail reads the same either side of
  the change; `appTabId`/`appTabName` are added. The assistant preamble is
  unchanged for one-tab apps and names the tab only when there are several.
- **Admin.** View Promotion lists, archives, restores, deletes and reads history
  through `/api/apps`. Promotion itself stays on `transfer_view` until slice 6.
  `/api/apps` now returns `timestamp`, which `/api/views` selected but dropped.
  That is why "Last Modified" was always blank.
- **Words on screen are unchanged** ("My Views", "New View", "View Promotion").
  Renaming what users see belongs with the change that gives them something new
  to see (slices 4–5), alongside the user guide and `app_guide.md`.
- **Not in this slice:** links stay `#/view/<id>` and `?shared_view=` (slice 3);
  variables stay provider-wide (slice 5); the provider still loads everything
  eagerly (slice 4).

### 4.3b Slice 3 as built

- **Links.** Share and the widget link icon emit `#/app/<appId>[/<tabId>]` and
  `#/app/<appId>/<tabId>/w/<widgetId>`. The tab is left out when it is the
  app's first, so a view's link is `#/app/<id>`. `?shared_view=`, `#/view/`,
  `#/template/` and `?widget=` parse to the same route (`src/store/appRoute.ts`)
  and the address bar is rewritten to the canonical link once read.
- **Opening a link subscribes, as `?shared_view=` did** (§2.3 kept that). It now
  happens for any link form, not only `?shared_view=`, so an address copied
  from the browser bar works as a share link; before, a `#/view/<id>` for a view
  you didn't have opened a blank canvas. Nobody can reach anything new: any id
  could already be subscribed to with `?shared_view=<id>`. The client subscribes
  only after a fresh list says the app isn't there, so your own apps and global
  apps you can see are never subscribed to (the old flow subscribed even then).
- **A tab id in a link is honoured.** `shownTab(app, tabId)` returns that tab,
  else the first. No tab bar yet, so a link is the only way to tab two of a
  composed app; Back/Forward move between tabs like apps.
- **`GET /api/apps/{id}/widgets`**: the library's rows for the widgets the app
  places, through the same query (`custom_widgets.library_rows`) and domain
  filter (`_visible`) as `/api/widgets/custom`, plus source for pinned versions.
  The workspace doesn't use it; slice 4's standalone load does.
- **Fixed on the way:** Agent Studio, User Guide and Release Notes were missing
  from the page lists, so Back and (for the last two) reload didn't reach them;
  a subscribe to an id that doesn't exist answered 500 instead of 404.

### 4.3c Slice 4 as built

- **The shell is chosen before anything is drawn.** `src/Root.tsx` owns the
  page. An address that names an app (any link form) is read with
  `GET /api/apps/{id}` behind a plain spinner. A standalone app gets
  `<DashboardProvider standalone>` + `AppShell`; anything else gets today's
  workspace, unchanged. That includes a link that can't be read, so the
  workspace still subscribes or shows nothing as before. `Layout` is never
  mounted for a standalone app.
- **Two addresses, one app.** `#/app/<id>` shows the app the way it presents
  itself. `#/workspace/<id>[/<tab>[/w/<widget>]]` is the same place inside the
  workspace whatever the app is. The workspace writes it for a standalone app,
  so an editor who reloads stays in the builder, and `Root` doesn't read the
  app first for it. Moving between the two (`Edit`, `Open`, Back/Forward)
  goes through `ShellContext` (`src/shell.ts`) with `pushState`, which raises
  no `hashchange`, so neither page reacts to the other's navigation. Inside
  the workspace, `openRoute` hands a standalone app named by its own link to
  the shell instead of selecting it.
- **Route-aware provider.** In standalone mode the store is seeded with the one
  app `Root` read. It never calls `GET /api/apps/` and is read-only for
  everyone, editors included (`DashboardGrid` reads `standalone`), which also
  turns off the orphan cleanup: the registry holds only this app's widgets.
  It still loads `/api/roles/my-permissions` (§5 #6: yes, it's acceptable; Edit
  needs it).
- **`AppShell`** (`src/components/AppShell.tsx`): logo, branded title, and the
  environment badge off prod. It loads `loadAppWidgets(id)` (slice 3's bundle)
  instead of the library. There is no tray, no `w`, no studio prefetch and no
  `ThumbnailCaptureHost`. It sets the tab title and favicon while mounted and
  restores them on exit. **Copy link** goes to the people who get Share in the
  workspace (admin for a global app, owner for a personal one). **Edit** goes
  to `canEditApp` and opens `#/workspace/<id>`. The assistant uses the same
  `AgentDrawer` as the workspace (lifted out of `Layout`), named by
  `branding.assistant_name` (replaced in §4.3g by an agent picker). It is absent when `assistant` is `off`, and the
  pin control is hidden, because pinning is an edit.
- **Subscribing is unchanged (§2.3).** Opening someone else's personal app by
  its link still puts it in your sidebar, once, from the provider's mount.
  `Root` itself only reads.
- **View settings** (workspace header, for `canEditApp`) sets presentation,
  title, logo, favicon, assistant on/off and assistant name. The client checks
  images against the server's rules (`imageProblem` mirrors `_image`). A save
  the server refuses is undone and shown in the dialog. `apiSyncApp` now
  resolves to the refusal.
- **Moved, not changed:** `DashboardGrid` now lives in its own module; the
  workspace page header, Lock and Share are unchanged. §5 #5: `activeDomain` is
  the only sidebar-era state the grid reads, and it is null without a sidebar,
  which filters nothing.

### 4.3d Slice 5 as built

- **Tab bar** (`src/components/TabBar.tsx`), under the header in both shells,
  shown only when an app has two or more tabs (§2.5). A one-tab app gets
  **Add tab** in the workspace header instead, so every existing view looks
  exactly as before until someone adds a tab. There is no separate New App
  flow: any view becomes a multi-tab app this way, and Q9 stands.
- **Editing.** Double-click renames, drag reorders, × deletes (confirming when
  the tab holds widgets; the last tab can't go), + adds up to `MAX_TABS` (50).
  A new tab is named before it exists, so adding one is one save. Each change
  sends the whole spec through the same per-app queue as widget edits, and a
  refusal is undone.
- **Who may edit tabs: whoever may move widgets** (§2.3, unchanged).
  `canEditLayout(app)` is that rule, now named once: not standalone, not
  locked, and a global app only for an admin. `DashboardGrid` uses it too.
  Standalone tabs switch but never change.
- **Addresses.** Switching tabs writes the tab into the hash, so Back steps
  between tabs and a link opens on the tab it was copied from. The tab is left
  out only when it is first (`routeTab`). A view's original tab has the app's
  id; once moved down the bar its links say `#/app/<id>/<id>`, while old
  `#/app/<id>` links now open the new first tab. `tabLabel` shows a view's
  unnamed first tab as the app's name wherever it moves.
- **Variables are per app.** Kept in the store keyed by app id and bound into
  `setVariable` per app, so an emitter seeding on mount in a newly opened app
  writes to that app. Shared by its tabs; another app starts empty.
- **Fixed on the way:** the "Empty Dashboard" hint never rendered, because the
  grid drops children that aren't its items. It now sits beside the grid and
  lets drops through.
- **Not in this slice:** a tab-level pin control. The pin button still changes
  the pin in force (tab → app), and no UI sets a tab's own pin. Q3's
  coalescing is still open; multi-tab apps make each row larger and each edit
  still adds a version, so it matters more now.

### 4.3e Slice 6 as built

- **`/api/views` is deleted.** Its subscribe, archive, restore, delete and
  archive-list handlers moved into `routes/apps.py` unchanged (same SQL, same
  rules, same messages), which is where `/api/apps` already delegated. The
  first-tab-only save path (`save_version(first_tab_widgets=...)`,
  `with_first_tab_widgets`) went with it; nothing else could use it. This closes
  Q8: the ungated `GET /api/views/history` no longer exists, and
  `/api/apps/history` applies the read rule. `tools/` probes moved to
  `/api/apps`.
- **`POST /api/promotion/transfer_app`** replaces `transfer_view`. Same rule
  (editor of the app's domain in the target), same rollback, same "already up to
  date" comparison, every tab carried in the row.
- **Preflight** (`POST /transfer_app/preflight`, read-only, same right as the
  transfer). Resolves by id against the target's live heads and returns:
  missing widgets; `_version` pins whose row of that number in the target is
  absent or different; pinned agents (app or tab, not `default`) the target
  lacks; and, when `require_certified_for_global_views` is on and the app is
  global, widgets uncertified in the target (or in the source, for ones it
  lacks).
- **Missing widgets can travel with the app.** `include_widgets` copies each
  one's current source version, under the rule promoting it alone has (editor
  of the widget's domain in the target), in the same transaction as the app. Only
  widgets the app places are accepted. The View Promotion dialog runs the
  preflight, lists the findings, and ticks **Promote them too** by default.
- **Nothing is refused for being missing,** as before. Agents have no
  promotion path, so a missing agent can only be reported.
- **Not changed, flagged:** promotion still copies a global app into an env
  without running `require_certified_widgets`, as `transfer_view` did. The
  preflight now names those widgets, and the first save in the target is
  refused until they're certified. Enforcing the check on promotion would be a
  tightening; it's left for a decision (Q10).
- **Pins aren't rewritten.** A `_version` pin is reported, not translated to
  the target's matching version number. Rewriting would change the copied row,
  so it would never compare equal to its source again.

### 4.3f Slice 7 as built

The three reserved fields are now interpreted, and validated like the rest of
the spec: strict on write, and on read a value that can't be used is dropped
(the read result always passes the write check).

- **`nav`: `{"style": "sidebar"}` or null** (tabs across the top). Applies in
  both shells: the same `TabBar`, with the same editing rules, drawn down the
  left of the canvas instead of above it. A one-tab app shows no tabs either way.
- **`theme`: `{"primary", "dark"}`, each `#rrggbb` or null** (ADR-002 §2.4 adds
  `background`, `font` and `cards`, and a `theme` on each tab). They replace
  `brand-blue` and `brand-navy`, which are now CSS variables (`rgb(var(--brand-*)
  / <alpha-value>)`, defaults in `index.css`), so opacity variants keep working
  and **generated widgets follow the theme with no generator, lint or runtime
  change**: they already use the classes. `AppShell` sets the variables on
  `<html>` so portalled dialogs pick them up too, and puts them back on close.
  In the workspace (added in §4.3g) `Layout` sets them on the element around
  the view's tabs, filter bar and canvas, so the sidebar and header, which use
  the same classes, stay Command Center's as you move between views. Both colours carry white text across the app and
  in widgets (and widgetLint treats them as dark), so each must reach 3:1
  contrast with white, which is what the default blue manages (3.98:1).
- **`filters`: up to 10 `{key, label, options[≤100], default}`.** `key` is an
  identifier, because a widget reads it as `variables.<key>`. A `FilterBar`
  under the header (both shells, any viewer) writes `setVariable(key, value)`;
  **All** writes `''`. Defaults are merged under chosen values in the store,
  so widgets see a default before anyone chooses, and a widget may still write
  the same key. Choices aren't persisted: reopening the app starts from the
  defaults, as variables always have. `compose` keeps the sources' filters
  (first view wins a shared key).
- **Edited in View settings** under `canEditApp`, the right that already covers
  presentation and branding. Nothing about who can see or change an app moved.

### 4.3g Follow-ups after slice 7

- **Per-tab agent pins have a UI.** On an app with two or more tabs, the pin
  beside the agent picker opens **This tab** / **Every tab**, each a toggle;
  `setPinnedAgent` now takes its target explicitly instead of guessing from
  which pin was in force. Same right as the app's pin (`canEditApp`).
- **View settings picks the agent, instead of naming one.** `assistant_name`
  only relabelled the built-in agent, beside a checkbox that read as choosing
  the assistant, and the launcher kept that label even when a pin put another
  agent in charge. It is gone: the server drops it on read and ignores it on
  write. **Agent** in View settings sets the app's pin (`updateAppSpec` takes it
  alongside the spec; on a one-tab app it also clears the tab's own pin, which
  does the same job). The launcher names the selected agent, or "Assistant"
  while the lazily loaded agent list hasn't arrived.
- **The theme applies in the workspace**, scoped to the view's own area (above).
- **Q3 decided: save coalescing, personal apps only.** `save_version` overwrites
  the newest version in place when it is personal and under five minutes old by
  the database's clock. The window slides, so an editing session is one version
  and a five-minute pause starts the next. Global apps keep a version per save:
  promotion copies and rolls back to them, editors share them, and the row
  doesn't record which editor saved. No client change: the save queue already
  serializes saves per app.
- **App-open cost measured (§4.5)** with `tools/app_open_probe.mjs`, the old
  startup harness rebuilt for `/api/apps` and committed. Production build, all
  `/api` faked, CPU ×4:

  | Scale | Shell, tabs | API KB | Usable | Longest task | Switch tab |
  | --- | --- | --- | --- | --- | --- |
  | 30 widgets × 8 versions, 60 views | workspace, 1 | 48 | 1.83s | 0.70s | — |
  | | workspace, 5 | 52 | 1.72s | 0.67s | 0.85s, longest 0.51s |
  | | on its own, 1 | 1 | 1.61s | 0.66s | — |
  | | on its own, 5 | 3 | 1.68s | 0.69s | 0.64s, longest 0.52s |
  | 150 × 20, 300 views | workspace, 1 | 238 | 2.18s | 0.73s | — |
  | | workspace, 10 | 246 | 2.09s | 0.64s | 0.69s, longest 0.44s |
  | | on its own, 1 | 1 | 1.64s | 0.69s | — |
  | | on its own, 10 | 5 | 1.70s | 0.67s | 0.64s, longest 0.51s |

  No task reaches a second. Opening an app on its own costs the same at any
  library size, because it fetches only its own widgets; the workspace grows
  with the library. Tabs add nothing to opening: only the shown tab renders.

### 4.4 Docs and tests (per AGENTS.md)

- User-visible behavior → update `RELEASE_NOTES.md` in the same commit, plus
  `src/pages/UserGuidePage.tsx` and `server/services/app_guide.md`.
- New pages → both `pageImports` and the prefetch list (and skip prefetch in
  standalone).
- Tests are standalone Python under the venv (no pytest harness). Cover at
  least: access is identical to views (global needs a domain role; personal
  opens by id; edit rights unchanged); alias resolution; pin semantics;
  certified check across tabs; legacy read and single-canvas saves.
- Run `npm run lint` and `npm run build` (real type gate) before claiming a
  slice done.

### 4.5 Prerequisites before broad rollout

- Confirm permission checks are really on in the target
  (`DISABLE_PERMISSION_CHECKS`; the `users` → admin lockout-prevention seed).
- ~~Measure app-open cost with the existing Playwright harness (longest
  main-thread task), especially standalone.~~ Done (§4.3g): longest task under
  0.8s in every case, across repeated runs. Re-run `tools/app_open_probe.mjs` against a real
  deployment's sizes before rollout if they exceed the 150 widgets / 300 views
  measured.

---

## 5. Verify before building

These are gates, not folklore. Resolve or document findings before the matching
slice lands.

1. Does any placed widget or endpoint run as the SP or without OBO?
   (§2.3 caveat)
2. Do any widgets depend on `variables` persisting across view switches?
   Slice 5 resets them, so check each deployed env: a receiver
   (`variables?.<key>`) placed in a view with no emitter
   (`setVariable('<key>'`) for that key. Local dev has too few widgets to tell.
3. Anything else that parses `widgets_json` outside the blast-radius list in
   §1.3?
4. ~~Does anything else rely on `?shared_view=` auto-subscribing?~~ Moot: the
   auto-subscribe stays (§2.3).
5. Which widgets/endpoints read sidebar-era global state (`activeTabId`,
   `activeDomain`) and would break when no Layout is mounted?
6. Is `/api/roles/my-permissions` acceptable from a standalone app, or is a
   lighter identity endpoint needed?

---

## 6. Open questions

Record answers here as they are decided; do not treat the brief as closed.

| # | Question | Lean | Decision |
| --- | --- | --- | --- |
| Q1 | Keep `presentation` flag, or force every app standalone? | Keep flag — analysts hop between one-canvas dashboards in the sidebar today | **Built:** kept; set in View settings |
| Q2 | How long to dual-write `widgets_json`? | "A couple of releases" after frontend flip | Open |
| Q3 | Coalesce window / what counts as "only layout changed"? | TBD with promotion head stability | **Decided:** any save to a personal app within 5 minutes of its last folds into that version; global apps never coalesce (§4.3g) |
| Q4 | Physical table rename (`dashboard_views` → `apps`)? | Optional later; not required for product | **Decided: no.** |
| Q5 | Tab-level lock? | Defer | **Decided: no.** |
| Q6 | Logo/favicon max size and allowlist | Server-side validate; CSP already allows data/https images | **Built:** https URL or base64 `data:image/*`, ≤ 256 KB encoded (`app_spec.MAX_IMAGE_CHARS`) |
| Q7 | What access do existing personal views get under apps? | — | **Decided:** no change to the security model at all; see §2.3. `link_access` dropped. |
| Q8 | Should `GET /api/views/history` get the access check too? Today it has no auth dependency and returns names/usernames/timestamps for any id. `/api/apps/history` is gated. | The admin screen moved to `/api/apps` in slice 2, so nothing in the UI calls it now. Gating it would still change access, so it's left for slice 6, which deletes it. | **Closed (slice 6):** deleted with `/api/views` |
| Q9 | Should New View make standalone apps, as §2.4 first said? | No: New View lives in the sidebar, among views people hop between, and a standalone default would make every new view leave it when its link is shared. | **Decided (slice 4):** New View stays workspace; standalone is opt-in in View settings. Revisit with slice 5's New App flow. |
| Q10 | Should promotion enforce `require_certified_for_global_views` in the target? Today it copies the row unchecked, as `transfer_view` did; the next save there is refused. | Enforcing it closes a gap in ISRP 30.1, but it changes what a promoter may do, so not in passing. | **Decided: no.** Promotion stays as it was; the preflight reports uncertified widgets (slice 6) |

---

## 7. Repo rules reminder

From root `AGENTS.md` / `server/AGENTS.md` / `src/AGENTS.md`:

- Default to `get_db_client` (OBO); frontend never holds secrets.
- Widgets, views/apps, and agents are database rows, not files in this repo.
- Version numbers are per environment — never reference across envs.
- Register routers by hand in `main.py`.

---

## Change log

| Date | Change |
| --- | --- |
| 2026-10-05 | Created from Apps brief + standalone-shell amendment. Status: Proposed. |
| 2026-10-05 | Slice 1 built: `spec_json` column, `services/app_spec.py` + `app_store.py`, `/api/apps` (CRUD, history, subscribe, archive/restore/delete, compose) with the access rule enforced on every read, `/api/views` shim writing tab one only, certified check across tabs, leaderboard counting every tab, promotion comparing meaning. Added §2.2a (existing deployments), Q7, Q8. Also fixed: making an app global now requires editor rights on the domain it lands in. |
| 2026-10-05 | Decided: apps inherit the views' security model unchanged. Rewrote §2.3; dropped `link_access`, the widget-domain bypass, and "opening must not subscribe". Q7 closed. |
| 2026-10-05 | Slice 2 built (§4.3a): store speaks `App`/`AppTab`, the browser uses only `/api/apps`, saves carry the whole spec, pins resolve tab → app. Corrected §1.2 (orphan cleanup never wrote). Q8 deferred to slice 6. |
| 2026-10-05 | Slice 3 built (§4.3b): canonical `#/app/...` links with permanent aliases, one parser, tab ids in links honoured, any link form subscribes as `?shared_view=` did, `GET /api/apps/{id}/widgets`. Fixed missing `hashchange` pages and a 500 on subscribing to a missing id. |
| 2026-10-05 | Slice 4 built (§4.3c): `Root` picks the shell before first paint; standalone apps render `AppShell` with no `Layout`, read-only, loading only their own widgets; `#/workspace/<id>` for building them; View settings for presentation, branding and assistant. Decided Q9 (New View stays workspace); closed Q1, §5 #5 and #6. |
| 2026-10-05 | Slice 5 built (§4.3d): tab bar and Add tab, rename/reorder/delete under the existing layout-edit rule, tabs in the address, variables per app. Fixed the empty-canvas hint. §5 #2 and Q3 still open; no tab-level pin UI. |
| 2026-10-05 | Slice 6 built (§4.3e): `/api/views` and the first-tab-only save path deleted, its handlers moved into `routes/apps.py`; `transfer_app` with a read-only preflight and optional widget promotion in one transaction; View Promotion dialog shows the preflight. Closed Q8; added Q10. |
| 2026-10-05 | Slice 7 built (§4.3f): `nav` (tabs top or side), `theme` (two brand colours as CSS variables, white-text contrast enforced, standalone only), `filters` (a filter bar that sets dashboard variables); all edited in View settings. |
| 2026-10-05 | Follow-ups (§4.3g): per-tab agent pin menu; theme also in the workspace, scoped to the view's area; Q3 decided (personal saves coalesce for 5 minutes); app-open cost measured and `tools/app_open_probe.mjs` committed. Q4, Q5, Q10 decided: no. |
| 2026-10-05 | `branding.assistant_name` replaced by an **Agent** picker in View settings that sets the app's pin; the launcher names the selected agent. |
