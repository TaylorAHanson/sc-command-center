import os

def is_lakebase_enabled():
    """Check if Lakebase (Postgres) is enabled via environment variable."""
    return os.environ.get("LAKEBASE_ENABLED", "false").lower() in ("true", "1", "yes", "on")

def get_lakebase_config():
    """Get Lakebase (Postgres) configuration from environment variables."""
    return {
        "host": os.environ.get("LAKEBASE_HOST", "localhost"),
        "port": os.environ.get("LAKEBASE_PORT", "5432"),
        "user": os.environ.get("LAKEBASE_USER", "postgres"),
        "password": os.environ.get("LAKEBASE_PASSWORD", ""),
        "database": os.environ.get("LAKEBASE_DB", "lakebase")
    }
