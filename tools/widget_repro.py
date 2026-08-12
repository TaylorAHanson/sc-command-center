"""Run one Widget Studio generation locally and show what came back.

Run from the repo root with the server's interpreter:

    server/venv/bin/python tools/widget_repro.py ["prompt"] [model]
    server/venv/bin/python tools/widget_repro.py --plan ["prompt"] [model]

Builds the same client, tool and system prompt the generation job builds, runs
one turn, and reports how long it took, what shape the reply arrived in, and how
much of it `reply_text` could actually read. The last of those is the point: a
model that answers in content blocks can leave the studio with an empty reply —
no explanation and no code — which looks like a slow, silent agent rather than a
parsing problem.

`--plan` runs the planning call instead, which is the one on a clock: it is
capped at `PLAN_SECONDS`, and a model that thinks for longer than that returns no
plan, so the staged checklist never appears and the request falls back to a
single long pass. That is worth re-measuring whenever the widget model changes.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from databricks.sdk import WorkspaceClient  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

import routes.agent_studio as studio  # noqa: E402
from services.settings_store import base_path_for_model, get_setting  # noqa: E402

PROMPT = "Build a widget that shows a count of orders."

# Long enough to take the staged path (`_wants_stages`), which is the one users
# see as a ticking checklist.
#: Requests of increasing size, for `SIZES=1 --plan`. The first two are the ones
#: worth watching: a plan is only worth its round trips if a small request stays
#: small, and both of these trip `_wants_stages` on their "and"s.
SIZES = [
    ("tiny", "Change the title to Orders and also make it blue."),
    ("small", "Add a search box to the table and also a row count underneath it."),
    ("large", None),  # filled in below with STAGED_PROMPT
]

STAGED_PROMPT = (
    "Build an orders dashboard widget: show a total order count at the top, then a bar "
    "chart of orders by status underneath it, and also add a date range filter that "
    "applies to both. It should show a loading state while data is fetching and an "
    "error state if the query fails."
)

SIZES[2] = ("large", STAGED_PROMPT)


def shape(content) -> str:
    if not isinstance(content, list):
        return type(content).__name__
    parts = [p.get("type", "dict") if isinstance(p, dict) else type(p).__name__ for p in content]
    return f"list[{', '.join(parts)}]"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--plan"]
    planning = "--plan" in sys.argv
    prompt = args[0] if args else (STAGED_PROMPT if planning else PROMPT)
    model = args[1] if len(args) > 1 else get_setting("widget_model")

    ws = WorkspaceClient()
    headers = ws.config.authenticate()
    headers = headers() if callable(headers) else headers
    api_key = (headers or {}).get("Authorization", "").replace("Bearer ", "") or ws.config.token
    base_url = f"{ws.config.host}{base_path_for_model(model)}"

    print(f"model={model}\nurl={base_url}\n")

    budget = studio._Budget(int(os.environ.get("BUDGET", "180")))

    if planning and os.environ.get("RUN_STAGES"):
        # The whole staged run, as the job does it, reporting each step as it
        # lands. This is the wait a user actually sits through.
        plan_prompt = studio._build_system_prompt(studio.GenerateRequest(prompt=prompt))

        calls: list = []

        def ask(messages, limit=None):
            client = studio._widget_llm(api_key, base_url, model, budget, None, limit)
            at = time.time()
            out = studio.reply_text(client.invoke(messages))
            calls.append((time.time() - at, len(out)))
            return out

        def next_llm():
            return studio._widget_llm(api_key, base_url, model, budget)

        started = time.time()
        stages = studio._plan_stages(ask, plan_prompt, prompt)
        print(f"  planning took        {calls[-1][0]:.1f}s for {len(stages)} steps\n")
        for i, stage in enumerate(stages):
            print(f"    {i + 1}. {stage['title']}")
        print()

        # Report each step as the run publishes it, which is also the moment the
        # studio ticks it off. Reported state is kept here rather than on the
        # stages themselves, which are published to the client as they are.
        original = studio._publish
        reported: set = set()

        def spy(job_id, **fields):
            for stage in fields.get("stages") or []:
                state = stage.get("status")
                key = (stage["title"], state)
                if state in ("done", "failed", "skipped") and key not in reported:
                    reported.add(key)
                    took = calls[-1][0] if calls else 0.0
                    size = len(fields.get("stage_code") or "")
                    print(f"  step {state:7} {took:5.1f}s  {stage['title'][:44]:44}"
                          f"{f' -> {size} chars' if size else ''}")
            original(job_id, **fields)

        studio._publish = spy
        job = "repro"
        studio.generation_jobs[job] = {"status": "running"}
        try:
            studio._run_stages(job, studio.GenerateRequest(prompt=prompt), stages, ask, next_llm, budget)
        finally:
            studio._publish = original
        result = studio.generation_jobs[job].get("result", {})

        print(f"\n  model calls          {len(calls)} "
              f"({', '.join(f'{t:.0f}s' for t, _ in calls)})")
        print(f"  whole run took       {time.time() - started:.1f}s")
        print(f"  code produced        {len(result.get('code') or '')} characters")
        print("\n  what the user reads:\n")
        for line in (result.get("explanation") or "(nothing)").splitlines():
            print(f"    {line}")
        return

    if planning and os.environ.get("SIZES"):
        # How many steps each size of request is planned into. The number is the
        # wait: every step is another model call, and on a thinking model that is
        # another 20-35 seconds before the user sees anything else happen.
        for label, text in SIZES:
            req = studio.GenerateRequest(prompt=text)
            if not studio._wants_stages(req):
                print(f"  {label:8} one pass (not planned)")
                continue

            def ask(messages, limit=None, _t=text):
                client = studio._widget_llm(api_key, base_url, model, budget, None, limit)
                return studio.reply_text(client.invoke(messages))

            started = time.time()
            stages = studio._plan_stages(ask, studio._build_system_prompt(req), text)
            titles = ", ".join(s["title"] for s in stages) or "one pass"
            print(f"  {label:8} {len(stages)} steps in {time.time() - started:4.1f}s  {titles}")
        return

    if planning:
        plan_prompt = studio._build_system_prompt(studio.GenerateRequest(prompt=prompt))

        def ask(messages, limit=None):
            client = studio._widget_llm(api_key, base_url, model, budget, None, limit)
            return studio.reply_text(client.invoke(messages))

        print(f"  wants stages         {studio._wants_stages(studio.GenerateRequest(prompt=prompt))}")
        print(f"  cap on this call     {studio.PLAN_SECONDS}s")
        started = time.time()
        stages = studio._plan_stages(ask, plan_prompt, prompt)
        print(f"  planning took        {time.time() - started:.1f}s")
        print(f"  steps planned        {len(stages)}" + ("  <- no checklist" if not stages else ""))
        for i, stage in enumerate(stages):
            print(f"    {i + 1}. {stage['title']}")
        return

    llm = studio._widget_llm(api_key, base_url, model, budget)
    agent = create_react_agent(
        model=llm,
        tools=[studio.search_widgets],
        prompt=studio._build_system_prompt(studio.GenerateRequest(prompt=prompt)),
    )

    started = time.time()
    response = agent.invoke({"messages": [HumanMessage(content=prompt)]})
    elapsed = time.time() - started

    last = response["messages"][-1]
    text = studio.reply_text(last)
    raw = last.content

    print(f"  elapsed              {elapsed:.1f}s")
    print(f"  reply arrived as     {shape(raw)}")
    print(f"  characters in reply  {sum(len(p if isinstance(p, str) else p.get('text', '')) for p in raw) if isinstance(raw, list) else len(raw)}")
    print(f"  reply_text read      {len(text)} characters")
    print(f"  code block found     {'yes' if '```' in text else 'NO'}")
    print(f"  prose before code    {len(text.split('```')[0].strip())} characters")

    # What the model thought, and whether any of it is readable. If a model has
    # moved its narration in here, the studio's chat panel has gone quiet.
    for part in raw if isinstance(raw, list) else []:
        if isinstance(part, dict) and part.get("type") == "reasoning":
            print(f"\n  reasoning block keys: {sorted(part.keys())}")
            summary = part.get("summary")
            print(f"  summary: {type(summary).__name__} "
                  f"{len(summary) if isinstance(summary, (list, str)) else ''}")
            if isinstance(summary, list) and summary:
                print(f"  summary[0]: {str(summary[0])[:300]!r}")
            for key in ("text", "reasoning", "thinking"):
                if part.get(key):
                    print(f"  {key}: {str(part[key])[:300]!r}")

    print(f"\n  first 200 read: {text[:200]!r}")


if __name__ == "__main__":
    main()
