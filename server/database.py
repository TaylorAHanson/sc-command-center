import os
import threading
import time
import uuid
import logging
from typing import Dict, List, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import get_lakebase_config
from databricks.sdk import WorkspaceClient
import db_pool

# Resolving Lakebase connection parameters is expensive: identifying the caller,
# listing database instances/projects to work out which naming convention this
# workspace uses, then minting a credential — three or more control-plane round
# trips. Doing that per HTTP request made pages that issue several calls at once
# (Widget Studio loads domains, categories and roles in parallel) intermittently
# fail on control-plane latency or throttling. The minted token is valid for
# roughly an hour; we reuse it for a conservative slice of that and drop the
# entry whenever a connection attempt with it fails.
_CRED_TTL_SECONDS = int(os.environ.get("LAKEBASE_CRED_TTL_SECONDS", "600"))
_cred_cache: Dict[str, Dict[str, Any]] = {}
_cred_cache_lock = threading.Lock()


def _cached_conn_kwargs(env: str) -> Optional[Dict[str, Any]]:
    with _cred_cache_lock:
        entry = _cred_cache.get(env)
        if not entry:
            return None
        if time.monotonic() >= entry["expires_at"]:
            _cred_cache.pop(env, None)
            return None
        return dict(entry["conn_kwargs"])


def _store_conn_kwargs(env: str, conn_kwargs: Dict[str, Any]) -> None:
    with _cred_cache_lock:
        _cred_cache[env] = {
            "conn_kwargs": dict(conn_kwargs),
            "expires_at": time.monotonic() + _CRED_TTL_SECONDS,
        }


def invalidate_db_credentials(env: Optional[str] = None) -> None:
    """Drop cached connection parameters so the next call re-resolves them.

    Also retires pooled connections opened with the credentials being dropped:
    they are usually being dropped because something about them stopped working,
    and a pool that kept serving them would keep serving the failure.
    """
    with _cred_cache_lock:
        if env is None:
            _cred_cache.clear()
        else:
            _cred_cache.pop(env, None)
    db_pool.invalidate(env)


def _sp_workspace_client() -> WorkspaceClient:
    """Build a service-principal WorkspaceClient with auth pinned explicitly.

    Used to mint Lakebase credentials. We pass the SP client_id/secret directly
    and set auth_type="oauth-m2m" rather than relying on the SDK's default-auth
    detection. Default detection reads process-global env vars at call time, so a
    concurrent request that was mutating those vars could make a bare
    ``WorkspaceClient()`` here fail with "default auth: cannot configure default
    credentials". Pinning the method removes that fragility. Falls back to
    default auth only when the SP env vars aren't present (e.g. local dev with a
    CLI profile).
    """
    host = os.environ.get("DATABRICKS_HOST")
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
    if host and client_id and client_secret:
        return WorkspaceClient(
            host=host,
            client_id=client_id,
            client_secret=client_secret,
            auth_type="oauth-m2m",
        )
    return WorkspaceClient()


def _schema_for(env: str) -> Optional[str]:
    """The schema this environment's tables live in, or None to leave the default.

    On managed Lakebase the app's role can CONNECT + CREATE but is NOT the owner
    of the `public` schema, so an unqualified CREATE TABLE fails with "permission
    denied for schema public" (Postgres 15+ no longer grants CREATE on `public` to
    PUBLIC). Use a dedicated, role-owned schema per environment and pin
    search_path to it so every table/query lives there. This also keeps
    dev/test/prod isolated now that they all share the one injected
    `databricks_postgres` database. Skipped locally (no PGDATABASE), where the
    default `public` schema is owned by the connecting user.

    An existing deployment whose data predates that change has all its rows in
    `public`; pinning to an empty env schema makes widgets/views appear to vanish.
    APP_DB_SCHEMA points such a deployment back at the schema that actually holds
    its data (e.g. "public") without a data migration. Unset => per-env isolation.
    """
    if not os.environ.get("PGDATABASE"):
        return None
    return os.environ.get("APP_DB_SCHEMA", "").strip() or (
        env if env in ("dev", "test", "prod") else "app"
    )


# `CREATE SCHEMA IF NOT EXISTS` needs to run once, not on every connection: it is
# three extra round trips (DDL plus the commit) against something that can only
# be true after the first time, measured at ~400ms per connection from outside the
# workspace. The search_path itself travels in the startup packet instead, which
# costs nothing. Per process, so a restart re-checks.
_schema_ready: set = set()
_schema_ready_lock = threading.Lock()


def _ensure_schema(conn, env: str, schema: str) -> None:
    with _schema_ready_lock:
        if (env, schema) in _schema_ready:
            return
    try:
        cur = conn.cursor()
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.commit()
        cur.close()
        with _schema_ready_lock:
            _schema_ready.add((env, schema))
    except Exception as e:
        conn.rollback()
        logging.warning(f"Could not ensure schema '{schema}': {e}")


def _connect(conn_kwargs: Dict[str, Any], env: str):
    """Open a connection and pin the schema this environment stores data in."""
    logging.info(
        "Connecting to Postgres host=%s, port=%s, dbname=%s, user=%s, sslmode=%s",
        conn_kwargs.get("host"), conn_kwargs.get("port"), conn_kwargs.get("dbname"),
        conn_kwargs.get("user"), conn_kwargs.get("sslmode", "default"),
    )
    schema = _schema_for(env)
    kwargs = dict(conn_kwargs)
    # A libpq `options` string is whitespace-separated, so only a plain identifier
    # can travel in it. Anything else falls back to a statement, quoted.
    inline_schema = bool(schema) and schema.replace("_", "").isalnum()
    if inline_schema:
        # Sent with the connection request, so the session starts on the right
        # search_path without a statement of its own.
        kwargs["options"] = f"-c search_path={schema}"
    conn = psycopg2.connect(**kwargs)
    if schema:
        _ensure_schema(conn, env, schema)
        if not inline_schema:
            try:
                cur = conn.cursor()
                cur.execute(f'SET search_path TO "{schema}"')
                conn.commit()
                cur.close()
            except Exception as e:
                conn.rollback()
                logging.warning(f"Could not select schema '{schema}': {e}")
    return conn


def get_db_connection(env: str = "dev", pooled: bool = True):
    """Get a database connection for ``env``.

    Connections are pooled per environment (see ``db_pool``), so most calls hand
    back a connection that is already open. Call ``close()`` when finished — that
    returns it to the pool — and the pool will reclaim it anyway if an error path
    misses the close.

    ``pooled=False`` opens a connection of its own, for work that changes session
    state the next caller must not inherit: schema init holds a session-level
    advisory lock, which would keep blocking other workers if the connection
    carrying it went back into circulation.
    """
    if not pooled:
        return _open_connection(env)
    return db_pool.acquire(env, lambda: _open_connection(env))


def _open_connection(env: str):
    """Open one new connection, resolving credentials if the cache has none."""
    cached = _cached_conn_kwargs(env)
    if cached:
        try:
            return _connect(cached, env)
        except Exception as e:
            # Most likely an expired or revoked credential. Re-resolve from
            # scratch below rather than failing the request.
            logging.warning(f"Cached Lakebase credentials failed for env={env}, re-resolving: {e}")
            invalidate_db_credentials(env)

    config = get_lakebase_config()
    db_name = config.get("database")
    instance_name = config.get("instance_name")

    if env and env in ("dev", "test", "prod"):
        # Format db_name
        base_name = db_name
        separator = "_"
        if db_name and "-" in db_name:
            separator = "-"
            
        for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break

        # Only synthesize a per-env database name for the legacy/local default.
        # When the Databricks Apps `postgres` resource injects a real PGDATABASE
        # (e.g. "databricks_postgres"), that logical database already exists and
        # must be used verbatim — appending "_dev" yields "databricks_postgres_dev",
        # which does not exist and fails startup with "database ... does not exist".
        if not os.environ.get("PGDATABASE"):
            db_name = f"{base_name}{separator}{env}"

        # Format instance_name variations
        target_hyphens = instance_name
        target_underscores = instance_name
        
        if instance_name:
            base_inst = instance_name
            for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
                if base_inst.endswith(suffix):
                    base_inst = base_inst[:-len(suffix)]
                    break
            
            base_inst_hyphens = base_inst.replace("_", "-")
            base_inst_underscores = base_inst.replace("-", "_")
            
            target_hyphens = f"{base_inst_hyphens}-{env}"
            target_underscores = f"{base_inst_underscores}_{env}"
            
            # Also just try the exact instance name provided, unmodified, since sometimes it doesn't match the env suffix
            raw_instance_name = instance_name
        
    host = config.get("host")
    port = config.get("port")
    user = config.get("user")
    password = config.get("password")
    
    # If no password is provided and we aren't using a local db,
    # generate a short-lived OAuth token via the Databricks SDK.
    if not password and host and host != "localhost":
        w = _sp_workspace_client()
        
        try:
            me = w.current_user.me()
            user = me.user_name
            logging.info(f"Set Postgres user to Databricks identity: {user}")
        except Exception as e:
            logging.warning(f"Could not get current Databricks user via SDK: {e}")
            try:
                # Fallback to direct API call if SDK method fails
                me_data = w.api_client.do("GET", "/api/2.0/preview/scim/v2/Me")
                user = me_data.get("userName", user)
                logging.info(f"Set Postgres user to Databricks identity (fallback): {user}")
            except Exception as e2:
                logging.warning(f"Could not get current Databricks user via fallback API: {e2}")
        
        # Robust credential generation strategy:
        # Try all permutations of Legacy/Provisioned and Modern/Autoscaling
        
        errors = []
        token_found = False
        
        logging.info(f"Attempting to generate Lakebase credentials for env '{env}'. Targets -> Hyphens: '{target_hyphens}', Underscores: '{target_underscores}'")
        
        # Super-robust strategy: Pull all instances first to see what actually exists
        try:
            logging.info("Fetching list of all Provisioned Lakebase instances in workspace...")
            list_res = w.api_client.do("GET", "/api/2.0/database-instances")
            instances = list_res.get("database_instances", [])
            instance_names = [inst.get("name") for inst in instances]
            logging.info(f"Found {len(instances)} Provisioned instances: {instance_names}")
            
            # Check if any of our targets match an existing instance
            target_uid = None
            matched_name = None
            for inst in instances:
                if inst.get("name") in (target_underscores, target_hyphens, raw_instance_name, base_inst, base_inst_hyphens):
                    target_uid = inst.get("uid")
                    matched_name = inst.get("name")
                    break
                    
            if target_uid:
                logging.info(f"Found match! Instance '{matched_name}' has UID {target_uid}. Generating token via UID...")
                creds = w.database.generate_database_credential(
                    request_id=str(uuid.uuid4()),
                    database_instance_uids=[target_uid]
                )
                password = creds.token
                token_found = True
                logging.info("Success! Generated token via UID.")
        except Exception as e:
            logging.warning(f"Failed to fetch/match instances by UID: {str(e)}")

        # Now try to dynamically discover Autoscaling endpoints
        if not token_found:
            try:
                logging.info("Fetching list of all Autoscaling projects in workspace...")
                projects_res = w.api_client.do("GET", "/api/2.0/postgres/projects")
                projects = projects_res.get("projects", [])
                
                project_names = [p.get("name", "") for p in projects]
                logging.info(f"Found {len(projects)} Autoscaling projects: {project_names}")
                
                # Check if any project matches our variations
                matched_project_name = None
                
                # Derive base instance name without suffix
                base_inst = instance_name if instance_name else ""
                for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
                    if base_inst.endswith(suffix):
                        base_inst = base_inst[:-len(suffix)]
                        break
                base_inst_hyphens = base_inst.replace("_", "-")
                
                potential_project_names = [
                    target_hyphens, 
                    target_underscores, 
                    instance_name, 
                    base_inst_hyphens
                ]
                
                for p in projects:
                    p_name = p.get("name", "")
                    # Project name usually follows 'projects/my-project' format in the API, or just 'my-project'
                    short_name = p_name.split("/")[-1] if "/" in p_name else p_name
                    
                    if short_name in potential_project_names:
                        matched_project_name = short_name
                        break
                        
                if matched_project_name:
                    dynamic_endpoint_path = f"projects/{matched_project_name}/branches/production/endpoints/primary"
                    logging.info(f"Found matching Autoscaling project '{matched_project_name}'! Attempting to generate token for {dynamic_endpoint_path}...")
                    
                    res = w.api_client.do(
                        "POST", 
                        f"/api/2.0/postgres/credentials",
                        body={"endpoint": dynamic_endpoint_path}
                    )
                    password = res.get("token")
                    token_found = True
                    logging.info(f"Success! Generated token dynamically for '{dynamic_endpoint_path}'")
                    
            except Exception as e:
                logging.warning(f"Failed to fetch/match Autoscaling projects: {str(e)}")

        # If dynamic approaches didn't work, fall back to standard hardcoded attempts
        
        if not token_found:
            provisioned_candidates = []
            for cand in [target_underscores, target_hyphens, raw_instance_name, base_inst, base_inst_hyphens]:
                if cand and cand not in provisioned_candidates:
                    provisioned_candidates.append(cand)
                    
            for cand in provisioned_candidates:
                if token_found:
                    break
                try:
                    logging.info(f"Attempting Provisioned SDK for '{cand}'")
                    creds = w.database.generate_database_credential(
                        request_id = str(uuid.uuid4()),
                        instance_names=[cand]
                    )
                    password = creds.token
                    token_found = True
                    logging.info(f"Success! Generated token using Provisioned SDK for '{cand}'")
                except Exception as e:
                    err_msg = str(e)
                    logging.warning(f"Provisioned attempt failed for '{cand}': {err_msg}")
                    errors.append(f"Provisioned ({cand}): {err_msg}")

        # 3. Try Autoscaling (requires hyphens)
        if not token_found:
            autoscaling_candidates = []
            
            if target_hyphens:
                if target_hyphens.startswith("projects/"):
                    autoscaling_candidates.append(target_hyphens)
                else:
                    autoscaling_candidates.append(f"projects/{target_hyphens}/branches/production/endpoints/primary")
            
            if instance_name:
                # Try the base instance name without the -dev/-test/-prod suffix
                base_inst = instance_name
                for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
                    if base_inst.endswith(suffix):
                        base_inst = base_inst[:-len(suffix)]
                        break
                base_inst_hyphens = base_inst.replace("_", "-")
                if base_inst_hyphens and base_inst_hyphens != target_hyphens:
                    autoscaling_candidates.append(f"projects/{base_inst_hyphens}/branches/production/endpoints/primary")
                    
            for endpoint_path in autoscaling_candidates:
                if token_found:
                    break
                try:
                    logging.info(f"Attempt 3: Autoscaling REST API '{endpoint_path}'")
                    res = w.api_client.do(
                        "POST", 
                        f"/api/2.0/postgres/credentials",
                        body={"endpoint": endpoint_path}
                    )
                    password = res.get("token")
                    token_found = True
                    logging.info(f"Success! Generated token using Autoscaling API for '{endpoint_path}'")
                except Exception as e:
                    err_msg = str(e)
                    logging.warning(f"Attempt 3 failed for {endpoint_path}: {err_msg}")
                    errors.append(f"Autoscaling ({endpoint_path}): {err_msg}")
                
        # 4. Try Autoscaling legacy API path just in case
        if not token_found:
            pass

        if not token_found:
            final_error = f"Failed to generate Lakebase credentials. Attempts: " + " | ".join(errors)
            logging.error(final_error)
            raise Exception(final_error)

    conn_kwargs = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "dbname": db_name
    }
    
    if host and host != "localhost":
        conn_kwargs["sslmode"] = "require"
        # Pooled connections sit idle between requests, where a silently dropped
        # socket would otherwise only surface as a failed query. Keepalives let
        # the kernel notice, and the pool then discards the connection instead of
        # handing it out.
        conn_kwargs.update({
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        })

    conn = _connect(conn_kwargs, env)
    # Only cache parameters that are known to work.
    _store_conn_kwargs(env, conn_kwargs)
    return conn

def _advisory_lock_key(env: str) -> int:
    """Stable per-env key for the schema-init advisory lock (see init_db)."""
    base = 918273645  # arbitrary constant, just needs to be app-unique
    return base + {"dev": 0, "test": 1, "prod": 2}.get(env, 9)


def init_db(env: str = "dev"):
    """Initialize database tables.

    Runs in EVERY uvicorn worker at startup (see server/main.py). Because the
    app runs multiple workers (databricks.yml `--workers`), two workers execute
    this concurrently. Postgres DDL — even ``CREATE TABLE IF NOT EXISTS`` and
    ``ADD COLUMN IF NOT EXISTS`` — is not atomic against the system catalogs, so
    concurrent runs can raise ``duplicate key``/``tuple concurrently updated``.
    An unhandled error here fails the worker's startup, and uvicorn then stops
    the whole app ("Child process failed to start, stopping the parent process").

    We serialize schema init with a session-level advisory lock so exactly one
    worker builds the schema while the others wait, then run the same (now no-op)
    idempotent statements. The connection is deliberately unpooled: the lock
    belongs to the session, so a connection that failed part-way through would
    otherwise return to the pool still holding it.
    """
    conn = get_db_connection(env, pooled=False)
    c = conn.cursor()

    lock_key = _advisory_lock_key(env)
    got_lock = False
    try:
        c.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
        conn.commit()
        got_lock = True
    except Exception as e:  # noqa: BLE001
        # Couldn't take the lock (unexpected) — proceed anyway; the idempotent
        # DDL below is still correct, just no longer serialized.
        conn.rollback()
        logging.warning(f"init_db advisory lock failed for env={env}: {e}")

    # Postgres
    auto_inc = "SERIAL PRIMARY KEY"
    default_ts = "DEFAULT CURRENT_TIMESTAMP" 

    # Widget Runs Table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS widget_runs (
            id {auto_inc},
            widget_id TEXT NOT NULL,
            timestamp TIMESTAMP {default_ts}
        )
    ''')
    
    # Action Logs (Telemetry) Table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS action_logs (
            id {auto_inc},
            widget_id TEXT,
            widget_name TEXT,
            action_name TEXT,
            user_explanation TEXT,
            dashboard_context TEXT,
            timestamp TIMESTAMP {default_ts}
        )
    ''')
    
    # Core + Custom Widgets Table with Versioning
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS widgets (
            id TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            domain TEXT,
            default_w INTEGER DEFAULT 4,
            default_h INTEGER DEFAULT 4,
            tsx_code TEXT,
            configuration_mode TEXT DEFAULT 'none',
            config_schema TEXT,
            data_source_type TEXT DEFAULT 'api',
            data_source TEXT,
            snapshot TEXT,
            open_in_new_tab_link TEXT,
            is_executable INTEGER DEFAULT 0,
            is_certified INTEGER DEFAULT 0,
            is_deprecated INTEGER DEFAULT 0,
            created_by TEXT,
            timestamp TIMESTAMP {default_ts},
            PRIMARY KEY (id, version)
        )
    ''')

    # Domain and Role Mapping Table
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS role_mappings (
            id {auto_inc},
            external_role TEXT NOT NULL,
            domain TEXT NOT NULL,
            permission_level TEXT DEFAULT 'editor',
            timestamp TIMESTAMP {default_ts}
        )
    ''')

    # Dashboard Views Table
    # Stores user-specific views and domain-specific global templates
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS dashboard_views (
            id TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            name TEXT NOT NULL,
            domain TEXT,
            username TEXT,
            is_global INTEGER DEFAULT 0,
            widgets_json TEXT,
            is_locked INTEGER DEFAULT 0,
            timestamp TIMESTAMP {default_ts},
            PRIMARY KEY (id, version)
        )
    ''')

    # Shared Views Table
    # Tracks which users have subscribed to which shared views
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS shared_views (
            username TEXT NOT NULL,
            view_id TEXT NOT NULL,
            timestamp TIMESTAMP {default_ts},
            PRIMARY KEY (username, view_id)
        )
    ''')

    # Agent Studio Profiles Table (versioned, domain-scoped)
    # Agents authored in the Agent Studio now live as DB rows instead of files on
    # Unity Catalog Volumes / Workspace folders. This mirrors the widget/view
    # storage model so a user with app access (but no workspace access) can still
    # save agents, and so visibility is governed by role_mappings (domains) rather
    # than UC file grants.
    #   - visibility='personal' : only the creator (username) sees it.
    #   - visibility='domain'   : anyone with access to `domain` sees it;
    #                             domain editors can edit.
    #   - visibility='global'   : visible to every user; only global admins edit.
    # Skills, tools, and author-written Python tools are stored inline as JSON so
    # the whole agent is one atomic row set (versioned like widgets/views).
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS agent_profiles (
            id TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            model TEXT DEFAULT '',
            base TEXT DEFAULT 'full',
            prompt TEXT DEFAULT '',
            tools_json TEXT DEFAULT '[]',
            skills_json TEXT DEFAULT '[]',
            python_tools_json TEXT DEFAULT '[]',
            domain TEXT DEFAULT 'General',
            visibility TEXT DEFAULT 'personal',
            username TEXT DEFAULT '',
            is_deprecated INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT '',
            timestamp TIMESTAMP {default_ts},
            PRIMARY KEY (id, version)
        )
    ''')

    # Widget Categories (managed by admins, surfaced in Widget Studio + Library)
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS widget_categories (
            id {auto_inc},
            name TEXT NOT NULL UNIQUE,
            timestamp TIMESTAMP {default_ts}
        )
    ''')

    # Widget Domains (managed by admins, surfaced in Widget Studio + Library)
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS widget_domains (
            id {auto_inc},
            name TEXT NOT NULL UNIQUE,
            timestamp TIMESTAMP {default_ts}
        )
    ''')

    # Deployment-wide admin settings (which serving endpoint the agents call, tool
    # and token limits). One row per key, last write wins. These override the
    # matching env vars at runtime so an admin can change models without a
    # redeploy; see services/settings_store.py for the precedence.
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_by TEXT DEFAULT '',
            timestamp TIMESTAMP {default_ts}
        )
    ''')

    # Assistant conversations. The transcript lives here rather than in the
    # browser for two reasons: the app runs multiple uvicorn workers so nothing
    # can be kept in process memory, and uploaded files are server-side rows that
    # a localStorage transcript could only dangle references to. Persisting turns
    # server-side also means an answer survives the tab closing mid-stream.
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT DEFAULT '',
            profile_id TEXT DEFAULT '',
            created_at TIMESTAMP {default_ts},
            updated_at TIMESTAMP {default_ts}
        )
    ''')

    # One row per turn. `seq` orders the transcript within a conversation and is
    # assigned server-side, so two browser tabs on the same conversation cannot
    # interleave into the same slot. tool_calls_json / attachments_json mirror the
    # shapes the drawer renders, so a reloaded conversation looks identical to a
    # live one (tool pills and file chips included).
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS chat_messages (
            conversation_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT DEFAULT '',
            reasoning TEXT DEFAULT '',
            tool_calls_json TEXT DEFAULT '[]',
            attachments_json TEXT DEFAULT '[]',
            is_error INTEGER DEFAULT 0,
            created_at TIMESTAMP {default_ts},
            PRIMARY KEY (conversation_id, seq)
        )
    ''')

    # Files a user attached to a conversation. `raw` keeps the original bytes so
    # images and PDFs can be handed to the model natively; `parsed` holds the
    # normalized form (a zip of Parquet, one member per sheet) so re-reading a
    # spreadsheet on each tool call costs a Parquet read instead of an XLSX parse.
    # Extraction happens in a background task, hence status/error.
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS chat_uploads (
            id TEXT PRIMARY KEY,
            conversation_id TEXT DEFAULT '',
            username TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime TEXT DEFAULT '',
            size_bytes INTEGER DEFAULT 0,
            kind TEXT DEFAULT '',
            status TEXT DEFAULT 'parsing',
            error TEXT DEFAULT '',
            raw BYTEA,
            parsed BYTEA,
            text_content TEXT DEFAULT '',
            profile_json TEXT DEFAULT '{{}}',
            warnings_json TEXT DEFAULT '[]',
            created_at TIMESTAMP {default_ts}
        )
    ''')

    # The drawer opens on "most recent conversation for this user" and every
    # transcript read is keyed by conversation, so both lookups get an index.
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON chat_conversations (username, updated_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_uploads_conversation ON chat_uploads (conversation_id)")
        conn.commit()
    except Exception:
        conn.rollback()

    # Seed defaults the first time the tables are created
    try:
        c.execute("SELECT COUNT(*) FROM widget_categories")
        if c.fetchone()[0] == 0:
            for name in [
                "Monitoring", "Analytics", "Planning", "AI & Automation",
                "Actions", "Finance", "Operations", "Sales", "Logistics", "Inventory"
            ]:
                c.execute("INSERT INTO widget_categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
        c.execute("SELECT COUNT(*) FROM widget_domains")
        if c.fetchone()[0] == 0:
            for name in ["General", "Supply Chain", "Engineering", "Sales"]:
                c.execute("INSERT INTO widget_domains (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
        conn.commit()
    except Exception:
        conn.rollback()
    
    # Simple migrations: add columns if they don't exist
    # Run these AFTER tables are created so they don't fail on a fresh DB
    try:
        c.execute("ALTER TABLE action_logs ADD COLUMN IF NOT EXISTS action_name TEXT")
        conn.commit()
    except Exception as e:
        conn.rollback() # MUST rollback aborted transaction before continuing
        pass # Ignore if not supported
        
    try:
        c.execute("ALTER TABLE widgets ADD COLUMN IF NOT EXISTS snapshot TEXT")
        conn.commit()
    except Exception as e:
        conn.rollback()
        pass
        
    try:
        c.execute("ALTER TABLE widgets ADD COLUMN IF NOT EXISTS help_text TEXT")
        conn.commit()
    except Exception as e:
        conn.rollback()
        pass

    try:
        c.execute("ALTER TABLE widgets ADD COLUMN IF NOT EXISTS open_in_new_tab_link TEXT")
        conn.commit()
    except Exception as e:
        conn.rollback()
        pass

    # Seed default global admin if none exists yet
    try:
        c.execute(
            "SELECT COUNT(*) FROM role_mappings WHERE LOWER(domain) IN ('global', 'all', 'app') AND permission_level = 'admin'"
        )
        count = c.fetchone()[0]
        if count == 0:
            logging.info("No global admin mapping found - seeding default global admin for group 'users'")
            c.execute(
                "INSERT INTO role_mappings (external_role, domain, permission_level) VALUES (%s, %s, %s)",
                ("users", "Global", "admin")
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        logging.warning(f"Could not seed default global admin mapping: {e}")

    conn.commit()

    # Release the schema-init lock so the next worker can proceed. (A crashed
    # worker would drop its connection and release it automatically, but release
    # explicitly on the happy path so we never hold it longer than needed.)
    if got_lock:
        try:
            c.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            conn.commit()
        except Exception:  # noqa: BLE001
            conn.rollback()

    conn.close()

def log_widget_run(widget_id: str, env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()
    # Postgres uses %s for placeholders
    c.execute('INSERT INTO widget_runs (widget_id) VALUES (%s)', (widget_id,))
        
    conn.commit()
    conn.close()
    return {"status": "success", "widget_id": widget_id}

def log_user_action(widget_id: str, widget_name: str, explanation: str, context: str, action_name: str = "", env: str = "dev"):
    conn = get_db_connection(env)
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO action_logs (widget_id, widget_name, action_name, user_explanation, dashboard_context) 
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    ''', (widget_id, widget_name, action_name, explanation, context))
    last_id = c.fetchone()[0]
        
    conn.commit()
    conn.close()
    return {"status": "success", "action_id": last_id}

def get_action_logs(limit: int = 100, offset: int = 0, env: str = "dev") -> List[Dict[str, Any]]:
    conn = get_db_connection(env)
    
    c = conn.cursor(cursor_factory=RealDictCursor)
    query = '''
        SELECT al.id, al.widget_id, al.widget_name, al.action_name, al.user_explanation, al.dashboard_context,
               al.timestamp, w.domain
        FROM action_logs al
        LEFT JOIN (
            SELECT id, domain
            FROM widgets
            WHERE is_deprecated = 0
            AND version = (
                SELECT MAX(version) FROM widgets w2
                WHERE w2.id = widgets.id AND w2.is_deprecated = 0
            )
        ) w ON al.widget_id = w.id
        ORDER BY al.timestamp DESC 
        LIMIT %s OFFSET %s
    '''
    c.execute(query, (limit, offset))
    
    # RealDictCursor return dict-like objects
    logs = [dict(row) for row in c.fetchall()]
        
    conn.close()
    return logs

def get_popularity_scores(env: str = "dev") -> Dict[str, int]:
    conn = get_db_connection(env)
    c = conn.cursor()
    c.execute('SELECT widget_id, COUNT(*) as count FROM widget_runs GROUP BY widget_id')
    rows = c.fetchall()
    
    scores = {}
    for row in rows:
        # Standard cursor returns tuples
        scores[row[0]] = row[1]
            
    conn.close()
    return scores
