import requests

TEMPLATES = [
    {
        'name': 'Executive View',
        'domain': 'General',
        'is_global': True,
        'widgets': [
            { "i": 'w1', "x": 0, "y": 0, "w": 3, "h": 6, "type": 'alerts' },
            { "i": 'w2', "x": 3, "y": 0, "w": 6, "h": 6, "type": 'inventory' },
            { "i": 'w3', "x": 9, "y": 0, "w": 3, "h": 6, "type": 'genie' },
            { "i": 'w4', "x": 0, "y": 6, "w": 3, "h": 3, "type": 'external' }
        ]
    },
    {
        'name': 'Production',
        'domain': 'Supply Chain',
        'is_global': True,
        'widgets': [
            { "i": 'p1', "x": 0, "y": 0, "w": 8, "h": 6, "type": 'gantt' },
            { "i": 'p2', "x": 8, "y": 0, "w": 4, "h": 4, "type": 'action' },
            { "i": 'p3', "x": 8, "y": 4, "w": 4, "h": 6, "type": 'supplier_form' }
        ]
    }
]

def seed():
    for t in TEMPLATES:
        r = requests.post("http://localhost:8000/api/views/", json=t)
        if r.status_code == 200:
            print(f"Created {t['name']}")
        else:
            print(f"Failed to create {t['name']}: {r.text}")

if __name__ == "__main__":
    seed()
