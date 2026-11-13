"""What an email may carry beyond Markdown: sanitized HTML and attached files.

`email_service` sends; this module decides what of a caller's HTML and files
survives. A widget or an agent chooses the content, and the person sees exactly
what will arrive in the Send dialog before anything goes, so the rules here are
not about taste. They hold back only what a preview can't show the person, or
what would turn an email under the app's own From address into something else:

  * **Nothing loads from elsewhere.** An `<img>` pointing at another site
    reports who opened the email and when, which no preview reveals. Images are
    embedded instead: a `data:` URL in the HTML, or `cid:<file name>` naming an
    attached image, travels inside the email as an inline part.
  * **Nothing runs.** HTML is parsed and written out again from an allow-list
    of tags, attributes and CSS properties; scripts, styles, forms, frames and
    event handlers never make it through, and links go only to http, https and
    mailto. Because the output is rebuilt rather than filtered, every tag it
    opens it also closes, so nothing can escape the body into the footer that
    names the sender.
  * **Files are the kinds a browser makes on its own**: text, CSV, TSV, JSON,
    Markdown, and PNG, JPEG, GIF or WebP images (a canvas's `toDataURL`). No
    office or PDF formats, which would need libraries the app doesn't carry, and
    nothing executable. An image must really be the image its name says, and a
    CSV gets the same spreadsheet-formula guard as the app's own.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import html
import io
import re
import uuid
from html.parser import HTMLParser
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

#: Extension → content type. Only what a widget can build with no library.
ATTACHMENT_TYPES: Dict[str, str] = {
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "txt": "text/plain",
    "json": "application/json",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_TYPES = {t for t in ATTACHMENT_TYPES.values() if t not in IMAGE_TYPES}

MAX_ATTACHMENTS = 10
MAX_INLINE_IMAGES = 20
ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
#: Every file together, inline images and table CSVs included. SES takes 40 MB
#: once base64 has grown it by a third; this leaves room for the HTML.
FILES_MAX_BYTES = 10 * 1024 * 1024
#: Markup after embedded images are lifted out of it.
MAX_HTML_CHARS = 200_000
#: What the request may carry before parsing: the markup plus base64 images.
MAX_HTML_INPUT_CHARS = MAX_HTML_CHARS + (FILES_MAX_BYTES * 4) // 3 + 1024
MAX_FILENAME_CHARS = 100

ALLOWED_EXTENSIONS_TEXT = ", ".join(f".{ext}" for ext in ATTACHMENT_TYPES if ext != "jpeg")


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class File(NamedTuple):
    filename: str
    content_type: str
    data: bytes
    #: Set when the HTML shows it; an inline part is referenced as `cid:<cid>`.
    cid: str = ""
    #: Rows, for a CSV made from a table; None otherwise.
    rows: Optional[int] = None

    @property
    def inline(self) -> bool:
        return bool(self.cid)


_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def image_matches(content_type: str, data: bytes) -> bool:
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(sig) for sig in _SIGNATURES.get(content_type, ()))


_UNSAFE_NAME = re.compile(r"[^\w.\- ()]+", re.UNICODE)


def clean_filename(raw: Any) -> str:
    """A file name safe to put in a MIME header: no path, no control
    characters, nothing a mail client could read as a second extension."""
    name = re.split(r"[\\/]", str(raw or ""))[-1]
    name = _UNSAFE_NAME.sub("-", name).strip(" .-")
    name = re.sub(r"-{2,}", "-", name)
    if len(name) > MAX_FILENAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:MAX_FILENAME_CHARS - len(ext) - 1].rstrip(" .-") + dot + ext) if dot else name[:MAX_FILENAME_CHARS]
    return name


def type_for(filename: str) -> Optional[str]:
    _stem, dot, ext = filename.rpartition(".")
    return ATTACHMENT_TYPES.get(ext.lower()) if dot else None


_DATA_URL = re.compile(r"^data:([\w.+/-]*)((?:;[\w.+-]+=[^;,]*)*)(;base64)?,(.*)$", re.S | re.I)


def decode_data(value: str) -> Tuple[Optional[str], bytes]:
    """(content type a data: URL declared, bytes) for a data: URL or plain
    base64. ValueError when it isn't either."""
    text = value.strip()
    declared = None
    m = _DATA_URL.match(text)
    if m:
        declared = (m.group(1) or "").lower() or None
        if not m.group(3):
            raise ValueError("not base64")
        text = m.group(4)
    try:
        return declared, base64.b64decode(re.sub(r"\s+", "", text), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64") from exc


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def csv_safe(value: str) -> str:
    # A spreadsheet runs a cell starting with = + - @ as a formula (CSV injection);
    # the quote makes it text. Plain negative numbers are left alone.
    if value.startswith(_FORMULA_START) and not _NUMBER.match(value):
        return "'" + value
    return value


def guard_delimited(text: str, delimiter: str) -> bytes:
    """A caller's CSV or TSV, rewritten cell by cell through `csv_safe`."""
    bom = text.startswith("﻿")
    rows = csv.reader(io.StringIO(text[1:] if bom else text), delimiter=delimiter)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return (("﻿" if bom else "") + out.getvalue()).encode("utf-8")


def unique_name(name: str, taken: set) -> str:
    if name.lower() not in taken:
        taken.add(name.lower())
        return name
    stem, dot, ext = name.rpartition(".")
    for n in range(2, 1000):
        candidate = f"{stem}-{n}{dot}{ext}" if dot else f"{name}-{n}"
        if candidate.lower() not in taken:
            taken.add(candidate.lower())
            return candidate
    raise ValueError("Too many files with the same name.")


def normalize_attachments(items: Any, taken: Optional[set] = None) -> List[File]:
    """Files as `[{filename, content}]` (text) or `[{filename, data}]` (base64
    or a data: URL). ValueError, with a sentence for the sender, for anything
    that can't go."""
    if items is None or items == []:
        return []
    if isinstance(items, Mapping):
        items = [items]
    if not isinstance(items, (list, tuple)):
        raise ValueError("Attachments must be a list of files.")
    if len(items) > MAX_ATTACHMENTS:
        raise ValueError(f"At most {MAX_ATTACHMENTS} attachments.")
    taken = taken if taken is not None else set()
    files: List[File] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("Each attachment needs a filename and its content.")
        name = clean_filename(item.get("filename") or item.get("name"))
        if not name:
            raise ValueError("Each attachment needs a filename.")
        content_type = type_for(name)
        if content_type is None:
            raise ValueError(f"Can't attach {name}: only {ALLOWED_EXTENSIONS_TEXT} files can be attached.")
        content, data_in = item.get("content"), item.get("data")
        if isinstance(content, str) and data_in is None:
            if content_type in IMAGE_TYPES:
                raise ValueError(f"{name} is an image, so send it as data (base64 or a data: URL), not text.")
            data = content.encode("utf-8")
        elif isinstance(data_in, str):
            try:
                _declared, data = decode_data(data_in)
            except ValueError:
                raise ValueError(f"{name} couldn't be read: its data must be base64 or a data: URL.") from None
        else:
            raise ValueError(f"{name} has no content.")
        if len(data) > ATTACHMENT_MAX_BYTES:
            raise ValueError(f"{name} is too large: at most {_mb(ATTACHMENT_MAX_BYTES)} a file.")
        if content_type in IMAGE_TYPES:
            if not image_matches(content_type, data):
                raise ValueError(f"{name} isn't the {content_type.split('/')[1].upper()} image its name says.")
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{name} isn't text: a .{name.rpartition('.')[2]} file must be UTF-8.") from None
            if content_type == "text/csv":
                data = guard_delimited(text, ",")
            elif content_type == "text/tab-separated-values":
                data = guard_delimited(text, "\t")
        files.append(File(unique_name(name, taken), content_type, data))
    return files


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup", "dd", "del", "div",
    "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li",
    "mark", "ol", "p", "pre", "q", "s", "small", "span", "strike", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
_VOID = {"br", "hr", "img", "col"}
# Dropped with everything inside them. Only elements that always have a closing
# tag: a void one here would swallow the rest of the email.
_DROP_WITH_CONTENT = {
    "script", "style", "head", "title", "iframe", "object", "noscript", "template", "svg", "math",
    "textarea", "select", "applet", "audio", "video", "canvas", "frameset", "noframes", "noembed",
    "xmp", "plaintext", "map", "picture",
}
_BLOCK = {"p", "div", "blockquote", "pre", "table", "tr", "ul", "ol", "dl", "dt", "dd", "caption",
          "h1", "h2", "h3", "h4", "h5", "h6", "hr"}

_COMMON_ATTRS = {"style", "title", "dir", "align"}
_TAG_ATTRS = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "valign", "width", "height", "bgcolor"},
    "th": {"colspan", "rowspan", "valign", "width", "height", "bgcolor"},
    "table": {"width", "border", "cellpadding", "cellspacing", "bgcolor"},
    "tr": {"valign", "bgcolor"},
    "col": {"span", "width"},
    "colgroup": {"span", "width"},
    "ol": {"start", "type"},
    "li": {"value"},
}
_NUMERIC_ATTRS = {"width", "height", "colspan", "rowspan", "border", "cellpadding", "cellspacing",
                  "span", "start", "value"}
_NUMERIC = re.compile(r"^\d{1,4}%?$")
_COLOUR_ATTR = re.compile(r"^#?[0-9a-zA-Z]{1,20}$")
_ENUM_ATTRS = {
    "align": {"left", "right", "center", "justify"},
    "valign": {"top", "middle", "bottom", "baseline"},
    "dir": {"ltr", "rtl", "auto"},
    "type": {"1", "a", "A", "i", "I"},
}
_SAFE_URL = re.compile(r"^(?:https?://[^\s<>\"'`]+|mailto:[^\s<>\"'`]+)$", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_STYLE_PROPS = {
    "color", "background-color", "font", "font-family", "font-size", "font-style", "font-weight",
    "font-variant", "line-height", "letter-spacing", "word-spacing", "text-align", "text-decoration",
    "text-transform", "text-indent", "white-space", "word-break", "overflow-wrap", "word-wrap",
    "vertical-align", "width", "min-width", "max-width", "height", "min-height", "max-height",
    "border-collapse", "border-spacing", "border-radius", "display", "list-style", "list-style-type",
    "list-style-position", "table-layout", "box-sizing", "text-overflow", "overflow",
}
_BOX_PROP = re.compile(r"^(?:margin|padding)(?:-(?:top|right|bottom|left))?$"
                       r"|^border(?:-(?:top|right|bottom|left))?(?:-(?:color|style|width))?$"
                       r"|^border-(?:top|bottom)-(?:left|right)-radius$")
# Values are words, numbers, colours and a few functions; nothing that fetches
# (url(), image-set()), nothing that escapes (\), and no second declaration.
_STYLE_VALUE = re.compile(r"^[\w\s#%.,'\"()+\-/!]*$")
_STYLE_FUNC = re.compile(r"([a-zA-Z-]+)\s*\(")
_STYLE_FUNCS = {"rgb", "rgba", "hsl", "hsla", "calc"}
# Hidden text would show in the plain-text part, which the preview doesn't.
_HIDDEN_DISPLAY = {"none"}


def clean_style(style: str) -> str:
    kept: List[str] = []
    for declaration in (style or "").split(";"):
        prop, sep, value = declaration.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if not sep or not value:
            continue
        if prop not in _STYLE_PROPS and not _BOX_PROP.match(prop):
            continue
        lowered = value.lower()
        if not _STYLE_VALUE.match(value) or "/*" in value or "expression" in lowered:
            continue
        if any(fn.lower() not in _STYLE_FUNCS for fn in _STYLE_FUNC.findall(value)):
            continue
        if prop == "display" and lowered.replace("!important", "").strip() in _HIDDEN_DISPLAY:
            continue
        kept.append(f"{prop}:{value}")
    return ";".join(kept)


class Sanitized(NamedTuple):
    html: str
    text: str
    #: Images the HTML embedded as data: URLs, now inline parts.
    images: List[File]
    #: The attachment names `cid:` references matched, which go inline.
    referenced: List[str]
    #: Sentences about what was left out, for the person previewing it.
    notes: List[str]


class _Sanitizer(HTMLParser):
    def __init__(self, attachments: Sequence[File], taken: set):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.text: List[str] = []
        self.open: List[str] = []
        self.skip: List[str] = []
        self.images: List[File] = []
        self.referenced: List[str] = []
        self.taken = taken
        self.by_name = {f.filename.lower(): f for f in attachments if f.content_type in IMAGE_TYPES}
        self.remote_images = 0
        self.bad_images = 0
        self.too_many_images = 0
        #: The href of each open <a>, "" when it had none worth keeping.
        self.links: List[str] = []
        self.href = ""
        self.pre = 0

    # -- attributes ----------------------------------------------------------
    def _attrs(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> Optional[str]:
        """The attribute string, or None when the element can't be kept."""
        allowed = _COMMON_ATTRS | _TAG_ATTRS.get(tag, set())
        out: List[str] = []
        for name, value in attrs:
            name = (name or "").lower()
            value = "" if value is None else _CONTROL.sub("", value).strip()
            if name not in allowed:
                continue
            if name == "style":
                value = clean_style(value)
                if not value:
                    continue
            elif name == "href":
                if not _SAFE_URL.match(value):
                    continue
                self.href = value
            elif name == "src":
                value = self._image_src(value)
                if value is None:
                    return None
            elif name in _NUMERIC_ATTRS:
                if not _NUMERIC.match(value):
                    continue
            elif name == "bgcolor":
                if not _COLOUR_ATTR.match(value):
                    continue
            elif name in _ENUM_ATTRS:
                if value not in _ENUM_ATTRS[name] and value.lower() not in _ENUM_ATTRS[name]:
                    continue
            else:
                value = value[:300]
            out.append(f' {name}="{html.escape(value, quote=True)}"')
        if tag == "img" and not any(a.startswith(" src=") for a in out):
            return None
        return "".join(out)

    def _image_src(self, src: str) -> Optional[str]:
        lowered = src.lower()
        if lowered.startswith("data:"):
            try:
                declared, data = decode_data(src)
            except ValueError:
                self.bad_images += 1
                return None
            if declared not in IMAGE_TYPES or not image_matches(declared, data):
                self.bad_images += 1
                return None
            if len(self.images) + len(self.referenced) >= MAX_INLINE_IMAGES:
                self.too_many_images += 1
                return None
            ext = "jpg" if declared == "image/jpeg" else declared.split("/")[1]
            name = unique_name(f"image-{len(self.images) + 1}.{ext}", self.taken)
            cid = f"img{len(self.images) + 1}.{uuid.uuid4().hex[:12]}@command-center"
            self.images.append(File(name, declared, data, cid))
            return f"cid:{cid}"
        if lowered.startswith("cid:"):
            wanted = src[4:].strip().lower()
            if wanted not in self.by_name:
                self.bad_images += 1
                return None
            if wanted not in (r.lower() for r in self.referenced):
                self.referenced.append(self.by_name[wanted].filename)
            return f"cid:{_cid_for(self.by_name[wanted].filename)}"
        self.remote_images += 1
        return None

    # -- text ----------------------------------------------------------------
    def _newline(self) -> None:
        if self.text and not self.text[-1].endswith("\n"):
            self.text.append("\n")

    # -- parser callbacks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.append(tag)
            return
        if tag in _DROP_WITH_CONTENT:
            self.skip.append(tag)
            return
        if tag not in _ALLOWED_TAGS:
            return
        self.href = ""
        attributes = self._attrs(tag, attrs)
        if attributes is None:
            return
        if tag == "a":
            self.links.append(self.href)
        if tag in _BLOCK or tag in ("br", "li"):
            self._newline()
        if tag == "li":
            self.text.append("- ")
        if tag == "pre":
            self.pre += 1
        self.out.append(f"<{tag}{attributes}>")
        if tag not in _VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if self.skip or tag in _DROP_WITH_CONTENT:
            return
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag not in self.open:
            return
        while self.open:
            top = self.open.pop()
            self.out.append(f"</{top}>")
            if top == "pre":
                self.pre -= 1
            if top == "a":
                href = self.links.pop() if self.links else ""
                # The plain-text part keeps where a link went, unless its text says so already.
                if href and href.lower().removeprefix("mailto:") not in "".join(self.text[-3:]).lower():
                    self.text.append(f" ({href})")
            if top in _BLOCK:
                self._newline()
            if top == tag:
                break

    def handle_data(self, data):
        if self.skip or not data:
            return
        self.out.append(html.escape(data, quote=False))
        self.text.append(data if self.pre else re.sub(r"\s+", " ", data))

    def close(self):
        super().close()
        while self.open:
            self.handle_endtag(self.open[-1])


def _cid_for(filename: str) -> str:
    """The Content-ID an attached image goes by when the HTML shows it. The
    hash keeps two names that slug alike apart."""
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", filename).strip("-")[:40] or "image"
    digest = hashlib.sha256(filename.lower().encode("utf-8")).hexdigest()[:8]
    return f"{slug}.{digest}@command-center"


def sanitize_html(markup: str, attachments: Sequence[File] = (), taken: Optional[set] = None) -> Sanitized:
    """`markup` rebuilt from the allow-list. Raises ValueError when it is too
    long to send."""
    if len(markup or "") > MAX_HTML_INPUT_CHARS:
        raise ValueError(f"The HTML is too long: at most {MAX_HTML_CHARS:,} characters, plus embedded images.")
    parser = _Sanitizer(attachments, taken if taken is not None else {f.filename.lower() for f in attachments})
    parser.feed(markup or "")
    parser.close()
    body = "".join(parser.out)
    if len(body) > MAX_HTML_CHARS:
        raise ValueError(f"The HTML is too long: at most {MAX_HTML_CHARS:,} characters, plus embedded images.")
    text = re.sub(r"[ \t]+\n", "\n", "".join(parser.text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    notes: List[str] = []
    if parser.remote_images:
        n = parser.remote_images
        notes.append(f"Left out {n} image{'' if n == 1 else 's'} that would load from another site; "
                     "only embedded images are sent.")
    if parser.bad_images:
        n = parser.bad_images
        notes.append(f"Left out {n} image{'' if n == 1 else 's'} that couldn't be read.")
    if parser.too_many_images:
        notes.append(f"Left out images past the first {MAX_INLINE_IMAGES}.")
    return Sanitized(body, text, parser.images, parser.referenced, notes)


def inline_for_html(files: Sequence[File], referenced: Sequence[str]) -> List[File]:
    """`files` with every attached image the HTML referenced given its Content-ID."""
    wanted = {name.lower() for name in referenced}
    return [f._replace(cid=_cid_for(f.filename)) if f.filename.lower() in wanted and not f.cid else f
            for f in files]


def with_data_urls(markup: str, files: Sequence[File]) -> str:
    """The HTML with each `cid:` swapped for the image itself, for a preview a
    browser can draw. The ids are ours, so a plain replace is exact."""
    for f in files:
        if f.cid:
            data = base64.b64encode(f.data).decode("ascii")
            markup = markup.replace(f'src="cid:{f.cid}"', f'src="data:{f.content_type};base64,{data}"')
    return markup
