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
    kind: str  # "endpoint" | "int" | "json" | "bool"
    label: str
    help: str
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    # Which card the Settings page shows this under. Add a group here and the UI
    # picks it up; it renders whatever the backend describes rather than holding its
    # own list of settings.
    group: str = "limits"


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
        group="models",
    ),
    "widget_model": Spec(
        env="LLM_MODEL",
        default="databricks-claude-sonnet-4-6",
        kind="endpoint",
        label="Widget generation model",
        help="Writes widget code in Widget Studio. Favour a model with a large output budget.",
        group="models",
    ),
    "widget_helper_model": Spec(
        env="WIDGET_AGENT_HELPER_MODEL",
        # Blank on purpose. The small jobs fall back to `widget_model`, so an
        # untouched deployment behaves exactly as it did; pointing this at a
        # small fast endpoint is what makes them cheap enough to be worth doing
        # before every request rather than only before large ones.
        default="",
        kind="endpoint",
        label="Widget helper model",
        help="Small model for Widget Studio's quick jobs: tightening a request, summarising the conversation so far, and deciding whether to ask a clarifying question. Leave blank to use the widget generation model for these too.",
        group="models",
    ),
    "authoring_model": Spec(
        env="AGENT_STUDIO_LLM_MODEL",
        default="databricks-claude-sonnet-4-6",
        kind="endpoint",
        label="Agent authoring model",
        help="Drafts and reviews agents in Agent Studio.",
        group="models",
    ),
    "model_params": Spec(
        env="LLM_MODEL_PARAMS",
        default="",
        kind="json",
        # Models disagree about the optional parameters, and none of them are sent
        # unless something asks for them (see services/llm_params.py). A rejection
        # teaches the app what to stop sending on its own; this is for the opposite
        # case, a model that needs a parameter we would never send by default.
        label="Model parameter overrides",
        help='Optional, per model. JSON like {"gpt-5.6-luna": {"reasoning_effort": "medium"}}; use null to stop sending one, e.g. {"my-model": {"temperature": null}}. Parameters a model rejects are dropped automatically, so leave this empty unless a model needs something extra.',
        group="models",
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
        group="chat",
    ),
    "chat_tool_timeout": Spec(
        env="AGENT_RUNTIME_TOOL_TIMEOUT",
        default="90",
        kind="int",
        label="Tool call timeout (seconds)",
        help="How long one tool call — a SQL query, an MCP call — may run before the agent is told it timed out and moves on.",
        minimum=5,
        maximum=600,
        group="chat",
    ),
    "chat_genie_timeout": Spec(
        env="AGENT_RUNTIME_GENIE_TIMEOUT",
        default="150",
        kind="int",
        label="Genie query timeout (seconds)",
        help="Genie answers are polled until this elapses. Longer suits large warehouses; the agent explains the timeout rather than inventing an answer.",
        minimum=10,
        maximum=900,
        group="chat",
    ),
    "widget_max_tokens": Spec(
        env="WIDGET_AGENT_MAX_TOKENS",
        default="16000",
        kind="int",
        label="Widget response length limit (tokens)",
        help="Ceiling on one Widget Studio reply. A cut-off reply is continued automatically, so raising this mainly saves round trips.",
        minimum=1000,
        maximum=128000,
        group="widget",
    ),
    "widget_timeout": Spec(
        env="WIDGET_AGENT_TIMEOUT",
        default="300",
        kind="int",
        label="Widget generation timeout (seconds)",
        help="How long one Widget Studio request may take before it gives up. Large widgets need longer; the studio waits as long as this allows and keeps whatever was applied.",
        minimum=30,
        maximum=1800,
        group="widget",
    ),
    "authoring_max_tokens": Spec(
        env="AGENT_STUDIO_MAX_TOKENS",
        default="16000",
        kind="int",
        label="Agent Studio response length limit (tokens)",
        help="Ceiling on one Agent Studio draft. The draft is a single JSON object holding every skill, so a low ceiling truncates it mid-string and the draft fails to parse.",
        minimum=1000,
        maximum=128000,
        group="widget",
    ),
    # --- Data reach -------------------------------------------------------
    # Switches, not limits: they decide whether the assistant can reach workspace
    # data at all. A deployment handling classified data can turn the data tools
    # off and keep an assistant that still answers questions about the app itself.
    # Genie matters most: Unity Catalog's request-context policies can restrict
    # what an OAuth application reads on a user's behalf, but they do not identify
    # Genie, so this switch is the only way to keep the agent away from a Genie
    # space that reaches classified tables.
    "enable_genie_tool": Spec(
        env="AGENT_TOOLS_ENABLE_GENIE",
        default="true",
        kind="bool",
        label="Allow the assistant to query Genie",
        help="Off removes every Genie tool from the assistant, and Genie research from Widget Studio and Agent Studio. Turn it off where Genie spaces can reach data the assistant must not read — Unity Catalog policies that restrict other agents cannot restrict Genie.",
        group="tools",
    ),
    "enable_sql_tool": Spec(
        env="AGENT_TOOLS_ENABLE_SQL",
        default="true",
        kind="bool",
        label="Allow the assistant to run SQL",
        help="Off removes the SQL and Unity Catalog tools from the assistant, and SQL research from Widget Studio and Agent Studio. Widgets themselves are unaffected, and so are Agent Studio's schema checks.",
        group="tools",
    ),
    "conversation_retention_days": Spec(
        env="CONVERSATION_RETENTION_DAYS",
        # 0, not a number, because picking one for every deployment would be
        # guessing: chats are the record of what people asked the data, and how
        # long that may be kept is a policy question, not an engineering default.
        default="0",
        kind="int",
        label="Delete conversations after (days)",
        help="Chats untouched for this long are deleted, with their attached files. 0 keeps them indefinitely. Applies to everyone; users can always delete their own from the chat drawer.",
        minimum=0,
        maximum=3650,
        group="privacy",
    ),
    "send_dashboard_context": Spec(
        env="AGENT_SEND_DASHBOARD_CONTEXT",
        default="true",
        kind="bool",
        label="Tell the assistant what is on screen",
        help="On, each question carries a summary of the current dashboard — widget names, titles and configuration — so the assistant can answer about what the user is looking at. Off, it sees only the question, which suits deployments where widget configuration is itself sensitive.",
        group="privacy",
    ),
    "enforce_content_security_policy": Spec(
        env="ENFORCE_CSP",
        default="true",
        kind="bool",
        label="Enforce the Content Security Policy",
        help="On, the browser blocks widget code from loading scripts or sending data anywhere except this app and the approved CDNs. Turn it off only to diagnose a widget that has stopped working — it downgrades the policy to report-only, so violations are logged in the browser console instead of blocked.",
        group="tools",
    ),
    "require_certified_for_global_views": Spec(
        env="REQUIRE_CERTIFIED_FOR_GLOBAL_VIEWS",
        # Off by default because certification is applied during promotion to
        # production: on a dev or test deployment nothing is certified yet, and
        # defaulting this on would mean no global view could be created there at
        # all. Turn it on for the deployment where "published to everyone" is
        # supposed to mean "someone reviewed this".
        default="false",
        kind="bool",
        label="Global views may only contain certified widgets",
        help="On, a view shared with everyone can only hold widgets an admin has certified. Leave off in dev and test, where nothing is certified yet.",
        group="tools",
    ),
    "enable_native_file_passthrough": Spec(
        env="AGENT_TOOLS_ENABLE_NATIVE_FILES",
        default="true",
        kind="bool",
        label="Send images and PDFs to the model directly",
        help="Off means attachments are only ever read through extraction tools, so no raw image or PDF is uploaded to the model. Scanned documents and screenshots stop working.",
        group="tools",
    ),
}

# Cards on the Settings page, in order. A group with no settings isn't rendered.
SETTING_GROUPS: List[Dict[str, str]] = [
    {"key": "models", "label": "Models"},
    {"key": "tools", "label": "What the assistant may reach"},
    {"key": "privacy", "label": "Retention and context"},
    {"key": "chat", "label": "Chat agent limits"},
    {"key": "widget", "label": "Studio limits"},
    {"key": "limits", "label": "Other limits"},
]

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


_TRUTHY = ("1", "true", "yes", "on")
_FALSEY = ("0", "false", "no", "off")


def get_bool_setting(key: str) -> bool:
    """Resolved boolean, following the same row > env var > default chain.

    Anything unrecognised falls back to the built-in default rather than being
    read as false: these switches gate whether the assistant can reach data at
    all, and a typo silently disabling a tool looks exactly like a broken agent.
    """
    raw = get_setting(key).strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSEY:
        return False
    return SETTING_SPECS[key].default.strip().lower() in _TRUTHY


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
            "group": spec.group,
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

    if spec.kind == "bool":
        # Stored as an explicit word rather than as presence/absence, because an
        # empty value already means "clear the override and inherit" — without a
        # spelled-out "false" there would be no way to turn something off whose
        # fallback is on.
        lowered = text.lower()
        if lowered in _TRUTHY:
            return "true", None
        if lowered in _FALSEY:
            return "false", None
        return "", f"{spec.label} must be true or false"

    if spec.kind == "json":
        # Rejected here rather than at request time: a typo in this field would
        # otherwise surface as an agent failing, far from the field that caused it.
        import json

        try:
            parsed = json.loads(text)
        except ValueError as exc:
            return "", f"Not valid JSON: {exc}"
        if not isinstance(parsed, dict) or not all(isinstance(v, dict) for v in parsed.values()):
            return "", 'Expected an object keyed by model name, e.g. {"my-model": {"temperature": null}}'
        if len(text) > 4000:
            return "", "Too long (4000 characters maximum)"
        # These parameters are spread into the request alongside the endpoint URL and
        # the app's credential, so the names allowed here are a closed list rather
        # than anything the model might accept. `base_url` in this field would send
        # the app's token and its prompts to whatever host it named.
        from services.llm_params import CONFIGURABLE

        stray = sorted({p for params in parsed.values() for p in params} - CONFIGURABLE)
        if stray:
            return "", (f"Not a model parameter: {', '.join(stray)}. "
                        f"Allowed: {', '.join(sorted(CONFIGURABLE))}")
        return json.dumps(parsed, separators=(", ", ": ")), None

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
