"""tools/check_site_meta.py catches metadata that breaks out of its HTML attribute."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_site_meta", Path(__file__).parents[2] / "tools" / "check_site_meta.py"
)
assert _spec and _spec.loader
meta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(meta)

LD = json.dumps({"@context": "https://schema.org", "@type": "TechArticle"})


def page(title_attr: str) -> str:
    return (
        "<html><head>"
        f'<meta property="og:title" content="{title_attr}">'
        f'<meta name="twitter:title" content="{title_attr}">'
        '<meta property="og:description" content="Quotes &quot;and&quot; &amp; ampersands">'
        '<meta property="og:url" content="https://example.test/">'
        '<meta property="og:image" content="https://example.test/i.png">'
        f'<script type="application/ld+json">{LD}</script>'
        "</head><body></body></html>"
    )


def test_escaped_quotes_and_ampersands_pass() -> None:
    assert meta.check_page(page("ADR-0001: Name the project &quot;ecsodus&quot; &amp; more")) == []


def test_unescaped_quote_is_caught() -> None:
    errors = meta.check_page(page('ADR-0001: Name the project "ecsodus" - site'))
    assert any("unexpected attributes" in e for e in errors)


def test_invalid_json_ld_is_caught() -> None:
    html = page("ok").replace(LD, "{not json")
    assert any("invalid JSON-LD" in e for e in meta.check_page(html))
