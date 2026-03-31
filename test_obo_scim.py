import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv('.env')

def run():
    host = os.environ.get('DATABRICKS_HOST').rstrip('/')
    
    # We need to simulate the OBO token from an actual user request
    # Since we can't easily get one from CLI, let's just make a mock route we can hit to test it
    pass

if __name__ == "__main__":
    run()
