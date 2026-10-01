"""The MkDocs list hook renders GitHub-style lists (docs_hooks/lists.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "lists", Path(__file__).parents[2] / "docs_hooks" / "lists.py"
)
assert _spec and _spec.loader
lists = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lists)


def test_blank_line_inserted_before_a_list_after_a_paragraph() -> None:
    assert lists.normalise("The report covers:\n- a\n- b") == "The report covers:\n\n- a\n- b"


def test_two_space_nesting_becomes_four() -> None:
    assert lists.normalise("- a\n  - b\n    - c") == "- a\n    - b\n        - c"


def test_sub_list_after_item_text_gets_a_blank_line() -> None:
    src = "1. Step\n\n   Details:\n   - x"
    assert lists.normalise(src) == "1. Step\n\n      Details:\n\n      - x"


def test_fenced_code_is_untouched() -> None:
    src = "Run:\n```bash\n- not a list\n  indented\n```"
    assert lists.normalise(src) == src


def test_list_context_ends_at_a_new_paragraph() -> None:
    assert lists.normalise("- a\n\nText\n  not a list") == "- a\n\nText\n  not a list"
