"""Ask a model endpoint what a tool-calling turn is allowed to look like.

Run from the repo root with the server's interpreter:

    server/venv/bin/python tools/tool_call_shape_probe.py [model]

LangChain sends an assistant message that only calls tools with ``"content":
null`` (langchain_openai `_convert_message_to_dict`, "If tool calls present,
content null value should be None"). Some Databricks routes accept that and some
answer 400 INVALID_PARAMETER_VALUE: "Content in ChatMessage must have type in
String or List[ContentItem]" — which surfaces in the studios as a generation
error on the turn *after* the first tool call.

This replays that exact second request with each candidate content value, against
whichever base path the model name implies, and reports which ones the endpoint
takes. One short completion per shape.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from databricks.sdk import WorkspaceClient  # noqa: E402

from services.settings_store import base_path_for_model, get_setting  # noqa: E402

TOOL = {
    "type": "function",
    "function": {
        "name": "list_catalogs",
        "description": "List catalogs.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def conversation(assistant_content):
    """The turn after a tool call: the assistant's request, and the tool's answer."""
    return [
        {"role": "system", "content": "You help author agents."},
        {"role": "user", "content": "test"},
        {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "list_catalogs", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "main, samples"},
    ]


def ask(url: str, token: str, model: str, messages: list) -> tuple[bool, str]:
    body = json.dumps({"model": model, "messages": messages, "tools": [TOOL], "max_tokens": 16}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            json.loads(resp.read())
        return True, "accepted"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("error", {}).get("message") or detail
        except ValueError:
            pass
        return False, f"{exc.code} {detail[:180]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else get_setting("authoring_model")
    client = WorkspaceClient()
    headers = client.config.authenticate()
    headers = headers() if callable(headers) else headers
    token = (headers or {}).get("Authorization", "").replace("Bearer ", "") or client.config.token
    base_path = base_path_for_model(model)
    url = f"{client.config.host}{base_path}/chat/completions"

    print(f"model={model}\nurl={url}\n")
    shapes = [
        ("null (what LangChain sends)", None),
        ("empty string", ""),
        ("a space", " "),
        ("one text content item", [{"type": "text", "text": "Calling a tool."}]),
    ]
    for label, content in shapes:
        ok, detail = ask(url, token, model, conversation(content))
        print(f"  {'OK  ' if ok else 'FAIL'} assistant content = {label:<28} {'' if ok else detail}")


if __name__ == "__main__":
    main()
