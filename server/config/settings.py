import os
import re


def get_app_environment() -> str:
    """Which deployment this process is: local / dev / stage / prod.

    Set from the bundle's `environment` variable per target (`databricks.yml`).
    Distinct from the `env` query parameter routes take, which selects *which
    stored data* to read — one deployment can serve all three. Empty when
    unconfigured, which callers should treat as unknown rather than production.
    """
    return os.environ.get("APP_ENVIRONMENT", "").strip().lower()


def get_app_brand() -> str:
    """The deployment's brand name, from `APP_BRAND` (the bundle's `brand` var).

    Widget code saved before the colour palette became `brand-*` names its
    colours after the brand (`text-<brand>-blue`); the SPA maps those onto
    `brand-*` before compiling. Kept out of the repo on purpose, so it is
    configured per deployment. Anything that isn't a plain lowercase word is
    ignored, since the browser builds a regular expression from it.
    """
    brand = os.environ.get("APP_BRAND", "").strip().lower()
    return brand if re.fullmatch(r"[a-z][a-z0-9]*", brand) else ""


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
