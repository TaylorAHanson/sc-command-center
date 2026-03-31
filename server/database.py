import os
import uuid
import logging
from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import get_lakebase_config
from databricks.sdk import WorkspaceClient

def get_db_connection(env: str = "dev"):
    """Get a database connection (SQLite or Lakebase/Postgres)."""
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
        
    host = config.get("host")
    port = config.get("port")
    user = config.get("user")
    password = config.get("password")
    
    # If no password is provided and we aren't using a local db,
    # generate a short-lived OAuth token via the Databricks SDK.
    if not password and host and host != "localhost":
        w = WorkspaceClient()
        
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
                if inst.get("name") in (target_underscores, target_hyphens, instance_name):
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
        
        # 1. Try Provisioned with underscores (e.g. command_center_dev)
        if not token_found:
            try:
                logging.info(f"Attempt 1: Provisioned with underscores '{target_underscores}'")
                creds = w.database.generate_database_credential(
                    request_id = str(uuid.uuid4()),
                    instance_names=[target_underscores]
                )
                password = creds.token
                token_found = True
                logging.info(f"Success! Generated token using Provisioned SDK for '{target_underscores}'")
            except Exception as e:
                err_msg = str(e)
                logging.warning(f"Attempt 1 failed: {err_msg}")
                errors.append(f"Provisioned ({target_underscores}): {err_msg}")
                
        # 2. Try Provisioned with hyphens (e.g. command-center-dev)
        if not token_found and target_hyphens != target_underscores:
            try:
                logging.info(f"Attempt 2: Provisioned with hyphens '{target_hyphens}'")
                creds = w.database.generate_database_credential(
                    request_id = str(uuid.uuid4()),
                    instance_names=[target_hyphens]
                )
                password = creds.token
                token_found = True
                logging.info(f"Success! Generated token using Provisioned SDK for '{target_hyphens}'")
            except Exception as e:
                err_msg = str(e)
                logging.warning(f"Attempt 2 failed: {err_msg}")
                errors.append(f"Provisioned ({target_hyphens}): {err_msg}")

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

    logging.info(f"Connecting to Postgres host={host}, port={port}, dbname={db_name}, user={user}, sslmode={conn_kwargs.get('sslmode', 'default')}")
    return psycopg2.connect(**conn_kwargs)

def init_db(env: str = "dev"):
    """Initialize database tables."""
    conn = get_db_connection(env)
    c = conn.cursor()
    
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
    
    # Simple migration: add action_name if it doesn't exist
    try:
        c.execute("ALTER TABLE action_logs ADD COLUMN IF NOT EXISTS action_name TEXT")
    except:
        pass # In case IF NOT EXISTS isn't supported or other issues
        
    try:
        c.execute("ALTER TABLE widgets ADD COLUMN IF NOT EXISTS snapshot TEXT")
    except:
        pass
        
    try:
        c.execute("ALTER TABLE widgets ADD COLUMN IF NOT EXISTS open_in_new_tab_link TEXT")
    except:
        pass
    
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

    
    conn.commit()
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
