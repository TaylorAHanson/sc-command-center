# AGENTS.md — Backend (FastAPI gateway)

Read `../AGENTS.md` first for the OBO rule, the environment/schema model, and
commands. This file covers what you need to change code in `server/`.

## Imports are flat — this bites everyone once

Uvicorn imports `main:app` with `server/` on `sys.path`, so packages resolve
from *inside* `server/`, not from the repo root:

```python
from routes import widgets            # correct
from middleware.auth import get_db_client
from database import init_db
from server.routes import widgets     # WRONG — will not import
```

Locally that's because `dev.sh` starts uvicorn from inside `server/`. The
deployed App starts from the repo root, and `--app-dir server` in `app.yaml`'s
command does the same job; don't move it into a `PYTHONPATH` env var, which a
platform restart from `app.yaml` alone would not have. The standalone tests
insert `server/` onto `sys.path` themselves. If you see
`ModuleNotFoundError: No module named 'server'`, this is why.

Run the backend alone with `cd server && ../.venv/bin/uvicorn main:app --reload
--port 8001`. Startup logs go to `../backend.log` when launched via `dev.sh`.

## Adding an endpoint

1. Create or extend a module in `routes/` that defines `router = APIRouter(...)`.
2. **Register it in `main.py`** — import it and call `app.include_router(...)`
   with an `/api/...` prefix. There is no auto-discovery, despite what the README
   implies. Anything under `/api/` that isn't mounted hits the SPA catch-all and
   returns a JSON 404.
3. Take auth as a dependency rather than reading headers yourself.
4. Don't add an `env` parameter. There is one content store per deployment, so
   call `get_db_connection()` and let it pick the content schema. Existing routes
   still accept `env` for older clients and saved links, but every value maps to
   the same store (see *Database*); a new route has no such callers.
5. Check access with `services/access.py` (see *Auth*), not with a role or a
   domain: `access.require(who, type, id, level)` for one object, or
   `access.visible_ids` / `levels_for` to filter a list.

Mounted prefixes (`main.py`): `/api/widgets`, `/api/actions`, `/api/genie`,
`/api/sql`, `/api/jobs`, `/api/roles`, `/api/apps`, `/api/sharing/migration`
(the cutover report, mounted ahead of `/api/sharing` because the latter's
`/{object_type}/{object_id}` would otherwise claim it), `/api/sharing`,
`/api/taxonomy`, `/api/settings`, `/api/databricks`, `/api/agent` (proxy),
`/api/agent/widget`, `/api/agent/studio`, `/api/agent/uploads`,
`/api/conversations`, `/api/migration`, `/api/capabilities`, plus `/api` for n8n
and Tableau.
Interactive docs are at `/api/docs`.

`/api/health` is the one unauthenticated route, so it doubles as the SPA's source
for `APP_ENVIRONMENT` (`config.settings.get_app_environment()` — local/dev/stage/
prod, set per bundle target: which Databricks App this is). That is the only
environment left. The `env` query parameter some routes still take used to pick
an in-app Dev/Test/Prod workspace; drafts replaced those, the browser no longer
sends it, and the server ignores its value.

## Auth (`middleware/auth.py`)

| Dependency | Identity | Use for |
| --- | --- | --- |
| `get_user_token` | raw forwarded OBO token | passing a token onward (agent proxy, MCP) |
| `get_db_client` | **user** (OBO) | default for anything touching data |
| `get_db_client_for_jobs` | user, jobs-tuned | Databricks Jobs calls |
| `get_db_client_sp` | app service principal | only where the app itself must act |
| `require_auth` | — | asserts a signed-in user, returns username |

Default to `get_db_client`. Reach for `get_db_client_sp` only when the operation
is genuinely app-level (minting Lakebase credentials, for instance) and say why
in a comment — a reviewer should not have to guess whether SP use was
deliberate.

These factories return **cached** clients, keyed by a hash of the credential and
held for `WORKSPACE_CLIENT_TTL_SECONDS` (300); see *What a request is allowed to
spend* for why. Two consequences: never mutate a client you are handed (its config
is shared with other requests on the same credential), and never key a cache on
anything but the credential itself — a key derived from a username would hand one
user's client to another.

**Access is per object** (`services/access.py`). Every view (`app`), widget
and agent has an access list in `object_permissions`: entries granting `MANAGE`
or `USE` to a user, a group, or everyone (`*`, principal type `all`). A caller's
level is the highest any entry gives them, directly, through a group, or through
`*`. `app_admins` lists Administrators, who hold `MANAGE` on everything and are
the only callers `require_app_admin(w)` lets through. Both tables live in the
settings schema (`settings_env()`), not the content store, because who may do
what is a fact about the deployment and is keyed by object id alone.

- `access.caller(w)` → `Caller(username, groups, is_admin)`, from the cached
  identity (see *What a request is allowed to spend*). Resolve it once per request.
- `access.require(who, type, id, level)` answers **404** when the caller holds no
  level, so a link never confirms that something exists, and **403** when they
  hold `USE` but `MANAGE` was needed — at that point they already know it exists.
- `grant_owner` runs **after** the content commit. The ACL write is a separate
  transaction on another schema, and ordered this way a failure leaves an object
  only Administrators can reach, never one the wrong person can.
- `replace_acl` refuses a list with no `MANAGE` entry unless an Administrator
  wrote it; otherwise an owner could lock everyone out of their own work.
- Users match case-insensitively (`creator_stats.same_person`), because SCIM is
  not consistent about case; groups match their SCIM display name exactly.

Domains grant nothing any more; they are labels for filtering. Don't reintroduce
a check on one. `role_mappings` is still in the settings schema for the access
migration and a rollback; nothing writes it, and nothing reads it for decisions.
`tests/test_role_mappings_home.py` stays until that table is dropped.

Administrators hold `MANAGE` on everything but are not *granted* it, so
`list_apps` lists only views an admin owns or is granted; listing every view in
each admin's sidebar would bury their own. Admin Panel → Content
(`GET /api/sharing/content`) is where they see the rest, and `_open` lets them
open any view by link.

## The one-time move to sharing (`services/consolidation.py`, `services/access_migration.py`, `routes/cutover.py`)

Startup runs two steps after `init_db`, in this order so the second sees every
object the first brought over:

1. **Consolidation** folds the retired Dev and Test content into the one content
   store as drafts: Prod's versions stay the published history, an object's
   newer Dev (else Test) version becomes its draft when it differs in meaning,
   and objects only in Dev or Test become never-published drafts. Dev and Test
   are read, never written.
2. **The access migration** writes, once, the ACL each object's domain used to
   imply, by replaying what the old checks did: `viewer` → `USE`, `editor` /
   `admin` → `MANAGE`, on every widget, every *global* view and every *domain*
   agent filed under exactly that domain (unset reads as `General`). Owners get
   `MANAGE`; `shared_views` subscribers get `USE` on the view, since that is who
   had a link open; global agents get Everyone `USE`. An `admin` mapping on a
   global alias (`global` / `all` / `app`) becomes an `app_admins` row; a `viewer`
   or `editor` mapping on one grants only what is literally filed under that
   alias, because only `admin` was ever read as global, and the report names each
   such mapping. If no mapping made anyone an admin, group `users` goes into
   `app_admins`, the lockout prevention `init_db` used to seed into
   `role_mappings`.

Both only add rows, so redeploying the previous release finds its tables as it
left them. Each records its outcome in **`cutover_log`** (settings schema, one row
per step: `done` / `skipped` / `failed`, with the report or the error) under the
step's advisory lock, so two uvicorn workers can't run a step at once. A step
with a row never runs again on startup, including a failed one: a failure that
repeats would cost every startup the same work and change the report under the
admin reading it. A step that couldn't reach the settings store at all logs
nothing, so the next start tries again; that is the transient case. The Admin
Panel's banner reads `GET /api/sharing/migration/report`, and its **Retry**
(`POST /retry`, admins only) deletes the failed rows and reruns those steps.
Like `init_db`, neither step raises out of startup.

## Database (`database.py`)

`get_db_connection(env="dev", pooled=True, physical=False)` hands out a pooled
connection (see *What a request is allowed to spend*), opening one only when the
pool has none. Any of `dev` / `test` / `prod` resolves to `content_env()`
(`APP_CONTENT_ENV`, default `prod`) unless `physical=True`, which addresses the
schema the name really denotes. Only the settings store and the one-time
consolidation, which reads the retired Dev and Test schemas, should ever pass it:
anything else that does reads a schema users no longer write to. Opening resolves the
Lakebase host/database, mints a short-lived OAuth token via the SDK when no
password is supplied, and pins the schema. That resolution costs three or more
control-plane round trips, so the working parameters are cached per env for
`LAKEBASE_CRED_TTL_SECONDS` (600) and dropped automatically when a connection using
them fails. Without it, a page that fires several API calls at once intermittently
failed on control-plane latency. Call `invalidate_db_credentials()` if you change
instance wiring at runtime — it retires pooled connections too, since they were
opened with the credentials being dropped.
Autoscaling Lakebase projects are **not** in the SDK's `DatabaseAPI`, so this
code falls back to raw REST (`/api/2.0/postgres/projects`,
`/api/2.0/postgres/credentials`) and tries several name permutations. If you're
debugging connectivity, that fallback chain logs each attempt.

`init_db(env)` builds the schema idempotently under an advisory lock. Keep it
that way: concurrent workers running `CREATE TABLE IF NOT EXISTS` can still
collide on the system catalogs, and an exception here kills every worker
("Child process failed to start, stopping the parent process").

Table shapes worth knowing before you write a query:

- **Versioned, PK `(id, version)`**: `widgets`, `dashboard_views`,
  `agent_profiles`. Reads must select the newest version per id — see the
  `MAX(version)` join in `routes/apps.py::list_apps`. Writes insert a new version rather
  than updating in place.
- **PK `(object_type, object_id)`**: `object_drafts` — at most one draft per
  view, widget or agent, as JSONB (see *Apps* → drafts).
- **PK `(username, view_id)`**: `shared_views` (subscriptions, now unused for
  access) and `sidebar_hidden` (views someone took off their Shared with me).
- **PK `id`**: `archived_views` — views taken out of circulation.
- **`SERIAL id`**: `widget_categories`, `widget_domains`, `role_mappings`,
  `widget_runs`, `action_logs`. Categories/domains are `UNIQUE (name)` and are
  seeded with defaults on first creation, so a "fresh" schema is not empty.
  `role_mappings` is still created but never written or seeded: the access
  migration reads it once, and a rollback to the previous release must find it
  as that release left it. The lockout fallback it used to seed (group `users`
  as global admin) moved to the migration, which adds `users` to `app_admins`
  only when no mapping made anyone an admin.
- **Settings schema only**: `app_settings`, `object_permissions`, `app_admins`,
  `known_principals` (everyone who has signed in, and their groups, for the share
  dialog's typeahead), and `cutover_log` (see *The one-time move to sharing*).

New columns go in as `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in the migration
block *after* table creation, each in its own try/except with a rollback, so one
failure can't abort the rest of the transaction.

### The agent a view is pinned to

`dashboard_views.pinned_agent_id` holds the Agent Studio profile the assistant
drawer opens with on that view (or the literal `'default'` for the built-in
agent). Permission is the view's own: `MANAGE` on the view, which
`PUT /api/apps/{id}` already enforces, and the pin lands in the view's draft like
any other change — there is no separate check, and none should be added. A pin
grants nothing on the agent: people using the view still need `USE` on it.

The one trap is that clients save a view **whole**: nudging a widget one square
PUTs name, lock, widgets and all. So `pin_value` treats an absent pin as "keep
what's there" and an empty string as "clear it", because a field that isn't sent
and a field sent as `null` are both `None` by the time Pydantic is done with
them. Get that backwards and every widget drag silently unpins the view.
`tests/test_view_pins.py` holds the distinction.

### Removing a view: archive, then delete

Two steps when other people can open the view. `POST /api/apps/{id}/archive`
inserts into `archived_views`; `list_apps` (and the creator leaderboard) skip
those ids, and `_open` reads them as missing, so the link stops opening too.
Every version and the draft stay, so `POST /{id}/restore` is exact. `DELETE /{id}`
answers 409 while a view shared beyond its owner (`_shared_beyond_owner`, from
the ACL summary) is unarchived, so someone can notice it gone before it is gone
for good; a private view is deleted outright, as closing one always did. Delete
removes every version, the draft, the link names, the sidebar markers and the
ACL. All three need `MANAGE`. The sidebar's × follows the same split: it deletes
a private view and archives a shared one, confirming either way.

`POST /{id}/discard` answers 409 for a view never published: the draft is all
there is, and discarding it would be a delete without Delete's confirmation.
Widgets refuse the same way, for the same reason.

The marker is its own table rather than a flag on `dashboard_views` because that
table is versioned — a flag would travel with one version and be lost on a
revert, when "retired" is a fact about the view's id. There is one content store,
so archiving is a single write. `tests/test_view_archive.py` holds the ordering
and the permissions.

### Apps: a view is an app with one tab (`services/app_spec.py`, `services/app_store.py`, `routes/apps.py`)

`docs/adr-001-apps-as-top-level-artifact.md` is the plan; this is what is built.
An app is a `dashboard_views` row under the view's own id, plus `spec_json`
(tabs, each a widget layout; presentation/assistant/branding; and `nav`
(tab placement), `theme` (two brand colours, each required to carry white text)
and `filters` (dropdowns whose choices are dashboard variables)). The rules
that keep the deployment already running intact:

- **No backfill, ever.** A NULL `spec_json` reads as the one-tab app the view
  always was, tab id = app id. Writing specs for old rows would add a version to
  every view.
- **`/api/views` is gone.** It spoke for one canvas, so every save it took had to
  change only the first tab; nothing calls it any more and `/api/apps` is the
  only way in. Don't bring back a single-canvas write path: anything that can't
  see tabs 2+ and saves would delete them. `widgets_json` is still written equal
  to tab one, so a rollback to pre-apps code still shows each app's first tab.
- **`read_spec` never raises; `validate_spec` refuses.** Reads (sidebar,
  leaderboard, publish preflight) keep widget entries verbatim and fall back to
  `widgets_json`; writes reject what they would have to guess at — no tabs, a
  widget instance on two tabs, an unknown choice, a spec from a newer schema.
- **Whatever a read returns, a write must accept.** The browser saves an app by
  sending back the spec it was given with one tab changed, so a row that reads
  fine but fails `validate_spec` is an app nobody can drag a widget on. That is
  why a view's only tab, named by the view's id, is accepted however long the id
  is. `test_every_app_the_api_hands_out_saves_back_unchanged` round-trips the
  awkward cases; add yours there.
- **Access is the app's own ACL.** `GET` needs `USE`, every write `MANAGE`
  (see *Auth*). `GET /api/apps/{id}` answers an app you hold no level on with the
  same 404 as a missing id. `POST /{id}/subscribe` survives as a no-op that checks
  `USE`, so links from before sharing still resolve; it grants nothing. Anyone
  could open a personal view by id before; the access migration gave each such
  subscriber `USE`, so nobody lost a view they had.
- **Saves write the draft** (`services/drafts.py`). A manager's `PUT` writes the
  app's row in `object_drafts`, in place, so a drag adds no version;
  `POST /{id}/publish` inserts the next `dashboard_views` version from it and
  drops it. `USE` holders read `drafts.latest` (newest published), `MANAGE`
  holders `drafts.current` (the draft over it), unless they ask for
  `?mode=published`. The draft is a separate row, not an unpublished version,
  because code from before drafts reads the newest version as live: a draft
  stored as a version would be shown to everyone on a rollback. `/discard` drops
  the draft (refused when nothing is published, see above); `/revert` copies a
  published version into it. `GET /history` needs `MANAGE`, as a Databricks
  dashboard's version history does; the UI offers it only to managers. The
  widget `/history` stays at `USE` because version pinning reads it.
- **Links name published apps** (`services/app_links.py`). `GET /{ref}`,
  `/{ref}/widgets` and `/{ref}/subscribe` take an id, a link name, or
  `<name>-<id>`, via `app_store.resolve_ref`; everything else takes ids. Names
  live in `app_links` (slug → app id, every name a view has held, newest wins) and
  are claimed on publish (inside a savepoint, so a failure can't fail it) and by
  `init_db`'s backfill — never on a read, because opening an app must write
  nothing. A never-published app is linked as `<name>-<id>`. A name resolving
  doesn't bypass access: the ACL is checked on the id it resolves to, and a caller
  with no level gets the same 404. A slug may not end in a UUID, or a view named
  after another's `<name>-<id>` link would answer for it. Permanent delete frees
  the names; archive keeps them.
- **Composition: a view lends its widgets** (`custom_widgets.lent_by_views`).
  `USE` on an app grants read of the latest published version of every widget it
  places, and of each exact version `props._version` pins — never a draft, and
  nothing it doesn't place; `MANAGE` lends the same for what its draft places.
  The widget's own ACL isn't consulted, because the app's managers chose to show
  it. Lent rows come back `in_library: false`: the registry needs them to render
  the view, and the library must not offer them. A placed widget that has never
  been published renders as a "Not published yet" card. In the draft, managers
  see their own widget drafts.
- **`POST /api/apps/compose`** copies existing views/apps into a new app the
  caller owns, a tab each. Sources are untouched (copy, not move) so their links and
  subscriptions keep working The app takes the first source's `theme`, since a
  view has one look and tabs carry none.
- **`POST /api/apps/look`** turns a description into a `theme` for View
  settings to show (`services/look_helper.py` prompts and validates; the call
  is `widget_studio.quick_helper_reply`, signed by the service principal like
  every studio inference). It saves nothing, so it needs only a signed-in caller;
  the save that follows is checked like any other. A `primary` / `dark` too light for
  white text is deepened (same hue) rather than dropped: models reach for the
  bright accent a description implies, and dropping it left the field empty.
- **`GET /api/apps/{id}/widgets`** is the app's widget bundle: the rows
  `/api/widgets/custom` would send, for only the widgets the app's tabs place,
  plus the source of any version a tab pins (`props._version`). Both go through
  `custom_widgets.library_rows` and `shape_rows`, so they can't drift apart, and
  the bundle applies the composition rule above (`bundle_rows`). The workspace doesn't
  call it; a standalone app opens with it instead of the whole library.

`tests/test_app_spec.py` and `tests/test_apps_routes.py` hold all of the above.

### Publishing an app (`routes/apps.py`)

An app's row is published alone, and the widgets and agent it names have drafts
and versions of their own, so a view can go out showing widgets its managers never
published. Two things cover that:

- **`POST /api/apps/{id}/publish/preflight`** writes nothing. It lists placed
  widgets that are never published or have unpublished changes, and the pinned
  agent (app or tab) in either state, marking which the caller can manage. It
  needs `MANAGE` on the app. Its `blocking` list is why publishing would be
  refused: no draft, or the certified-widgets rule below.
- **`include`** on `POST /{id}/publish` publishes those widgets' and the agent's
  drafts first, each needing `MANAGE` on *that* object, in the same transaction
  as the app. A refusal for one leaves everything unpublished.

Nothing is refused for being unpublished; the Publish dialog shows the preflight
and offers to include what the caller can manage. The one refusal is the
certified-widgets setting (`require_certified_for_global_views`, labelled
"Shared views may only contain certified widgets"; the key kept its old name
because saved rows are found by it). When it is on, an app shared with anyone
besides its owner (`app_store.certification_problem`, judged from the ACL
summary, not `is_global`) can't be published while any widget it places on any
tab has an uncertified current version; checking only the first tab would let
one through a tab over. Built-in widget types count as certified. The check runs
after `include` is published, inside the same transaction, so a refusal rolls
those back too. On publish the row's legacy `is_global` is set to whether the
ACL includes Everyone, for code from before sharing that still reads it.

Certifying (`POST /api/widgets/custom/{id}/certify`, `{version?, certified}`) is
a `MANAGE` action on the widget and defaults to the latest published version;
`drafts.RESET_ON_PUBLISH` clears it on every new version, because certification
reviews one version's code. Publishing a widget re-runs `_reject_unsafe` on the
draft, so nothing goes live that the current rules would refuse to save.

## Who made what (`services/creator_stats.py`)

The Widget Library credits an author on every card and ranks creators behind the
**Top creators** button (`GET /api/widgets/creators`). Three figures go into a
rank, and they answer different questions: `published` (live widgets authored),
`reach` (how many *other* people have one on a view) and `placements` (appearances
across everyone's views), weighted 5/3/1 and always reported alongside the score so
a rank can be explained rather than asserted.

The parts that matter if you touch it:

- **Using your own widget is not reach.** Otherwise the way to the top of the board
  is to fill your own dashboards, and nobody trusts it twice.
- **Placeholder authors are never credited.** `"dev"`, `"unknown"` and friends are
  what a failed identity lookup used to write; counting them invents a prolific
  creator who doesn't exist. They're reported as `unattributed_widgets` instead,
  because a silent drop hides the identity problem that caused them.
- **`tally` takes plain data**, so the ranking is tested without a database
  (`tests/test_creator_stats.py`). Keep the queries out of it.
- `widget_runs.username` records *who* added a widget, not just that it was added;
  `"unknown"` is stored as NULL so an unresolved caller never becomes a person in
  the reach count. Rows predating the column are counted as adds and nothing more.
- **The author of an old widget is gone and cannot be computed.** The resolver that
  wrote `created_by` shipped broken in the same commit that added the column, so
  nothing before the fix has a real name on it, and nothing else recorded one:
  `action_logs` has no username, `widget_runs` says who *used* a widget, and a view
  only says who placed one. Don't write a backfill from those — it would invent
  attribution. `POST /custom/{id}/claim` lets the person who recognises their own
  work say so, which is the only honest route back. It fills a blank and never
  changes a real name: the placeholder test is repeated *inside* the UPDATE (via
  `unowned_sql`, the same `NOT_A_PERSON` list rendered for Postgres) so two people
  claiming at once can't overwrite each other, and the loser is told who won.

## Agent runtime (`services/agent_runtime.py`)

A self-contained streaming tool-calling loop that runs **in this process** —
this is the primary path (`AGENT_LOCAL_RUNTIME` defaults to `true`). Setting it
to `false` makes `routes/agent_proxy.py` forward to the external consolidated
agent at `CONSOLIDATED_AGENT_URL` instead. It emits SSE frames shaped for the
existing frontend hook: `chunk`, `reasoning`, `reclassify`, `tool_calls`,
`trace_id`, `final`, `error`.

**The answer is the last step's text, not every step's.** A step that ends by
calling a tool was thinking out loud ("let me check the orders file"), so its prose
goes out as `reclassify` — the client moves it into the thinking disclosure — and
only the final step's text becomes the answer. Accumulating all of it and sending
that as `final` meant the user read the same prose twice, once as it streamed and
again inside the answer. It also means a run that exhausts the step limit has no
answer to give, by definition: every step it took ended in a tool call, and that
prose is already on screen as thinking, so it says so rather than repeating it.

Defaults: model `databricks-claude-sonnet-4-6`, 8 steps, 16000 max tokens, 90 s per
tool call, 10 s heartbeat. The first three are admin-settable — see *Deployment
settings* below — with `AGENT_RUNTIME_MODEL` / `_MAX_STEPS` / `_MAX_TOKENS` as
fallbacks. The heartbeat matters: without periodic `: keepalive` bytes, proxies
close a slow SSE stream mid-turn.

Two behaviors that look odd but are intentional:

- **Auth is split.** The LLM call is signed by the service principal
  (`AGENT_RUNTIME_LLM_AUTH=sp`, the default) so users don't each need a
  foundation-model entitlement; every tool executes under the caller's OBO
  token. See `_llm_auth_mode` for the reasoning.
- **`max_tokens` is clamped per model, learned from failure.** The setting is one
  number for the deployment but caps are per model (128000 on Claude Sonnet 5 and
  GPT-5.6, 8192 on `meta-llama-3-1-8b` and `gemma-3-12b`), and there is no API that
  reports them. `_stream_completion` retries a rejected turn once with the cap named
  in the error and remembers it per model for the life of the process, so picking a
  small model in the Admin Panel can't wedge chat.
- **The general Genie server is Genie One.** The server list (`mcp_servers`) defaults
  to `/api/2.0/mcp/sql` plus `/ai-gateway/mcp-services/system.ai.genie_one_mcp`
  (`GENIE_ONE_PATH` in `agent_runtime.py`). It replaces `/api/2.0/mcp/genie`,
  which is sunset on 2026-10-31: same four tools, same `question` /
  `conversation_id` arguments, and it needs only the `ai-gateway` scope. A
  setting that still names the old path is read as Genie One
  (`_mcp_server_urls`), and Genie One keeps the label `genie`, so saved tool ids
  (`genie/…`) keep matching. `research_tools._genie_client` uses it too.
  Genie One can end a response as `incomplete`; `_genie_wait` treats that as
  final and returns what it has. The per-space servers are still
  `/api/2.0/mcp/genie/<id>`; no sunset date is announced for them.
- **Genie One's ask tool is `genie_one` here and `genie_ask` on the server.**
  Nobody using the app knows it by the server's name, so `_server_tools` lists it
  as `genie/genie_one` (`GENIE_ONE_TOOL`) with `GENIE_ONE_DESCRIPTION`, and keeps
  the server's name as the entry's `upstream_name`, which `_build_tools` puts in
  `real_name` for the call (`agent_runtime.GENIE_ONE_ASK_TOOL`). Only the general
  server's tool is renamed; a space's tools keep their own names. Agents saved
  with `genie/genie_ask` (or bare `genie_ask`) are not migrated:
  `agent_studio_store.canonical_tool_ids` maps them on read and on save, and the
  runtime maps them again for a "Try it" draft. Rows are versioned, sit in
  drafts, were consolidated from the retired Dev/Test schemas and also arrive by
  snapshot import, so a read-time alias covers what a migration would miss. The external agent
  (`AGENT_LOCAL_RUNTIME=false`) is sent the servers' names (`upstream_tool_ids`).
- **Genie is made synchronous.** The Genie MCP server is a polling
  API: the ask tool returns a handle and `genie_poll_response` retrieves the
  answer. Handing the model a handle is useless, so `_exec_genie` drives the
  poll loop internally and `genie_poll_response` is hidden from the tool list
  the model sees (`AGENT_RUNTIME_GENIE_TIMEOUT`, `AGENT_RUNTIME_GENIE_POLL_MS`).
  Genie's own description of its ask tool says to poll, so `discover_mcp_tools`
  replaces Genie One's and puts a note in front of each space's, saying the call
  waits for the answer itself. Without that, Agent Studio's authoring assistant
  reported the hidden poll tool under `review.missing` (`tests/test_mcp_catalog.py`).
  Each Genie space also has a server of its own (`/api/2.0/mcp/genie/<id>`)
  whose tool names needn't match the general one's, so discovery records each
  ask tool's `poll_tool` and `_exec_mcp` polls with that. Its arguments differ
  too: a space's poll requires `message_id` where Genie One's takes
  `response_id` (`_genie_poll_args`), and a space answers with Genie's message
  as JSON and no `final_answer`, which `_space_answer` turns into the prose, the
  SQL and a capped table. A space's ask holds the request open 10–15 s before
  answering or handing back a handle, which is what the MCP client's timeout
  (below) has to allow for.
- **The tool catalog is unfiltered; the picker filters.** `discover_mcp_tools`
  asks the configured servers (the `mcp_servers` setting, see *Deployment
  settings*; `AGENT_STUDIO_MCP_SERVERS` is its fallback) and, with
  `genie_spaces=True`, one server per Genie space the caller can list
  (`AGENT_STUDIO_MAX_GENIE_SPACES`, 200). Nothing is dropped: plumbing such as
  Genie's poll tool comes back with `internal: true`, and every entry carries a
  `source` the Agent Studio picker hides or shows by (Genie spaces start hidden).
  Servers are listed in parallel and each list is cached per credential for
  `AGENT_STUDIO_MCP_CACHE_SECONDS` (300; `GET /tools?refresh=true` bypasses it),
  because the runtime rebuilds its tools every turn and a cold list is a session
  per server. That is also why the runtime never lists every space: a saved
  agent's tool ids name their servers (`server_for_tool_id`, `genie.<id>/…` →
  `/api/2.0/mcp/genie/<id>`), so it opens only those, and the default agent
  stays on the configured servers. The picker (`GET /tools`) alone also passes
  `extra_kinds=True`, which adds `extra_mcp_servers`: UC function schemas (one
  `system.information_schema.routines` read as the caller on `SQL_WAREHOUSE_ID`,
  which can start the warehouse), vector-search schemas (endpoints → indexes) and
  external MCP connections (UC HTTP connections with `is_mcp_connection`). Each
  kind is cached and degrades to nothing on failure, so a missing user scope
  (`vector-search`, `catalog.connections`) empties that kind and breaks nothing
  else; `AGENT_STUDIO_MAX_EXTRA_SERVERS` (100) caps each kind separately (a total cap
  once let 100 function schemas hide every external connection). A server that
  refuses `list_tools` is retried twice with a short wait, since opening the
  picker can list a couple of hundred at once and the workspace answers the
  overflow with 429. They start hidden in the picker. AI Gateway services under `system.ai`
  (`/ai-gateway/mcp-services/…`) and custom MCP apps are not *discovered*:
  listing them needs the `unity-catalog` user scope, which the App doesn't
  request, and an app's tools can't be reopened from its tool id. Name one in
  the server list and it is listed (sources `gateway` / `app`, both shown by
  default in the picker since only an admin can put them there), and a
  `gateway.` id round-trips through `server_for_tool_id`; an `app.` id doesn't.
  A gateway server that holds a per-user credential (`system.ai.atlassian`, i.e.
  Jira and Confluence) refuses `list_tools` until that person signs in under AI
  Gateway → MCPs. `needs_sign_in` spots the refusal, it is not retried, and
  `GET /tools` returns it in `problems` with `sign_in: true` so the picker says
  what to do instead of showing nothing. `problems` also names any *configured*
  server that failed — an admin typed it, so silence reads as a typo nobody can
  see — but not failing discovered servers, which can number in the hundreds.
  Everything here is the app's own workspace.
  Status comes from `structuredContent`; the reply *text* is markdown for a model
  (`**Status:** completed`, "Still running…"), and `_genie_status` reads that
  header as a fallback — without it, a reply missing structuredContent never
  reads as finished and the loop waits out the full timeout on a done answer.
  `_genie_start` / `_genie_wait` are the two halves, so a caller that ran out of
  time can wait on the same handle again rather than re-ask.
  SQL is deliberately *not* wrapped this way — `execute_sql` answers inline for
  normal queries and `poll_sql_result` stays model-facing by design, which is
  part of why the step cap is 8 rather than 6.

### MCP connections (`services/mcp_client.py`)

Every MCP call — the runtime's tools, the picker's discovery, the studios'
`ask_genie` — goes through `mcp_client(server_url, ws)`, not
`databricks_mcp.DatabricksMCPClient`. On mcp 2.x, `databricks-mcp` 0.9.2 (the
newest release) builds its HTTP client with no timeout, so httpx's 5 s default
applied to every read and every Genie space call failed with a `ReadTimeout`.
The client is built from public pieces only (mcp's `Client` and
`streamable_http_client`, `databricks_mcp`'s `DatabricksOAuthClientProvider`),
with the read bounded by `chat_tool_timeout` and never below 30 s. Two things
to keep:

- **Don't reach into `databricks_mcp` privates to fix something.** Pinning
  `mcp<2` would also have restored the timeouts, and it was rejected: it freezes
  the client that carries users' tokens and brings the bug back on any upgrade.
  `tests/test_mcp_client.py` fails if a piece the client is built from moves.
- **Read both spellings of a result's fields.** mcp 2.x says `structured_content`
  / `is_error`; `_parse_mcp_result` read only the 1.x names, so a tool error read
  as an answer. Errors are also unwrapped from the transport's task group,
  which reported every failure as "unhandled errors in a TaskGroup".

Tests replace `services.mcp_client.mcp_client`, where the call sites look it up.

`RUNTIME_CONTRACT`'s *Charts* section tells the model to answer with a fenced
`vega-lite` block of inline `data.values`, which the drawer renders (see
src/AGENTS.md → Assistant panel). Keep it short: it is paid on every turn.

### Knowledge about the app itself (`services/app_help.py`)

Users ask the assistant how the Command Center works, not only what their data
says, so every agent gets both halves of `app_help.py`:

- `APP_PRIMER` is spliced into the system prompt as `APP_KNOWLEDGE`, between the
  runtime contract and the persona (neutral facts, so a profile persona still
  wins any conflict). It is the vocabulary — widget, view, domain, the three role
  Can use / Can manage, highest-level-wins, draft vs published — that the agent must not get
  wrong when it answers without calling a tool. Keep it short; it is paid for on
  every turn. A `base: none` (standalone) profile skips it, like the rest of the
  scaffold.
- The `app_help` tool searches `services/app_guide.md` for the detail: exact
  steps, sharing and publishing rules, agent authoring. Registered before MCP discovery and
  attached to *every* agent, including profiles with a curated tool list, because
  an agent without it invents answers about the UI. Section titles are advertised
  in the tool description, so renaming a `##` heading changes what the model
  knows it can ask for.

`app_guide.md` describes app behavior and drifts silently when the app changes —
update it alongside `src/pages/guide/sections/*.tsx` (the human guide). Relevance is keyword scoring
weighted by term rarity; the guide says "widget" everywhere, so without that
weighting a question like "get my widget into prod" never reaches the publishing
section. `tests/test_app_help.py` pins that and the topic list.

Author-written Python tools execute via `_exec_python` in a subprocess with
credentials stripped from the environment (`_run_python_sandbox` in
`routes/agent_studio_profiles.py` handles the authoring-time trial run,
`AGENT_STUDIO_PY_SANDBOX_TIMEOUT` bounds it). Never widen that environment to
pass secrets into user-authored code.

## Conversations and attachments

Three tables (`chat_conversations`, `chat_messages`, `chat_uploads`) and three
services. The load-bearing decisions:

- **History comes from the database, not the request.** `proxy_chat` writes the
  user turn before the loop starts (`_open_turn`) and the answer as it settles
  (`_turn_recorder`, passed to the runtime as `on_finish`), then reads prior turns
  with `conversation_store.history_for_model`. A `conversation_id` in the request
  body is what switches this on; Agent Studio's "Try it" omits it and stays
  ephemeral. Persisting from the runtime's worker thread rather than the streaming
  generator is deliberate — the answer is recorded even if the browser goes away
  mid-stream. Storage failures log and degrade to an unpersisted turn: losing the
  history of an answer beats losing the answer.
- **A disconnect is not a Stop.** Reloading or switching conversation drops the
  stream too, and that turn should still land. So each drawer turn carries a
  client-issued `turn_id`, and Stop first calls `POST /api/agent/chat/stop` with
  it, which inserts into `chat_turn_stops` (a table, because the request may
  reach the other worker; keyed by turn, because Stop can beat the turn's own
  message and even the conversation row into the database), then aborts. The
  runtime's `should_stop` only turns true once the client has gone, and then
  either immediately (unpersisted: nothing would ever show the rest) or when
  `conversation_store.stop_requested` confirms it, polled at most once per
  `STOP_POLL_SECS`, so a connected turn never touches the database for this. A
  stopped turn closes the model stream, runs no further tools, and settles with
  its partial text plus `_Stopped._`. A tool already running finishes first.
- **The client's history shape was the bug, not just a wart.** The drawer labels
  assistant turns `type: "agent"`; read as a role, that failed the runtime's
  `user`/`assistant` filter and silently dropped every prior answer. `_normalize_role`
  maps it now, but the real fix is that persisted conversations never consult the
  client transcript at all.
- **A replay is text, and the model knows what it lost.** `history_for_model`
  appends `[tools used: …]` to assistant turns that had tool calls, and
  `_system_prompt` explains the line. Without it, an agent asked "what did you tell
  me earlier?" sees a bare figure with nothing behind it and announces to the user
  that it made the number up. Cheaper than replaying whole tool exchanges, and it
  fixed the behaviour outright.
- **One connection per read that the drawer waits on.** Restoring a conversation
  needs metadata, turns and files; `conversation_store.read_conversation` gets all
  three through one cursor (`upload_store.fetch_uploads` takes it). That halved the
  endpoint back when every connection was a fresh handshake, and it still helps:
  each connection a caller borrows costs a round trip to start and end its
  transaction, so several reads through one cursor beat several connections.
- **A file's content never enters the prompt.** `upload_tools.attachments_prompt`
  adds a constant-size card (columns, row counts, a few sample rows) and registers
  `inspect_file` / `query_file` / `search_file` / `read_file`; the agent pulls what
  it needs. `query_file` takes a *structured* spec — computed columns, filters,
  group-by, aggregations, sort, paging — not a pandas or SQL string, because
  evaluating model-authored code in the web process (which holds the caller's
  credentials) is not a trade worth making. Computed columns are not a nicety:
  revenue is units times price per row, `sum(units) * mean(price)` is a different
  number, and without them a model will page through the file by hand or answer
  wrongly. `tests/test_upload_tools.py` pins that distinction.
- **Images and short PDFs go to the model directly** (`services/native_files.py`,
  shared with Widget Studio — a screenshot of a widget is an image with no text in
  it, and the flavor table is not worth writing twice), because
  extraction cannot read a chart or a scan. The content part differs by provider —
  Claude takes an Anthropic `document` block and rejects `file`, GPT takes `file`
  and rejects `document`, and anything else gets neither and falls back to the
  extracted text. That is why extraction always runs. A PDF over
  `AGENT_RUNTIME_NATIVE_PDF_PAGES` (20) with real text stays on the tool path;
  pushing 300 pages through the context window to answer one question is the thing
  this design exists to avoid. Native files ride on the current turn's user
  message only, so re-sending never compounds across a conversation.
- **Images are shrunk to fit before they go** (`native_files.fit_image`, both for
  uploads and Widget Studio's preview capture). Anthropic refuses an image whose
  base64 passes 5 MB, which a full-resolution Retina screenshot does, and scales
  past 1568 px anyway; so anything larger on either count is resized to that long
  edge, as PNG, or JPEG when PNG still won't fit. That is why images skip the
  `AGENT_RUNTIME_NATIVE_FILE_MB` cap. One that can't be made to fit is left out
  rather than failing the call. Needs `pillow`, listed in `pyproject.toml`
  because locally only matplotlib brings it.
- **Nothing lives in process memory.** Two uvicorn workers mean an upload handled
  by one is invisible to the other, so every tool call re-reads from Postgres.
  Spreadsheets are normalized to Parquet (one member per sheet in a zip, described
  by its own `manifest.json`) at upload time so that re-read is cheap; the cache in
  `upload_store` is a read-through cache of immutable derived bytes and is safe to
  be cold. Parsing itself runs as a FastAPI background task, since a 25 MB workbook
  is far too slow to hold a request open.
- **Limits** are `CHAT_MAX_UPLOAD_MB` (25), `CHAT_MAX_ATTACHMENTS` (5 per
  conversation), `CHAT_KEEP_CONVERSATIONS` (50 per user, pruned when a new
  conversation is created). `file_extract.py` owns parsing and has no database or
  HTTP imports at all — keep it that way, it is the only part that is cheap to test
  exhaustively.

## What a request is allowed to spend (`db_pool.py`, `services/caller_identity.py`)

Every request used to open a Postgres connection, resolve the caller against SCIM,
and build a `WorkspaceClient`, none of which it reused. Measured from a laptop that
was ~1.9 s of setup for ~100 ms of work, and one call of each of the nine main
endpoints took 12.9 s; they now take 2.2 s, and fired in parallel the way a page
load fires them, 8.4 s became 0.3 s. Three things changed, and each is easy to
undo by accident.

- **Connections are pooled per env** (`db_pool`). `get_db_connection(env)` returns
  a `PooledConnection` whose `close()` checks it back in. Keep calling `close()` —
  it is now the *cheap* thing — but the pool also reclaims connections on garbage
  collection, which is what saves the many routes that only close on the happy
  path. Read the module header before changing it: the pool is credential-aware
  because Lakebase passwords are minted tokens that expire, it never blocks (past
  `LAKEBASE_POOL_MAX_SIZE` it opens an unpooled connection rather than queueing),
  and it uses an idle timeout with a warm floor rather than a hard idle cap — a cap
  made every page load open and close the same connections. `pooled=False` is for
  work whose session state must not be inherited; `init_db` uses it because it
  holds a session-level advisory lock.
- **`search_path` travels in the connection request.** `CREATE SCHEMA IF NOT
  EXISTS` plus `SET search_path` plus the commit was three round trips on every
  connection (~400 ms from outside the workspace) to assert something only the
  first connection can change. The schema check now runs once per process and the
  search path rides in libpq's `options`.
- **The caller is resolved once per credential** (`services.caller_identity`,
  default 300 s). `roles._get_current_username` and `get_user_entitlements` both
  read it, and one SCIM call answers both — routes that wanted both used to make
  two. Everything funnels through those two helpers, so cache there rather than
  adding another cache; `agent_proxy` had its own and it has been folded in,
  because two caches of the same username can disagree and conversations are keyed
  by it.
- **`WorkspaceClient`s are cached per credential** (`middleware.auth._cached_client`,
  default 300 s). The constructor resolves auth and then builds the SDK's whole
  service surface: over 100 ms per request against a route that did nothing else,
  and it is CPU under the GIL, so concurrent requests queued behind it. Every
  factory in `middleware/auth.py` and `agent_studio_store._client` goes through it.
- **A response is a cost too, and the widget library was the worst of them.**
  `GET /custom` answers the app's first request, and it used to be `SELECT *`:
  every version of every widget with its full source and its base64 thumbnail.
  Widget Studio publishes a version per save, so it grew with use — a library of
  30 widgets with 8 saves each measures 10 MB and 900 ms, against 0.2 MB and 75 ms
  for what it sends now (`tools/widget_payload_probe.py`, which will seed a dev
  database if yours is empty). Old versions keep their metadata, because the
  version dropdown needs to know they exist, and give up their source, which
  `/version` will hand over if anyone pins one; thumbnails moved to
  `/custom/snapshots` for the library to fetch when it opens. Anything you add to
  this response is paid for by every user on every page load — including the ones
  who never open the library.

### The username is data, not a label

`caller_identity.username` returns a real address or `"unknown"`, and nothing in
between. Rows all over the app are owned by that string — views, conversations,
uploads, widget authorship — and a widget can write it into a table of its own, so
a plausible-looking stand-in is worse than an honest failure: after the fact it is
indistinguishable from real attribution. Three things went wrong here and all three
are worth not repeating:

- `custom_widgets.py` defined its own resolver that **shadowed the import** from
  `roles`, and it called `w.current_user()` — but `current_user` is a property
  returning a `CurrentUserAPI`, which is not callable. Every call raised, so every
  widget was published as `"dev"` locally and `"unknown"` in the deployment. Use
  `roles._get_current_username`; don't add a local copy.
- `_get_user_permissions` seeded the literal `"dev"` in the permissions-disabled
  branch and only replaced it inside a bare `except: pass`. Bypassing permission
  *checks* must never bypass identity.
- The same function omitted `username` from its other return shape, so turning the
  checks on made everyone `"unknown"` in the UI. Both shapes carry it now.

Local runs authenticate as a service principal, which SCIM answers for with an
application id — a bare UUID — or with nothing. `DEV_USERNAME` (only honoured when
`DEV_MODE=true`) covers **both**, so a developer owns what they create. Covering
only the "nothing" case was the same bug one layer down: the usual outcome is a
UUID, which is not `"unknown"`, so it sailed past the override.

An application id is a truthful owner and stays on the row, but it is not a person:
`creator_stats.is_person` excludes it, alongside the placeholders in `NOT_A_PERSON`,
so no UUID collects points on the leaderboard. That same predicate is what decides
whether a widget **has** an owner at all — `custom_widgets.delete_custom_widget`
uses it, because a row nobody owns should be anyone's to tidy up. Testing for
`"unknown"` alone there left every widget the bug stamped `"dev"` undeletable by
anyone. Comparisons go through `creator_stats.same_person` (and `isSamePerson` in
`src/creators.ts`), since SCIM is not consistent about case.
`tests/test_caller_identity.py` guards the lot, including that no caller ever
resolves to `"dev"`.

`/api/health` reports the pool's counters per worker. `reused` far above `opened`
is healthy; a climbing `overflow` means bursts exceed `LAKEBASE_POOL_MAX_SIZE`, and
a climbing `gc_released` means routes are leaking connections rather than closing
them. `LAKEBASE_POOL=0` turns pooling off if you need to compare behaviour.

### Blocking work belongs in a sync handler

FastAPI runs `def` handlers in a thread pool and `async def` handlers on the event
loop. Twenty-three route handlers were `async def` with no `await` in them, doing
blocking psycopg2 and SDK calls, so each one held the loop for its whole duration:
requests that should have overlapped ran one at a time, and they stalled the
agent's SSE streaming too. Sixty requests, twelve at a time, took 9.0 s; as sync
handlers they take 1.7 s. **Declare a handler `def` unless it actually awaits
something.** `main.py` raises the thread-pool limit to 64 for this.

Two probes live in `tools/`: `db_latency_probe.py` splits a Lakebase round trip
into credentials, handshake, schema statements and query, and `api_latency_probe.py`
times the endpoints against one or two servers (run one with `LAKEBASE_POOL=0` for
a comparison). `db_pool_soak.py` checks the pool under load — writes still commit,
a failing request doesn't poison a connection, and no lease is lost.

## Deployment settings (`services/settings_store.py`)

Which model each LLM caller uses — chat, widget generation, the studio's cheap
side-calls (`widget_helper_model`, default `system.ai.gpt-6-luna`, falling back to
`widget_model` where that isn't served), and agent
authoring — plus the chat agent's step and
token caps, are rows in `app_settings` edited from Admin Panel → Settings
(`routes/app_settings.py`, Administrators only). Resolution is
**row > env var > built-in default**, so an untouched deployment behaves exactly as
it did when these were env-only, and saving a setting blank deletes the row rather
than pinning an empty value. Reads are cached ~15 s and never raise: a settings
outage falls back to the env var instead of breaking chat.

Two things to keep in mind when touching this:

- **Settings live in the settings schema, not the content one.** Content is in
  `content_env()`'s schema; settings are in `APP_SETTINGS_ENV`'s (default `dev`)
  because they describe the deployment, not the data it addresses. The access
  tables (`object_permissions`, `app_admins`, `known_principals`), `cutover_log`
  and the retired `role_mappings` live there too, for the same reason. The two defaults differ —
  `prod` for content, `dev` for settings — because each is where that data already
  was; don't "fix" one to match the other without moving the data.
- **The base path is derived from the model name**, by `base_path_for_model`. A
  `system.ai.…` name is an AI Gateway name and 404s (`ENDPOINT_NOT_FOUND`) on
  `/serving-endpoints`; a bare endpoint name works there and also on the gateway.
  The gateway alias is the endpoint name minus its `databricks-` prefix, which is
  how `routes/app_settings.py` synthesizes the picker list — there is no listing
  API for gateway model names, and `system.ai` in Unity Catalog is a different,
  incomplete set. `AGENT_RUNTIME_LLM_BASE_PATH` / `AGENT_STUDIO_LLM_BASE_PATH`
  still override the derivation.

New settings are one entry in `SETTING_SPECS`; the admin UI renders from that
(label, help text, bounds, and which card it appears under via `group`) with no
frontend change. `kind` is `endpoint` (model picker), `int` (bounded number),
`bool`, `json` (validated on save, so a typo surfaces in the form and not later as
an agent failing), or `hosts` (one Databricks App host, or one workspace as
`*-<workspace-id>.<region>.databricksapps.com`, per line), or `mcp_servers` (the
MCP servers every agent gets, one per line). A new kind
needs a branch in `SettingsManager.tsx`, which otherwise renders it as a number.
`hosts` values are written into the CSP header, so `get_host_list_setting`
re-validates them on read: a row can arrive by data migration without passing
`validate_value`. `get_mcp_server_list` re-validates for a different reason:
every server on that list is opened with the caller's OBO token, so a row may
name only this workspace — a `system.ai.<name>` gateway server, a path under
`/api/2.0/mcp/` or `/ai-gateway/mcp-services/`, or a URL on `DATABRICKS_HOST`'s
host, reduced to its path (`parse_mcp_server`). A custom MCP app is refused
there, since `databricksapps.com` is every customer's; only the env var, which
the deployer controls, may name one, and it passes through unchecked. A row with
nothing usable left falls back to the env var rather than to no tools.

The limits that live here are the ones a big request runs into: tool and Genie
timeouts for chat, and for Widget Studio a token ceiling and a wall-clock
`widget_timeout`. Anything time-related must be enforced where the work happens and
reported to the client — `/api/agent/widget/generate` returns `timeout_seconds` and
the studio sizes its own polling from it, because a client giving up on its own
schedule made raising the setting do nothing.

## Timers, optional features and the activity log (`services/background.py`, `services/capabilities.py`, `services/activity.py`)

Three small services that several features share. Each one's module docstring
explains its design; this is what you need to use them.

**Work on a timer goes through `background.register(name, every_seconds, fn)`**,
called in `main.py`'s startup between the `from services import background,
capabilities` line and `background.start()`, so everything that runs on a timer
is listed in one place. Don't start a thread or an `asyncio` task of your own:
the App runs two workers, and either may restart at any moment. Every worker runs
the same loop, and a job runs only when its advisory lock is free *and* a
conditional upsert on its `background_jobs` row says it is due. That gives one run
per interval across the deployment, never overlapping. `fn` takes no arguments
and runs on the loop's thread with no request behind it, so there is no user
token: work that must act as a user needs that user's stored credential, which is
what the token vault is for, never the service principal. A job that raises is logged and recorded on its
row as `failed`, and the loop moves on. The minimum interval is the 5-second tick.
`BACKGROUND_JOBS=0` turns the loop off for tools and probes that import the app.

**A feature that needs customer setup registers a check with
`capabilities.register(name, label, fn)`**, in the same place. `fn` returns
`capabilities.result(available, mode=None, missing=[...], next_step="...")`;
write `missing` and `next_step` for the customer's admins, because the Setup card
in Admin Panel → Settings shows them verbatim. Results are cached for 60 seconds,
and saving a setting clears the cache on that worker. A check that raises reads as
unavailable rather than breaking the page. Gate server-side work with
`capabilities.available(name)` (or `get(name)` for the mode), and the browser with
`useCapabilities()` from `src/capabilities.ts`. Off until set up turns a feature
off; it never skips a safeguard, so a check reports what is missing and never
stands in for it. `GET /api/capabilities` gives everyone `name`, `label`,
`available` and `mode`, and Administrators also `missing`, `next_step` and the
background jobs' last runs; `?refresh=true` from an Administrator skips the cache.

**Record what happened with `activity.record(who, verb, object_type, object_id,
detail)`** after the action has committed. The verb is dotted lowercase, object
first (`view.publish`, `email.send`, `schedule.run`). `detail` is metadata only:
`clean_detail` keeps at most 20 short scalars and drops any key that names user
content (`prompt`, `body`, `sql`, `results` and the rest of `_CONTENT_KEYS`),
because an audit trail that copied people's work would be an ungoverned second
copy every administrator could read. It never raises, and it writes synchronously,
so call it from a sync handler (see *Blocking work belongs in a sync handler*).

`activity_events` and `background_jobs` live in the content schema, created by
`_create_operations_tables` in `database.py`. Each feature's own tables get a
`_create_<feature>_tables` function there too, called from the same block of
`init_db`, rather than DDL in the feature's module: `test_data_migration.py` reads
`database.py` to check that every table is either copied by Data Migration or
listed in `NOT_COPIED`. `activity_events` travels with the activity group;
`background_jobs` is never copied, since it describes this deployment's own runs.

## What each model will accept (`services/llm_params.py`)

Endpoints disagree about the optional parameters, so nothing optional is sent unless
something asks for it. Widget Studio used to pin `temperature=0.1`, and pointing the
Settings page at a model that refuses temperature — newer Claude and the reasoning
models all do — failed every generation while chat, which never sent it, kept
working. Policy per model, in three layers:

    built-in rules  <  admin override (`model_params`)  <  what the endpoint told us

The last layer does the work: a rejection names its cause ("unsupported parameter:
'temperature'", "max_tokens: 32000 > 8192", "reasoning: Field required"), so `adapt`
reads it, changes the policy and the call is retried — `with_adaptation` is that
loop, and every LLM call site goes through it. The exception is Agent Studio's
authoring run, which can't be rerun from the top once a poll may have shown its
text: it runs the same `adapt` loop itself, and only until prose or a tool pill is
on the job (`tests/test_agent_studio_authoring.py`). The lesson is remembered per
process. The settled job also carries `draft_error` when the reply attempted a
draft (a ```json fence or a `"prompt"` key) that `_read_draft` couldn't use: cut
off (the model's `finish_reason` says whether by the length limit) or invalid JSON
with its position. The studio shows it; without it the run looked like a success.
Two rules worth knowing before you change it:

- **A parameter is only dropped if it's in `_DROPPABLE`.** An error naming
  `messages` or `tools` is a broken request, and silently dropping either would turn
  a loud failure into an agent that has mysteriously lost its tools.
- **A missing parameter is only supplied if it's in `_SUPPLIABLE`.** We can name a
  reasoning effort; we are not going to invent a value for `safety_mode`.
- **`model_params` may only name a key in `CONFIGURABLE`.** That setting's value is
  spread into the request the app builds, next to `api_key`, `base_url`, `model` and
  `messages`. Without the closed list an entry could replace any of them — a
  `base_url` would mail the app's own credential and every prompt to another host,
  and a `model` would collide with the argument already there and fail the call with
  an error `adapt` cannot read. Enforced twice: `settings_store.validate_value`
  refuses it on save with the offending names, and `_admin_overrides` drops it on
  read, for a value stored before that check existed. Call sites also put the keys
  they own **last** in the kwargs dict, so ordering can't be the weak link either.

LangChain callers use `langchain_params`, not `request_params`. `ChatOpenAI` renames
`max_tokens` to `max_completion_tokens` itself, and a `reasoning` **object** makes it
switch to the Responses API (`input`, `max_output_tokens`), which Databricks serving
endpoints do not speak — so the effort has to travel as flat `reasoning_effort`.

## What a message may look like (`services/llm_client.py`)

Build LangChain clients with `chat_client()`, never `ChatOpenAI` directly. It is
`ChatOpenAI` with one repair, and the repair is not optional on current models:

    INVALID_PARAMETER_VALUE: Content in ChatMessage must have type in
    String or List[ContentItem]

A model that answers in content blocks — Claude Opus 5 does, Opus 4.8 did not —
comes back as reasoning plus text. LangChain strips the reasoning on the way out
and appends what it doesn't recognise verbatim (`_format_message_content`, the
bare `else: formatted_content.append(block)`), so the assistant turn leaves as
`["I'll start by..."]`: a list of bare strings, which is neither of the two things
a ChatMessage accepts. Databricks refuses it on the request *after* the first tool
call, so what a user sees is a studio that answers "test" with a 400 — and because
the previous model was fine, it reads as "the new model is broken".

`normalise_content` rebuilds the list: text becomes text, images pass through, the
model's private reasoning is dropped because it cannot be replayed, and an all-text
list collapses to the plain string these models used to send. Two things to keep
in mind if you touch it:

- **A null content is legitimate** on an assistant turn that only calls tools, and
  every endpoint tested takes it. Don't "fix" it to an empty string.
- **Don't gate this on a model name.** Nothing here knows about Opus 5; any model
  that returns blocks does the same thing, and the list of which ones do changes
  faster than this file.

`tools/authoring_repro.py` runs one real authoring turn and prints every payload;
`RAW=1` skips the repair, which is how to see the original failure or check
whether an endpoint still needs it. `tools/tool_call_shape_probe.py` asks an
endpoint directly which content shapes it will take.

### Reading one back

`reply_text` is the mirror, and the only sanctioned way to read a reply. Every
other way of doing it has been in production and each failed differently, which
is why they are worth listing:

- `str(content)` on a block list splices `[{'type': 'text', ...}]` into a widget
  file.
- `getattr(msg, "content", "")` hands the list on unchanged, and it surfaces
  wherever it lands — `TypeError: expected string or bytes-like object, got
  'list'` out of `parse_edits`, from a repair path that only runs when an edit
  fails to apply, which is why it was intermittent.
- Matching only `dict` blocks returns `""` for a model that answers in bare
  strings: a studio that runs its whole allowance and displays nothing.

Do not expect to read the thinking. Claude returns its reasoning summary with
`text: ''` and a signature, so there is nothing in it to show a user — if you
want the model's narration on screen, the prompt has to ask for it as ordinary
text. `tools/widget_repro.py` prints what a reply contained and how much of it
survived the read, including how much prose arrived before the code.

## Principal names (`services/access.py`, `routes/sharing.py`)

An access-list entry's principal is free text, matched **exactly** for groups
(the SCIM display name) and case-insensitively for users, so a typo saves fine
and grants nothing. The share dialog warns when a name isn't one the app has seen,
and that is all the checking there is.

**The name is not looked up, deliberately.** There used to be a SCIM typeahead
and verdict (`/api/roles/principals`). It worked locally, where `DEV_MODE` runs as
the service principal, and never in a deployed App: listing groups needs the
`scim` scope, which isn't one Databricks Apps can request in `user_api_scopes`.
Doing the lookups as the service principal would extend SP auth beyond
inference. Instead `access.caller` records each caller and their groups in
`known_principals` (at most every ten minutes per person), and
`GET /api/sharing/principals?q=` suggests from that, the caller's own groups
first. Don't reintroduce a lookup that only works on the SP.

`taxonomy._near_duplicate` is the same idea for categories and domains:
`UNIQUE (name)` is case-sensitive, so `Logistics` and `logistics` could coexist.

## Studio research tools (`services/research_tools.py`)

Widget Studio and Agent Studio's authoring agent both get `run_sql` (read-only,
`SQL_WAREHOUSE_ID`, classified by `sql_safety` before anything is sent) and
`ask_genie` (the Genie MCP server via `agent_runtime._genie_start` /
`_genie_wait`, capped to the caller's clock). A wait that runs out returns the
handle, and `ask_genie(response_id=…)` resumes it without asking again — broad
questions can outlast one research turn, and re-asking restarts Genie's search. Both run on the **caller's OBO client** — the studios sign
inference with the SP, and that exception must not spread to data, which is why
`/api/agent/widget/generate` now takes `get_db_client` as well as
`get_db_client_sp`. The admin switches `enable_sql_tool` / `enable_genie_tool`
remove them, as they do in chat.

In Widget Studio the one-pass ReAct call has them directly, and so does each step
of a planned run (`ask_step`, a ReAct agent capped at `STEP_RECURSION_LIMIT`
that falls back to a plain call if it never converges). The plan itself is a plain
call, so `_research` runs one ReAct round *before* planning, on its own
`RESEARCH_SECONDS` clock inside the job's, and its findings are appended to the
plan prompt and to every step's system prompt (`_run_stages(context=...)`). It
costs a model call even when it finds nothing, so `_wants_research` only asks for
it when the request names a `catalog.schema.table` (not `props.data.x`) or asks to
look at data. With `run_sql` bound, `_sql_check_hint` tells both paths to run any
statement they wrote once before handing code back. In Agent Studio they ride on
`confirm_schema`, like the probes.

The prompt alone didn't stop the agent running `SELECT 1` as a "connectivity
check" on edits that touched no SQL, so two things enforce it. `_may_need_data`
binds no research tools to an edit of a widget with no data source and no
queries in its code, unless the request names a table or asks to look at data;
a new widget always gets them. And `run_sql` answers a SELECT of constants only
(`research_tools.is_ping`) itself, without the warehouse. It answers with the
result (`ping_result`: the row, then `PING_NOTE`), not a refusal: told "Not run",
the agent read a failed check and sent the same `SELECT 1` again. A second ping
in one run gets `PING_REPEATED`, which tells it to return the code.

## Moving data between apps (`services/data_migration.py`, `routes/data_migration.py`)

Each bundle target has its own Lakebase instance, so moving users from the dev
app to the stage app needs the data moved *between databases*. It travels as a gzipped JSON snapshot the admin downloads from one app
and uploads to the other — never a connection between apps, which would need one
app's SP granted into the other's database, or an app-to-app hop with the user's
token (the proxy's old 401/403 source).

- **Preview is the import, rolled back**, so its counts are exact.
- **Merge** matches on natural keys (`TableSpec.key`: `(id, version)`, name, the
  three mapping fields, the content of activity rows) as a *multiset*, and never
  carries serial ids — the two databases numbered rows independently. Repeating a
  merge writes nothing. **Replace** deletes and inserts with ids, then `setval`s.
- **One transaction per schema, committed only after every part succeeded.**
  `app_settings` goes to `settings_env()`'s schema, which may be a different
  connection; content to `content_env()`'s.
- **A replace that would leave the importer no longer an Administrator is rolled
  back** (`_still_admin`, read inside the uncommitted transaction).
- Only columns both sides have are written, so snapshots survive a version skew.
  `test_data_migration.py` fails if `init_db` gains a table that neither `TABLES`
  nor `NOT_COPIED` lists.
- Exports and imports are written to `action_logs`. Conversations are opt-in.
- **Snapshots are format 2** (`FORMAT_VERSION`): the content group carries every
  published version *and* `object_drafts`, and the access group carries
  `object_permissions`, `app_admins` and the taxonomy. Each table goes back to the
  store its kind lives in (`SETTINGS_TABLES` to `settings_env()`). On a merge the
  target's own access level and draft win. A file from a newer format is refused.
- **Format-1 files still import.** They carry `role_mappings` and no access lists,
  and imported as they stand everything in them would be reachable by
  Administrators alone, so `routes/data_migration.legacy_tables` converts the
  mappings with the same rules as the startup migration and says so in the
  preview. `role_mappings` itself is never written (`LEGACY_TABLES`).
  `cutover_log` is never copied (`NOT_COPIED`): it records what startup did on the
  source deployment, and the target ran its own.

## Agent Studio storage (`agent_studio_store.py`)

Authored agents are DB rows in `agent_profiles`, one per published version, with
at most one draft in `object_drafts`, exactly like widgets and views. This
replaced files on UC Volumes so that users with app access but no workspace
access can still save agents. Authorization lives in the store, not the routes,
so the Studio's CRUD and the chat proxy resolve an agent through the same checks.

- **Who** is the agent's access list (see *Auth*): `USE` to read it and pick it
  in chat, `MANAGE` to edit, publish, share and delete it. Anyone may create one,
  and `POST /profiles` without a `profile_id` makes the caller its owner. A `USE`
  holder's **Save a copy** in the Studio is exactly that call: the browser drops
  the id, so a copy can't overwrite the original.
- **What** is draft or published. `POST /profiles` with an id writes the draft
  (`MANAGE`, refused if `expected_updated_at` is stale); `/publish`, `/discard`,
  `/revert` and `/history` work as they do for widgets. `GET /profiles` gives a
  manager the draft merged over the newest published row and anyone else the
  published row; `?usable=true`, what the chat picker asks for, gives everyone
  published rows only, so a never-published agent is listed only for its
  managers and never offered in chat.
- **Chat runs only the published version**, managers included
  (`resolve_published`). The proxy turns "none the caller can use" into an
  explicit *That agent isn't available to you* turn rather than falling back to
  the default agent, which would answer under a name the user didn't pick.
  **Try it** sends whatever the Studio has on screen inline, so it never goes
  through this. A view's pin naming an agent the caller can't use is simply not
  applied by the browser, so they start on the default agent there.
- The old `visibility` column (`personal` / `domain` / `global`) is read only by
  the access migration. Publishing still writes it (`legacy_visibility`) so a
  rollback lists the agent no wider than its access list does now: Everyone maps
  to `global`, anything narrower to `personal`.

Skills, MCP tools, and Python tools are stored inline as JSON on the row so an
agent is one atomic record set. The default agent is the runtime's built-in
persona and is unaffected by this storage.

## Widget generation (`routes/widget_studio.py`)

This module was called `agent_studio` until it was renamed, which put it one
character from `agent_studio_profiles` — the *authored agents* studio — and cost
at least one person a jump-scare on their own codebase. Widget Studio is
`routes/widget_studio.py` at `/api/agent/widget`; Agent Studio is
`routes/agent_studio_profiles.py` at `/api/agent/studio`. Anything mounted on the
old name in a branch you are rebasing needs the same rename.

A background job (`generation_jobs`, polled by the studio) that drives a LangGraph
ReAct agent. The contract for what it may emit is
`routes/agent_instructions.md` — edit that file, not the Python, when you want to
change the model's output shape.

**Pages get a second contract.** A widget is a card or a page (`widgets.layout_kind`,
`'card'` by default, sent on generate and on save). For a page,
`_build_system_prompt` appends `routes/page_instructions.md` straight after
`agent_instructions.md`, and the review is built by the same function, so it holds
the page to the same rules. It stays a separate file because it overrides the card
rules (white background, fill the tile) and only pages should pay for it. Anything
that reads widget rows for the browser must pass `layout_kind` through, or the
library loses the **PAGE** badge; publishing copies the draft's columns, so it already does.

**Jobs are shared between workers (`services/generation_jobs.py`).** The deploy
runs two uvicorn workers, so a poll or a Stop can land on the one that isn't
running the job. `generation_jobs` is a `JobStore`: the running worker keeps the
job in memory and writes each change through to `widget_generation_jobs` (settings
schema), and `GET` / `DELETE /generate/{id}` read and write that row. It was a
module-level dict, which 404'd half the polls (masked, because the studio keeps
polling) and silently dropped half the Stops. Two rules: the table is a copy, never
a dependency — a failed write is logged and the job carries on, intermediate writes
back off, and `_settle` always forces the final one — and `cancelled` is its own
column, which saves never write, so progress can't undo a Stop. Read cancellation
with `generation_jobs.is_cancelled(job_id)`, never `job.get("cancelled")`: the
flag may have been set on the other worker. Standalone tests set
`generation_jobs.persist = False`.

Agent Studio's authoring runs use a second `JobStore` over the same table
(`authoring_jobs`; job ids are UUIDs, so they can't collide): `POST /generate`
answers with a job id, `GET` / `DELETE /generate/{id}` poll and stop it. It used
to stream each run over the request that started it, and a run with Genie
research outlasted something between the browser and the app: the connection was
cut, the studio showed "network error", and the run was cancelled with it, even
though keepalives were going out every 10 s. A poll that fails is now retried for
a minute before the studio gives up. The prose is the job's `text`, written
through at most once a second (`_AUTHORING_SAVE_SECS`), and Stop is checked
between the agent's messages, so it can't cut into a tool call already running.

It responds in one of two shapes, and the difference is the fix for large widgets
failing:

- **Editing** — the model returns `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE`
  blocks and `services/code_patch.py` splices them into `current_code`. Matching
  degrades from exact substring, to ignoring trailing whitespace, to ignoring
  indentation (re-indenting the replacement). A block that still can't be placed
  gets **one** corrective round trip, then is reported in the explanation rather
  than guessed at. Re-emitting a whole component used to blow the token budget
  and arrive truncated.

  Two things are refused outright rather than approximated, because both produce
  a broken widget that then costs several auto-fix rounds. A block carrying a
  **stray marker line** — the regex splits SEARCH at the first `=======`, so a
  duplicated one lands inside the replacement and gets written into the file. And
  a SEARCH matching in **more than one place**, which used to take the first
  match and so edited the wrong region most of the time. Once markers are in a
  file, edits cannot remove them (no SEARCH body can quote a `=======`), so
  `has_conflict_markers` gates the prompt: damaged code asks for a whole-file
  rewrite instead, and `assess_rewrite` blocks a rewrite that echoes the markers
  back.
- **Creating** — a whole `tsx` block. If the response is cut off (unbalanced code
  fence, or `finish_reason == "length"`) it's continued from its own tail, up to
  `WIDGET_AGENT_MAX_CONTINUATIONS` (3) times, instead of restarted.

A whole `tsx` block arriving in answer to an *edit* is the dangerous case: it
becomes the entire widget, so a fragment erases everything around it. That was the
studio's most-reported bug — the model answering "add a column" with just the
function it changed, or with `// ... rest of the component unchanged`. So when
`current_code` is non-empty, `assess_rewrite` vets the block first and
`_vet_rewrite` acts on the verdict:

- A fragment (an excerpt of the current file, an elided "rest of the code"
  placeholder, no export, unbalanced brackets) is **never written**. The model gets
  one round trip to resend the change as SEARCH/REPLACE blocks against the current
  code; if that fails too, the code is left alone and the explanation says so.
- A rewrite that merely shrinks the widget by more than half is written, since it
  may be what was asked for, but the explanation points at History.

Keep the two halves in step: `assess_rewrite` decides, `_vet_rewrite` reacts, and
`routes/agent_instructions.md` tells the model the rule so it rarely comes up.

**One clock for the whole job.** A generation is not one model call — there may be a
tool round, a continuation for a cut-off file, and a follow-up asking for edits — so
`_Budget` holds the `widget_timeout` allowance and every optional round asks
`next_llm()` for a client, getting `None` once the time is gone. That keeps the work
already applied (and the widget itself: a fragment is still refused when there's no
time to ask for edits) instead of losing the turn to a timeout, and it stops a slow
first call from costing several multiples of the configured limit.

Two things the clock depends on, both easy to undo by accident:

- **`max_retries=0` on every client `_widget_llm` builds.** `timeout` is per
  attempt, and langchain leaves retries at `None`, which the OpenAI client reads as
  its own default of 2 — so a client built with `timeout=budget.left` could spend
  three times the entire allowance on one call. The deadline held; nothing obeyed it.
- **Planning is capped at `PLAN_SECONDS`, separately from the work.** It used to get
  `budget.left` like everything else, so a slow plan could return with nothing left:
  every step skipped for want of time, the full timeout spent, no code at all. If
  planning yields nothing *and* leaves less than `MIN_ONE_PASS_SECONDS`, the job
  fails saying so rather than starting a one-pass run that cannot finish.

**Big requests are planned, then applied a step at a time.** Partial editing made
one change cheap; it did nothing for "build a table, add filters, add an export",
which is a single reply too long to finish. `_wants_stages` spots those (length, or
a list, or two "and also"-shaped hints — never a compile-error retry, which is one
job), `_plan_stages` asks for two to six ordered steps as JSON, and `_run_stages`
walks them, feeding each step the code the last one produced. Every step is an
ordinary generation through `_apply_reply`, so editing, continuation and rewrite
vetting all apply within a step.

What makes this worth the extra round trips is where the failures land:

- Progress goes onto the polled job as it happens, `stage_code` included, so the
  studio applies each step as it lands and gives it a History entry. A step that
  fails or a run that stops keeps everything before it.
- A step that fails or raises is recorded and the run carries on; the explanation
  names the steps that didn't land so they can be asked for again.
- `budget.has(25)` guards the *start* of each step — a step begun with seconds left
  just fails slowly. Remaining steps are marked `skipped` and the explanation says
  to raise `widget_timeout` or ask for the rest.
- `result["code"]` is `None` when no step changed anything, so the studio keeps what
  the user has rather than recording a no-op snapshot.
- `DELETE /api/agent/widget/generate/{job_id}` sets `cancelled` on the job's row,
  which `is_cancelled` checks between steps and before each optional follow-up
  round (`next_llm` returns `None`). The studio's Stop button stops polling at once and ignores whatever
  the job produces afterwards; "Stop after this step" keeps polling. Stopping
  keeps the applied steps; it is not an undo.
- Each step's line in the summary is the prose it wrote outside its code block —
  and a model that thinks privately writes none, which reduced a whole run to
  "Worked through 6 of 6 steps" with nothing underneath. Both ends are covered:
  the prompt asks for the sentence and says why, and a step that lands silently
  falls back to what it was asked to do. The fallback only speaks for steps that
  succeeded, or the summary would describe work the widget doesn't contain.

**The step count is the wait, so the plan is asked to earn each one.** A model
call cost a few seconds when this was built and costs 20–35 on a thinking model,
which turned a padded plan into minutes: asked for "a search box and a row
count", the planner returned four steps — `add search input state`, `filter rows
by search term` — splitting one feature into the mechanics of building it, and a
four-feature dashboard came back as six with `Polish and responsiveness` on the
end. The prompt now says one step per thing *the request asks for*, names the
padding words, and gives the pressure in both directions: too many steps and the
user waits, too few and a step becomes the over-long reply that staging exists to
avoid. That took the two-thing request to one pass or two steps, and the
dashboard from six steps to three or four — 40 to 50 seconds end to end on
Sonnet 5, against the two to three minutes users were reporting. Per step it is
5–15s, and the file grows rather than being rewritten (3.0k → 5.3k → 5.7k → 8.4k
characters over four steps), which is the check that the edits are landing on
each other rather than each step starting again.

`MAX_STAGES` is a ceiling, not a target, and it is not the interesting number —
what the planner does below it is. `SIZES=1 tools/widget_repro.py --plan` prints
the step count for a tiny, a small and a large request, which is how both of the
above were found; run it three times, since a single plan is not a measurement.
`RUN_STAGES=1` walks a whole plan and prints what the user would end up reading.

Anything unexpected in the plan means no plan and the request is answered in one
pass, which is the pre-existing behavior — a plan that won't parse must never cost
someone their turn.

Steps run as ReAct agents with the same tools as the one-pass path
(`search_widgets` and the research tools; see *Studio research tools*), so a step
that adds a query can look up the column and run the statement it just wrote.

**SQL quoting.** Databricks needs backtick-quoted identifiers for names that aren't
plain (column mapping, on by default in Unity Catalog, allows spaces and punctuation
in column names), and a model that forgets tends to invent a different column rather
than quote the one it had. The rule is in `agent_instructions.md` and the runtime
contract, and `services/sql_advice.py` attaches it to the failure itself for both
surfaces that run model-written SQL. Related: `routes/sql_query.py` now inspects
`statement.status` — `execute_statement` reports a rejected query in its status
rather than raising, so a failed query used to return HTTP 200 with zero rows, which
is how a missing backtick became a blank widget instead of a fixable error.

That error has to satisfy two audiences at once, which is why it is a
`SqlStatementError` and not a plain `HTTPException` (`tests/test_sql_errors.py`):

- **Non-2xx with the reason in `detail`**, for anything written against the current
  contract — that is what lets the studio's auto-fix see a real error and repair the
  query. Both endpoints re-raise it untouched; `execute_sql_query`'s blanket
  `except Exception` would otherwise have turned every one into a 500.
- **A body that still reads as an empty result** (`rows`, `columns`, `row_count`).
  Widgets already in the `widgets` table were generated before that contract existed
  and do `setRows(payload.rows)` without checking the status. Without this they
  throw on `undefined` and take a live dashboard panel with them.

A query can fail in two places and both have to arrive in that shape. `status`
covers the ones the warehouse ran and rejected; the SDK *raises* for the ones it
never ran at all — a stopped warehouse, an expired token, a statement refused
before planning — and those went to the catch-all as HTTP 500 with a Python
traceback in `detail`, which the widget printed into the panel. `_refusal` maps
them instead, taking the status from the SDK's own `STATUS_CODE_MAPPING` so a
permission problem reads as 403 and a starting warehouse as 503 rather than
everything looking like the app falling over. Two details worth keeping: an SDK
error carrying no message stringifies as the literal `"None"`, which is what the
user would otherwise be shown as the reason, and tracebacks belong in the log —
never in `detail`, which is rendered verbatim on someone's dashboard.

A `widget-meta` JSON block carries proposed Configuration-tab values. Backend
sanitizes: categories/domains must be one of the values the request supplied,
dimensions are range-checked, and keys listed in `locked_settings` are dropped.
The frontend applies what's left only to fields the user hasn't touched. `links`
is the exception: each becomes a `link` settings field if no field has its key
yet, and existing fields are never renamed or removed.

**The cheap side-calls (`ask_helper`).** Compacting history and deciding whether
to ask a question run on `widget_helper_model` (default
`system.ai.gpt-6-luna`) with their own small `HELPER_SECONDS` /
`HELPER_MAX_TOKENS` slice of the same `_Budget`. `_helper_params` adds
`reasoning_effort="none"` for OpenAI-flavoured models unless an admin override, a
learned drop or the built-in policy already decides the effort; a model that
refuses the *value* (which `llm_params.adapt` can't read) goes into
`_helper_no_effort` and is retried without it. An endpoint that isn't served is
remembered in `_helper_missing` for `HELPER_MISSING_SECONDS` and the job switches
to `widget_model` for its quick checks, so the default is safe on a workspace
without that model. Every
one of them is skippable by construction: `ask_helper` returns `""` when there is
no time or the call fails, and each caller reads that as "do what you did before".
Nothing here may become load-bearing — a helper outage must cost quality, never a
turn.

There used to be a third, `_refine_prompt`, which had the helper restate the
request before generation, and it was removed rather than tuned. It saw nothing
the generation model doesn't (the same request, the same code), so at best it
agreed with the stronger model and at worst overruled it — and it replaced the
user's words, so the generation model couldn't tell. The case that removed it:
"the time keeps changing width due to kerning" arrived as "keep the span's width
fixed", the user's guess at a cause promoted to a requirement and the likely fix
(tabular digits) ruled out. It cost two seconds on every turn and was never
measured. A helper job earns its place by *deciding* something or *shrinking*
what the big model reads, as compaction and the question gate do. They also share `_json_reply`, which digs the object out of a fenced or
chatty reply and returns `{}` rather than raising.

`_base_url` is per model, not per job, and this is the trap: a `system.ai.…` name
resolves only on the AI Gateway route and a plain endpoint name only on
`/serving-endpoints`, so deriving one URL from one of the two 404s the other. A job
that calls a helper alongside the generation model needs both.

**Clarifying questions** (`_clarify`) are gated on `_wants_stages` — the same
judgement that decides a request is worth planning decides it is worth a question,
because that is exactly where a wrong guess costs minutes. A question set settles
the job with `code: None` and a `questions` list; nothing is generated. Two guards
stop a loop: the client sends `allow_clarify: false` on the answering turn, and
`CLARIFY_MARKER` in the history means one has already been asked.

**The data-source test runs as the user (`get_db_client`).** It ran as the SP,
with no statement check, which let anyone with studio access run any SQL with the
app's grants — writes included — and made the server GET any URL it was handed.
Now: SQL goes through `sql_safety.classify_statement` and a write is answered 200
with a `note` and never run; a read runs as `_probe_statement` (bounded to
`SAMPLE_ROWS`; a newline before the closing parenthesis so a trailing `--` comment
can't swallow it); column types come from the manifest (`_column_types`), since
every Statement Execution value is a string; and a plain `api` source is refused
with 400, because the studio tests it from the browser (`src/widgetDataSource.ts`).
The sample comes back on generate as `data_source_sample` (`_sample_section`).

**What the studio saw when the widget ran.** The browser is the only place widget
code runs, so the studio sends it back: `runtime_log` (requests, row counts,
errors — `src/widgetRuntime.ts`), `lint_findings` (`src/widgetLint.ts`) and, on
review and runtime-fix turns, `preview_screenshot`, a PNG data URL turned into an
image part by `native_files.image_part` (image data URLs only, size-limited, and
gated like any native file). `_runtime_section` / `_lint_section` are appended only
when there is current code for them to describe, and bounded here as well as in
the browser. `_review_evidence` points the reviewer at whichever of the three it
has.

**Row estimate.** `POST /datasource/test` on a SQL source returns `row_estimate`
from a wrapped `COUNT(*)`, the studio keeps it, and it comes back on generate as
`data_source_row_estimate`. `_size_guidance` turns it into the paragraph that
decides whether the widget pages in SQL or in the browser, appended to the system
prompt rather than living in `agent_instructions.md`: the instructions are paid for
on every call including every step of a plan, and only a request with a tested
source can be told anything specific. **`None` means "treat as large"** — reading
silence as "small" is how a 40,000-row table ends up in a tab.

The studio no longer offers a SQL data source, so the SQL branches of
`/datasource/test` and `_size_guidance` now serve only widgets saved with one
(the studio shows that query read-only and never tests it again). New widgets
write their SQL in code and the agent sizes it itself with a `COUNT(*)` through
`run_sql`, which `agent_instructions.md` asks for. Keep the stored `data_source`
injected at runtime and keep `review_widget`'s write check: placed copies of those
widgets still run, and may override, that query.

The line between the two is a *payload*, not a row count: rows × columns ×
`BYTES_PER_CELL` against `CLIENT_SIDE_MAX_MB` (10, a desktop-only rule of thumb), with
the column count taken from the tested schema. It is the server-side versus
client-side choice every table library exposes, and both sides work at any row
count — which is why it is advice in the prompt and not a cap. Tune the two
constants, not the prose.

**The 500-row default is the thing people call "the query limit".**
`/api/sql/execute-raw` returns 500 rows unless the body asks for more, and until
`truncated` / `total_rows` were added it said nothing about the rest: `row_count`
was just the length of what arrived. Asking for a number didn't fix it either: a
`max_rows` sized to the data the day the widget was built drops rows as the table
grows, and past 25 MiB the warehouse refuses to return a result inline at all.
So a widget that works on the whole result sends `all_rows: true`, bounded only by
the `widget_query_max_rows` setting, and `_size_guidance`, the generation contract
and `widgetLint.ts` (`fixed-row-cap`) all steer to it.

`_run_statement` tries plans in order (`fetch_plans`): INLINE, then INLINE with a
`row_limit`, then EXTERNAL_LINKS, moving on only when the warehouse answers
"inline byte limit exceeded". A capped read therefore runs exactly as it always
did. External links are presigned cloud-storage URLs, fetched with only the
headers the link carries — the Databricks token must not go to storage. The body
is streamed (`result_body`) in the same JSON shape as before, gzipped when the
browser accepts it, so neither the server nor the browser's runtime log
(`readSummary`, which reads only the trailing summary) holds a second copy. A
failure part-way still closes the JSON, with `error` set and `truncated: true`.
Writes take only the first plan: re-running one to fetch its result differently
would apply it twice. Unverified on a deployed App: that its egress reaches the
storage URLs (it answers 502 with that explanation if not), and how the Apps proxy
treats a large streamed body. The 50 s `wait_timeout` still bounds the statement
itself. `tests/test_sql_rows.py` pins all of it with a fake statement API.

**Trace (`_trace` / `_settle`).** The studio's "Thinking" is narration the job
writes about its own decisions, not model reasoning — the current models keep that
private and the app never sees it. `_settle` exists because a plain
`generation_jobs[id] = {...}` drops the trace that was accumulating alongside it.

**`POST /review`** is the QA pass, and it is deliberately a second request rather
than a tail on the generation job: the only compiler here is the browser's, so the
studio is the one that knows whether the code it was handed builds — and, now, how
it behaved once it ran, which is when the studio sends it (with a screenshot). It shares the job shape, so the
studio polls it with the same code, and findings come back through `_apply_reply`
like any other reply — a review is not allowed to eat the widget it was checking.
It gets `REVIEW_SECONDS` (a page, `PAGE_REVIEW_SECONDS`), a fraction of the generation allowance, and a failure
settles as *completed* with an apology: the user's code is already fine.

## Tests

```bash
PYTHONPATH=server .venv/bin/python tests/test_agent_studio_store.py   # 23 passed
PYTHONPATH=server .venv/bin/python tests/test_agent_studio_authoring.py # 15 passed
PYTHONPATH=server .venv/bin/python tests/test_agent_runtime.py        # 10 passed
PYTHONPATH=server .venv/bin/python tests/test_mcp_catalog.py          # 35 passed
PYTHONPATH=server .venv/bin/python tests/test_mcp_client.py           # 5 passed
PYTHONPATH=server .venv/bin/python tests/test_code_patch.py           # 22 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_agent_meta.py    # 9 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_agent_rewrite.py # 9 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_agent_stages.py  # 15 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_agent_helper.py  # 25 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_agent_context.py # 23 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_generation_jobs.py # 8 passed
PYTHONPATH=server .venv/bin/python tests/test_native_files.py         # 16 passed
PYTHONPATH=server .venv/bin/python tests/test_creator_stats.py        # 16 passed
PYTHONPATH=server .venv/bin/python tests/test_caller_identity.py      # 11 passed
PYTHONPATH=server .venv/bin/python tests/test_settings_store.py       # 27 passed
PYTHONPATH=server .venv/bin/python tests/test_llm_params.py           # 17 passed
PYTHONPATH=server .venv/bin/python tests/test_llm_client.py           # 16 passed
PYTHONPATH=server .venv/bin/python tests/test_sql_errors.py           # 10 passed
PYTHONPATH=server .venv/bin/python tests/test_view_pins.py            # 7 passed
PYTHONPATH=server .venv/bin/python tests/test_view_archive.py         # 12 passed
PYTHONPATH=server .venv/bin/python tests/test_app_spec.py             # 44 passed
PYTHONPATH=server .venv/bin/python tests/test_app_links.py            # 8 passed
PYTHONPATH=server .venv/bin/python tests/test_look_helper.py          # 7 passed
PYTHONPATH=server .venv/bin/python tests/test_apps_routes.py          # 58 passed
PYTHONPATH=server .venv/bin/python tests/test_sql_rows.py             # 26 passed
.venv/bin/python tests/test_file_extract.py                           # 22 passed
.venv/bin/python tests/test_upload_tools.py                           # 28 passed
PYTHONPATH=server .venv/bin/python tests/test_conversation_store.py   # 5 passed
PYTHONPATH=server .venv/bin/python tests/test_db_pool.py              # 14 passed
PYTHONPATH=server .venv/bin/python tests/test_research_tools.py       # 30 passed
PYTHONPATH=server .venv/bin/python tests/test_data_migration.py       # 25 passed
PYTHONPATH=server .venv/bin/python tests/test_app_help.py            # 9 passed
PYTHONPATH=server .venv/bin/python tests/test_role_mappings_home.py   # 2 passed
PYTHONPATH=server .venv/bin/python tests/test_access.py               # 21 passed
PYTHONPATH=server .venv/bin/python tests/test_drafts.py               # 16 passed
PYTHONPATH=server .venv/bin/python tests/test_access_migration.py     # 34 passed
PYTHONPATH=server .venv/bin/python tests/test_consolidation.py        # 29 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_publish.py       # 31 passed
PYTHONPATH=server .venv/bin/python tests/test_widget_safety.py        # 31 passed
PYTHONPATH=server .venv/bin/python tests/test_background.py           # 9 passed
PYTHONPATH=server .venv/bin/python tests/test_capabilities.py         # 7 passed
PYTHONPATH=server .venv/bin/python tests/test_activity.py             # 6 passed
PYTHONPATH=server .venv/bin/python tests/test_actions_routes.py       # 7 passed
```

`test_file_extract.py` and `test_upload_tools.py` need the venv interpreter, not
a bare `python3`: they exercise pandas, openpyxl, pypdf and python-docx.
`test_role_mappings_home.py` stays until `role_mappings` is dropped.

Run from the repo root. A bare `python3` also works, but one store test skips
without the venv's dependencies, so prefer the venv interpreter for full
coverage.

No pytest, no network, no credentials — they cover pure helpers only
(frontmatter parsing, slug generation, response normalization, the TTL job
store). When you add a testable pure helper, extend these files in the same
style; when you need to fake a collaborator, patch it where it's *used*
(e.g. `routes.agent_studio_profiles.discover_mcp_tools`), not where it's defined.

`test_db_pool.py` is the exception that proves the rule: the pool has no database
in it either, because a fake connection object is enough to pin every decision it
makes — reuse, ping, recycle, retire on new credentials, reclaim a connection a
caller forgot. Anything about the pool that needs a real Lakebase belongs in
`tools/db_pool_soak.py` against a running server, not here.
