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
    plan = build_plan(app(worker_type="Request-Driven Web Service"))
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


def test_independent_env_not_truncated_by_kept_env() -> None:
    """A kept env must not truncate an independent handed-off env (dual ownership)."""
    import copy

    inv = app()
    env2 = copy.deepcopy(inv.stacks["demo-test"])
    env2.name, env2.env = "demo-zprod", "zprod"
    inv.stacks[env2.name] = env2
    inv.envs.append("zprod")
    inv.stacks["demo-test-worker"].workload_type = "Request-Driven Web Service"  # keeps env "test"
    plan = build_plan(inv)
    assert not plan.stacks["demo-test"].handoff
    assert plan.stacks["demo-zprod"].handoff
    assert "demo-zprod" in plan.teardown
    for rp in plan.resources:
        if rp.fate == IMPORT:
            assert plan.stacks[rp.stack].handoff and rp.stack in plan.teardown


def test_kept_stack_depending_on_cleanup_resource_is_a_closure_error() -> None:
    inv = app(worker_migrates=False)
    worker = inv.stacks["demo-test-worker"]
    worker.template_body += (
        "  Uses:\n    Type: AWS::SNS::Topic\n    Properties:\n"
        "      DisplayName: demo-test-api-EnvCtl-Z9\n"
    )
    plan = build_plan(inv)
    assert any("kept stack demo-test-worker" in e for e in plan.closure_errors)


def test_out_of_band_certificate_gets_a_fate() -> None:
    from ecsodus.model import OutOfBand

    inv = app()
    arn = "arn:aws:acm:us-west-2:123456789012:certificate/abc"
    inv.out_of_band.append(
        OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", {"DomainName": "api.example.com"})
    )
    plan = build_plan(inv)
    cert = [r for r in plan.resources if r.physical_id == arn][0]
    assert cert.fate == IMPORT and cert.spec.tf_type == "aws_acm_certificate"
    kept = build_plan(app(worker_type="Request-Driven Web Service"))
    inv2 = app(worker_type="Request-Driven Web Service")
    inv2.out_of_band.append(
        OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", {"DomainName": "api.example.com"})
    )
    plan2 = build_plan(inv2)
    assert [r for r in plan2.resources if r.physical_id == arn][0].fate == (
        RETAIN_UNDER_EXISTING_OWNER
    )
    assert kept is not None


def test_user_lambda_is_blocked_not_manual_cleanup() -> None:
    inv = app()
    w = inv.stacks["demo-test-worker"]
    w.template_body += "  UserFn:\n    Type: AWS::Lambda::Function\n    Properties: {}\n"
    w.resources.append(type(w.resources[0])("UserFn", "AWS::Lambda::Function", "user-fn-1234"))
    plan = build_plan(inv)
    assert fates(plan, "demo-test-worker")["EnvControllerFunction"] == MANUAL_CLEANUP
    assert not plan.stacks["demo-test-worker"].handoff
    assert "user function" in " ".join(plan.stacks["demo-test-worker"].kept_because)


def test_transform_templates_are_blocked() -> None:
    inv = app()
    inv.stacks["demo-test-worker"].template_body = (
        "Transform: AWS::Serverless-2016-10-31\n" + inv.stacks["demo-test-worker"].template_body
    )
    plan = build_plan(inv)
    assert not plan.stacks["demo-test-worker"].handoff
    assert "Transform" in " ".join(plan.stacks["demo-test-worker"].kept_because)


def test_envs_elsewhere_keep_the_app_layer() -> None:
    inv = app()
    inv.unavailable.append({"env": "prod", "reason": "registered in SSM, other region"})
    plan = build_plan(inv)
    assert not plan.stacks["demo-infrastructure-roles"].handoff
    assert plan.stacks["demo-test"].handoff


def test_cleanup_handle_sharing_an_imported_id_is_not_a_closure_error() -> None:
    """Aurora's SecretTargetAttachment reports the secret's ARN as its own physical ID."""
    inv = app()
    env = inv.stacks["demo-test"]
    shared = "/copilot/demo-test"  # the env log group's ID, also claimed by a cleanup handle
    env.template_body += "  Attach:\n    Type: Custom::Whatever\n"
    env.resources.append(
        type(env.resources[0])("Attach", "AWS::SecretsManager::SecretTargetAttachment", shared)
    )
    env.template_body = env.template_body.replace(
        "  Attach:\n    Type: Custom::Whatever\n",
        "  Attach:\n    Type: AWS::SecretsManager::SecretTargetAttachment\n    Properties: {}\n",
    )
    plan = build_plan(inv)
    assert plan.closure_errors == []


def test_blocked_out_of_band_certificate_keeps_its_stack() -> None:
    from ecsodus.model import OutOfBand

    inv = app()
    inv.out_of_band.append(
        OutOfBand(
            "acm_certificate", "arn:aws:acm:us-west-2:1:certificate/x", "demo-test/HTTPSCert", {}
        )
    )
    plan = build_plan(inv)
    assert not plan.stacks["demo-test"].handoff


def test_unselected_env_without_workloads_is_kept() -> None:
    import copy

    inv = app()
    env2 = copy.deepcopy(inv.stacks["demo-test"])
    env2.name, env2.env = "demo-prod", "prod"
    inv.stacks[env2.name] = env2
    inv.selection = {"envs": ["test"], "keep_on_copilot": []}
    plan = build_plan(inv)
    assert not plan.stacks["demo-prod"].handoff
    assert not plan.stacks["demo-infrastructure-roles"].handoff


def test_dns_ownership_is_per_zone() -> None:
    from ecsodus.mappers import tf_oob
    from ecsodus.mappers.fates import ResourcePlan

    zone = ResourcePlan("demo-test", "Zone", "AWS::Route53::HostedZone", "Z111", IMPORT)
    live = {
        "HostedZone": {"Name": "example.com."},
        "RecordSets": [
            {
                "Name": "api.example.com.",
                "Type": "A",
                "TTL": 60,
                "ResourceRecords": [{"Value": "1.2.3.4"}],
            }
        ],
    }
    other_zone_owner = {("z222", "api.example.com", "A|")}
    out = tf_oob.plan_zone_records(zone, live, other_zone_owner, set())
    assert [r.fate for r in out] == [IMPORT]
    same_zone_owner = {("z111", "api.example.com", "A|")}
    assert tf_oob.plan_zone_records(zone, live, same_zone_owner, set()) == []
