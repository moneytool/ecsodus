"""MkDocs hook: render GitHub-style Markdown lists correctly.

The docs are written for GitHub, which accepts a list directly after a paragraph line and
nests lists with 2-space indentation. Python-Markdown (used by MkDocs) needs a blank line before
a list and 4-space nesting; without them, lists render as one paragraph with literal hyphens.
Several pages are verbatim records (council reviews, plan snapshots) that must not be edited, so
the fix is applied at render time: insert the blank line, and double list indentation.
Fenced code blocks are left untouched.
"""

from __future__ import annotations

import re
from typing import Any

_ITEM = re.compile(r"^( *)([-*+]|\d+[.)])\s+\S")
_FENCE = re.compile(r"^\s*(```|~~~)")


def normalise(markdown: str) -> str:
    out: list[str] = []
    in_fence = False
    in_list = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        is_item = bool(_ITEM.match(line))
        if is_item:
            prev = out[-1] if out else ""
            # A list (or a sub-list inside an item) must start a new block: Python-Markdown
            # needs a blank line after any non-item text line, at any nesting level.
            if prev.strip() and not _ITEM.match(prev):
                out.append("")
            in_list = True
        elif not line.strip():
            pass  # blank lines keep the list context (loose lists, continuations)
        elif not line.startswith(" ") and not is_item:
            in_list = False
        if in_list and line.startswith(" ") and line.strip():
            indent = len(line) - len(line.lstrip(" "))
            line = " " * (indent * 2) + line.lstrip(" ")
        out.append(line)
    return "\n".join(out)


def on_page_markdown(markdown: str, **kwargs: Any) -> str:
    return normalise(markdown)
