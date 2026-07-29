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

## Database (`database.py`)

`get_db_connection(env)` resolves the Lakebase host/database, mints a short-lived
OAuth token via the SDK when no password is supplied, and pins the schema. That
resolution costs three or more control-plane round trips, so the working
parameters are cached per env for `LAKEBASE_CRED_TTL_SECONDS` (600) and dropped
automatically when a connection using them fails. Without it, a page that fires
several API calls at once intermittently failed on control-plane latency. Call
`invalidate_db_credentials()` if you change instance wiring at runtime.
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
existing frontend hook: `chunk`, `reasoning`, `tool_calls`, `trace_id`, `final`,
`error`.

Defaults: model `databricks-claude-sonnet-4-6` (`AGENT_RUNTIME_MODEL`), 8 steps
(`AGENT_RUNTIME_MAX_STEPS`), 4000 max tokens, 90 s per tool call, 10 s heartbeat.
The heartbeat matters — without periodic `: keepalive` bytes, proxies close a
slow SSE stream mid-turn.

Two behaviors that look odd but are intentional:

- **Auth is split.** The LLM call is signed by the service principal
  (`AGENT_RUNTIME_LLM_AUTH=sp`, the default) so users don't each need a
  foundation-model entitlement; every tool executes under the caller's OBO
  token. See `_llm_auth_mode` for the reasoning.
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

A `widget-meta` JSON block carries proposed Configuration-tab values. Backend
sanitizes: categories/domains must be one of the values the request supplied,
dimensions are range-checked, and keys listed in `locked_settings` are dropped.
The frontend applies what's left only to fields the user hasn't touched.

## Tests

```bash
PYTHONPATH=server server/venv/bin/python tests/test_agent_studio_store.py   # 7 passed
PYTHONPATH=server server/venv/bin/python tests/test_agent_runtime.py        # 3 passed
PYTHONPATH=server server/venv/bin/python tests/test_code_patch.py           # 12 passed
PYTHONPATH=server server/venv/bin/python tests/test_widget_agent_meta.py    # 5 passed
```

Run from the repo root. A bare `python3` also works, but one store test skips
without the venv's dependencies, so prefer the venv interpreter for full
coverage.

No pytest, no network, no credentials — they cover pure helpers only
(frontmatter parsing, slug generation, response normalization, the TTL job
store). When you add a testable pure helper, extend these files in the same
style; when you need to fake a collaborator, patch it where it's *used*
(e.g. `routes.agent_studio_profiles.discover_mcp_tools`), not where it's defined.
