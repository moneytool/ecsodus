"""Retain patches (PLAN §2.4).

For every stack ecsodus emits the *deployed* template with ``DeletionPolicy: Retain`` and
``UpdateReplacePolicy: Retain`` on every resource, with no exceptions. Nothing else may change,
except two carve-outs:

* a nested stack's ``TemplateURL`` may point at the patched child template; and
* the ``Metadata`` fallback (an ``ecsodus:retain`` key per resource) used only if CloudFormation
  treats a policy-only change set as a no-op (cloudformation-coverage-roadmap #1543).

YAML is patched by editing lines of the original text, so every untouched byte stays identical.
:func:`verify_patch` proves the semantic invariant independently of how the patch was made.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ecsodus import cfn

POLICY_ATTRIBUTES = ("DeletionPolicy", "UpdateReplacePolicy")
METADATA_KEY = "ecsodus:retain"
NESTED_STACK_TYPE = "AWS::CloudFormation::Stack"


@dataclass
class PatchResult:
    text: str
    sha256: str
    changed_resources: list[str] = field(default_factory=list)
    template_url_overrides: dict[str, str] = field(default_factory=dict)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_template(
    text: str,
    template_url_overrides: Mapping[str, str] | None = None,
    metadata_fallback: bool = False,
) -> PatchResult:
    """Return the retain-patched template text.

    ``template_url_overrides`` maps nested-stack logical IDs to the S3 URL of their patched
    child template. Raises :class:`cfn.TemplateError` for shapes ecsodus refuses to edit.
    """
    overrides = dict(template_url_overrides or {})
    template = cfn.load(text)
    res = cfn.resources(template)
    for lid in overrides:
        if lid not in res:
            raise cfn.TemplateError(f"TemplateURL override for unknown resource {lid}")
        if res[lid].get("Type") != NESTED_STACK_TYPE:
            raise cfn.TemplateError(f"TemplateURL override on non-stack resource {lid}")
    patched = (
        _patch_json(text, overrides, metadata_fallback)
        if cfn.is_json(text)
        else _patch_yaml(text, overrides, metadata_fallback)
    )
    changed = sorted(
        lid
        for lid, body in res.items()
        if any(body.get(a) != "Retain" for a in POLICY_ATTRIBUTES) or lid in overrides
    )
    result = PatchResult(
        text=patched,
        sha256=sha256(patched),
        changed_resources=changed,
        template_url_overrides=overrides,
    )
    problems = verify_patch(text, patched, overrides, metadata_fallback)
    if problems:  # a patcher bug must never produce output
        raise cfn.TemplateError("retain patch failed verification: " + "; ".join(problems))
    return result


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _patch_yaml(text: str, overrides: Mapping[str, str], metadata_fallback: bool) -> str:
    nl = _newline(text)
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += nl
    positions = cfn.yaml_positions(text)
    # (line index, sort key, kind, payload); applied bottom-up so indices stay valid.
    edits: list[tuple[int, int, str, Any]] = []
    for lid, pos in positions.items():
        if pos.flow_style:
            raise cfn.TemplateError(f"resource {lid} uses flow style; refusing to patch")
        if pos.body_line <= pos.key_line:
            raise cfn.TemplateError(f"resource {lid} body starts on its key line")
        indent = " " * pos.body_col
        for order, attr in enumerate(POLICY_ATTRIBUTES):
            if attr in pos.keys:
                line, col = pos.keys[attr]
                edits.append((line, 0, "replace", (col, f"{attr}: Retain")))
            else:
                edits.append((pos.body_line, order, "insert", f"{indent}{attr}: Retain"))
        if lid in overrides:
            if pos.template_url is None:
                raise cfn.TemplateError(f"nested stack {lid} has no TemplateURL to override")
            line, col = pos.template_url
            edits.append((line, 0, "replace", (col, f"TemplateURL: {json.dumps(overrides[lid])}")))
        if metadata_fallback:
            if pos.metadata is None:
                child = " " * (pos.body_col + 2)
                edits.append((pos.body_line, 9, "insert", f"{indent}Metadata:"))
                edits.append((pos.body_line, 10, "insert", f"{child}'{METADATA_KEY}': 'true'"))
            elif pos.metadata[2]:
                mline, mcol, _ = pos.metadata
                edits.append((mline, 9, "insert", f"{' ' * mcol}'{METADATA_KEY}': 'true'"))
            else:
                raise cfn.TemplateError(f"resource {lid} has non-block Metadata; refusing")

    # One bottom-up pass: an edit never shifts the lines of edits above it. At the same line the
    # replace runs first, then inserts (highest order first, so they end up in ascending order).
    for line, _, kind, payload in sorted(edits, key=lambda e: (-e[0], e[2] != "replace", -e[1])):
        if kind == "replace":
            col, new = payload
            end = line + 1
            while end < len(lines) and _is_continuation(lines[end], col):
                end += 1
            lines[line:end] = [" " * col + new + nl]
        else:
            lines.insert(line, payload + nl)
    return "".join(lines)


def _is_continuation(line: str, col: int) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return (len(line) - len(line.lstrip(" "))) > col


def _patch_json(text: str, overrides: Mapping[str, str], metadata_fallback: bool) -> str:
    data = json.loads(text)
    for lid, body in data["Resources"].items():
        for attr in POLICY_ATTRIBUTES:
            body[attr] = "Retain"
        if lid in overrides:
            body.setdefault("Properties", {})["TemplateURL"] = overrides[lid]
        if metadata_fallback:
            body.setdefault("Metadata", {})[METADATA_KEY] = "true"
    indent = _json_indent(text)
    out = json.dumps(data, indent=indent, ensure_ascii=False)
    return out + ("\n" if text.endswith("\n") else "")


def _json_indent(text: str) -> int | None:
    for line in text.splitlines()[1:]:
        if line.strip():
            n = len(line) - len(line.lstrip(" "))
            return n or None
    return None


def _strip(
    template: dict[str, Any], overrides: Mapping[str, str], metadata_fallback: bool
) -> dict[str, Any]:
    t = copy.deepcopy(template)
    for lid, body in t["Resources"].items():
        for attr in POLICY_ATTRIBUTES:
            body.pop(attr, None)
        meta = body.get("Metadata")
        if metadata_fallback and isinstance(meta, dict):
            meta.pop(METADATA_KEY, None)
            if not meta:
                body.pop("Metadata")
        if lid in overrides and isinstance(body.get("Properties"), dict):
            body["Properties"].pop("TemplateURL", None)
    return t


def verify_patch(
    original: str,
    patched: str,
    overrides: Mapping[str, str] | None = None,
    metadata_fallback: bool = False,
) -> list[str]:
    """Problems with ``patched`` relative to ``original``; empty means the invariant holds."""
    overrides = dict(overrides or {})
    problems: list[str] = []
    try:
        before = cfn.load(original)
        after = cfn.load(patched)
    except cfn.TemplateError as exc:
        return [str(exc)]
    if set(before["Resources"]) != set(after["Resources"]):
        problems.append("resource set changed")
        return problems
    for lid, body in after["Resources"].items():
        for attr in POLICY_ATTRIBUTES:
            if body.get(attr) != "Retain":
                problems.append(f"{lid}: {attr} is {body.get(attr)!r}, expected 'Retain'")
        if lid in overrides:
            url = body.get("Properties", {}).get("TemplateURL")
            if url != overrides[lid]:
                problems.append(f"{lid}: TemplateURL is {url!r}, expected {overrides[lid]!r}")
        if metadata_fallback and (body.get("Metadata") or {}).get(METADATA_KEY) != "true":
            problems.append(f"{lid}: missing Metadata {METADATA_KEY}")
    # Canonical JSON keeps scalar types distinct (1, 1.0, true and "1" differ; == would not).
    if _canonical(_strip(before, overrides, metadata_fallback)) != _canonical(
        _strip(after, overrides, metadata_fallback)
    ):
        problems.append("template changed outside the permitted retain-patch edits")
    if not cfn.is_json(original) and _skeleton(original) != _skeleton(patched):
        problems.append("template text changed outside the permitted retain-patch lines")
    return problems


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


_EDIT_KEY = re.compile(r"^(\s*)(DeletionPolicy|UpdateReplacePolicy|TemplateURL)\s*:")
_META_LINE = re.compile(r"^\s*(Metadata:\s*|'ecsodus:retain': 'true'\s*)$")


def _skeleton(text: str) -> list[str]:
    """The template's lines minus every line a retain patch may add, replace or remove.

    Removed: policy and TemplateURL key lines with their continuation lines, and the Metadata
    fallback lines. Everything else must be byte-identical between original and patched.
    """
    out: list[str] = []
    skipping_indent: int | None = None
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if skipping_indent is not None:
            if stripped and not stripped.startswith("#") and indent > skipping_indent:
                continue
            skipping_indent = None
        m = _EDIT_KEY.match(line)
        if m:
            skipping_indent = len(m.group(1))
            continue
        if _META_LINE.match(line):
            continue
        out.append(line)
    # Blank lines at end of file carry no meaning; `aws ... --output text` appends one.
    while out and not out[-1].strip():
        out.pop()
    return out


def missing_retain(text: str) -> list[str]:
    """Logical IDs whose deployed template lacks either Retain policy (for verify-retain)."""
    template = cfn.load(text)
    return sorted(
        lid
        for lid, body in cfn.resources(template).items()
        if any(body.get(a) != "Retain" for a in POLICY_ATTRIBUTES)
    )
