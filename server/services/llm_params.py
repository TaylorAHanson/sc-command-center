"""What to send each model, and what to leave out.

Every endpoint this app talks to speaks the OpenAI chat-completions shape, but they
disagree about the optional parameters. Newer Claude endpoints reject `temperature`
outright ("does not support the temperature parameter"); some reasoning models
refuse `max_tokens` and want `max_completion_tokens`, or fail unless a reasoning
effort is named; small open-weight endpoints cap output far below a
deployment-wide setting. A fixed parameter set therefore breaks the moment an admin
picks a different model in Admin Panel → Settings, which was the whole point of
making the model settable.

So the parameters are decided per model, in three layers:

    built-in rules  <  admin override  <  what the endpoint told us

The last layer is the one that does the work. A rejection names its own cause
("unsupported parameter: 'temperature'", "max_tokens: 32000 > 8192", "reasoning:
Field required"), so `adapt` reads it, changes the policy for that model, and the
call is retried — no admin needs to know each model's quirks, and the fix holds for
the rest of the process. It sits last because a refusal is ground truth: a
parameter the endpoint has already rejected is not sent again even if it was
configured by hand (that gets logged, so it isn't silent).

The admin override (`model_params` in Settings) covers what learning cannot: a
parameter we would never send by default but a model needs. JSON keyed by model
name, `null` meaning "never send this one":

    {"gpt-5.6-luna": {"reasoning_effort": "medium"},
     "databricks-claude-sonnet-5": {"temperature": null}}

Nothing here sends `temperature` on its own. It used to be hardcoded in Widget
Studio, which is why switching that model to one that refuses it broke generation
while the chat agent — which never sent it — kept working.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Callable, Dict, Optional, Set, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Optional parameters we are willing to stop sending. Deliberately a closed list:
# an error mentioning `messages`, `model` or `tools` is a bug in the request or a
# broken endpoint, and quietly dropping any of those would turn a loud failure into
# an agent that has mysteriously lost its tools.
_DROPPABLE: Set[str] = {
    "temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty",
    "seed", "n", "stop", "logprobs", "logit_bias", "user",
    "reasoning", "reasoning_effort", "thinking", "verbosity",
    "max_tokens", "max_completion_tokens",
}

# Values we understand well enough to supply when a model reports one missing.
# Anything not listed here is reported rather than guessed at.
_SUPPLIABLE: Dict[str, Any] = {
    "reasoning_effort": "medium",
    "reasoning": {"effort": "medium"},
    "verbosity": "medium",
}

# Built-in rules, applied before anything is learned. Matched as substrings of the
# model name, so `databricks-claude-sonnet-5` and `system.ai.claude-sonnet-5` are
# both covered by one entry. Keep this short: learning handles the rest, and a stale
# rule here is worse than no rule.
_BUILT_IN: Dict[str, Dict[str, Any]] = {
    # Reasoning models bill and budget output differently, and reject the sampling
    # parameters a chat model takes.
    "gpt-5": {"temperature": None, "top_p": None},
    "o1": {"temperature": None, "top_p": None},
    "o3": {"temperature": None, "top_p": None},
    # Claude on Databricks stopped accepting `temperature` from Opus 4.8 on.
    "claude-opus-4-8": {"temperature": None},
    "claude-sonnet-5": {"temperature": None},
    "claude-opus-5": {"temperature": None},
}

_UNSUPPORTED_RES = (
    re.compile(r"unsupported parameter:?\s*['\"]?([a-z_]+)", re.I),
    re.compile(r"does not support (?:the )?['\"]?([a-z_]+)['\"]?\s*(?:parameter|argument|field|value)", re.I),
    re.compile(r"extra inputs are not permitted[^a-z]{0,20}([a-z_]+)", re.I),
    re.compile(r"unrecognized (?:request )?(?:argument|parameter|key|field):?\s*['\"]?([a-z_]+)", re.I),
    re.compile(r"['\"]?([a-z_]+)['\"]?\s+is not (?:a )?(?:supported|allowed|valid|recognized)\s*(?:parameter|argument|field)", re.I),
    re.compile(r"(?:parameter|argument|field)\s+['\"]?([a-z_]+)['\"]?\s+is not (?:supported|allowed)", re.I),
)

_REQUIRED_RES = (
    re.compile(r"['\"]?([a-z_]+)['\"]?\s*:?\s*field required", re.I),
    re.compile(r"missing (?:required )?(?:parameter|argument|field|property):?\s*['\"]?([a-z_]+)", re.I),
    re.compile(r"['\"]?([a-z_]+)['\"]?\s+must not be (?:null|none|empty)", re.I),
    re.compile(r"['\"]?([a-z_]+)['\"]?\s+is required", re.I),
    re.compile(r"(?:requires|expected)\s+(?:a\s+)?['\"]?([a-z_]+)['\"]?\s+(?:parameter|argument|field|to be set)", re.I),
)

_TOKEN_KEYS = ("max_tokens", "max_completion_tokens", "max_new_tokens", "max_output_tokens")


class _Policy:
    """Everything learned or configured about one model, guarded by the lock below."""

    def __init__(self) -> None:
        self.drop: Set[str] = set()
        self.add: Dict[str, Any] = {}
        self.cap: Optional[int] = None
        self.token_key: str = "max_tokens"


_lock = threading.Lock()
_policies: Dict[str, _Policy] = {}


def _policy(model: str) -> _Policy:
    """The learned policy for `model`, seeded from the built-in rules."""
    key = (model or "").strip()
    with _lock:
        existing = _policies.get(key)
        if existing:
            return existing
        policy = _Policy()
        lowered = key.lower()
        for fragment, params in _BUILT_IN.items():
            if fragment in lowered:
                for name, value in params.items():
                    if value is None:
                        policy.drop.add(name)
                    else:
                        policy.add[name] = value
        _policies[key] = policy
        return policy


def reset(model: str = "") -> None:
    """Forget what was learned — for tests, and for a settings change."""
    with _lock:
        if model:
            _policies.pop(model.strip(), None)
        else:
            _policies.clear()


def _admin_overrides(model: str) -> Dict[str, Any]:
    """Per-model parameters from the `model_params` setting, `{}` when unset or bad.

    A malformed value must not take the agents down with it, so a parse failure is
    logged and ignored; the Settings page validates on save, so this is belt only.
    """
    from services.settings_store import get_setting

    raw = (get_setting("model_params") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        logger.warning("Ignoring malformed model_params setting: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        return {}

    lowered = (model or "").strip().lower()
    merged: Dict[str, Any] = {}
    # Longest key first, so an entry for a specific model wins over a family prefix.
    for name in sorted(parsed, key=len, reverse=True):
        params = parsed[name]
        if isinstance(params, dict) and name.strip().lower() in lowered:
            for param, value in params.items():
                merged.setdefault(param, value)
    return merged


def request_params(model: str, max_tokens: Optional[int] = None) -> Dict[str, Any]:
    """The optional parameters to send `model`, ready to merge into a request.

    `max_tokens` is named under whichever key this model accepts, and clamped to a
    cap the endpoint has already told us about.
    """
    policy = _policy(model)
    params: Dict[str, Any] = {}

    with _lock:
        add, drop, cap, token_key = dict(policy.add), set(policy.drop), policy.cap, policy.token_key

    params.update(add)

    for param, value in _admin_overrides(model).items():
        if value is None:
            drop.add(param)
        elif param in drop:
            logger.info("%s rejected %s earlier, so the configured value is not sent.", model, param)
        else:
            params[param] = value

    if max_tokens:
        budget = min(int(max_tokens), cap) if cap else int(max_tokens)
        params[token_key] = budget

    for param in drop:
        params.pop(param, None)
    return params


def langchain_params(model: str, max_tokens: Optional[int] = None) -> Dict[str, Any]:
    """The same policy, spelled the way `ChatOpenAI` constructor arguments want it.

    Two translations, both learned the hard way:

      * `ChatOpenAI` already renames `max_tokens` to `max_completion_tokens` on the
        wire, so the budget is handed over under the name it expects.
      * A `reasoning` **object** makes langchain switch to the Responses API — the
        request goes out as `input`/`max_output_tokens` — which Databricks serving
        endpoints do not speak. The effort therefore travels as the flat
        `reasoning_effort`, which stays on chat completions.
    """
    params = request_params(model, max_tokens)
    if "max_completion_tokens" in params:
        params["max_tokens"] = params.pop("max_completion_tokens")
    reasoning = params.pop("reasoning", None)
    if isinstance(reasoning, dict) and reasoning.get("effort") and "reasoning_effort" not in params:
        params["reasoning_effort"] = reasoning["effort"]
    return params


def _requested_tokens(params: Dict[str, Any]) -> int:
    """The output budget in `params`, whichever name it went out under."""
    values = [int(params[key]) for key in _TOKEN_KEYS if str(params.get(key) or "").isdigit()]
    return max(values) if values else 0


def _token_cap(message: str, requested: int) -> Optional[int]:
    """The cap a token rejection names, or None if that isn't what failed.

    Wording differs per provider ("max_tokens: 900000 > 128000, which is the
    maximum…", "max_new_tokens 16000 cannot be greater than max_output_tokens
    8192"), so this reads the numbers rather than the prose: a cap has to be below
    what we asked for, and above a floor that skips version numbers like the "5" in
    "claude-sonnet-5".
    """
    lowered = (message or "").lower()
    if not any(key in lowered for key in _TOKEN_KEYS) and "completion tokens" not in lowered:
        return None
    caps = [int(n) for n in re.findall(r"\d+", message) if 256 <= int(n) < requested]
    return max(caps) if caps else None


def _named(patterns, message: str) -> Optional[str]:
    for pattern in patterns:
        match = pattern.search(message or "")
        if match:
            return match.group(1).lower()
    return None


def adapt(model: str, error: str, requested_tokens: int = 0) -> Optional[str]:
    """Learn from a rejection. Returns what changed, or None if nothing did.

    None means the failure wasn't about parameters and a retry would fail the same
    way, so callers re-raise instead.
    """
    message = str(error or "")
    policy = _policy(model)

    cap = _token_cap(message, requested_tokens) if requested_tokens else None
    if cap:
        with _lock:
            if policy.cap == cap:
                return None  # already clamped there; the failure is something else
            policy.cap = cap
        return f"{model} caps output at {cap} tokens"

    unsupported = _named(_UNSUPPORTED_RES, message)
    if unsupported in _DROPPABLE:
        # An endpoint that refuses `max_tokens` usually wants the reasoning-model
        # spelling instead, and says so in the same breath.
        if unsupported in _TOKEN_KEYS:
            for alternative in _TOKEN_KEYS:
                if alternative != unsupported and alternative in message.lower():
                    with _lock:
                        if policy.token_key == alternative:
                            return None
                        policy.token_key = alternative
                    return f"{model} wants the output budget as {alternative}"
        with _lock:
            if unsupported in policy.drop:
                return None
            policy.drop.add(unsupported)
            policy.add.pop(unsupported, None)
        return f"{model} does not accept {unsupported}"

    required = _named(_REQUIRED_RES, message)
    if required in _SUPPLIABLE:
        with _lock:
            if required in policy.add:
                return None
            policy.add[required] = _SUPPLIABLE[required]
            policy.drop.discard(required)
        return f"{model} requires {required}, sending {_SUPPLIABLE[required]!r}"

    return None


def with_adaptation(
    model: str,
    attempt: Callable[[Dict[str, Any]], T],
    max_tokens: Optional[int] = None,
    attempts: int = 3,
    params_fn: Callable[[str, Optional[int]], Dict[str, Any]] = request_params,
) -> T:
    """Run `attempt` with this model's parameters, learning from a rejection.

    `attempt` receives the parameter dict and makes the call. It may be run more
    than once, so it must not have side effects of its own beyond the request —
    for LangChain callers that means building the client inside it, since the
    parameters are constructor arguments there (pass `params_fn=langchain_params`).
    """
    last_note = ""
    for remaining in range(attempts - 1, -1, -1):
        params = params_fn(model, max_tokens)
        try:
            return attempt(params)
        except Exception as exc:  # noqa: BLE001
            note = adapt(model, str(exc), _requested_tokens(params))
            if not note or not remaining:
                raise
            if note == last_note:
                raise  # the same lesson twice means it didn't help
            last_note = note
            logger.info("Retrying: %s.", note)
    raise RuntimeError("unreachable")  # pragma: no cover


def describe(model: str) -> Dict[str, Any]:
    """What is currently being sent to `model` — for logs and error messages."""
    policy = _policy(model)
    with _lock:
        return {
            "model": model,
            "omitted": sorted(policy.drop),
            "added": dict(policy.add),
            "output_cap": policy.cap,
            "token_parameter": policy.token_key,
        }
