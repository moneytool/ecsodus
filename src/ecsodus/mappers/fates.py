"""Fates, stack hand-off, blocker propagation, closure and teardown order (PLAN §2.2, §2.5).

Hand-off is decided per *stack*, atomically: a stack is either handed off completely (every
resource imported into Terraform or explicitly left for manual cleanup / external reference)
or kept completely (every resource ``retain-under-existing-owner``). A stack is never split
between CloudFormation and Terraform, so no resource ever has two live owners.

Propagation (to a fixpoint):

* a workload stack is kept if its workload is not migrating, its type is unsupported, or any
  resource in it or its nested addons is ``blocked``;
* an env stack is kept if any workload stack in that env is kept, or it (or its env addons)
  has a blocked resource;
* the app stack and StackSet instances are kept if any env is kept or they hold a blocked
  resource.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ecsodus import cfn
from ecsodus.mappers import tfmap
from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.model import (
    ADDONS,
    APP,
    ENV,
    ENV_ADDONS,
    STACKSET_INSTANCE,
    SUPPORTED_WORKLOAD_TYPES,
    WORKLOAD,
    Inventory,
    Stack,
)

IMPORT = "import"
RETAIN_UNDER_EXISTING_OWNER = "retain-under-existing-owner"
MANUAL_CLEANUP = tfmap.MANUAL_CLEANUP
EXTERNAL_REFERENCE = tfmap.EXTERNAL_REFERENCE
BLOCKED = tfmap.BLOCKED
NESTED_WRAPPER = tfmap.NESTED_WRAPPER
CONDITION_OFF = "not-created"  # resource whose Condition is false in this deployment

HANDOFF_OK_FATES = {IMPORT, MANUAL_CLEANUP, EXTERNAL_REFERENCE, NESTED_WRAPPER, CONDITION_OFF}


@dataclass
class ResourcePlan:
    stack: str
    logical_id: str
    type: str
    physical_id: str | None
    fate: str
    reason: str = ""
    tf_address: str | None = None
    spec: tfmap.TfSpec | None = None


@dataclass
class StackPlan:
    name: str
    kind: str
    handoff: bool = True
    kept_because: list[str] = field(default_factory=list)
    unpatched_side_effects: list[str] = field(default_factory=list)


@dataclass
class ExpressFit:
    eligible: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class MigrationPlan:
    inventory: Inventory
    resources: list[ResourcePlan] = field(default_factory=list)
    stacks: dict[str, StackPlan] = field(default_factory=dict)
    closure_errors: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)  # stack names, in deletion order
    teardown_stops_at: str | None = None
    express: dict[str, ExpressFit] = field(default_factory=dict)
    workload_status: dict[str, str] = field(default_factory=dict)  # "env/name" -> status

    def by_stack(self, name: str) -> list[ResourcePlan]:
        return [r for r in self.resources if r.stack == name]

    def imports(self) -> list[ResourcePlan]:
        return [r for r in self.resources if r.fate == IMPORT]

    def fate_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.resources:
            counts[r.fate] = counts.get(r.fate, 0) + 1
        return counts


# ------------------------------------------------------------------------------------------
def build_plan(inv: Inventory) -> MigrationPlan:
    tfmap.load_family_modules()
    plan = MigrationPlan(inventory=inv)
    mapped: dict[str, list[ResourcePlan]] = {}
    resolvers: dict[str, Resolver] = {}
    templates: dict[str, dict[str, Any]] = {}

    for stack in inv.stacks.values():
        plan.stacks[stack.name] = StackPlan(stack.name, stack.kind)
        try:
            templates[stack.name] = cfn.load(stack.template_body)
        except cfn.TemplateError as exc:
            plan.stacks[stack.name].handoff = False
            plan.stacks[stack.name].kept_because.append(f"template unreadable: {exc}")
            mapped[stack.name] = [
                ResourcePlan(stack.name, r.logical_id, r.type, r.physical_id, BLOCKED, str(exc))
                for r in stack.resources
            ]
            continue
        resolvers[stack.name] = Resolver(inv, stack, templates[stack.name])
        mapped[stack.name] = _map_stack(inv, stack, resolvers[stack.name], templates[stack.name])

    _seed_kept(inv, plan, mapped)
    _propagate(inv, plan)

    for stack in inv.stacks.values():
        handoff = plan.stacks[stack.name].handoff
        for rp in mapped[stack.name]:
            if not handoff and rp.fate in (IMPORT, BLOCKED):
                rp.reason = (
                    f"stack kept ({'; '.join(plan.stacks[stack.name].kept_because)})"
                    + (f"; would be: {rp.fate}" if rp.fate != IMPORT else "")
                )
                rp.fate = RETAIN_UNDER_EXISTING_OWNER
                rp.spec = None
                rp.tf_address = None
            plan.resources.append(rp)

    _closure(plan)
    _teardown(inv, plan)
    for stack in inv.stacks.values():
        if stack.name in templates:
            plan.stacks[stack.name].unpatched_side_effects = _side_effects(
                stack, templates[stack.name], resolvers[stack.name]
            )
    for s in inv.stacks_of(WORKLOAD):
        if s.name in templates:
            plan.express[f"{s.env}/{s.workload}"] = _express_fit(inv, s, templates[s.name])
    return plan


def _map_stack(
    inv: Inventory, stack: Stack, resolver: Resolver, template: dict[str, Any]
) -> list[ResourcePlan]:
    out: list[ResourcePlan] = []
    bodies = template.get("Resources") or {}
    names: set[str] = set()
    for res in stack.resources:
        body = bodies.get(res.logical_id) or {}
        try:
            exists = resolver.resource_exists(res.logical_id)
        except Unresolvable as exc:
            out.append(
                ResourcePlan(stack.name, res.logical_id, res.type, res.physical_id, BLOCKED,
                             f"condition unresolved: {exc}")
            )
            continue
        if not exists or not res.physical_id:
            out.append(
                ResourcePlan(stack.name, res.logical_id, res.type, res.physical_id, CONDITION_OFF,
                             "not created in this deployment")
            )
            continue
        result = tfmap.map_resource(inv, stack, resolver, res, body)
        if isinstance(result, tfmap.TfSpec):
            name = tfmap.tf_name(stack, res.logical_id)
            while name in names:
                name += "_x"
            names.add(name)
            out.append(
                ResourcePlan(stack.name, res.logical_id, res.type, res.physical_id, IMPORT,
                             "" if result.fidelity == "full" else "partial argument coverage",
                             f"{result.tf_type}.{name}", result)
            )
        else:
            out.append(
                ResourcePlan(stack.name, res.logical_id, res.type, res.physical_id, result.fate,
                             result.reason)
            )
    # Stack resources CloudFormation reports but the template no longer lists are suspicious.
    for lid in bodies:
        if stack.resource(lid) is None and resolver.resource_exists(lid):
            out.append(
                ResourcePlan(stack.name, lid, bodies[lid].get("Type", "?"), None, BLOCKED,
                             "in template but not in DescribeStackResources")
            )
    return out


def _seed_kept(inv: Inventory, plan: MigrationPlan, mapped: dict[str, list[ResourcePlan]]) -> None:
    for stack in inv.stacks.values():
        sp = plan.stacks[stack.name]
        blocked = [r for r in mapped[stack.name] if r.fate == BLOCKED]
        if blocked:
            sp.handoff = False
            sp.kept_because.append(
                f"{len(blocked)} blocked resource(s), e.g. {blocked[0].logical_id}: "
                f"{blocked[0].reason}"
            )
        if stack.kind == WORKLOAD:
            wl = inv.workload(stack.workload or "", stack.env or "")
            key = f"{stack.env}/{stack.workload}"
            if stack.workload_type not in SUPPORTED_WORKLOAD_TYPES:
                sp.handoff = False
                sp.kept_because.append(f"workload type {stack.workload_type!r} blocked in v0.1")
                plan.workload_status[key] = f"blocked: type {stack.workload_type}"
            elif wl is not None and not wl.migrate:
                sp.handoff = False
                sp.kept_because.append("workload not selected for migration")
                plan.workload_status[key] = "not migrating (stays on Copilot)"
        if stack.status and not stack.status.endswith("_COMPLETE"):
            sp.handoff = False
            sp.kept_because.append(f"stack status {stack.status} is not *_COMPLETE")


def _propagate(inv: Inventory, plan: MigrationPlan) -> None:
    changed = True
    while changed:
        changed = False

        def keep(name: str, why: str) -> None:
            nonlocal changed
            sp = plan.stacks[name]
            if sp.handoff:
                sp.handoff = False
                sp.kept_because.append(why)
                changed = True

        for s in inv.stacks.values():
            if s.kind in (ADDONS, ENV_ADDONS) and s.parent in plan.stacks:
                if not plan.stacks[s.name].handoff:
                    keep(s.parent, f"nested stack {s.name} is kept")
                elif not plan.stacks[s.parent].handoff:
                    keep(s.name, f"parent stack {s.parent} is kept")
        for s in inv.stacks_of(WORKLOAD):
            if not plan.stacks[s.name].handoff:
                for env_stack in inv.stacks_of(ENV):
                    if env_stack.env == s.env:
                        keep(env_stack.name, f"workload stack {s.name} is kept")
        any_env_kept = any(not plan.stacks[e.name].handoff for e in inv.stacks_of(ENV))
        app_layer = inv.stacks_of(APP) + inv.stacks_of(STACKSET_INSTANCE)
        if any_env_kept:
            for s in app_layer:
                keep(s.name, "an environment of the app is kept")
        if any(not plan.stacks[s.name].handoff for s in app_layer):
            for s in app_layer:
                keep(s.name, "the app layer is handed off together")

    for s in inv.stacks_of(WORKLOAD):
        key = f"{s.env}/{s.workload}"
        if key not in plan.workload_status:
            plan.workload_status[key] = (
                "migrating" if plan.stacks[s.name].handoff
                else "kept: " + "; ".join(plan.stacks[s.name].kept_because)
            )


def _closure(plan: MigrationPlan) -> None:
    """An imported resource must not depend on anything that manual cleanup will delete."""
    cleanup = [r for r in plan.resources if r.fate == MANUAL_CLEANUP and r.physical_id]
    cleanup_by_stack: dict[str, set[str]] = {}
    for r in cleanup:
        cleanup_by_stack.setdefault(r.stack, set()).add(r.logical_id)
    inv = plan.inventory
    for rp in plan.imports():
        stack = inv.stacks[rp.stack]
        body = (cfn.load(stack.template_body)["Resources"].get(rp.logical_id) or {})
        refs = cfn.references(body.get("Properties") or {})
        for lid in refs & cleanup_by_stack.get(rp.stack, set()):
            target = stack.resource(lid)
            # Reading a custom resource's output is a captured value, not a live dependency.
            if target is not None and target.type.startswith("Custom::"):
                continue
            plan.closure_errors.append(
                f"{rp.tf_address} references {rp.stack}/{lid}, which is manual-cleanup"
            )
        rendered = repr(rp.spec.body) if rp.spec else ""
        for r in cleanup:
            if r.type.startswith("Custom::") or not r.physical_id or len(r.physical_id) < 8:
                continue
            if r.physical_id in rendered:
                plan.closure_errors.append(
                    f"{rp.tf_address} embeds the id of {r.stack}/{r.logical_id} "
                    f"({r.type}), which is manual-cleanup"
                )


def _teardown(inv: Inventory, plan: MigrationPlan) -> None:
    order: list[Stack] = []
    order += sorted(inv.stacks_of(WORKLOAD), key=lambda s: s.name)
    order += sorted(inv.stacks_of(ADDONS), key=lambda s: s.name)
    order += sorted(inv.stacks_of(ENV), key=lambda s: s.name)
    order += sorted(inv.stacks_of(ENV_ADDONS), key=lambda s: s.name)
    order += sorted(inv.stacks_of(STACKSET_INSTANCE), key=lambda s: s.name)
    order += sorted(inv.stacks_of(APP), key=lambda s: s.name)
    for s in order:
        if plan.stacks[s.name].handoff:
            plan.teardown.append(s.name)
        elif s.kind in (ENV, STACKSET_INSTANCE, APP) and plan.teardown_stops_at is None:
            plan.teardown_stops_at = s.name
    if plan.teardown_stops_at:
        # Nothing at or after the first kept shared stack may be deleted.
        idx = [s.name for s in order].index(plan.teardown_stops_at)
        later = {s.name for s in order[idx:]}
        plan.teardown = [n for n in plan.teardown if n not in later]


def _side_effects(stack: Stack, template: dict[str, Any], resolver: Resolver) -> list[str]:
    """What deleting this stack *without* the retain patch would destroy (for the report)."""
    from ecsodus import knowledge

    out: list[str] = []
    for lid, body in (template.get("Resources") or {}).items():
        try:
            if not resolver.resource_exists(lid):
                continue
        except Unresolvable:
            pass
        rtype = body.get("Type", "")
        policy = body.get("DeletionPolicy", "Delete")
        if rtype.startswith("Custom::"):
            info = knowledge.CUSTOM_RESOURCES.get(rtype)
            if info and info.get("destructive"):
                out.append(f"{lid} ({rtype}): Delete handler {info.get('delete_behaviour', '')}")
            continue
        if policy not in ("Retain", "RetainExceptOnCreate"):
            label = "snapshot then delete" if policy == "Snapshot" else "delete"
            out.append(f"{lid} ({rtype}): {label}")
    return out


def _express_fit(inv: Inventory, stack: Stack, template: dict[str, Any]) -> ExpressFit:
    """The Express Mode predicate (PLAN §2.3); informational in v0.1."""
    reasons: list[str] = []
    res = template.get("Resources") or {}
    tds = [b for b in res.values() if b.get("Type") == "AWS::ECS::TaskDefinition"]
    if stack.workload_type != "Load Balanced Web Service":
        reasons.append("not a Load Balanced Web Service")
    if tds:
        props = tds[0].get("Properties") or {}
        if len(props.get("ContainerDefinitions") or []) != 1:
            reasons.append("more than one container (sidecars)")
        if props.get("Volumes"):
            reasons.append("uses volumes")
        try:
            cpu = int(str(Resolver(inv, stack, template).resolve(props.get("Cpu", "0"))))
            mem = int(str(Resolver(inv, stack, template).resolve(props.get("Memory", "0"))))
            if not 256 <= cpu <= 4096 or not 512 <= mem <= 8192:
                reasons.append(f"cpu {cpu}/memory {mem} outside 256-4096/512-8192")
        except (Unresolvable, ValueError):
            reasons.append("cpu/memory not resolvable")
    types = {b.get("Type") for b in res.values()}
    if any(
        b.get("Type") == "AWS::ElasticLoadBalancingV2::LoadBalancer"
        and (b.get("Properties") or {}).get("Type") == "network"
        for b in res.values()
    ) or "AWS::ElasticLoadBalancingV2::LoadBalancer" in types and "NLB" in stack.template_body:
        reasons.append("uses a Network Load Balancer")
    if "ServiceConnectConfiguration" in stack.template_body:
        reasons.append("uses Service Connect")
    return ExpressFit(eligible=not reasons, reasons=reasons)
