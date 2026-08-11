"""Tests for what gets sent to a model, and what happens when it says no.

The bug these exist for: Widget Studio pinned `temperature=0.1`, so choosing a model
that refuses temperature in Admin Panel → Settings broke every generation, while the
chat agent — which never sent it — kept working. The fix has to hold in both
directions, so the cases below cover a parameter being dropped after a refusal and a
parameter being added when a model demands one.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import llm_params  # noqa: E402
from services.llm_params import (  # noqa: E402
    adapt,
    langchain_params,
    request_params,
    with_adaptation,
)


def setup_function(_=None):
    llm_params.reset()


_REAL_OVERRIDES = llm_params._admin_overrides


def _no_overrides(monkeypatch=None):
    """Neutralise the admin setting; these tests are about code paths, not config."""
    llm_params._admin_overrides = lambda model: {}


setup_function()
_no_overrides()


# --------------------------------------------------------------- what we send

def test_nothing_optional_is_sent_unless_something_asks_for_it():
    # The whole point: an unknown model gets the output budget and nothing else, so
    # switching to it cannot fail on a parameter nobody needed.
    assert request_params("some-new-endpoint", 8000) == {"max_tokens": 8000}


def test_models_known_to_refuse_temperature_never_see_it():
    llm_params._policies.clear()
    assert "temperature" not in request_params("databricks-claude-sonnet-5", 8000)
    assert "temperature" not in request_params("system.ai.gpt-5-mini", 8000)


def test_reads_the_cap_a_rejection_names():
    # Each provider words this differently, and the caps that matter in practice are
    # 128000 (Claude Sonnet 5, GPT-5.6) and 8192 (meta-llama-3-1-8b, gemma-3-12b).
    cases = [
        ("max_tokens: 900000 > 128000, which is the maximum allowed number of output tokens for anthropic.claude-sonnet-5", 900000, 128000),
        ("max_tokens is too large: 900000. This model supports at most 128000 completion tokens, whereas you provided 900000.", 900000, 128000),
        ("max_new_tokens 16000 cannot be greater than max_output_tokens 8192.", 16000, 8192),
        ("max_tokens (16000) cannot exceed 8192. Please reduce the length of max output tokens generated.", 16000, 8192),
    ]
    for message, requested, expected in cases:
        assert llm_params._token_cap(message, requested) == expected, message


def test_ignores_failures_that_are_not_about_length():
    assert llm_params._token_cap("ENDPOINT_NOT_FOUND: the given endpoint does not exist", 16000) is None
    assert llm_params._token_cap("", 16000) is None
    # A length complaint with no usable number must not invent one.
    assert llm_params._token_cap("max_tokens is invalid", 16000) is None


def test_a_learned_cap_clamps_the_budget_without_being_asked_twice():
    adapt("small-model", "max_tokens: 16000 > 8192, which is the maximum", requested_tokens=16000)
    assert request_params("small-model", 16000) == {"max_tokens": 8192}
    # A deployment-wide setting below the cap is still honoured.
    assert request_params("small-model", 4000) == {"max_tokens": 4000}


# ------------------------------------------------------- learning from refusals

def test_an_unsupported_parameter_is_dropped_and_stays_dropped():
    llm_params._policies.clear()
    llm_params._policy("m").add["temperature"] = 0.1
    note = adapt("m", "BAD_REQUEST: model m does not support the temperature parameter")
    assert note and "temperature" in note
    assert "temperature" not in request_params("m", 1000)
    # Learning the same thing twice means the retry didn't help, so callers stop.
    assert adapt("m", "does not support the temperature parameter") is None


def test_the_wording_providers_actually_use_is_understood():
    for message, param in [
        ("Unsupported parameter: 'temperature' is not supported with this model.", "temperature"),
        ("Extra inputs are not permitted: reasoning_effort", "reasoning_effort"),
        ("unrecognized request argument: top_p", "top_p"),
        ("Invalid request: 'seed' is not a valid parameter", "seed"),
    ]:
        llm_params._policies.clear()
        note = adapt("m", message)
        assert note, message
        assert param not in request_params("m", 1000), message


def test_a_required_reasoning_flag_is_supplied_and_remembered():
    # The Luna case: the model rejects the request until an effort is named.
    note = adapt("gpt-5.6-luna", "Invalid request: reasoning: Field required")
    assert note and "reasoning" in note
    params = request_params("gpt-5.6-luna", 4000)
    assert params["reasoning"] == {"effort": "medium"}


def test_a_required_parameter_we_do_not_understand_is_not_guessed_at():
    # Better a clear failure than a made-up value for something like `safety_mode`.
    assert adapt("m", "Invalid request: safety_mode: Field required") is None


def test_an_endpoint_that_wants_the_other_token_name_gets_it():
    note = adapt("m", "Unsupported parameter: 'max_tokens' is not supported. Use 'max_completion_tokens' instead.")
    assert note and "max_completion_tokens" in note
    assert request_params("m", 4000) == {"max_completion_tokens": 4000}


def test_a_failure_that_is_not_about_parameters_teaches_nothing():
    assert adapt("m", "ENDPOINT_NOT_FOUND: no endpoint named m") is None
    assert adapt("m", "503 upstream connect error") is None


# ------------------------------------------------------------ langchain shape

def test_langchain_gets_the_flat_reasoning_effort_not_the_object():
    # A `reasoning` object makes ChatOpenAI switch to the Responses API, which
    # Databricks serving endpoints do not speak — so the effort has to go flat.
    adapt("gpt-5.6-luna", "reasoning: Field required")
    params = langchain_params("gpt-5.6-luna", 4000)
    assert params == {"reasoning_effort": "medium", "max_tokens": 4000}


def test_langchain_names_the_budget_max_tokens_whatever_the_endpoint_calls_it():
    adapt("m", "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'.")
    # ChatOpenAI renames it on the wire itself, so it must not arrive pre-renamed.
    assert langchain_params("m", 4000) == {"max_tokens": 4000}


# ------------------------------------------------------------------- retrying

def test_a_refusal_is_retried_with_the_lesson_applied():
    seen = []

    def attempt(params):
        seen.append(dict(params))
        if "temperature" in params:
            raise RuntimeError("model does not support the temperature parameter")
        return "answered"

    llm_params._policy("m").add["temperature"] = 0.2
    assert with_adaptation("m", attempt, max_tokens=1000) == "answered"
    assert len(seen) == 2
    assert "temperature" in seen[0] and "temperature" not in seen[1]


def test_a_failure_nothing_can_be_learned_from_is_raised_as_it_is():
    def attempt(_params):
        raise RuntimeError("ENDPOINT_NOT_FOUND")

    try:
        with_adaptation("m", attempt, max_tokens=1000)
    except RuntimeError as exc:
        assert "ENDPOINT_NOT_FOUND" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("the failure should have been raised")


def test_retrying_stops_instead_of_looping_on_one_lesson():
    calls = []

    def attempt(_params):
        calls.append(1)
        raise RuntimeError("does not support the temperature parameter")

    try:
        with_adaptation("m", attempt, max_tokens=1000)
    except RuntimeError:
        pass
    # First call learns to drop it; the second shows dropping didn't help, so it
    # gives up rather than burning the remaining attempts on the same idea.
    assert len(calls) == 2


# --------------------------------------------------------- the admin setting

def test_a_stray_key_in_the_setting_never_reaches_the_request():
    # These parameters are spread into the request beside `api_key` and `base_url`,
    # so the setting takes tuning knobs only. The Settings page refuses the rest on
    # save; this is the second lock, for a value stored before that check existed.
    from services import settings_store

    stored = '{"a-model": {"temperature": 0.3, "base_url": "https://elsewhere/v1"}}'
    real_get = settings_store.get_setting
    settings_store.get_setting = lambda key: stored if key == "model_params" else real_get(key)
    llm_params._admin_overrides = _REAL_OVERRIDES
    try:
        llm_params.reset()
        params = request_params("a-model", 1000)
    finally:
        settings_store.get_setting = real_get
        _no_overrides()

    assert params["temperature"] == 0.3  # the knob it is for still works
    assert "base_url" not in params


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        setup_function()
        _no_overrides()
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
