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
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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


# Anthropic refuses an image whose base64 exceeds 5 MB, and scales anything
# past 1568 px on its long edge down anyway, so a full-resolution screenshot
# costs a failed call for pixels the model never sees. The byte budget leaves
# room for base64's four-for-three growth.
IMAGE_LONG_EDGE = 1568
IMAGE_MAX_BYTES = 3_500_000


def fit_image(raw: bytes, media_type: str) -> Optional[Tuple[bytes, str]]:
    """`raw` as an image a model will accept, as (bytes, media type), or None.

    Left alone when it is already small enough on both counts. Otherwise it is
    scaled to `IMAGE_LONG_EDGE` and saved as PNG, which keeps screenshot text
    crisp, falling back to JPEG for a photo PNG can't fit in the budget.
    """
    try:
        from PIL import Image
    except ImportError:
        return (raw, media_type) if len(raw) <= IMAGE_MAX_BYTES else None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if len(raw) <= IMAGE_MAX_BYTES and max(img.size) <= IMAGE_LONG_EDGE:
                return raw, media_type
            img.seek(0)
            frame = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    except Exception as e:  # noqa: BLE001
        logger.info("Image could not be read for resizing: %s", e)
        return (raw, media_type) if len(raw) <= IMAGE_MAX_BYTES else None

    frame.thumbnail((IMAGE_LONG_EDGE, IMAGE_LONG_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    frame.save(out, format="PNG", optimize=True)
    if out.tell() <= IMAGE_MAX_BYTES:
        return out.getvalue(), "image/png"
    for quality in (85, 70):
        out = io.BytesIO()
        frame.convert("RGB").save(out, format="JPEG", quality=quality)
        if out.tell() <= IMAGE_MAX_BYTES:
            return out.getvalue(), "image/jpeg"
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


_DATA_URL_PREFIXES = tuple(f"data:{mime};base64," for mime in sorted(set(_IMAGE_MIMES.values())))


def image_part(model: str, data_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """A content part for an image the browser sent inline, or None.

    For Widget Studio's capture of its own preview, which never becomes an upload.
    Held to the same rules as an uploaded image — a model that reads images, the
    admin switch, the size limit — and to image data URLs only, since the value
    comes straight from a request body and is forwarded to the model as-is.
    """
    url = (data_url or "").strip()
    if not url or not flavor(model) or not url.startswith(_DATA_URL_PREFIXES):
        return None
    max_bytes, _ = limits()
    # base64 is four characters per three bytes.
    if (len(url) - url.index(",") - 1) * 3 // 4 > max_bytes:
        return None
    head, _, data = url.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        return None
    fitted = fit_image(raw, head[len("data:"):-len(";base64")])
    if not fitted:
        return None
    if fitted[0] is not raw:
        url = f"data:{fitted[1]};base64,{base64.b64encode(fitted[0]).decode('ascii')}"
    try:
        from services.settings_store import get_bool_setting

        if not get_bool_setting("enable_native_file_passthrough"):
            return None
    except Exception:  # noqa: BLE001
        pass
    return {"type": "image_url", "image_url": {"url": url}}


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

    # An admin can stop raw bytes reaching the model entirely; extraction still
    # runs, so files remain readable through the tools. Guarded because a settings
    # outage must not quietly change what the model can see.
    try:
        from services.settings_store import get_bool_setting

        if not get_bool_setting("enable_native_file_passthrough"):
            return []
    except Exception:  # noqa: BLE001
        pass

    from services import upload_store

    max_bytes, max_pages = limits()
    out: List[Dict[str, Any]] = []
    for meta in attachments:
        kind = meta.get("kind") or ""
        size = int(meta.get("size_bytes") or 0)
        # An image of any size is shrunk to fit below; only a PDF is too big to send.
        if size > max_bytes and kind != "image":
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
        if kind == "image":
            fitted = fit_image(raw, media_type)
            if not fitted:
                logger.info("Image %s left out: too large to send even when shrunk", filename)
                continue
            raw, media_type = fitted
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
