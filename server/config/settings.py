import os


def get_app_environment() -> str:
    """Which deployment this process is: local / dev / stage / prod.

    Set from the bundle's `environment` variable per target (`databricks.yml`).
    Distinct from the `env` query parameter routes take, which selects *which
    stored data* to read — one deployment can serve all three. Empty when
    unconfigured, which callers should treat as unknown rather than production.
    """
    return os.environ.get("APP_ENVIRONMENT", "").strip().lower()


def get_lakebase_config():
    """Get Lakebase (Postgres) configuration from environment variables."""
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
        "database": os.environ.get("PGDATABASE", "lakebase"),
        "instance_name": os.environ.get("LAKEBASE_INSTANCE_NAME", "scm-oltp")
    }
