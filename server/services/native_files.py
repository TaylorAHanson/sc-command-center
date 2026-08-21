"""Handing an uploaded file to a model verbatim, rather than via a tool.

Extraction cannot read a chart, a screenshot or a scan, so images and short PDFs
travel to the model as content parts. Both providers do this, but through
different shapes — Anthropic wants a `document` block and rejects `file`, OpenAI
wants `file` and rejects `document` — and a model that is neither gets nothing
here and works from the extracted text instead, which is why extraction never
gets skipped on the strength of this module.

Lives here rather than in `agent_runtime` because Widget Studio needs the same
thing: a screenshot of the widget being edited is an image with no text in it,
and the flavor table is not worth writing twice.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional, Tuple

ANTHROPIC = "anthropic"
OPENAI = "openai"

_IMAGE_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}


def flavor(model: str) -> Optional[str]:
    """Which content-part shape `model` accepts, or None if it takes neither."""
    name = (model or "").lower()
    if "claude" in name:
        return ANTHROPIC
    if "gpt" in name or name.startswith("system.ai.o"):
        return OPENAI
    return None


def guess_image_mime(filename: str) -> str:
    return _IMAGE_MIMES.get(os.path.splitext(filename)[1].lower(), "image/png")


def limits() -> Tuple[int, int]:
    """(max bytes, max PDF pages) for handing a file over verbatim."""
    try:
        mb = int(os.environ.get("AGENT_RUNTIME_NATIVE_FILE_MB", "") or 8)
    except ValueError:
        mb = 8
    try:
        pages = int(os.environ.get("AGENT_RUNTIME_NATIVE_PDF_PAGES", "") or 20)
    except ValueError:
        pages = 20
    return max(1, mb) * 1024 * 1024, max(1, pages)


def parts(model: str, env: str, attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Content parts for files the model should read itself rather than via tools.

    Images always go over: there is no text to extract, and they are cheap. A PDF
    only goes over when it is small, or when extraction found no text at all —
    that last case is a scanned document, where the model's own reading is the
    only thing that will work. Big text-bearing PDFs deliberately stay on the
    tool path, since pushing 300 pages through the context window to answer one
    question is exactly what this design avoids.
    """
    shape = flavor(model)
    if not shape or not attachments:
        return []

    from services import upload_store

    max_bytes, max_pages = limits()
    out: List[Dict[str, Any]] = []
    for meta in attachments:
        kind = meta.get("kind") or ""
        size = int(meta.get("size_bytes") or 0)
        if size > max_bytes:
            continue

        mime = (meta.get("mime") or "").lower()
        filename = meta.get("filename") or "file"
        if kind == "image":
            media_type = mime if mime.startswith("image/") else guess_image_mime(filename)
        elif kind == "document" and (mime == "application/pdf" or filename.lower().endswith(".pdf")):
            profile = meta.get("profile") or {}
            pages = int(profile.get("pages") or 0)
            has_text = int(profile.get("chars") or 0) > 40
            if has_text and pages > max_pages:
                continue
            media_type = "application/pdf"
        else:
            continue

        raw = upload_store.load_raw(env, meta["id"])
        if not raw:
            continue
        encoded = base64.b64encode(raw).decode("ascii")

        if kind == "image":
            out.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}})
        elif shape == ANTHROPIC:
            out.append({
                "type": "document",
                "source": {"type": "base64", "media_type": media_type, "data": encoded},
            })
        else:
            out.append({
                "type": "file",
                "file": {"filename": filename, "file_data": f"data:{media_type};base64,{encoded}"},
            })
    return out
