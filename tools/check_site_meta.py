"""Verify the search metadata in a built docs site (run after `mkdocs build`).

    python tools/check_site_meta.py site/

For every page: each <meta>/<link> tag in <head> parses with only the expected attributes (a
stray attribute means a value broke out of its quotes), og:title and twitter:title are present
and equal, and the JSON-LD block is valid JSON with a @type.
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path

ALLOWED = {
    "meta": {"name", "property", "content", "charset", "http-equiv"},
    "link": {"rel", "href", "type", "sizes", "hreflang", "title", "crossorigin", "as",
             "media"},
}  # fmt: skip


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self._in_ld = False
        self._in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._in_head = True
        if not self._in_head:
            return
        if tag in ALLOWED:
            extra = {k for k, _ in attrs} - ALLOWED[tag]
            if extra:
                self.errors.append(f"<{tag}> has unexpected attributes {sorted(extra)}: {attrs}")
            d = dict(attrs)
            key = d.get("property") or d.get("name")
            if tag == "meta" and key:
                self.meta[key] = d.get("content") or ""
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._in_ld = True
            self.jsonld.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        if tag == "script":
            self._in_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_ld:
            self.jsonld[-1] += data


def check_page(html: str) -> list[str]:
    p = _Head()
    p.feed(html)
    errors = list(p.errors)
    for key in ("og:title", "og:description", "og:url", "og:image", "twitter:title"):
        if not p.meta.get(key):
            errors.append(f"missing {key}")
    if p.meta.get("og:title") != p.meta.get("twitter:title"):
        errors.append(f"og:title {p.meta.get('og:title')!r} != twitter:title")
    if not p.jsonld:
        errors.append("missing JSON-LD")
    for block in p.jsonld:
        try:
            if "@type" not in json.loads(block):
                errors.append("JSON-LD without @type")
        except ValueError as exc:
            errors.append(f"invalid JSON-LD: {exc}")
    return errors


def main(site: str) -> int:
    pages = sorted(Path(site).rglob("index.html"))
    failed = 0
    for page in pages:
        for e in check_page(page.read_text(encoding="utf-8")):
            failed += 1
            print(f"FAIL {page.relative_to(site)}: {e}")
    print(f"checked {len(pages)} pages, {failed} problem(s)")
    return 1 if failed or not pages else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
