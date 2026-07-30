"""Deployment-wide settings an admin can change without a redeploy.

Which serving endpoint each agent calls used to be reachable only through the
bundle's env vars, so trying a different model meant editing `databricks.yml` and
redeploying. These live in the `app_settings` table instead, with the env var kept
as the fallback:

    database row  >  env var  >  built-in default

so an untouched deployment behaves exactly as it did before, and clearing a
setting in the UI (saving it blank) deletes the row and hands control back to the
env var rather than pinning an empty value.

Two deliberate simplifications:

  * **Settings are global, not per-environment.** Every other table in this app is
    scoped per env (dev/test/prod schemas), but "which model does the chat use" is
    a property of the deployment, not of the data it is addressing. All reads and
    writes therefore use one env — `APP_SETTINGS_ENV`, default `dev` — regardless
    of the `env` a request is otherwise working in.
  * **Reads are cached for a few seconds.** The chat runtime resolves settings on
    every turn and must not add a database round trip to each one. A save
    invalidates this process's cache immediately; with multiple uvicorn workers,
    other workers pick the change up within the TTL.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15.0


class Spec(NamedTuple):
    """One setting: where it falls back to, and what a valid value looks like."""
    env: str
    default: str
    kind: str  # "endpoint" | "int"
    label: str
    help: str
    minimum: Optional[int] = None
    maximum: Optional[int] = None


# Model settings are separate on purpose: the chat agent, the widget generator and
# the Agent Studio drafting assistant have genuinely different needs (a cheap fast
# model is fine for chat while widget generation wants a long output budget), and
# they were already three separate env vars.
SETTING_SPECS: Dict[str, Spec] = {
    "chat_model": Spec(
        env="AGENT_RUNTIME_MODEL",
        default="databricks-claude-sonnet-4-6",
        kind="endpoint",
        label="Chat agent model",
        help="Serving endpoint behind the assistant panel. An agent saved with its own model overrides this.",
    ),
    "widget_model": Spec(
        env="LLM_MODEL",
        default="databricks-claude-sonnet-4-6",
        kind="endpoint",
        label="Widget generation model",
        help="Writes widget code in Widget Studio. Favour a model with a large output budget.",
    ),
    "authoring_model": Spec(
        env="AGENT_STUDIO_LLM_MODEL",
        default="databricks-claude-sonnet-4-6",
        kind="endpoint",
        label="Agent authoring model",
        help="Drafts and reviews agents in Agent Studio.",
    ),
    "chat_max_steps": Spec(
        env="AGENT_RUNTIME_MAX_STEPS",
        default="8",
        kind="int",
        label="Tool calls per turn",
        help="How many rounds of tool calls the chat agent may take before it must answer.",
        minimum=1,
        maximum=30,
    ),
    "chat_max_tokens": Spec(
        env="AGENT_RUNTIME_MAX_TOKENS",
        default="16000",
        kind="int",
        label="Response length limit (tokens)",
        # 16000 rather than a token-thrifty number: this is a ceiling, not a target,
        # so it costs nothing until an answer actually needs the room, and a low
        # ceiling truncates mid-sentence — worse, a reasoning model can spend the
        # whole budget thinking and return nothing. Models that cap lower are
        # clamped automatically (see agent_runtime._stream_completion).
        help="Ceiling on a single chat response. It costs nothing unless an answer needs the room; models that allow less are clamped automatically.",
        minimum=256,
        maximum=128000,
    ),
}

# The two OpenAI-compatible routes a Databricks workspace offers, and the naming
# each one accepts. They are not interchangeable: a `system.ai.…` name posted to
# `/serving-endpoints` comes back ENDPOINT_NOT_FOUND, which is exactly the kind of
# mismatch an admin picking a model from a list should never have to reason about.
SERVING_BASE_PATH = "/serving-endpoints"
AI_GATEWAY_BASE_PATH = "/ai-gateway/mlflow/v1"
AI_GATEWAY_PREFIX = "system.ai."


def base_path_for_model(model: str, env_var: str = "") -> str:
    """Which base path to call `model` on.

    Derived from the name — `system.ai.claude-opus-5` goes to the AI Gateway,
    `databricks-claude-opus-5` to the serving endpoint — so switching models in
    the Admin Panel can't leave a deployment pointed at the wrong route. An
    explicitly set env var still wins, for workspaces that front these with
    something custom.
    """
    if env_var:
        explicit = (os.environ.get(env_var) or "").strip()
        if explicit:
            return explicit if explicit.startswith("/") else "/" + explicit
    return AI_GATEWAY_BASE_PATH if model.strip().startswith(AI_GATEWAY_PREFIX) else SERVING_BASE_PATH


_lock = threading.Lock()
_cache: Dict[str, Any] = {"rows": {}, "at": 0.0, "loaded": False}


def settings_env() -> str:
    """The env whose schema holds the settings table (settings are global)."""
    return os.environ.get("APP_SETTINGS_ENV", "dev").strip() or "dev"


def _read_rows() -> Dict[str, str]:
    from database import get_db_connection

    conn = None
    try:
        conn = get_db_connection(settings_env())
        c = conn.cursor()
        c.execute("SELECT key, value FROM app_settings")
        return {row[0]: (row[1] or "") for row in c.fetchall()}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _rows(force: bool = False) -> Dict[str, str]:
    """Stored settings, cached. Never raises: a settings read failing must not
    take the chat down with it, so a failure falls back to env vars/defaults."""
    now = time.monotonic()
    with _lock:
        fresh = (now - float(_cache["at"])) < _CACHE_TTL_SECONDS
        if not force and _cache["loaded"] and fresh:
            return dict(_cache["rows"])

    try:
        rows = _read_rows()
    except Exception as exc:  # noqa: BLE001
        logger.warning("app_settings read failed, using env defaults: %s", exc)
        with _lock:
            # Keep serving the last good values rather than flapping to defaults.
            return dict(_cache["rows"]) if _cache["loaded"] else {}

    with _lock:
        _cache["rows"] = rows
        _cache["at"] = now
        _cache["loaded"] = True
    return dict(rows)


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def get_setting(key: str) -> str:
    """Resolved string value: stored row, else env var, else built-in default."""
    spec = SETTING_SPECS[key]
    stored = (_rows().get(key) or "").strip()
    if stored:
        return stored
    return (os.environ.get(spec.env) or "").strip() or spec.default


def get_int_setting(key: str) -> int:
    spec = SETTING_SPECS[key]
    raw = get_setting(key)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = int(spec.default)
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return value


def _source_of(key: str, rows: Dict[str, str]) -> str:
    if (rows.get(key) or "").strip():
        return "database"
    if (os.environ.get(SETTING_SPECS[key].env) or "").strip():
        return "environment"
    return "default"


def describe_settings() -> List[Dict[str, Any]]:
    """Every setting with its effective value and where that value came from, so
    the admin UI can say "inherited from the deployment" instead of implying an
    admin chose it."""
    rows = _rows(force=True)
    out: List[Dict[str, Any]] = []
    for key, spec in SETTING_SPECS.items():
        out.append({
            "key": key,
            "label": spec.label,
            "help": spec.help,
            "kind": spec.kind,
            "value": get_setting(key),
            "stored": (rows.get(key) or "").strip(),
            "source": _source_of(key, rows),
            "env_var": spec.env,
            "fallback": (os.environ.get(spec.env) or "").strip() or spec.default,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
        })
    return out


def validate_value(key: str, raw: Any) -> Tuple[str, Optional[str]]:
    """(cleaned, error). A cleaned empty string means "delete the row and fall
    back to the env var" — that is how the UI clears an override."""
    if key not in SETTING_SPECS:
        return "", f"Unknown setting '{key}'"
    spec = SETTING_SPECS[key]
    text = ("" if raw is None else str(raw)).strip()
    if not text:
        return "", None

    if spec.kind == "endpoint":
        if len(text) > 200:
            return "", "Endpoint name is too long"
        if any(ch.isspace() for ch in text):
            return "", "Endpoint names cannot contain spaces"
        return text, None

    try:
        value = int(float(text))
    except (TypeError, ValueError):
        return "", f"{spec.label} must be a whole number"
    if spec.minimum is not None and value < spec.minimum:
        return "", f"{spec.label} must be at least {spec.minimum}"
    if spec.maximum is not None and value > spec.maximum:
        return "", f"{spec.label} must be at most {spec.maximum}"
    return str(value), None


def save_settings(values: Dict[str, Any], username: str = "") -> Dict[str, Any]:
    """Validate and persist. Returns {"saved": [...], "cleared": [...], "errors": {...}}.

    Validation happens before any write, so a request with one bad field changes
    nothing rather than half-applying.
    """
    from database import get_db_connection

    cleaned: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    for key, raw in (values or {}).items():
        value, error = validate_value(key, raw)
        if error:
            errors[key] = error
        else:
            cleaned[key] = value
    if errors:
        return {"saved": [], "cleared": [], "errors": errors}

    saved: List[str] = []
    cleared: List[str] = []
    conn = get_db_connection(settings_env())
    try:
        c = conn.cursor()
        for key, value in cleaned.items():
            if value:
                c.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key) DO UPDATE
                       SET value = EXCLUDED.value,
                           updated_by = EXCLUDED.updated_by,
                           timestamp = CURRENT_TIMESTAMP
                    """,
                    (key, value, username or ""),
                )
                saved.append(key)
            else:
                c.execute("DELETE FROM app_settings WHERE key = %s", (key,))
                cleared.append(key)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    invalidate()
    return {"saved": saved, "cleared": cleared, "errors": {}}
