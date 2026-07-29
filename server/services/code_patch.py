"""Splicing model-authored edits into existing widget source.

The Widget Studio agent used to re-emit an entire component on every turn. Past a
few hundred lines that runs into the response token budget, and the studio ends
up with a half-written file that won't compile — the failure mode users saw as
"the agent gives up on complicated widgets".

So the model now sends only the regions it wants to change, in the conflict-marker
form below, and we splice them into the code we already have:

    <<<<<<< SEARCH
    lines that currently exist, copied exactly
    =======
    lines to put there instead
    >>>>>>> REPLACE

Matching walks a ladder from strict to forgiving, because models reliably get the
code right and the whitespace wrong: exact substring, then ignoring trailing
whitespace, then ignoring indentation (re-indenting the replacement to match what
was actually found). A block that still doesn't match is reported rather than
guessed at, so the caller can ask for a correction instead of writing damage.
"""
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Tuple

# Tolerant of the marker length drifting (models sometimes emit 6 or 8 chars) and
# of a trailing language hint after SEARCH.
_EDIT_BLOCK_RE = re.compile(
    r"<{4,}[ \t]*SEARCH[^\n]*\n(.*?)\n?={4,}[ \t]*\n(.*?)\n?>{4,}[ \t]*REPLACE",
    re.DOTALL,
)

_FENCE_RE = re.compile(r"^```[a-zA-Z]*[ \t]*$", re.MULTILINE)


class Edit(NamedTuple):
    search: str
    replace: str


class EditResult(NamedTuple):
    code: str
    applied: int
    failures: List[str]
    warnings: List[str]


def parse_edits(text: str) -> List[Edit]:
    """Pull every SEARCH/REPLACE block out of a model response."""
    edits = []
    for search, replace in _EDIT_BLOCK_RE.findall(text or ""):
        edits.append(Edit(_strip_fences(search), _strip_fences(replace)))
    return edits


def strip_edit_blocks(text: str) -> str:
    """The prose left over once the edit blocks are removed."""
    remainder = _EDIT_BLOCK_RE.sub("", text or "")
    # Fences that wrapped the removed blocks, now empty.
    remainder = re.sub(r"```[a-zA-Z]*\s*```", "", remainder)
    return re.sub(r"\n{3,}", "\n\n", remainder).strip()


def _strip_fences(chunk: str) -> str:
    """Drop a code fence a model wrapped around a SEARCH or REPLACE body."""
    lines = (chunk or "").split("\n")
    while lines and _FENCE_RE.match(lines[0].strip()):
        lines.pop(0)
    while lines and _FENCE_RE.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines)


def _find_exact(code: str, search: str) -> Tuple[Optional[int], int]:
    """Byte offset of `search` in `code`, plus how many times it occurs."""
    count = code.count(search)
    return (code.find(search) if count else None, count)


def _find_lines(code_lines: List[str], search_lines: List[str], strip_indent: bool) -> Optional[int]:
    """Index in `code_lines` where `search_lines` matches, or None.

    With `strip_indent`, leading whitespace is ignored too — which is what lets a
    model that reproduced a nested block at the wrong indentation still land its
    edit.
    """
    norm = (lambda s: s.strip()) if strip_indent else (lambda s: s.rstrip())
    needle = [norm(s) for s in search_lines]
    if not needle:
        return None
    span = len(needle)
    for i in range(0, len(code_lines) - span + 1):
        if [norm(s) for s in code_lines[i:i + span]] == needle:
            return i
    return None


def _leading_ws(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _shift_indent(block: str, from_ws: str, to_ws: str, skip_first: bool = False) -> str:
    """Move a block from one base indentation to another, keeping relative depth.

    `skip_first` leaves the opening line alone, for when it is being spliced in
    after indentation that is already present in the file.
    """
    if from_ws == to_ws:
        return block
    out = []
    for i, line in enumerate(block.split("\n")):
        if skip_first and i == 0:
            out.append(line)
        elif not line.strip():
            out.append("")
        elif from_ws and line.startswith(from_ws):
            out.append(to_ws + line[len(from_ws):])
        elif from_ws:
            out.append(to_ws + line.lstrip())
        else:
            out.append(to_ws + line)
    return "\n".join(out)


def apply_edits(code: str, edits: List[Edit]) -> EditResult:
    """Apply edits in order, returning the new code and what went wrong.

    Edits are applied sequentially so a later block can match text an earlier one
    introduced, mirroring how the model reasons about its own changes.
    """
    current = code or ""
    applied = 0
    failures: List[str] = []
    warnings: List[str] = []

    for n, edit in enumerate(edits, start=1):
        if not edit.search.strip():
            # An empty SEARCH is only meaningful as "write the whole file".
            if not current.strip():
                current = edit.replace
                applied += 1
            else:
                failures.append(f"Edit {n}: empty SEARCH block; nothing to locate.")
            continue

        offset, count = _find_exact(current, edit.search)
        if offset is not None:
            if count > 1:
                warnings.append(
                    f"Edit {n}: SEARCH text occurs {count} times; applied to the first match. "
                    "Include more surrounding context to disambiguate."
                )
            replacement = edit.replace
            # A match that starts part-way into a line of pure indentation means
            # the model dropped the leading whitespace. Its first line splices in
            # after the indentation that's already there, but any further lines
            # would land flush-left, so shift them to line up.
            prefix = current[current.rfind("\n", 0, offset) + 1:offset]
            if "\n" in replacement and prefix and not prefix.strip():
                replacement = _shift_indent(
                    replacement, _leading_ws(edit.search.split("\n")[0]), prefix, skip_first=True
                )
            current = current[:offset] + replacement + current[offset + len(edit.search):]
            applied += 1
            continue

        code_lines = current.split("\n")
        search_lines = edit.search.split("\n")

        idx = _find_lines(code_lines, search_lines, strip_indent=False)
        if idx is not None:
            replacement = edit.replace.split("\n")
        else:
            idx = _find_lines(code_lines, search_lines, strip_indent=True)
            if idx is None:
                preview = search_lines[0][:80] if search_lines else ""
                failures.append(
                    f"Edit {n}: could not find the SEARCH text in the current code "
                    f"(starting \"{preview}\"). Copy the existing lines exactly."
                )
                continue
            replacement = _shift_indent(
                edit.replace,
                _leading_ws(search_lines[0]),
                _leading_ws(code_lines[idx]),
            ).split("\n")
            warnings.append(f"Edit {n}: matched ignoring indentation; replacement was re-indented.")

        current = "\n".join(code_lines[:idx] + replacement + code_lines[idx + len(search_lines):])
        applied += 1

    return EditResult(current, applied, failures, warnings)


def extract_code_block(content: str) -> Tuple[Optional[str], str]:
    """Split a response into (code, prose).

    Prefers an explicitly typed fence so a SQL or JSON block in the explanation
    isn't mistaken for the component. Falls back to an unterminated fence, which
    is what a truncated response looks like.
    """
    content = content or ""
    match = re.search(r"```(?:tsx|jsx|typescript|javascript|ts|js)\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r"```[a-zA-Z]+\n(.*?)```", content, re.DOTALL)
    if match:
        code = match.group(1).strip()
        prose = content.replace(match.group(0), "").strip()
        return code, re.sub(r"\n{3,}", "\n\n", prose)

    partial = re.search(r"```(?:tsx|jsx|typescript|javascript|ts|js)\n(.*)", content, re.DOTALL | re.IGNORECASE)
    if partial:
        return partial.group(1).strip(), re.sub(r"\n{3,}", "\n\n", content[:partial.start()].strip())

    return None, content.strip()


def looks_truncated(content: str) -> bool:
    """True when a response opened a code fence it never closed.

    Fence parity is the only reliable signal. Asking instead whether the last
    fence is followed by another one calls every well-formed response truncated,
    because the closing fence never is.
    """
    return len(re.findall(r"^```", content or "", re.MULTILINE)) % 2 == 1


def continuation_anchor(code: str, lines: int = 12) -> str:
    """The tail of a partial file, to show the model where to resume."""
    tail = (code or "").split("\n")
    return "\n".join(tail[-lines:])
