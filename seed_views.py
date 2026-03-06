import os
import sys
import json

# Add server to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'server'))

from database import get_db_connection, init_db
from config.settings import is_lakebase_enabled

# Re-create the two templates
TEMPLATES = {
    'temp-exec': {
        'id': 'temp-exec',
        'name': 'Executive View',
        'domain': 'General',
        'is_global': 1,
        'widgets': [
            { "i": 'w1', "x": 0, "y": 0, "w": 3, "h": 6, "type": 'alerts' },
            { "i": 'w2', "x": 3, "y": 0, "w": 6, "h": 6, "type": 'inventory' },
            { "i": 'w3', "x": 9, "y": 0, "w": 3, "h": 6, "type": 'genie' },
            { "i": 'w4', "x": 0, "y": 6, "w": 3, "h": 3, "type": 'external' }
        ]
    },
    'temp-prod': {
        'id': 'temp-prod',
        'name': 'Production',
        'domain': 'Supply Chain',
        'is_global': 1,
        'widgets': [
            { "i": 'p1', "x": 0, "y": 0, "w": 8, "h": 6, "type": 'gantt' },
            { "i": 'p2', "x": 8, "y": 0, "w": 4, "h": 4, "type": 'action' },
            { "i": 'p3', "x": 8, "y": 4, "w": 4, "h": 6, "type": 'supplier_form' }
        ]
    }
}

def seed_templates():
    init_db("dev")
    conn = get_db_connection("dev")
    c = conn.cursor()
    
    for _, t in TEMPLATES.items():
        # Check if exists
        if is_lakebase_enabled():
            c.execute("SELECT id FROM dashboard_views WHERE id = %s", (t['id'],))
        else:
            c.execute("SELECT id FROM dashboard_views WHERE id = ?", (t['id'],))
            
        if not c.fetchone():
            print(f"Inserting template {t['name']}")
            widgets_json = json.dumps(t['widgets'])
            if is_lakebase_enabled():
                c.execute("""
                    INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (t['id'], 1, t['name'], t['domain'], 'system', t['is_global'], widgets_json, 1))
            else:
                c.execute("""
                    INSERT INTO dashboard_views (id, version, name, domain, username, is_global, widgets_json, is_locked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (t['id'], 1, t['name'], t['domain'], 'system', t['is_global'], widgets_json, 1))
        else:
            print(f"Template {t['name']} already exists.")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_templates()
