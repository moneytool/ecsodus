"""CloudFormation change-set acceptance rule for retain patches (PLAN §2.4, §13.2–3).

Input: the JSON of ``aws cloudformation describe-change-set`` for the root change set and every
nested change set (created with ``--include-nested-stacks``; describe each nested one by the
``ChangeSetId`` shown on its ``AWS::CloudFormation::Stack`` resource change). Create change sets
with ``--include-property-values`` so Metadata before/after values can be checked.

Every resource change must be a policy-only ``Modify`` with ``Replacement: False``. Allowed
detail targets:

* ``Attribute`` DeletionPolicy / UpdateReplacePolicy;
* ``Properties``/``TemplateURL`` with ``RequiresRecreation: Never`` on an
  ``AWS::CloudFormation::Stack`` that ``generate`` patched (listed in the manifest);
* ``Metadata`` whose only change is the ``ecsodus:retain`` key, when the Metadata fallback is on;
* optionally, ``Dynamic`` ``ResourceAttribute`` entries caused by a patched nested stack's
  outputs, only when explicitly allowed and that nested change set itself passes.

An empty change set is not a pass: it means either the stack is already retained (verify with
``ecsodus verify-retain`` and skip it) or CloudFormation treated the policy-only change as a no-op
(use the Metadata fallback). The result distinguishes this case.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ecsodus.emit.retain_patch import METADATA_KEY, NESTED_STACK_TYPE

POLICY_ATTRIBUTES = {"DeletionPolicy", "UpdateReplacePolicy"}
NESTED_UNAVAILABLE_REASON = "Only executable from the root change set."
NO_CHANGES_REASONS = ("didn't contain changes", "No updates are to be performed")

PASS = "pass"
FAIL = "fail"
EMPTY = "empty"


@dataclass
class ChangeSetResult:
    verdict: str
    errors: list[str] = field(default_factory=list)
    accepted: int = 0
    change_sets: int = 0

    @property
    def ok(self) -> bool:
        return self.verdict == PASS


def _is_empty(cs: dict[str, Any]) -> bool:
    if cs.get("Changes"):
        return False
    reason = cs.get("StatusReason") or ""
    if cs.get("Status") == "FAILED":
        return any(r in reason for r in NO_CHANGES_REASONS)
    return cs.get("Status") == "CREATE_COMPLETE"


def _metadata_only_ecsodus(detail: dict[str, Any]) -> bool:
    target = detail.get("Target") or {}
    before, after = target.get("BeforeValue"), target.get("AfterValue")
    if after is None:
        return False  # without --include-property-values the change cannot be verified
    try:
        b = json.loads(before) if before else {}
        a = json.loads(after)
    except (TypeError, ValueError):
        return False
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    a = dict(a)
    if a.pop(METADATA_KEY, None) not in ("true", True):
        return False
    b.pop(METADATA_KEY, None)
    return a == b


def check_change_sets(
    change_sets: Iterable[dict[str, Any]],
    patched_nested: Iterable[str] | Mapping[str, str] = (),
    allow_metadata_key: bool = False,
    allow_nested_dynamic: bool = False,
) -> ChangeSetResult:
    """Apply the acceptance rule to a root change set and all of its nested change sets.

    ``patched_nested`` maps each patched nested-stack wrapper's logical ID to the S3 URL of its
    patched child template (from the manifest); a plain list of IDs is accepted but then the
    ``TemplateURL`` value cannot be verified and the rule fails closed.

    Requirements beyond the per-change rule:

    * every change set is ``CREATE_COMPLETE`` and executable (``ExecutionStatus: AVAILABLE``);
      anything still in progress fails;
    * every nested change set referenced by a stack-resource change is supplied, and every
      supplied change set is the root or referenced by one;
    * a ``TemplateURL`` change's new value (``describe-change-set --include-property-values``)
      equals the manifest URL of the patched child.
    """
    sets = list(change_sets)
    nested_urls: dict[str, str | None] = (
        dict(patched_nested)
        if isinstance(patched_nested, Mapping)
        else dict.fromkeys(patched_nested)
    )
    result = ChangeSetResult(verdict=PASS, change_sets=len(sets))
    if not sets:
        return ChangeSetResult(verdict=FAIL, errors=["no change sets given"])
    if len(sets) == 1 and _is_empty(sets[0]):
        return ChangeSetResult(verdict=EMPTY, change_sets=1)

    ids = {cs.get("ChangeSetId") for cs in sets if cs.get("ChangeSetId")}
    roots = [cs for cs in sets if not cs.get("ParentChangeSetId")]
    if len(roots) != 1:
        result.errors.append(f"expected exactly one root change set, got {len(roots)}")
    referenced: set[str] = set()
    for cs in sets:
        for change in cs.get("Changes") or []:
            child = (change.get("ResourceChange") or {}).get("ChangeSetId")
            if child:
                referenced.add(child)
    for child in sorted(referenced - ids):
        result.errors.append(f"nested change set {child} was not supplied (describe it too)")
    root_id = roots[0].get("ChangeSetId") if len(roots) == 1 else None
    by_id = {cs.get("ChangeSetId"): cs for cs in sets}
    for cs in sets:
        cid = cs.get("ChangeSetId")
        parent = cs.get("ParentChangeSetId")
        if parent and cid not in referenced:
            result.errors.append(f"change set {cid} is not referenced by the root")
        if parent and (parent not in by_id or parent == cid):
            result.errors.append(f"change set {cid} has parent {parent}, which was not supplied")
        if cs.get("RootChangeSetId") and root_id and cs["RootChangeSetId"] != root_id:
            result.errors.append(f"change set {cid} belongs to another root")
    # Wrapper logical IDs whose child change set was actually supplied (for Dynamic entries),
    # and each child's claimed parent and stack must match the change that references it.
    supplied_children: set[str] = set()
    for cs in sets:
        for change in cs.get("Changes") or []:
            rcx = change.get("ResourceChange") or {}
            child_id = rcx.get("ChangeSetId")
            if child_id not in ids:
                continue
            supplied_children.add(rcx.get("LogicalResourceId", ""))
            child = by_id[child_id]
            if child.get("ParentChangeSetId") != cs.get("ChangeSetId"):
                result.errors.append(f"change set {child_id} does not name its referencing parent")
            phys = rcx.get("PhysicalResourceId")
            if phys and child.get("StackId") and child["StackId"] != phys:
                result.errors.append(
                    f"change set {child_id} is for stack {child['StackId']}, not {phys}"
                )

    for cs in sets:
        name = cs.get("StackName") or cs.get("ChangeSetName") or "?"
        status, execution = cs.get("Status"), cs.get("ExecutionStatus")
        # Nested change sets are never executable on their own: AWS reports them
        # UNAVAILABLE with this exact reason (observed in the AWS end-to-end run).
        nested_ok = (
            bool(cs.get("ParentChangeSetId"))
            and execution == "UNAVAILABLE"
            and cs.get("StatusReason") == NESTED_UNAVAILABLE_REASON
        )
        if status != "CREATE_COMPLETE" or (execution != "AVAILABLE" and not nested_ok):
            result.errors.append(
                f"{name}: change set is {status}/{execution}, not CREATE_COMPLETE/AVAILABLE"
                + (f" ({cs.get('StatusReason')})" if cs.get("StatusReason") else "")
            )
            continue
        for change in cs.get("Changes") or []:
            if change.get("Type") not in (None, "Resource"):
                result.errors.append(f"{name}: unexpected change type {change.get('Type')}")
                continue
            rc = change.get("ResourceChange") or {}
            where = f"{name}/{rc.get('LogicalResourceId', '?')}"
            problems = _check_resource_change(
                rc, nested_urls, allow_metadata_key, allow_nested_dynamic, supplied_children
            )
            if problems:
                result.errors.extend(f"{where}: {p}" for p in problems)
            else:
                result.accepted += 1
    if result.errors:
        result.verdict = FAIL
    elif result.accepted == 0:
        result.verdict = EMPTY
    return result


def _check_resource_change(
    rc: dict[str, Any],
    nested_ok: Mapping[str, str | None],
    allow_metadata_key: bool,
    allow_nested_dynamic: bool,
    supplied_children: set[str] = frozenset(),  # type: ignore[assignment]
) -> list[str]:
    problems: list[str] = []
    action = rc.get("Action")
    if action != "Modify":
        return [f"action {action} is not allowed (only policy-only Modify)"]
    replacement = rc.get("Replacement")
    if replacement != "False":
        problems.append(f"Replacement is {replacement!r}, must be 'False'")
    rtype = rc.get("ResourceType", "")
    lid = rc.get("LogicalResourceId", "")
    details = rc.get("Details") or []
    if not details:
        scope = set(rc.get("Scope") or [])
        if not scope or scope - POLICY_ATTRIBUTES:
            problems.append(f"Modify with no details and scope {sorted(scope)}")
        return problems
    for d in details:
        target = d.get("Target") or {}
        attr = target.get("Attribute")
        evaluation = d.get("Evaluation", "Static")
        if evaluation == "Dynamic":
            causing = d.get("CausingEntity") or ""
            if (
                allow_nested_dynamic
                and d.get("ChangeSource") == "ResourceAttribute"
                and causing.split(".", 1)[0] in nested_ok
                and causing.split(".", 1)[0] in supplied_children
            ):
                continue
            problems.append(
                f"dynamic change to {attr}/{target.get('Name')} (caused by {causing or '?'})"
            )
            continue
        if attr in POLICY_ATTRIBUTES:
            continue
        if (
            attr == "Properties"
            and target.get("Name") == "TemplateURL"
            and rtype == NESTED_STACK_TYPE
            and lid in nested_ok
        ):
            if target.get("RequiresRecreation") != "Never":
                problems.append(
                    f"TemplateURL change has RequiresRecreation={target.get('RequiresRecreation')}"
                )
            expected = nested_ok.get(lid)
            after = target.get("AfterValue")
            if expected is None or after is None:
                problems.append(
                    "TemplateURL new value cannot be verified: describe the change set with "
                    "--include-property-values and pass the manifest"
                )
            elif after.strip('"') != expected:
                problems.append(f"TemplateURL points at {after!r}, not the patched child")
            continue
        if attr == "Metadata" and allow_metadata_key and _metadata_only_ecsodus(d):
            continue
        problems.append(f"change to {attr}/{target.get('Name') or '-'} is not policy-only")
    return problems
