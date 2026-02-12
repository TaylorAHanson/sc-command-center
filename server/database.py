import sqlite3
import os
from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import is_lakebase_enabled, get_lakebase_config

DB_PATH = os.path.join(os.path.dirname(__file__), "widgets.db")

def get_db_connection():
    """Get a database connection (SQLite or Lakebase/Postgres)."""
    if is_lakebase_enabled():
        config = get_lakebase_config()
        return psycopg2.connect(
            host=config.get("host"),
            port=config.get("port"),
            user=config.get("user"),
            password=config.get("password"),
            dbname=config.get("database")
        )
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """Initialize database tables."""
    conn = get_db_connection()
    c = conn.cursor()
    
    use_lakebase = is_lakebase_enabled()
    
    # DDL nuances
    if use_lakebase:
        # Postgres
        auto_inc = "SERIAL PRIMARY KEY"
        default_ts = "DEFAULT CURRENT_TIMESTAMP" 
    else:
        # SQLite
        auto_inc = "INTEGER PRIMARY KEY AUTOINCREMENT"
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
            user_explanation TEXT,
            dashboard_context TEXT,
            timestamp TIMESTAMP {default_ts}
        )
    ''')
    
    conn.commit()
    conn.close()

def log_widget_run(widget_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    if is_lakebase_enabled():
        # Postgres uses %s for placeholders
        c.execute('INSERT INTO widget_runs (widget_id) VALUES (%s)', (widget_id,))
    else:
        # SQLite uses ? for placeholders
        c.execute('INSERT INTO widget_runs (widget_id) VALUES (?)', (widget_id,))
        
    conn.commit()
    conn.close()
    return {"status": "success", "widget_id": widget_id}

def log_user_action(widget_id: str, widget_name: str, explanation: str, context: str):
    conn = get_db_connection()
    c = conn.cursor()
    
    if is_lakebase_enabled():
        c.execute('''
            INSERT INTO action_logs (widget_id, widget_name, user_explanation, dashboard_context) 
            VALUES (%s, %s, %s, %s) RETURNING id
        ''', (widget_id, widget_name, explanation, context))
        last_id = c.fetchone()[0]
    else:
        c.execute('''
            INSERT INTO action_logs (widget_id, widget_name, user_explanation, dashboard_context) 
            VALUES (?, ?, ?, ?)
        ''', (widget_id, widget_name, explanation, context))
        last_id = c.lastrowid
        
    conn.commit()
    conn.close()
    return {"status": "success", "action_id": last_id}

def get_action_logs(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    
    if is_lakebase_enabled():
        c = conn.cursor(cursor_factory=RealDictCursor)
        query = '''
            SELECT id, widget_id, widget_name, user_explanation, dashboard_context, timestamp 
            FROM action_logs 
            ORDER BY timestamp DESC 
            LIMIT %s OFFSET %s
        '''
    else:
        c = conn.cursor()
        query = '''
            SELECT id, widget_id, widget_name, user_explanation, dashboard_context, timestamp 
            FROM action_logs 
            ORDER BY timestamp DESC 
            LIMIT ? OFFSET ?
        '''
    
    c.execute(query, (limit, offset))
    
    if is_lakebase_enabled():
        # RealDictCursor return dict-like objects
        logs = [dict(row) for row in c.fetchall()]
    else:
        # SQLite Row factory
        logs = [dict(row) for row in c.fetchall()]
        
    conn.close()
    return logs

def get_popularity_scores() -> Dict[str, int]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT widget_id, COUNT(*) as count FROM widget_runs GROUP BY widget_id')
    rows = c.fetchall()
    
    scores = {}
    if is_lakebase_enabled():
         for row in rows:
             # Standard cursor returns tuples
             scores[row[0]] = row[1]
    else:
        for row in rows:
             # SQLite Row object access
            scores[row['widget_id']] = row['count']
            
    conn.close()
    return scores
