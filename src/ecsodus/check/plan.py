"""Terraform plan and state gates (PLAN §2.6, §13.5-6).

Input is ``terraform show -json <planfile>``. An import is marked by a non-null
``change.importing`` (its ``id`` is the physical ID being adopted); the ``actions`` array only
ever holds no-op / create / read / update / delete / forget, so imports must be detected through
``importing`` (council note §13.6).

Both phases require the plan to cover exactly the manifest's import set:

* **import**: every managed change is a pure import (``importing`` set, actions ``["no-op"]``) of
  the physical ID the manifest expects at that address; nothing else.
* **steady**: every expected address is present as a plain no-op (so a targeted or empty plan
  cannot pass), and nothing else changes.

ecsodus generates no data sources, so any data source in the plan fails: a data source can read
secret material into state (e.g. ``aws_secretsmanager_secret_version``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

IMPORT = "import"
STEADY = "steady"
AWS_PROVIDER = "registry.terraform.io/hashicorp/aws"


def _identity_matches(import_id: str, before: Any) -> bool:
    """Does the refreshed object carry the physical ID it was imported from?

    Import IDs are either a plain ID/ARN/name or a composite of several (``cluster/service``,
    ``ZONE_name_TYPE``); every component must appear among the object's attribute values.
    Without ``before`` (not in state) there is nothing to prove, which is a failure.
    """
    if not isinstance(before, dict):
        return False
    text = json.dumps(before, sort_keys=True).lower()
    if import_id.lower() in text:
        return True
    parts = [p for p in re.split(r"[/_:|,]", import_id.lower()) if len(p) > 2]
    return bool(parts) and all(p in text for p in parts)


@dataclass
class CheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def _changes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if "resource_changes" not in plan and "format_version" not in plan:
        raise ValueError("not a `terraform show -json` plan document")
    return list(plan.get("resource_changes") or [])


def check_plan(
    plan: dict[str, Any],
    expected_imports: Mapping[str, str] | Iterable[str],
    phase: str,
    forgotten: Iterable[str] = (),
) -> CheckResult:
    """Gate a plan for ``phase``. ``expected_imports`` maps address -> physical import ID.

    ``forgotten`` lists addresses being handed off with a ``removed { destroy = false }`` block
    (the imported task-definition revision): in the steady phase exactly those may show the
    ``forget`` action, and they are no longer required to be present.
    """
    forgotten_set = {a for a in forgotten if a.split(".", 1)[0] == "aws_ecs_task_definition"}
    res_pre = [a for a in forgotten if a not in forgotten_set]
    forget_seen: set[str] = set()
    if phase not in (IMPORT, STEADY):
        raise ValueError(f"unknown phase {phase!r}")
    expected: dict[str, str | None] = (
        dict(expected_imports)
        if isinstance(expected_imports, Mapping)
        else dict.fromkeys(expected_imports)
    )
    res = CheckResult(ok=True)
    for a in res_pre:
        res.errors.append(f"{a}: only aws_ecs_task_definition addresses can be --forgotten")
    counts: dict[str, int] = {}
    importing_seen: set[str] = set()
    noop_seen: set[str] = set()
    if plan.get("errored"):
        res.errors.append("the plan errored")
    for rc in _changes(plan):
        address = rc.get("address", "?")
        change = rc.get("change") or {}
        actions = list(change.get("actions") or [])
        importing = change.get("importing")
        mode = rc.get("mode", "managed")
        key = "+".join(actions) + ("+import" if importing else "")
        counts[key] = counts.get(key, 0) + 1
        if mode == "data":
            res.errors.append(f"{address}: data sources are not allowed (ecsodus generates none)")
            continue
        if actions == ["forget"] and phase == STEADY and address in forgotten_set:
            forget_seen.add(address)
            continue
        provider = rc.get("provider_name", AWS_PROVIDER)
        if provider != AWS_PROVIDER:
            res.errors.append(f"{address}: provider {provider} is not {AWS_PROVIDER}")
            continue
        if rc.get("type") and rc["type"] != address.split(".", 1)[0].split("[", 1)[0]:
            res.errors.append(f"{address}: resource type {rc['type']} does not match the address")
            continue
        if actions != ["no-op"]:
            verb = "/".join(actions) or "?"
            what = "pure imports and no-ops" if phase == IMPORT else "a zero-change plan"
            res.errors.append(f"{address}: {verb} — the {phase} phase allows only {what}")
            continue
        if importing:
            if phase == STEADY:
                res.errors.append(f"{address}: still importing in the steady phase")
                continue
            importing_seen.add(address)
            want = expected.get(address)
            got = (importing or {}).get("id")
            if address in expected and want is not None and got != want:
                res.errors.append(f"{address}: imports {got!r}, but the manifest expects {want!r}")
        else:
            want = expected.get(address)
            if phase == STEADY and want and not _identity_matches(want, change.get("before")):
                res.errors.append(
                    f"{address}: the resource in state does not carry the manifest's ID {want!r}"
                )
                continue
            noop_seen.add(address)
    if phase == IMPORT:
        for address in sorted(set(expected) - importing_seen):
            res.errors.append(f"{address}: expected import is missing from the plan")
        for address in sorted(importing_seen - set(expected)):
            res.errors.append(f"{address}: plan imports an address ecsodus did not generate")
    else:
        for address in sorted(forgotten_set - forget_seen):
            res.errors.append(f"{address}: --forgotten but the plan does not forget it")
        for address in sorted(set(expected) - noop_seen - forget_seen):
            res.errors.append(
                f"{address}: missing from the steady plan (targeted or incomplete plan?)"
            )
    for dd in plan.get("resource_drift") or []:
        res.warnings.append(f"{dd.get('address', '?')}: drift detected during refresh")
    res.summary = counts
    res.ok = not res.errors
    return res


def check_state(state_addresses: Iterable[str], expected_imports: Iterable[str]) -> CheckResult:
    """Every import-fated address must be in ``terraform state list`` output."""
    present = {a.strip() for a in state_addresses if a.strip()}
    wanted = set(expected_imports)
    missing = sorted(wanted - present)
    res = CheckResult(ok=not missing)
    res.errors = [f"{a}: not in Terraform state" for a in missing]
    res.summary = {"expected": len(wanted), "present": len(present)}
    return res
