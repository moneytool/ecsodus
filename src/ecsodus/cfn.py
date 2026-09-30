"""CloudFormation template parsing.

Two views of a template are needed:

* a *semantic* view (plain dicts, short-form tags such as ``!Ref`` normalised to the long form
  ``{"Ref": ...}``), used for analysis and for verifying patches; and
* *source positions* of each resource, used by the retain patcher to edit the original text
  without re-serialising it (re-serialising YAML changes indentation and quoting, which would
  break the "byte-stable apart from the patch" rule).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import SafeConstructor
from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode

_SHORT_TAGS = {
    "Ref": "Ref",
    "Condition": "Condition",
    "GetAtt": "Fn::GetAtt",
}


class TemplateError(ValueError):
    """The template cannot be parsed or has a shape ecsodus refuses to handle."""


def _construct_tagged(loader: Any, tag_suffix: str, node: Any) -> dict[str, Any]:
    name = _SHORT_TAGS.get(tag_suffix, f"Fn::{tag_suffix}")
    if isinstance(node, ScalarNode):
        value: Any = loader.construct_scalar(node)
        if tag_suffix == "GetAtt" and isinstance(value, str):
            head, _, tail = value.partition(".")
            value = [head, tail]
    elif isinstance(node, SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:  # pragma: no cover - ruamel only produces the three node kinds
        raise TemplateError(f"unsupported node for !{tag_suffix}")
    return {name: _plain(value)}


def _plain(value: Any) -> Any:
    """Convert ruamel containers to plain dict/list recursively."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class _CfnConstructor(SafeConstructor):
    """The semantic view's constructor.

    ruamel registers constructors on the *class*. Registering on the shared SafeConstructor
    leaked the ``!`` multi-constructor into the round-trip loader that :func:`yaml_positions`
    uses, so after any :func:`load` a tagged mapping (``!GetAZs {Ref: AWS::Region}``) broke
    retain patching. A private subclass keeps both registrations to this view.
    """


_CfnConstructor.add_multi_constructor("!", _construct_tagged)
# CloudFormation treats unquoted dates as strings (AWSTemplateFormatVersion: 2010-09-09).
_CfnConstructor.add_constructor("tag:yaml.org,2002:timestamp", SafeConstructor.construct_yaml_str)


def _semantic_yaml() -> YAML:
    y = YAML(typ="safe", pure=True)
    y.Constructor = _CfnConstructor
    return y


def is_json(text: str) -> bool:
    return text.lstrip().startswith("{")


def load(text: str) -> dict[str, Any]:
    """Parse a template (JSON or YAML) into plain dicts with long-form intrinsics."""
    try:
        data = json.loads(text) if is_json(text) else _semantic_yaml().load(io.StringIO(text))
    except Exception as exc:  # noqa: BLE001 - surface any parser error uniformly
        raise TemplateError(f"cannot parse template: {exc}") from exc
    data = _plain(data)
    if not isinstance(data, dict) or not isinstance(data.get("Resources"), dict):
        raise TemplateError("template has no Resources mapping")
    return data


@dataclass(frozen=True)
class ResourcePosition:
    """Where one resource's mapping sits in the template source (0-based lines)."""

    logical_id: str
    key_line: int  # the "LogicalId:" line
    body_line: int  # first line of the resource body
    body_col: int  # indentation of the resource body keys
    keys: dict[str, tuple[int, int]]  # attribute key -> (line, col)
    flow_style: bool
    template_url: tuple[int, int] | None = None  # Properties.TemplateURL key (line, col)
    metadata: tuple[int, int, bool] | None = None  # Metadata body (line, col, is_block_map)


def yaml_positions(text: str) -> dict[str, ResourcePosition]:
    """Source positions of every resource in a block-style YAML template."""
    y = YAML(typ="rt", pure=True)
    try:
        doc = y.load(io.StringIO(text))
    except Exception as exc:  # noqa: BLE001
        raise TemplateError(f"cannot parse template: {exc}") from exc
    resources = doc.get("Resources") if hasattr(doc, "get") else None
    if resources is None:
        raise TemplateError("template has no Resources mapping")
    out: dict[str, ResourcePosition] = {}
    for lid, body in resources.items():
        key_line, _ = resources.lc.key(lid)
        if not hasattr(body, "lc"):
            raise TemplateError(f"resource {lid} is not a mapping")
        flow = body.fa.flow_style() if hasattr(body, "fa") else False
        keys = {str(k): tuple(body.lc.key(k)) for k in body}
        template_url = None
        props = body.get("Properties")
        if hasattr(props, "lc") and "TemplateURL" in props:
            template_url = tuple(props.lc.key("TemplateURL"))
        metadata = None
        meta = body.get("Metadata")
        if meta is not None:
            is_block = hasattr(meta, "lc") and not (hasattr(meta, "fa") and meta.fa.flow_style())
            if is_block and len(meta):
                metadata = (meta.lc.line, meta.lc.col, True)
            else:
                metadata = (*keys["Metadata"], False)
        out[str(lid)] = ResourcePosition(
            logical_id=str(lid),
            key_line=key_line,
            body_line=body.lc.line,
            body_col=body.lc.col,
            keys=keys,  # type: ignore[arg-type]
            flow_style=bool(flow),
            template_url=template_url,  # type: ignore[arg-type]
            metadata=metadata,  # type: ignore[arg-type]
        )
    return out


def resources(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return template.get("Resources", {})


def references(value: Any) -> set[str]:
    """Logical IDs referenced by Ref / GetAtt / Sub / DependsOn inside ``value``."""
    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, inner in v.items():
                if k == "Ref" and isinstance(inner, str):
                    found.add(inner)
                elif k == "Fn::GetAtt":
                    if isinstance(inner, list) and inner and isinstance(inner[0], str):
                        found.add(inner[0])
                    elif isinstance(inner, str):
                        found.add(inner.split(".", 1)[0])
                elif k == "Fn::Sub":
                    tpl = inner[0] if isinstance(inner, list) else inner
                    if isinstance(tpl, str):
                        found.update(_sub_vars(tpl))
                    walk(inner)
                    continue
                walk(inner)
        elif isinstance(v, list):
            for inner in v:
                walk(inner)

    walk(value)
    return found


def _sub_vars(template: str) -> set[str]:
    out: set[str] = set()
    i = 0
    while True:
        start = template.find("${", i)
        if start < 0:
            return out
        end = template.find("}", start)
        if end < 0:
            return out
        name = template[start + 2 : end]
        if not name.startswith("!"):
            out.add(name.split(".", 1)[0])
        i = end + 1
