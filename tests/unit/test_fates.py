"""Fates, atomic stack hand-off, blocker propagation, closure and teardown (PLAN §2.2, §2.5)."""

from __future__ import annotations

from ecsodus.mappers.fates import (
    IMPORT,
    MANUAL_CLEANUP,
    RETAIN_UNDER_EXISTING_OWNER,
    build_plan,
)
from tests.synthetic import app


def fates(plan, stack):
    return {r.logical_id: r.fate for r in plan.by_stack(stack)}


def test_full_handoff() -> None:
    plan = build_plan(app())
    assert all(s.handoff for s in plan.stacks.values()), {
        n: s.kept_because for n, s in plan.stacks.items() if not s.handoff
    }
    f = fates(plan, "demo-test-api")
    assert f["LogGroup"] == IMPORT
    assert f["EnvControllerAction"] == MANUAL_CLEANUP
    assert f["EnvControllerFunction"] == MANUAL_CLEANUP
    assert f["AddonsStack"] == "nested-wrapper"
    assert fates(plan, "demo-test-api-AddonsStack-1")["DataLogGroup"] == IMPORT
    assert plan.closure_errors == []
    # Teardown: workloads, orphaned addons, env, app. Nothing stops.
    assert plan.teardown == [
        "demo-test-api",
        "demo-test-worker",
        "demo-test-api-AddonsStack-1",
        "demo-test",
        "demo-infrastructure-roles",
    ]
    assert plan.teardown_stops_at is None


def test_unsupported_workload_type_keeps_env_and_app() -> None:
    plan = build_plan(app(worker_type="Worker Service"))
    assert not plan.stacks["demo-test-worker"].handoff
    assert not plan.stacks["demo-test"].handoff
    assert not plan.stacks["demo-infrastructure-roles"].handoff
    assert plan.stacks["demo-test-api"].handoff
    assert plan.teardown == ["demo-test-api", "demo-test-api-AddonsStack-1"]
    assert plan.teardown_stops_at == "demo-test"
    assert set(fates(plan, "demo-test").values()) <= {RETAIN_UNDER_EXISTING_OWNER, MANUAL_CLEANUP}
    assert "blocked" in plan.workload_status["test/worker"]


def test_partial_migration_keeps_shared_stacks() -> None:
    plan = build_plan(app(worker_migrates=False))
    assert plan.workload_status["test/worker"].startswith("not migrating")
    assert not plan.stacks["demo-test"].handoff
    assert plan.teardown_stops_at == "demo-test"
    assert "demo-test" not in plan.teardown


def test_blocked_resource_keeps_its_stack_atomically() -> None:
    plan = build_plan(app(extra_workload_resource=("Mystery", "AWS::Mystery::Thing")))
    worker = fates(plan, "demo-test-worker")
    # Nothing in a kept stack is imported: no dual ownership.
    assert IMPORT not in worker.values()
    assert worker["LogGroup"] == RETAIN_UNDER_EXISTING_OWNER
    assert "Mystery" in " ".join(plan.stacks["demo-test-worker"].kept_because)
    assert not plan.stacks["demo-test"].handoff


def test_blocked_nested_stack_keeps_parent() -> None:
    inv = app()
    child = inv.stacks["demo-test-api-AddonsStack-1"]
    child.template_body += "  Weird:\n    Type: AWS::Mystery::Thing\n"
    child.resources.append(type(child.resources[0])("Weird", "AWS::Mystery::Thing", "w-1"))
    plan = build_plan(inv)
    assert not plan.stacks["demo-test-api-AddonsStack-1"].handoff
    assert not plan.stacks["demo-test-api"].handoff


def test_in_progress_stack_is_kept() -> None:
    inv = app()
    inv.stacks["demo-test-worker"].status = "UPDATE_IN_PROGRESS"
    plan = build_plan(inv)
    assert not plan.stacks["demo-test-worker"].handoff


def test_side_effects_report_destructive_handlers() -> None:
    plan = build_plan(app())
    effects = " ".join(plan.stacks["demo-test-api"].unpatched_side_effects)
    assert "EnvControllerAction" in effects and "Delete handler" in effects
    assert "LogGroup" in effects
    env_effects = " ".join(plan.stacks["demo-test"].unpatched_side_effects)
    assert "CustomDomainAction" in env_effects


def test_closure_catches_reference_to_manual_cleanup() -> None:
    inv = app()
    env = inv.stacks["demo-test"]
    env.template_body = env.template_body.replace(
        "      RetentionInDays: 30\n  Cluster:",
        "      RetentionInDays: 30\n      KmsKeyId: !GetAtt CustomDomainFunction.Arn\n  Cluster:",
    )
    plan = build_plan(inv)
    assert any("CustomDomainFunction" in e for e in plan.closure_errors)
