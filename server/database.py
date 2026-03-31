import os
import uuid
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
        for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break
                
        separator = "_"
        if "-" in base_name:
            separator = "_"
            base_name = base_name.replace("-", "_")
            
        db_name = f"{base_name}{separator}{env}"
        
        # Format instance_name
        if instance_name:
            base_inst = instance_name
            for suffix in ("-dev", "-test", "-prod", "_dev", "_test", "_prod"):
                if base_inst.endswith(suffix):
                    base_inst = base_inst[:-len(suffix)]
                    break
            # Lakebase instance and project names CANNOT contain underscores.
            # Convert any existing underscores to hyphens.
            inst_separator = "-"
            if "_" in base_inst:
                base_inst = base_inst.replace("_", "-")
            instance_name = f"{base_inst}{inst_separator}{env}"
        
    host = config.get("host")
    port = config.get("port")
    user = config.get("user")
    password = config.get("password")
    
    # If no password is provided and we aren't using a local db,
    # generate a short-lived OAuth token via the Databricks SDK.
    if not password and host and host != "localhost":
        w = WorkspaceClient()
        
        # Determine if this is an Autoscaling or Provisioned Lakebase.
        # Autoscaling uses a path like projects/NAME/branches/...
        # If the user just provided a plain name, try Autoscaling defaults first, then fall back to Provisioned.
        endpoint_path = instance_name
        if instance_name and not instance_name.startswith("projects/"):
            endpoint_path = f"projects/{instance_name}/branches/production/endpoints/primary"
            
        try:
            # Try Autoscaling Lakebase (the modern default)
            res = w.api_client.do(
                "POST", 
                f"/api/2.0/postgres-databases/{endpoint_path}/generate-database-credential",
                body={}
            )
            password = res.get("token")
        except Exception as e:
            # Fall back to Provisioned Lakebase (legacy)
            try:
                # Based on user logs, `generate_database_credential` is not finding the instance by name
                # Let's try to query the list of instances, find the one matching the name to get its UID,
                # and then generate the token via UID.
                try:
                    list_res = w.api_client.do("GET", "/api/2.0/database-instances")
                    instances = list_res.get("database_instances", [])
                except Exception:
                    instances = []
                
                target_uid = None
                for inst in instances:
                    if inst.get("name") == instance_name:
                        target_uid = inst.get("uid")
                        break
                        
                if target_uid:
                    # Now we have the UID, generate the token
                    creds = w.database.generate_database_credential(
                        request_id = str(uuid.uuid4()),
                        database_instance_uids=[target_uid]
                    )
                    password = creds.token
                else:
                    # Absolute fallback to the SDK method just in case
                    creds = w.database.generate_database_credential(
                        request_id = str(uuid.uuid4()),
                        instance_names=[instance_name] if instance_name else []
                    )
                    password = creds.token
            except Exception as e2:
                raise Exception(f"Failed to generate Lakebase credentials. Autoscaling attempt failed: {str(e)}. Provisioned attempt failed: {str(e2)}")

    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=db_name
    )

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
