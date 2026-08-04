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
- **Images and short PDFs go to the model directly** (`_native_parts`), because
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

Which model each of the three LLM callers uses, plus the chat agent's step and
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
(label, help text, bounds) with no frontend change.

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

## Widget generation (`routes/agent_studio.py`)

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

A `widget-meta` JSON block carries proposed Configuration-tab values. Backend
sanitizes: categories/domains must be one of the values the request supplied,
dimensions are range-checked, and keys listed in `locked_settings` are dropped.
The frontend applies what's left only to fields the user hasn't touched.

## Tests

```bash
PYTHONPATH=server server/venv/bin/python tests/test_agent_studio_store.py   # 7 passed
PYTHONPATH=server server/venv/bin/python tests/test_agent_runtime.py        # 3 passed
PYTHONPATH=server server/venv/bin/python tests/test_code_patch.py           # 18 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_meta.py    # 5 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_rewrite.py # 5 passed
PYTHONPATH=server server/venv/bin/python tests/test_settings_store.py       # 14 passed
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
