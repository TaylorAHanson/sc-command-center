"""The chat client the studios talk to, and the one thing it fixes on the way out.

Every model this app uses speaks the OpenAI chat-completions shape, and
`langchain_openai.ChatOpenAI` is what speaks it. That client disagrees with
Databricks about one detail, and the disagreement only shows up on models that
answer in content blocks:

    INVALID_PARAMETER_VALUE: Content in ChatMessage must have type in
    String or List[ContentItem].

An assistant turn from Claude Opus 5 arrives as blocks — some reasoning, some
text — rather than as a string. LangChain strips the reasoning on the way back
out and appends anything it doesn't recognise verbatim
(`_format_message_content`, "else: formatted_content.append(block)"), so the
message leaves as `["I'll start by..."]`: a list of bare strings, which is
neither a string nor a list of content items. Databricks refuses it, and because
the refusal happens on the *second* request of a tool-using run, what the user
sees is an agent that answers a simple prompt with a 400.

Opus 4.8 replies with a plain string and is unaffected, which is why this looked
like "the new model is broken" rather than a shape problem. It isn't specific to
Opus 5 either — any model that returns content blocks will do the same, so the
repair belongs here rather than in a list of model names.

`tools/authoring_repro.py` reproduces the failure and prints the payload.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from langchain_openai import ChatOpenAI

#: Content items that mean something to the endpoint and travel unchanged.
#: Anything else in an assistant turn is the model's own working — reasoning,
#: thinking, tool-use traces — which cannot be replayed and is dropped.
_PASS_THROUGH = {"image_url", "input_audio", "file", "audio"}


def normalise_content(content: Any, role: str = "") -> Union[str, List[Dict[str, Any]], None]:
    """Coerce one message's content into something a ChatMessage will accept.

    A string or `None` is already fine (the endpoint takes a null content on an
    assistant turn that only calls tools). A list is rebuilt: bare strings and
    text blocks become text, images and their kin pass through, and everything
    else is dropped. An all-text list collapses back to a plain string, which is
    the shape every endpoint agrees on and the one these models used to send.
    """
    if content is None or isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    items: List[Dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            items.append({"type": "text", "text": block})
        elif isinstance(block, dict):
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                items.append({"type": "text", "text": block["text"]})
            elif kind in _PASS_THROUGH:
                items.append(block)

    if not items:
        # Nothing survived, so this was a pure reasoning turn. An assistant may
        # say nothing while it calls a tool; anyone else has to say something.
        return None if role == "assistant" else ""
    if all(item.get("type") == "text" for item in items):
        return "\n\n".join(item["text"] for item in items)
    return items


class DatabricksChatOpenAI(ChatOpenAI):
    """`ChatOpenAI` with every outgoing message's content in an accepted shape.

    Overrides the one method that builds the request body, so streaming and
    non-streaming, tool calls and plain turns all go through it.
    """

    def _get_request_payload(self, input_: Any, *, stop: Optional[List[str]] = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload.get("messages") or []:
            if isinstance(message, dict):
                message["content"] = normalise_content(message.get("content"), message.get("role", ""))
        return payload


def chat_client(**kwargs: Any) -> DatabricksChatOpenAI:
    """Build the app's chat client. Use this rather than `ChatOpenAI` directly."""
    return DatabricksChatOpenAI(**kwargs)
