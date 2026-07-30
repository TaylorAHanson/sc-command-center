# AGENTS.md — Enterprise Command Center

React SPA + FastAPI gateway, deployed as a Databricks App. On the surface it's a
configurable widget dashboard; the strategic point is telemetry — pairing "see
data" with "take action" on one screen yields cause/effect rows that feed the
4-stage AI maturity model described in `README.md`.

The most important thing to internalize: **widgets, views, and agents are
database rows, not files in this repo.** They're authored in the app's own
Widget Studio / Agent Studio UI and stored (versioned) in Lakebase Postgres. Do
not look for a `src/widgets/` directory — there isn't one.

Scoped guidance lives in `server/AGENTS.md` and `src/AGENTS.md`. Read those
before editing either side.

## Commands

| Task | Command |
| --- | --- |
| Run both servers | `./dev.sh` |
| Frontend only | `npm run dev` |
| Backend only | `cd server && venv/bin/uvicorn main:app --reload --port 8001` |
| Build frontend | `npm run build` (`tsc -b && vite build` → `dist/`) |
| Lint | `npm run lint` |
| Backend tests | `PYTHONPATH=server server/venv/bin/python tests/test_agent_studio_store.py` |
| Deploy | `databricks bundle deploy -t <target>` (targets in `databricks.yml`) |

Backend runs on **8001**, frontend on **5174**, and Vite proxies `/api` to
`127.0.0.1:8001` (`vite.config.ts`). `dev.sh` is the happy path: it clears both
ports, creates `server/venv` if missing, installs `requirements.txt` when a key
import is absent, and tees output to `backend.log` / `frontend.log` rather than
the terminal — so read those files when something fails to start.

There is **no pytest harness**. Tests in `tests/` are written to run standalone
under plain `python3` (they insert `server/` on `sys.path` themselves), and they
deliberately cover only pure helpers so they need no Databricks credentials. Use
the venv interpreter to run them all: the file-parsing tests need pandas, openpyxl,
pypdf and python-docx. `server/AGENTS.md` lists each file with its expected count.

## Layout

```
databricks.yml          Asset Bundle: app resource, env vars, per-target overrides
dev.sh / deploy.sh      Local dev launcher / manual sync+deploy to an existing App
RELEASE_NOTES.md        User-facing changelog, rendered in-app; update every change
requirements.txt        Backend deps (frontend deps in package.json)
server/                 FastAPI gateway — see server/AGENTS.md
  main.py               App factory, router registration, SPA catch-all
  database.py           Lakebase connection, schema selection, init_db
  db_pool.py            Connection pool behind get_db_connection
  agent_studio_store.py DB-backed CRUD for authored agents
  routes/               One module per API area, explicitly mounted in main.py
  services/             agent_runtime.py (in-process agent), databricks_service.py
                        app_help.py + app_guide.md (what agents know about this
                        app), code_patch.py (widget edit splicing),
                        conversation_store.py + upload_store.py + upload_tools.py
                        + file_extract.py (saved chats and attached files),
                        caller_identity.py (who is calling, cached)
  middleware/auth.py    OBO token extraction and WorkspaceClient factories
  config/               Static config + settings.py (env var reads)
src/                    React SPA — see src/AGENTS.md
  api.ts                Relative-path fetch helpers (`/api/...`)
  widgetRegistry.ts     Loads DB-stored widgets at runtime; type contracts
  pages/ components/ hooks/ contexts/ store/
tests/                  Standalone Python tests (no pytest)
tools/                  Latency probes and a pool soak test, run against a server
dist/                   Build output; FastAPI serves it in production
```

## Non-negotiables

**On-Behalf-Of for data.** Every Databricks data operation runs as the
signed-in user via their forwarded OBO token, so Unity Catalog governs access
per user. There is exactly one deliberate exception, documented in
`server/services/agent_runtime.py`: LLM *inference* is signed by the app's
service principal (`AGENT_RUNTIME_LLM_AUTH=sp`) because per-user
foundation-model entitlements produced 403 "Unauthorized access to Org" for some
users. Inference touches no user data; every tool call still uses OBO. Don't
extend SP auth beyond that without a comparable justification.

**The frontend never holds a secret.** No API keys, M2M credentials, or database
connection strings in `src/`. If an integration needs a secret, static
credential, or DB access, it gets a backend endpoint in `server/routes/` and the
browser talks only to that. Client-side integration is acceptable only for
embeds that manage their own session securely (e.g. a Tableau iframe).

**Don't hand-write widgets into the repo.** Widget TSX is authored in Widget
Studio and persisted to the `widgets` table. The generation contract the LLM and
the browser runtime must both satisfy is `server/routes/agent_instructions.md`
— treat that file as the source of truth for what widget code may contain.

**Every user-visible change updates `RELEASE_NOTES.md`, in the same commit.**
That file is bundled and rendered in the app under Resources → Release Notes, so
it is the only changelog users ever see; a separate "docs pass" never happens.
Newest release on top, `## <version> — <YYYY-MM-DD>`, bullets grouped under
Added / Changed / Fixed, written in terms of what someone can now do rather than
what you edited. Add to the existing top block if it is unreleased, otherwise
start a new one. Skip it only for changes nobody using the app could notice —
refactors, tests, comments.

**Changing how the app behaves updates the agent's copy of the docs too.** Users
ask the in-app assistant how things work, and it answers from
`server/services/app_guide.md` (plus the primer in `services/app_help.py`), which
nothing validates against reality. Rename a button or change who may promote a
widget and you edit three files: `src/pages/UserGuidePage.tsx` for humans,
`app_guide.md` for the agent, `RELEASE_NOTES.md` for the changelog.

## Environments and the database model

The app takes an `env` parameter per request (`"dev"` default) and picks storage
from it, so a single deployment can address `dev` / `test` / `prod`. Startup
initializes all three:

```python
for _env in ("dev", "test", "prod"):
    init_db(_env)
```

Two generations of storage layout exist, and they encode `env` in *different
places* — this has already caused an incident where widgets appeared to vanish:

- **Legacy instance `command-center`**: no injected `PGDATABASE`, so the code
  synthesized a per-env **database** (`command-center-dev` / `-test` / `-prod`)
  and never pinned a schema. Data sits in **`public`**.
- **Bundle-managed instances `command-center-<environment>-v1`**: Databricks Apps
  injects `PGDATABASE=databricks_postgres`, which is used verbatim *and* is the
  condition that enables schema pinning. Environment becomes the **schema**
  (`dev` / `test` / `prod`).

`APP_DB_SCHEMA` overrides schema selection (e.g. `public`) so a deployment whose
data predates the split can be pointed back at it without migrating.

**Before deploying `stage` or `prod`, check whether
`command-center-<env>-v1` already exists.** If it doesn't, the bundle creates a
fresh empty instance and that environment's widgets will look deleted — the data
is still in the legacy instance, just unreferenced. Note also that both the
`enterprise-dev` and `supply-dev` targets set `environment: "dev"`, so they
share one instance.

Schema DDL is idempotent (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT
EXISTS`) and serialized across uvicorn workers with a Postgres advisory lock,
because concurrent DDL can raise `duplicate key` / `tuple concurrently updated`.
An unhandled exception during startup takes down the whole app with "Child
process failed to start, stopping the parent process", which is why `init_db`
failures are caught and logged instead of raised.

## Configuration

`databricks.yml` is authoritative for deployed configuration; `.env` covers
local development (`dev.sh` sources it). Bundle variables let a target override
warehouse, app name, permissions, and Lakebase wiring without duplicating the
resource block.

Not everything is env-only any more: the model each LLM caller uses and the chat
agent's step/token caps are rows in `app_settings`, edited from Admin Panel →
Settings, with the env vars below as fallbacks (**row > env var > built-in
default**). See `server/AGENTS.md` → *Deployment settings*, and don't add a new env
var for something an admin should be able to change without a redeploy.

Frequently relevant env vars: `DATABRICKS_HOST` / `DATABRICKS_CLIENT_ID` /
`DATABRICKS_CLIENT_SECRET` (SP auth), `SQL_WAREHOUSE_ID`, `APP_DB_SCHEMA`,
`LAKEBASE_INSTANCE_NAME`, `AGENT_LOCAL_RUNTIME` (default `true` — in-process
agent; `false` forwards to the external consolidated agent at
`CONSOLIDATED_AGENT_URL`), the `AGENT_RUNTIME_*` family (model, auth mode, step
cap, Genie polling), the `AGENT_STUDIO_*` family (authoring model, MCP servers,
sandbox limits), `APP_SETTINGS_ENV` (which schema holds `app_settings`; settings
are deployment-global, not per-env), and `DISABLE_PERMISSION_CHECKS`.

`DISABLE_PERMISSION_CHECKS=true` is a **temporary demo kill-switch that makes
every signed-in user a global admin.** It is currently enabled. Don't build
logic that assumes it's off, and don't quietly leave it on when hardening.

## Known documentation drift

`README.md` is the product/ops manual and is broadly right about intent, but a
few specifics have rotted. Trust the code over the docs here:

- The custom-widget template imports `from server.auth import get_current_user,
  get_obo_token`. No such module. Auth dependencies live in
  `server/middleware/auth.py` as `get_user_token`, `get_db_client`,
  `get_db_client_for_jobs`, `get_db_client_sp`, `require_auth`.
- It describes `server/routes/custom_widgets/` as a directory that's
  dynamically scanned for routers. Reality: `server/routes/custom_widgets.py`,
  a single module explicitly mounted in `main.py`. New routers must be
  registered there by hand.
- It documents the backend on port 8000 (as does `.env.example`, which then sets
  `AGENT_BASE_URL` to 8001). Actual backend port is 8001.
- The repo-structure block shows a `client/` prefix and `src/widgets/`; the real
  tree is `src/` at the root with no widgets directory.

`.claude/project_context.md` is an earlier AI-context file with overlapping
content and a couple of stale "known bugs". Prefer these AGENTS.md files; update
that one only if you're already working in it.

## Conventions

Match surrounding style rather than importing your own. Comments in this
codebase are used to explain *why* — particularly the non-obvious platform
constraints (advisory locks, OBO vs SP, Genie's polling contract). That's a
deliberate pattern worth continuing; skip comments that merely restate code.

Gitflow: feature branch → PR into `develop`. External contributors fork and PR.
