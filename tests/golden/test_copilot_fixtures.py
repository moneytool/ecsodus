"""Golden tests over real Copilot-rendered stacks (verbatim fixtures, no live data).

Without live reads many values cannot be known exactly (custom-resource outputs, AZs, rule IDs),
so ecsodus must *keep* those stacks rather than guess. The report is snapshotted so any change in
planning behaviour is reviewed. Regenerate with ``ECSODUS_UPDATE_GOLDEN=1 uv run pytest``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ecsodus.emit import report
from ecsodus.emit.patches import build_patches
from ecsodus.mappers.fates import BLOCKED, IMPORT, build_plan
from ecsodus.model import Workload
from tests.helpers import FIXTURES, inventory_from_template

GOLDEN = Path(__file__).parent / "snapshots"


def fixture_app():
    inv, env = inventory_from_template(
        FIXTURES / "rendered/environments/template-with-basic-manifest.yml",
        stack_name="my-app-test",
        kind="env",
        workload=None,
        workload_type=None,
        app="my-app",
    )
    env.exports = env_exports(inv, env)
    for rel, name, wtype in (
        ("rendered/workloads/svc-test.stack.yml", "fe", "Load Balanced Web Service"),
        ("rendered/backend/simple-template.yml", "be", "Backend Service"),
        ("rendered/workloads/worker-test.stack.yml", "worker", "Worker Service"),
    ):
        other, stack = inventory_from_template(
            FIXTURES / rel,
            stack_name=f"my-app-test-{name}",
            workload=name,
            workload_type=wtype,
            app="my-app",
        )
        inv.stacks[stack.name] = stack
        inv.workloads.append(Workload(name, wtype, "test"))
    return inv


def env_exports(inv, env) -> dict[str, str]:
    """Resolve the env stack's exported outputs, as CloudFormation would have."""
    from ecsodus.mappers.resolve import Resolver, Unresolvable

    r = Resolver(inv, env)
    out = {}
    for spec in (r.template.get("Outputs") or {}).values():
        try:
            if "Export" in spec and ("Condition" not in spec or r.condition(spec["Condition"])):
                out[r.resolve(spec["Export"]["Name"])] = str(r.resolve(spec["Value"]))
        except Unresolvable:
            continue
    return out


def normalise(text: str) -> str:
    return re.sub(r"captured \S+", "captured <ts>", text)


def test_real_fixtures_fail_closed() -> None:
    inv = fixture_app()
    plan = build_plan(inv)
    # The Worker Service type is blocked, which keeps the env stack (a shared dependency).
    assert not plan.stacks["my-app-test-worker"].handoff
    assert not plan.stacks["my-app-test"].handoff
    assert plan.teardown_stops_at == "my-app-test"
    # Nothing in a kept stack is imported.
    for rp in plan.resources:
        if not plan.stacks[rp.stack].handoff:
            assert rp.fate != IMPORT, rp
    # No unresolvable value was guessed: every blocked reason is explicit.
    assert all(r.reason for r in plan.resources if r.fate == BLOCKED)


def test_retain_patches_for_real_fixtures() -> None:
    inv = fixture_app()
    ps = build_patches(inv, "bucket")
    for name, p in ps.stacks.items():
        assert not p.already_retained, name  # Copilot templates set Retain almost nowhere


def test_report_snapshot() -> None:
    text = normalise(report.render(build_plan(fixture_app())))
    snap = GOLDEN / "fixture-app-report.md"
    if os.environ.get("ECSODUS_UPDATE_GOLDEN") or not snap.exists():
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(text)
    assert text == snap.read_text()
