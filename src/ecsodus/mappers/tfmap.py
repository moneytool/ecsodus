"""CloudFormation resource -> Terraform resource mapping (PLAN §2.4, ADR-0006).

Each mapper turns one deployed CloudFormation resource into a flat root-module ``aws_*`` block
plus its import ID, using literal values resolved from the deployed template, the stack
parameters and live reads. A mapper that cannot produce an exact argument raises
:class:`Unresolvable`; the resource becomes ``blocked`` with that reason.

Mappers live in family modules (``tf_network``, ``tf_compute``, ``tf_data``, ``tf_iam_dns``)
and register themselves with :func:`mapper`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ecsodus.emit.hcl import Body
from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.model import Inventory, Resource, Stack

# Fates that do not produce Terraform (PLAN §2.2).
MANUAL_CLEANUP = "manual-cleanup"
EXTERNAL_REFERENCE = "external-reference"
BLOCKED = "blocked"
NESTED_WRAPPER = "nested-wrapper"  # AWS::CloudFormation::Stack; its child stack is inventoried

_MISSING = object()


@dataclass
class TfSpec:
    """A resource ecsodus will import."""

    tf_type: str
    import_id: str
    body: Body
    stateful: bool = False
    fidelity: str = "full"  # "full" or "partial" (arguments ecsodus could not cover)
    notes: list[str] = field(default_factory=list)
    # Further Terraform resources the same CloudFormation resource deploys (an Events rule's
    # targets): (address suffix, spec). Each is imported alongside the main resource.
    companions: list[tuple[str, TfSpec]] = field(default_factory=list)


@dataclass
class NotImported:
    fate: str
    reason: str


MapResult = TfSpec | NotImported
Mapper = Callable[["Ctx"], MapResult]

MAPPERS: dict[str, Mapper] = {}


def mapper(*cfn_types: str) -> Callable[[Mapper], Mapper]:
    def register(fn: Mapper) -> Mapper:
        for t in cfn_types:
            if t in MAPPERS:
                raise RuntimeError(f"duplicate mapper for {t}")
            MAPPERS[t] = fn
        return fn

    return register


@dataclass
class Ctx:
    inv: Inventory
    stack: Stack
    resolver: Resolver
    resource: Resource
    template_body: dict[str, Any]  # the resource's template body (Type, Properties, ...)

    @property
    def props(self) -> dict[str, Any]:
        return self.template_body.get("Properties") or {}

    @property
    def pid(self) -> str:
        if not self.resource.physical_id:
            raise Unresolvable("resource has no physical id")
        return self.resource.physical_id

    @property
    def live(self) -> dict[str, Any]:
        return self.inv.live.get(self.resource.physical_id or "", {})

    def has(self, key: str) -> bool:
        return key in self.props

    def r(self, key: str, default: Any = _MISSING) -> Any:
        """Resolved property ``key``; ``default`` if absent (Unresolvable if no default)."""
        if key not in self.props:
            if default is _MISSING:
                raise Unresolvable(f"property {key} missing")
            return default
        return self.resolver.resolve(self.props[key])

    def tags(self, key: str = "Tags") -> dict[str, str]:
        """The resource's tags as a map, without ``aws:`` tags (the provider ignores them).

        CloudFormation copies stack-level tags onto every taggable resource, so template tags
        alone would show a diff on import. Live tags win when the live read carries them
        (exact); otherwise stack tags are merged under the template's own tags.
        """
        live_tags = _live_tags(self.live)
        if live_tags is not None:
            return {k: v for k, v in live_tags.items() if not k.startswith("aws:")}
        raw = self.r(key, [])
        items = raw.items() if isinstance(raw, dict) else ((t["Key"], t["Value"]) for t in raw)
        merged = {k: v for k, v in self.stack.tags.items() if not k.startswith("aws:")}
        merged.update({str(k): str(v) for k, v in items if not str(k).startswith("aws:")})
        return merged


def _live_tags(live: dict[str, Any]) -> dict[str, str] | None:
    for field_name in ("Tags", "tags", "TagList", "TagSet"):
        raw = live.get(field_name)
        if raw is None:
            continue
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if isinstance(raw, list):
            out: dict[str, str] = {}
            for t in raw:
                if isinstance(t, dict):
                    k = t.get("Key", t.get("key"))
                    v = t.get("Value", t.get("value"))
                    if k is not None:
                        out[str(k)] = str(v if v is not None else "")
            return out
    return None


def tf_name(stack: Stack, logical_id: str) -> str:
    """A stable Terraform resource name: <scope>_<logical id> in snake case."""
    scope = stack.workload or stack.env or stack.kind
    if stack.kind in ("addons", "env-addons"):
        scope = f"{scope}_addons"
    raw = f"{scope}_{logical_id}"
    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", raw)
    snake = re.sub(r"[^A-Za-z0-9_]", "_", snake).lower()
    return re.sub(r"_+", "_", snake).strip("_")


def map_resource(
    inv: Inventory, stack: Stack, resolver: Resolver, res: Resource, body: dict[str, Any]
) -> MapResult:
    rtype = res.type
    if rtype.startswith("Custom::") or rtype == "AWS::CloudFormation::CustomResource":
        return NotImported(MANUAL_CLEANUP, "custom-resource handle: retained, then cleaned up")
    if rtype == "AWS::CloudFormation::Stack":
        return NotImported(NESTED_WRAPPER, "nested stack wrapper; its child stack is inventoried")
    fn = MAPPERS.get(rtype)
    if fn is None:
        return NotImported(BLOCKED, f"no Terraform mapping for {rtype} in v0.1")
    try:
        return fn(Ctx(inv, stack, resolver, res, body))
    except Unresolvable as exc:
        return NotImported(BLOCKED, f"cannot resolve exactly: {exc}")


def load_family_modules() -> None:
    """Import the family modules so their mappers register."""
    from ecsodus.mappers import tf_compute, tf_data, tf_iam_dns, tf_network  # noqa: F401
