"""Terraform plan and state gates (PLAN §2.6, §13.5–6).

Input is ``terraform show -json <planfile>``. ``terraform show -json`` marks an import with a
non-null ``change.importing``; the ``actions`` array itself only ever holds no-op / create /
read / update / delete, so imports must be detected through ``importing`` (council note §13.6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

IMPORT = "import"
STEADY = "steady"


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


def check_plan(plan: dict[str, Any], expected_imports: Iterable[str], phase: str) -> CheckResult:
    """Gate a plan for ``phase`` ("import" or "steady").

    * import: every managed resource change must be a pure import (``importing`` set, actions
      ``["no-op"]``) or a plain no-op; every expected import address must be present.
    * steady: every change must be a no-op, and nothing may be importing any more.
    """
    if phase not in (IMPORT, STEADY):
        raise ValueError(f"unknown phase {phase!r}")
    expected = set(expected_imports)
    res = CheckResult(ok=True)
    counts: dict[str, int] = {}
    importing_seen: set[str] = set()
    for rc in _changes(plan):
        address = rc.get("address", "?")
        change = rc.get("change") or {}
        actions = list(change.get("actions") or [])
        importing = change.get("importing")
        mode = rc.get("mode", "managed")
        key = "+".join(actions) + ("+import" if importing else "")
        counts[key] = counts.get(key, 0) + 1
        if mode == "data":
            if actions not in (["read"], ["no-op"]):
                res.errors.append(f"{address}: data source action {actions}")
            continue
        if importing:
            importing_seen.add(address)
        if actions == ["no-op"]:
            if phase == STEADY and importing:
                res.errors.append(f"{address}: still importing in the steady phase")
            continue
        verb = "/".join(actions)
        if phase == IMPORT:
            res.errors.append(
                f"{address}: {verb}{' while importing' if importing else ''} — the import phase "
                "allows only pure imports and no-ops (the HCL must match live state exactly)"
            )
        else:
            res.errors.append(f"{address}: {verb} — the steady phase requires a zero-change plan")
    if phase == IMPORT:
        missing = sorted(expected - importing_seen)
        for address in missing:
            res.errors.append(f"{address}: expected import is missing from the plan")
        unexpected = sorted(importing_seen - expected)
        for address in unexpected:
            res.errors.append(f"{address}: plan imports an address ecsodus did not generate")
    for dd in plan.get("resource_drift") or []:
        res.warnings.append(f"{dd.get('address', '?')}: drift detected during refresh")
    res.summary = counts
    res.ok = not res.errors
    return res


def check_state(state_addresses: Iterable[str], expected_imports: Iterable[str]) -> CheckResult:
    """Every import-fated address must be in ``terraform state list`` output."""
    present = {a.strip() for a in state_addresses if a.strip()}
    missing = sorted(set(expected_imports) - present)
    res = CheckResult(ok=not missing)
    res.errors = [f"{a}: not in Terraform state" for a in missing]
    res.summary = {"expected": len(set(expected_imports)), "present": len(present)}
    return res
