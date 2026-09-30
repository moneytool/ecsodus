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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ecsodus.emit.retain_patch import METADATA_KEY, NESTED_STACK_TYPE

POLICY_ATTRIBUTES = {"DeletionPolicy", "UpdateReplacePolicy"}
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
    return cs.get("Status") in ("FAILED", "CREATE_COMPLETE") and (
        not reason or any(r in reason for r in NO_CHANGES_REASONS)
    )


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
    patched_nested: Iterable[str] = (),
    allow_metadata_key: bool = False,
    allow_nested_dynamic: bool = False,
) -> ChangeSetResult:
    """Apply the acceptance rule to a root change set and its nested change sets.

    ``patched_nested`` lists the logical IDs of nested-stack wrappers whose ``TemplateURL`` the
    retain patch rewrote (from the generate manifest).
    """
    sets = list(change_sets)
    nested_ok = set(patched_nested)
    result = ChangeSetResult(verdict=PASS, change_sets=len(sets))
    if not sets:
        return ChangeSetResult(verdict=FAIL, errors=["no change sets given"])
    if all(_is_empty(cs) for cs in sets):
        return ChangeSetResult(verdict=EMPTY, change_sets=len(sets))

    for cs in sets:
        name = cs.get("StackName") or cs.get("ChangeSetName") or "?"
        if cs.get("Status") == "FAILED" and not _is_empty(cs):
            result.errors.append(f"{name}: change set FAILED: {cs.get('StatusReason')}")
            continue
        for change in cs.get("Changes") or []:
            if change.get("Type") not in (None, "Resource"):
                result.errors.append(f"{name}: unexpected change type {change.get('Type')}")
                continue
            rc = change.get("ResourceChange") or {}
            lid = rc.get("LogicalResourceId", "?")
            where = f"{name}/{lid}"
            problems = _check_resource_change(
                rc, nested_ok, allow_metadata_key, allow_nested_dynamic
            )
            if problems:
                result.errors.extend(f"{where}: {p}" for p in problems)
            else:
                result.accepted += 1
    if result.errors:
        result.verdict = FAIL
    return result


def _check_resource_change(
    rc: dict[str, Any],
    nested_ok: set[str],
    allow_metadata_key: bool,
    allow_nested_dynamic: bool,
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
            continue
        if attr == "Metadata" and allow_metadata_key and _metadata_only_ecsodus(d):
            continue
        problems.append(f"change to {attr}/{target.get('Name') or '-'} is not policy-only")
    return problems
