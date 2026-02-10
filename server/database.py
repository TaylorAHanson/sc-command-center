import sqlite3
import os
from typing import Dict, List, Tuple

DB_PATH = os.path.join(os.path.dirname(__file__), "widgets.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS widget_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            widget_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Action Logs (Telemetry)
    c.execute('''
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            widget_id TEXT,
            widget_name TEXT,
            user_explanation TEXT,
            dashboard_context TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def log_widget_run(widget_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO widget_runs (widget_id) VALUES (?)', (widget_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "widget_id": widget_id}

def log_user_action(widget_id: str, widget_name: str, explanation: str, context: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO action_logs (widget_id, widget_name, user_explanation, dashboard_context) 
        VALUES (?, ?, ?, ?)
    ''', (widget_id, widget_name, explanation, context))
    conn.commit()
    conn.close()
    return {"status": "success", "action_id": c.lastrowid}

def get_action_logs(limit: int = 100, offset: int = 0) -> List[Dict]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, widget_id, widget_name, user_explanation, dashboard_context, timestamp 
        FROM action_logs 
        ORDER BY timestamp DESC 
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    rows = c.fetchall()
    conn.close()
    
    logs = []
    for row in rows:
        logs.append(dict(row))
    return logs

def get_popularity_scores() -> Dict[str, int]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT widget_id, COUNT(*) as count FROM widget_runs GROUP BY widget_id')
    rows = c.fetchall()
    conn.close()
    
    scores = {}
    for row in rows:
        scores[row['widget_id']] = row['count']
    return scores
