"""A small, deterministic HCL writer for generated Terraform.

Bodies are ordered lists of ``(name, value)``. A value is a Python scalar/list/dict (an HCL
attribute), a :class:`Block` (a nested block, repeated for lists of blocks), or :class:`Raw`
(an HCL expression written verbatim).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

Body = list[tuple[str, Any]]


@dataclass
class Block:
    body: Body = field(default_factory=list)
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Raw:
    expr: str


def _ident_ok(key: str) -> bool:
    return key.replace("_", "a").replace("-", "a").isalnum() and not key[0].isdigit()


def value(v: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(v, Raw):
        return v.expr
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        s = json.dumps(v, ensure_ascii=False)
        return s.replace("${", "$${").replace("%{", "%%{")
    if isinstance(v, list):
        if not v:
            return "[]"
        inner = ",\n".join(f"{pad}  {value(x, indent + 1)}" for x in v)
        return f"[\n{inner},\n{pad}]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        lines = []
        for k, x in v.items():
            key = k if _ident_ok(k) else json.dumps(k).replace("${", "$${").replace("%{", "%%{")
            lines.append(f"{pad}  {key} = {value(x, indent + 1)}")
        return "{\n" + "\n".join(lines) + f"\n{pad}}}"
    raise TypeError(f"cannot render {type(v).__name__} as HCL")


def body(items: Body, indent: int = 0) -> str:
    pad = "  " * indent
    out: list[str] = []
    width = max((len(k) for k, v in items if not isinstance(v, Block)), default=0)
    for k, v in items:
        if isinstance(v, Block):
            labels = "".join(f" {json.dumps(label)}" for label in v.labels)
            out.append(f"{pad}{k}{labels} {{")
            inner = body(v.body, indent + 1)
            if inner:
                out.append(inner)
            out.append(f"{pad}}}")
        else:
            out.append(f"{pad}{k.ljust(width)} = {value(v, indent)}")
    return "\n".join(out)


def block(kind: str, labels: tuple[str, ...], items: Body) -> str:
    return body([(kind, Block(items, labels))])
