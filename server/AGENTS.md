# AGENTS.md — Backend (FastAPI gateway)

Read `../AGENTS.md` first for the OBO rule, the environment/schema model, and
commands. This file covers what you need to change code in `server/`.

## Imports are flat — this bites everyone once

Uvicorn runs with `server/` as the working directory (`main:app`), so packages
resolve from *inside* `server/`, not from the repo root:

```python
from routes import widgets            # correct
from middleware.auth import get_db_client
from database import init_db
from server.routes import widgets     # WRONG — will not import
```

`databricks.yml` sets `PYTHONPATH` to match in the deployed App, and the
standalone tests insert `server/` onto `sys.path` themselves. If you see
`ModuleNotFoundError: No module named 'server'`, this is why.

Run the backend alone with `cd server && venv/bin/uvicorn main:app --reload
--port 8001`. Startup logs go to `../backend.log` when launched via `dev.sh`.

## Adding an endpoint

1. Create or extend a module in `routes/` that defines `router = APIRouter(...)`.
2. **Register it in `main.py`** — import it and call `app.include_router(...)`
   with an `/api/...` prefix. There is no auto-discovery, despite what the README
   implies. Anything under `/api/` that isn't mounted hits the SPA catch-all and
   returns a JSON 404.
3. Take auth as a dependency rather than reading headers yourself.
4. Accept `env: str = "dev"` if the endpoint touches stored state, and pass it
   through to `get_db_connection(env)`. Every existing data route does this.

Mounted prefixes (`main.py`): `/api/widgets`, `/api/actions`, `/api/genie`,
`/api/sql`, `/api/jobs`, `/api/roles`, `/api/views`, `/api/promotion`,
`/api/taxonomy`, `/api/databricks`, `/api/agent` (proxy), `/api/agent/widget`,
`/api/agent/studio`, plus `/api` for n8n and Tableau. Interactive docs are at
`/api/docs`.

`/api/health` is the one unauthenticated route, so it doubles as the SPA's source
for `APP_ENVIRONMENT` (`config.settings.get_app_environment()` — local/dev/stage/
prod, set per bundle target). Do not confuse it with the `env` query parameter,
which picks *which stored data* a route reads; one deployment serves all three.

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

## Database (`database.py`)

`get_db_connection(env)` hands out a pooled connection (see *What a request is
allowed to spend*), opening one only when the pool has none. Opening resolves the
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
  `MAX(version)` join in `routes/views.py`. Writes insert a new version rather
  than updating in place.
- **PK `(username, view_id)`**: `shared_views` (subscriptions).
- **`SERIAL id`**: `widget_categories`, `widget_domains`, `role_mappings`,
  `widget_runs`, `action_logs`. Categories/domains are `UNIQUE (name)` and are
  seeded with defaults on first creation, as is a fallback global-admin
  `role_mappings` row — so a "fresh" schema is not empty.

New columns go in as `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in the migration
block *after* table creation, each in its own try/except with a rollback, so one
failure can't abort the rest of the transaction.

### The agent a view is pinned to

`dashboard_views.pinned_agent_id` holds the Agent Studio profile the assistant
drawer opens with on that view (or the literal `'default'` for the built-in
agent). Permission is the view's own: personal views by their owner, global ones
by a domain editor, which `PUT /api/views/{id}` already enforces — there is no
separate check, and none should be added.

The one trap is that clients save a view **whole**: nudging a widget one square
PUTs name, lock, widgets and all. So `pin_value` treats an absent pin as "keep
what's there" and an empty string as "clear it", because a field that isn't sent
and a field sent as `null` are both `None` by the time Pydantic is done with
them. Get that backwards and every widget drag silently unpins the view.
`tests/test_view_pins.py` holds the distinction.

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
- **Genie is made synchronous.** The AI Gateway Genie MCP server is a polling
  API: `genie_ask` returns a handle and `genie_poll_response` retrieves the
  answer. Handing the model a handle is useless, so `_exec_genie` drives the
  poll loop internally and `genie_poll_response` is hidden from the tool list
  the model sees (`AGENT_RUNTIME_GENIE_TIMEOUT`, `AGENT_RUNTIME_GENIE_POLL_MS`).
  SQL is deliberately *not* wrapped this way — `execute_sql` answers inline for
  normal queries and `poll_sql_result` stays model-facing by design, which is
  part of why the step cap is 8 rather than 6.

### Knowledge about the app itself (`services/app_help.py`)

Users ask the assistant how the Command Center works, not only what their data
says, so every agent gets both halves of `app_help.py`:

- `APP_PRIMER` is spliced into the system prompt as `APP_KNOWLEDGE`, between the
  runtime contract and the persona (neutral facts, so a profile persona still
  wins any conflict). It is the vocabulary — widget, view, domain, the three role
  levels, highest-level-wins, Dev → Test → Prod — that the agent must not get
  wrong when it answers without calling a tool. Keep it short; it is paid for on
  every turn. A `base: none` (standalone) profile skips it, like the rest of the
  scaffold.
- The `app_help` tool searches `services/app_guide.md` for the detail: exact
  steps, promotion rules, agent authoring. Registered before MCP discovery and
  attached to *every* agent, including profiles with a curated tool list, because
  an agent without it invents answers about the UI. Section titles are advertised
  in the tool description, so renaming a `##` heading changes what the model
  knows it can ask for.

`app_guide.md` describes app behavior and drifts silently when the app changes —
update it alongside `src/pages/UserGuidePage.tsx`. Relevance is keyword scoring
weighted by term rarity; the guide says "widget" everywhere, so without that
weighting a question like "get my widget into prod" never reaches the promotion
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
side-calls (`widget_helper_model`, blank means reuse `widget_model`), and agent
authoring — plus the chat agent's step and
token caps, are rows in `app_settings` edited from Admin Panel → Settings
(`routes/app_settings.py`, global admin only). Resolution is
**row > env var > built-in default**, so an untouched deployment behaves exactly as
it did when these were env-only, and saving a setting blank deletes the row rather
than pinning an empty value. Reads are cached ~15 s and never raise: a settings
outage falls back to the env var instead of breaking chat.

Two things to keep in mind when touching this:

- **Settings are global, not per-env.** Everything else in the database is scoped
  to a dev/test/prod schema; these live in one (`APP_SETTINGS_ENV`, default `dev`)
  because they describe the deployment, not the data it addresses.
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
frontend change. `kind` is `endpoint` (model picker), `int` (bounded number) or
`json` (validated on save, so a typo surfaces in the form and not later as an agent
failing).

The limits that live here are the ones a big request runs into: tool and Genie
timeouts for chat, and for Widget Studio a token ceiling and a wall-clock
`widget_timeout`. Anything time-related must be enforced where the work happens and
reported to the client — `/api/agent/widget/generate` returns `timeout_seconds` and
the studio sizes its own polling from it, because a client giving up on its own
schedule made raising the setting do nothing.

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
loop, and every LLM call site goes through it. The lesson is remembered per process.
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

## Agent Studio storage (`agent_studio_store.py`)

Authored agents are DB rows in `agent_profiles`, versioned like widgets. This
replaced files on UC Volumes so that users with app access but no workspace
access can still save agents. Visibility governs sharing:

- `personal` — only the creator (`username`).
- `domain` — anyone with access to `domain`; domain editors can edit.
- `global` — every authenticated user; only global admins can edit.

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
- `DELETE /api/agent/widget/generate/{job_id}` sets `cancelled`, which is checked
  between steps. Stopping keeps the applied steps; it is not an undo.
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

Steps are plain model calls, not the ReAct agent, so they can't reach the
`search_widgets` tool. That's a deliberate trade — a step is a described change to
code the model already has — but it's the thing to revisit if planned builds start
ignoring existing widgets the way one-pass builds don't.

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
The frontend applies what's left only to fields the user hasn't touched.

**The cheap side-calls (`ask_helper`).** Refining the prompt, compacting history
and deciding whether to ask a question all run on `widget_helper_model` with their
own small `HELPER_SECONDS` / `HELPER_MAX_TOKENS` slice of the same `_Budget`. Every
one of them is skippable by construction: `ask_helper` returns `""` when there is
no time or the call fails, and each caller reads that as "do what you did before".
Nothing here may become load-bearing — a helper outage must cost quality, never a
turn. They also share `_json_reply`, which digs the object out of a fenced or
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

**Row estimate.** `POST /datasource/test` on a SQL source returns `row_estimate`
from a wrapped `COUNT(*)`, the studio keeps it, and it comes back on generate as
`data_source_row_estimate`. `_size_guidance` turns it into the paragraph that
decides whether the widget pages in SQL or in the browser, appended to the system
prompt rather than living in `agent_instructions.md`: the instructions are paid for
on every call including every step of a plan, and only a request with a tested
source can be told anything specific. **`None` means "treat as large"** — reading
silence as "small" is how a 40,000-row table ends up in a tab.

**Trace (`_trace` / `_settle`).** The studio's "Thinking" is narration the job
writes about its own decisions, not model reasoning — the current models keep that
private and the app never sees it. `_settle` exists because a plain
`generation_jobs[id] = {...}` drops the trace that was accumulating alongside it.

**`POST /review`** is the QA pass, and it is deliberately a second request rather
than a tail on the generation job: the only compiler here is the browser's, so the
studio is the one that knows whether the code it was handed builds, and reviewing
before that means auditing code that may not run. It shares the job shape, so the
studio polls it with the same code, and findings come back through `_apply_reply`
like any other reply — a review is not allowed to eat the widget it was checking.
It gets `REVIEW_SECONDS`, a fraction of the generation allowance, and a failure
settles as *completed* with an apology: the user's code is already fine.

## Tests

```bash
PYTHONPATH=server server/venv/bin/python tests/test_agent_studio_store.py   # 7 passed
PYTHONPATH=server server/venv/bin/python tests/test_agent_runtime.py        # 5 passed
PYTHONPATH=server server/venv/bin/python tests/test_code_patch.py           # 22 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_meta.py    # 5 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_rewrite.py # 9 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_stages.py  # 15 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_helper.py  # 23 passed
PYTHONPATH=server server/venv/bin/python tests/test_native_files.py         # 10 passed
PYTHONPATH=server server/venv/bin/python tests/test_creator_stats.py        # 16 passed
PYTHONPATH=server server/venv/bin/python tests/test_caller_identity.py      # 11 passed
PYTHONPATH=server server/venv/bin/python tests/test_settings_store.py       # 14 passed
PYTHONPATH=server server/venv/bin/python tests/test_llm_params.py           # 17 passed
PYTHONPATH=server server/venv/bin/python tests/test_llm_client.py           # 16 passed
PYTHONPATH=server server/venv/bin/python tests/test_sql_errors.py           # 10 passed
PYTHONPATH=server server/venv/bin/python tests/test_view_pins.py            # 7 passed
server/venv/bin/python tests/test_file_extract.py                           # 22 passed
server/venv/bin/python tests/test_upload_tools.py                           # 28 passed
PYTHONPATH=server server/venv/bin/python tests/test_conversation_store.py   # 5 passed
PYTHONPATH=server server/venv/bin/python tests/test_db_pool.py              # 14 passed
```

The last two need the venv interpreter, not a bare `python3`: they exercise
pandas, openpyxl, pypdf and python-docx.

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
