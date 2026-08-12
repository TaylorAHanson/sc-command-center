"""Run one Agent Studio authoring turn locally and show what goes on the wire.

Run from the repo root with the server's interpreter:

    server/venv/bin/python tools/authoring_repro.py ["your prompt"]

Builds the same client, tools and system prompt `POST /generate/stream` builds,
streams one turn, and prints a summary of every request payload — role, content
type and tool calls — so a rejection like "Content in ChatMessage must have type
in String or List[ContentItem]" can be traced to the message that caused it.

    RAW=1 server/venv/bin/python tools/authoring_repro.py test system.ai.claude-opus-5

sends what LangChain produces without `services.llm_client` tidying it, which is
how to see that failure again (and to check whether an endpoint still needs the
repair).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from databricks.sdk import WorkspaceClient  # noqa: E402

from services import llm_client  # noqa: E402
from routes.agent_studio_profiles import (  # noqa: E402
    AuthorRequest,
    _build_authoring_llm,
    _build_authoring_system_prompt,
    _llm_credentials,
    _make_tools,
)
from services.settings_store import get_setting  # noqa: E402


def describe(payload: dict) -> str:
    lines = []
    for m in payload.get("messages", []):
        content = m.get("content")
        kind = type(content).__name__
        if isinstance(content, list):
            kind += "[" + ",".join(str(b.get("type") if isinstance(b, dict) else type(b).__name__) for b in content) + "]"
        preview = json.dumps(content)[:80] if content is not None else "null"
        calls = ",".join(tc["function"]["name"] for tc in m.get("tool_calls", []) or [])
        lines.append(f"      {m.get('role'):<10} content={kind:<28} {preview}{'  tool_calls=' + calls if calls else ''}")
    return "\n".join(lines)


def main() -> None:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "test"

    # A second argument pins the model, so a deployment's stored setting can be
    # compared against the one that is misbehaving.
    if len(sys.argv) > 2:
        import routes.agent_studio_profiles as studio
        wanted = sys.argv[2]
        real = studio.get_setting
        studio.get_setting = lambda key: wanted if key == "authoring_model" else real(key)

    model = get_setting("authoring_model") if len(sys.argv) <= 2 else sys.argv[2]
    print(f"model={model}\n")

    if os.environ.get("RAW") == "1":
        print("  (RAW=1: sending LangChain's shapes untouched)\n")
        llm_client.normalise_content = lambda content, role="": content

    # Wrapping the subclass shows what actually leaves, after any repair.
    original = llm_client.DatabricksChatOpenAI._get_request_payload
    seen = {"n": 0}

    def spy(self, input_, *, stop=None, **kwargs):
        payload = original(self, input_, stop=stop, **kwargs)
        seen["n"] += 1
        print(f"  request {seen['n']}:")
        print(describe(payload))
        return payload

    llm_client.DatabricksChatOpenAI._get_request_payload = spy

    from langchain_core.messages import HumanMessage
    from langgraph.prebuilt import create_react_agent

    ws = WorkspaceClient()
    api_key, base_url = _llm_credentials(ws)
    print(f"base_url={base_url}\n")

    req = AuthorRequest(prompt=prompt, history=[], confirm_schema=True)
    agent = create_react_agent(
        model=_build_authoring_llm(api_key, base_url),
        tools=_make_tools(ws, True),
        prompt=_build_authoring_system_prompt(req),
    )

    try:
        for msg, _meta in agent.stream({"messages": [HumanMessage(content=prompt)]}, stream_mode="messages"):
            pass
        print("\n  completed without error")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  FAILED: {type(exc).__name__}: {str(exc)[:400]}")


if __name__ == "__main__":
    main()
