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

import json
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
        transform = _uses_transform(templates[stack.name])
        if transform:
            mapped[stack.name] = [
                ResourcePlan(
                    stack.name,
                    r.logical_id,
                    r.type,
                    r.physical_id,
                    BLOCKED,
                    f"template uses {transform}; blocked in v0.1",
                )
                for r in stack.resources
            ]
            continue
        mapped[stack.name] = _map_stack(inv, stack, resolvers[stack.name], templates[stack.name])
        _classify_lambdas(templates[stack.name], mapped[stack.name])

    _seed_kept(inv, plan, mapped)
    _propagate(inv, plan)

    for stack in inv.stacks.values():
        plan.resources.extend(mapped[stack.name])

    _out_of_band(inv, plan)
    _demote_kept(inv, plan)
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


def _uses_transform(template: dict[str, Any]) -> str | None:
    """Macros change what CloudFormation deploys versus the Original template (SAM, ForEach,
    AWS::Include), so neither the patch nor verify-retain would see the real resources."""
    if template.get("Transform"):
        return f"Transform {template['Transform']}"
    for key in template.get("Resources") or {}:
        if str(key).startswith("Fn::"):
            return str(key).split("::", 2)[0] + "::" + str(key).split("::")[1]
    if "Fn::Transform" in json.dumps(template):
        return "Fn::Transform"
    return None


def _classify_lambdas(template: dict[str, Any], rows: list[ResourcePlan]) -> None:
    """Only custom-resource handlers are Copilot-internal. A Lambda that no ``Custom::``
    resource uses as its ``ServiceToken`` is a user function (addons): blocked in v0.1, never
    sent to manual cleanup."""
    bodies = template.get("Resources") or {}
    handlers: set[str] = set()
    for body in bodies.values():
        if str(body.get("Type", "")).startswith("Custom::") or body.get("Type") == (
            "AWS::CloudFormation::CustomResource"
        ):
            handlers |= cfn.references((body.get("Properties") or {}).get("ServiceToken"))
    for rp in rows:
        if rp.fate != MANUAL_CLEANUP:
            continue
        if rp.type == "AWS::Lambda::Function" and rp.logical_id not in handlers:
            rp.fate = BLOCKED
            rp.reason = "Lambda function is not a custom-resource handler (user function)"
        elif rp.type == "AWS::Lambda::Permission":
            fn = (bodies.get(rp.logical_id) or {}).get("Properties", {}).get("FunctionName")
            if not (cfn.references(fn) & handlers):
                rp.fate = BLOCKED
                rp.reason = "Lambda permission for a function that is not a custom-resource handler"


def _demote_kept(inv: Inventory, plan: MigrationPlan) -> None:
    """Propagate kept status again (out-of-band blockers may add some) and demote every
    import in a kept stack to retain-under-existing-owner: no stack is ever split."""
    _propagate(inv, plan)
    for rp in plan.resources:
        sp = plan.stacks.get(rp.stack)
        if sp is None or sp.handoff or rp.fate not in (IMPORT, BLOCKED):
            continue
        rp.reason = f"stack kept ({'; '.join(sp.kept_because)})" + (
            f"; would be: {rp.fate}: {rp.reason}" if rp.fate != IMPORT else ""
        )
        rp.fate = RETAIN_UNDER_EXISTING_OWNER
        rp.spec = None
        rp.tf_address = None


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
                ResourcePlan(
                    stack.name,
                    res.logical_id,
                    res.type,
                    res.physical_id,
                    BLOCKED,
                    f"condition unresolved: {exc}",
                )
            )
            continue
        if not exists or not res.physical_id:
            out.append(
                ResourcePlan(
                    stack.name,
                    res.logical_id,
                    res.type,
                    res.physical_id,
                    CONDITION_OFF,
                    "not created in this deployment",
                )
            )
            continue
        result = tfmap.map_resource(inv, stack, resolver, res, body)
        if isinstance(result, tfmap.TfSpec):
            name = tfmap.tf_name(stack, res.logical_id)
            while name in names:
                name += "_x"
            names.add(name)
            out.append(
                ResourcePlan(
                    stack.name,
                    res.logical_id,
                    res.type,
                    res.physical_id,
                    IMPORT,
                    "" if result.fidelity == "full" else "partial argument coverage",
                    f"{result.tf_type}.{name}",
                    result,
                )
            )
            for suffix, comp in result.companions:
                cname = tfmap.tf_name(stack, f"{res.logical_id}_{suffix}")
                while cname in names:
                    cname += "_x"
                names.add(cname)
                out.append(
                    ResourcePlan(
                        stack.name,
                        f"{res.logical_id}/{suffix}",
                        res.type,
                        comp.import_id,
                        IMPORT,
                        f"deployed by {res.logical_id}",
                        f"{comp.tf_type}.{cname}",
                        comp,
                    )
                )
        else:
            out.append(
                ResourcePlan(
                    stack.name,
                    res.logical_id,
                    res.type,
                    res.physical_id,
                    result.fate,
                    result.reason,
                )
            )
    # Stack resources CloudFormation reports but the template no longer lists are suspicious.
    for lid in bodies:
        if stack.resource(lid) is None and resolver.resource_exists(lid):
            out.append(
                ResourcePlan(
                    stack.name,
                    lid,
                    bodies[lid].get("Type", "?"),
                    None,
                    BLOCKED,
                    "in template but not in DescribeStackResources",
                )
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
        selected_envs = set((inv.selection or {}).get("envs") or [])
        if selected_envs and stack.kind in (ENV, ENV_ADDONS) and stack.env not in selected_envs:
            sp.handoff = False
            sp.kept_because.append("environment not selected with --env")
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
        elsewhere = [u for u in inv.unavailable if "env" in u or "stackset_instance" in u]
        if elsewhere:
            for s in app_layer:
                keep(
                    s.name,
                    "the app has environments or StackSet instances outside this "
                    f"account/region ({len(elsewhere)})",
                )
        if any(not plan.stacks[s.name].handoff for s in app_layer):
            for s in app_layer:
                keep(s.name, "the app layer is handed off together")

    for s in inv.stacks_of(WORKLOAD):
        key = f"{s.env}/{s.workload}"
        if key not in plan.workload_status:
            plan.workload_status[key] = (
                "migrating"
                if plan.stacks[s.name].handoff
                else "kept: " + "; ".join(plan.stacks[s.name].kept_because)
            )


def _closure(plan: MigrationPlan) -> None:
    """Nothing that survives may depend on something manual cleanup will delete.

    "Surviving" covers imported resources *and* everything in kept stacks (they keep running on
    Copilot). Dependencies are found through template references within a stack and through
    literal ID/ARN strings anywhere (imported arguments, kept stacks' templates and parameters).
    """
    inv = plan.inventory
    cleanup = [
        r
        for r in plan.resources
        if r.fate == MANUAL_CLEANUP and r.physical_id and not r.type.startswith("Custom::")
    ]
    cleanup_lids: dict[str, set[str]] = {}
    for r in cleanup:
        cleanup_lids.setdefault(r.stack, set()).add(r.logical_id)
    for rp in plan.imports():
        stack = inv.stacks.get(rp.stack)
        if stack is None:
            continue
        body = cfn.load(stack.template_body)["Resources"].get(rp.logical_id) or {}
        for lid in cfn.references(body.get("Properties") or {}) & cleanup_lids.get(rp.stack, set()):
            plan.closure_errors.append(
                f"{rp.tf_address} references {rp.stack}/{lid}, which is manual-cleanup"
            )
    haystacks: list[tuple[str, str]] = [
        (rp.tf_address or rp.logical_id, repr(rp.spec.body))
        for rp in plan.imports()
        if rp.spec is not None
    ]
    for name, sp in plan.stacks.items():
        if not sp.handoff and name in inv.stacks:
            st = inv.stacks[name]
            haystacks.append((f"kept stack {name}", st.template_body + repr(st.parameters)))
    imported_ids = {rp.physical_id for rp in plan.imports() if rp.physical_id}
    for r in cleanup:
        pid = r.physical_id or ""
        # Some handles report another resource's ID as their own (an Aurora
        # SecretTargetAttachment reports the secret's ARN). If that ID is itself imported, the
        # dependency is on the imported resource, not on the cleanup handle.
        if len(pid) < 8 or pid in imported_ids:
            continue
        # A kept stack referencing its *own* manual-cleanup resource is fine: it is not deleted.
        needles = {pid, pid.rsplit(":", 1)[-1] if pid.startswith("arn:") else pid}
        for label, text in haystacks:
            if label == f"kept stack {r.stack}":
                continue
            if any(n and n in text for n in needles):
                plan.closure_errors.append(
                    f"{label} depends on {r.stack}/{r.logical_id} ({r.type}), which is "
                    "manual-cleanup"
                )


def _teardown(inv: Inventory, plan: MigrationPlan) -> None:
    """Deletion order over handed-off stacks.

    Hand-off already implies no remaining consumer (propagation keeps every shared stack that a
    kept stack needs), so every handed-off stack is deletable and nothing is truncated: a kept
    environment never removes an independent, handed-off environment from the list (that would
    leave imported resources inside a live stack). ``teardown_stops_at`` names the first kept
    shared stack for the report.
    """
    order: list[Stack] = []
    for kind in (WORKLOAD, ADDONS, ENV, ENV_ADDONS, STACKSET_INSTANCE, APP):
        order += sorted(inv.stacks_of(kind), key=lambda s: s.name)
    for s in order:
        if plan.stacks[s.name].handoff:
            plan.teardown.append(s.name)
        elif s.kind in (ENV, STACKSET_INSTANCE, APP) and plan.teardown_stops_at is None:
            plan.teardown_stops_at = s.name


def _out_of_band(inv: Inventory, plan: MigrationPlan) -> None:
    """Give objects that custom resources created outside CloudFormation a fate (PLAN §2.2).

    * ACM certificates created by a Copilot custom resource: imported with the creating stack's
      hand-off, otherwise kept with it.
    * Route 53 records inside an imported hosted zone that no CloudFormation RecordSet owns
      (alias A records, validation CNAMEs, NS delegations): imported; a record shape ecsodus
      cannot reproduce exactly blocks the zone's stack.
    * Validation and alias records Copilot wrote into a zone that is not Copilot's (the root
      domain's): external references, listed in the report (``_unmanaged_dns``).
    """
    from ecsodus.mappers import tf_oob

    names = {r.tf_address for r in plan.resources if r.tf_address}
    for obj in inv.out_of_band:
        stack_name = obj.created_by.split("/", 1)[0]
        if stack_name not in plan.stacks:
            plan.closure_errors.append(
                f"out-of-band {obj.kind} {obj.id} has no known creating stack ({obj.created_by})"
            )
        handoff = plan.stacks.get(stack_name) is not None and plan.stacks[stack_name].handoff
        rp = tf_oob.plan_certificate(obj, stack_name, handoff, names)
        plan.resources.append(rp)
        if rp.fate == BLOCKED:
            owner = plan.stacks.get(stack_name)
            if owner is None:
                plan.closure_errors.append(
                    f"out-of-band {obj.kind} {obj.id} has unknown owner {obj.created_by}"
                )
            else:
                owner.handoff = False
                owner.kept_because.append(f"out-of-band certificate blocked: {rp.reason}")
    owned_records: set[tuple[str, str, str]] = set()  # (zone id or name, record name, type)
    for st in inv.stacks.values():
        try:
            tpl = cfn.load(st.template_body)
        except cfn.TemplateError:
            continue
        res = Resolver(inv, st, tpl)
        for body in (tpl.get("Resources") or {}).values():
            rtype = body.get("Type")
            if rtype not in ("AWS::Route53::RecordSet", "AWS::Route53::RecordSetGroup"):
                continue
            props = body.get("Properties") or {}
            # A RecordSetGroup's records sit in the group's zone unless they name their own
            # (Copilot's LoadBalancerDNSAlias is a group in the env zone, and a CloudFormation
            # record must not be imported a second time as an out-of-band one).
            records = (
                props.get("RecordSets") if rtype == "AWS::Route53::RecordSetGroup" else [props]
            )
            for rec in records if isinstance(records, list) else []:
                key = _record_key(res, props, rec)
                if key is not None:
                    owned_records.add(key)
    for rp in list(plan.imports()):
        if rp.type != "AWS::Route53::HostedZone" or rp.physical_id is None:
            continue
        live = inv.live.get(rp.physical_id) or {}
        for rp2 in tf_oob.plan_zone_records(rp, live, owned_records, names):
            plan.resources.append(rp2)
            if rp2.fate == BLOCKED:
                sp = plan.stacks[rp.stack]
                sp.handoff = False
                sp.kept_because.append(f"out-of-band record blocked: {rp2.reason}")
    _unmanaged_dns(inv, plan, owned_records)


def _record_key(res: Resolver, group: dict[str, Any], rec: Any) -> tuple[str, str, str] | None:
    """(zone, record name, type|set id) of a template record, or None if it cannot be resolved.

    Only the identifying fields are resolved: an alias target that is not resolvable offline
    must not hide which record the stack owns.
    """
    if not isinstance(rec, dict):
        return None
    try:
        zone_raw = rec.get("HostedZoneId") or rec.get("HostedZoneName")
        if zone_raw is None:
            zone_raw = group.get("HostedZoneId") or group.get("HostedZoneName")
        zone = str(res.resolve(zone_raw) or "")
        name = str(res.resolve(rec.get("Name", "")) or "")
        rtype = str(res.resolve(rec.get("Type", "")) or "")
        set_id = str(res.resolve(rec.get("SetIdentifier", "")) or "")
    except Unresolvable:
        return None
    return (
        zone.rsplit("/", 1)[-1].rstrip(".").lower(),
        name.rstrip(".").lower(),
        f"{rtype}|{set_id}",
    )


def _unmanaged_dns(
    inv: Inventory, plan: MigrationPlan, owned_records: set[tuple[str, str, str]]
) -> None:
    """List Copilot-written DNS records that no imported zone or stack resource covers.

    Copilot's certificate validator and custom-domain handler also write into zones that are
    not Copilot resources: the customer's root zone ``<domain>``, for an alias such as
    ``www.<domain>``. Inventory reads only the zones Copilot created, so those records get no
    Terraform resource. Their handlers are retained, so nothing deletes them; they are listed
    as external references so the report says who must keep them (ACM renewal needs the
    validation CNAMEs).
    """
    from ecsodus.mappers import tf_oob

    covered = {(name, rtype.split("|", 1)[0]) for _zone, name, rtype in owned_records}
    for r in plan.resources:
        if r.type == tf_oob.RECORD_TYPE and r.logical_id.startswith("out-of-band:"):
            name, _, rtype = r.logical_id.removeprefix("out-of-band:").rpartition("/")
            covered.add((name, rtype))
    wanted: list[tuple[str, str, str, str]] = []  # (stack, record name, type, what it is)
    certs = {r.physical_id: r for r in plan.resources if r.type == tf_oob.CERT_TYPE}
    for obj in inv.out_of_band:
        cert = certs.get(obj.id)
        if cert is None or cert.fate != IMPORT:
            continue
        for opt in obj.details.get("DomainValidationOptions") or []:
            rr = opt.get("ResourceRecord") or {}
            if rr.get("Name") and rr.get("Type"):
                what = f"ACM validation record for {opt.get('DomainName')} (certificate {obj.id})"
                wanted.append((cert.stack, tf_oob.record_name(rr["Name"]), rr["Type"], what))
    for st in inv.stacks_of(ENV):
        sp = plan.stacks.get(st.name)
        if sp is None or not sp.handoff or st.resource("CustomDomainAction") is None:
            continue
        try:
            aliases = json.loads(st.parameters.get("Aliases") or "{}")
        except ValueError:
            continue
        for svc, names in sorted(aliases.items()) if isinstance(aliases, dict) else []:
            for alias in names if isinstance(names, list) else []:
                what = f"alias record for {svc}, written by {st.name}/CustomDomainAction"
                wanted.append((st.name, tf_oob.record_name(str(alias)), "A", what))
    seen: set[tuple[str, str]] = set()
    for stack, name, rtype, what in wanted:
        if (name, rtype) in covered or (name, rtype) in seen:
            continue
        seen.add((name, rtype))
        plan.resources.append(
            ResourcePlan(
                stack,
                f"out-of-band:{name}/{rtype}",
                tf_oob.RECORD_TYPE,
                None,
                EXTERNAL_REFERENCE,
                f"{what} is in a hosted zone ecsodus does not import (not a Copilot zone, "
                "such as the root domain's). Its handler is retained, so nothing deletes it, "
                "but Terraform will not manage it: keep it, or import it yourself.",
            )
        )


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
            info = knowledge.CUSTOM_RESOURCES.get(rtype) or {}
            variants = [v for v in info.get("variants", ()) if lid in v.get("logical_ids", ())]
            variants = variants or list(info.get("variants", ()))
            if info.get("destructive") and variants:
                behaviour = " / ".join(sorted({v.get("delete_behaviour", "") for v in variants}))
                out.append(f"{lid} ({rtype}): Delete handler: {behaviour}")
            elif not info:
                out.append(f"{lid} ({rtype}): unknown custom resource; Delete behaviour unknown")
            continue
        if policy not in ("Retain", "RetainExceptOnCreate"):
            label = "snapshot then delete" if policy == "Snapshot" else "delete"
            out.append(f"{lid} ({rtype}): {label}")
    return out


def _express_fit(inv: Inventory, stack: Stack, template: dict[str, Any]) -> ExpressFit:
    """The Express Mode predicate (PLAN §2.3); informational in v0.1.

    Properties are resolved (Copilot uses Fn::If with AWS::NoValue for optional features), so
    a feature counts only if it is actually on in this deployment.
    """
    reasons: list[str] = []
    resolver = Resolver(inv, stack, template)
    res = template.get("Resources") or {}

    def live_props(rtype: str) -> list[dict[str, Any]]:
        out = []
        for lid, body in res.items():
            if body.get("Type") != rtype:
                continue
            try:
                if resolver.resource_exists(lid):
                    out.append(resolver.resolve(body.get("Properties") or {}) or {})
            except Unresolvable:
                out.append({"__unresolved__": True})
        return out

    if stack.workload_type != "Load Balanced Web Service":
        reasons.append("not a Load Balanced Web Service")
    for props in live_props("AWS::ECS::TaskDefinition"):
        if props.get("__unresolved__"):
            reasons.append("task definition not resolvable offline")
            continue
        if len(props.get("ContainerDefinitions") or []) != 1:
            reasons.append("more than one container (sidecars)")
        if props.get("Volumes"):
            reasons.append("uses volumes")
        try:
            cpu, mem = int(str(props.get("Cpu", "0"))), int(str(props.get("Memory", "0")))
            if not 256 <= cpu <= 4096 or not 512 <= mem <= 8192:
                reasons.append(f"cpu {cpu}/memory {mem} outside 256-4096/512-8192")
        except ValueError:
            reasons.append("cpu/memory not numeric")
    for props in live_props("AWS::ECS::Service"):
        sc = props.get("ServiceConnectConfiguration") or {}
        if props.get("__unresolved__"):
            reasons.append("service not resolvable offline")
        elif sc.get("Enabled") in (True, "true"):
            reasons.append("uses Service Connect")
    for props in live_props("AWS::ElasticLoadBalancingV2::LoadBalancer"):
        if props.get("Type") == "network":
            reasons.append("uses a Network Load Balancer")
    return ExpressFit(eligible=not reasons, reasons=sorted(set(reasons)))
