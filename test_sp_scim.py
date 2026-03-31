import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv('.env')

def run():
    host = os.environ.get('DATABRICKS_HOST').rstrip('/')
    client_id = os.environ.get('DATABRICKS_CLIENT_ID')
    client_secret = os.environ.get('DATABRICKS_CLIENT_SECRET')

    import base64
    auth_string = base64.b64encode(f"{client_id}:{client_secret}".encode('utf-8')).decode('utf-8')
    
    # 1. Get Token
    req = urllib.request.Request(
        f'{host}/oidc/v1/token',
        data=b'grant_type=client_credentials&scope=all-apis',
        headers={
            'Authorization': f'Basic {auth_string}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode('utf-8'))
            token = data.get('access_token')
            print('SP Token acquired!')
    except Exception as e:
        print(f'Token fail: {e}')
        return

    # 2. Call Me API
    req = urllib.request.Request(
        f'{host}/api/2.0/preview/scim/v2/Me',
        headers={'Authorization': f'Bearer {token}'}
    )
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode('utf-8'))
            print('--- ME API RESPONSE ---')
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f'Me API fail: {e}')
        if hasattr(e, 'read'):
            print(e.read().decode('utf-8'))

if __name__ == "__main__":
    run()
