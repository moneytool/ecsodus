"""Fates, atomic stack hand-off, blocker propagation, closure and teardown (PLAN §2.2, §2.5)."""

from __future__ import annotations

import json

from ecsodus.mappers.fates import (
    EXTERNAL_REFERENCE,
    IMPORT,
    MANUAL_CLEANUP,
    RETAIN_UNDER_EXISTING_OWNER,
    build_plan,
)
from tests.synthetic import app

CERT_DETAILS = {
    "DomainName": "api.example.com",
    "Tags": {"copilot-application": "demo", "copilot-environment": "test"},
}


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
    inv.out_of_band.append(OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", CERT_DETAILS))
    plan = build_plan(inv)
    cert = [r for r in plan.resources if r.physical_id == arn][0]
    assert cert.fate == IMPORT and cert.spec.tf_type == "aws_acm_certificate"
    kept = build_plan(app(worker_type="Request-Driven Web Service"))
    inv2 = app(worker_type="Request-Driven Web Service")
    inv2.out_of_band.append(OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", CERT_DETAILS))
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


def _oob_rows(plan):
    return {r.logical_id: r for r in plan.resources if r.logical_id.startswith("out-of-band:")}


def test_out_of_band_certificate_keeps_copilot_tags() -> None:
    """Without the tags in the configuration the provider plans their removal (an update)."""
    from ecsodus.model import OutOfBand

    inv = app()
    arn = "arn:aws:acm:us-west-2:123456789012:certificate/abc"
    inv.out_of_band.append(OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", CERT_DETAILS))
    cert = [r for r in build_plan(inv).resources if r.physical_id == arn][0]
    assert dict(cert.spec.body)["tags"] == CERT_DETAILS["Tags"]


def test_out_of_band_certificate_without_read_tags_is_blocked() -> None:
    from ecsodus.model import OutOfBand

    inv = app()
    arn = "arn:aws:acm:us-west-2:123456789012:certificate/abc"
    inv.out_of_band.append(
        OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", {"DomainName": "api.example.com"})
    )
    plan = build_plan(inv)
    assert not plan.stacks["demo-test"].handoff
    assert "re-run ecsodus inventory" in " ".join(plan.stacks["demo-test"].kept_because)


def _env_zone(inv) -> None:
    """Give the synthetic env a delegated hosted zone, exported as Copilot exports it."""
    env = inv.stacks["demo-test"]
    env.template_body = env.template_body.replace(
        "Outputs:\n",
        "  EnvironmentHostedZone:\n    Type: AWS::Route53::HostedZone\n"
        "    Properties:\n      Name: test.demo.example.com\n"
        "      HostedZoneConfig:\n        Comment: env zone\nOutputs:\n",
    )
    env.resources.append(
        type(env.resources[0])("EnvironmentHostedZone", "AWS::Route53::HostedZone", "ZENV1")
    )
    env.exports["demo-test-HostedZone"] = "ZENV1"
    inv.live["ZENV1"] = {
        "HostedZone": {"Name": "test.demo.example.com.", "Config": {"Comment": "env zone"}},
        "NameServers": ["ns-1.awsdns-01.org"],
        "RecordSets": [
            {"Name": "test.demo.example.com.", "Type": "SOA", "TTL": 900,
             "ResourceRecords": [{"Value": "soa"}]},
            # Owned by the api stack's RecordSetGroup (Copilot's LoadBalancerDNSAlias).
            {"Name": "api.test.demo.example.com.", "Type": "A",
             "AliasTarget": {"HostedZoneId": "Z1H1FL5HABSF5", "DNSName": "lb.example.",
                             "EvaluateTargetHealth": False}},
            # Written by the env CustomDomainAction (out of band).
            {"Name": "web.test.demo.example.com.", "Type": "A",
             "AliasTarget": {"HostedZoneId": "Z1H1FL5HABSF5", "DNSName": "lb.example.",
                             "EvaluateTargetHealth": True}},
        ],
    }  # fmt: skip


def test_record_set_group_record_is_not_imported_twice() -> None:
    inv = app()
    _env_zone(inv)
    api = inv.stacks["demo-test-api"]
    api.template_body += (
        "  LoadBalancerDNSAlias:\n    Type: AWS::Route53::RecordSetGroup\n    Properties:\n"
        "      HostedZoneId:\n        Fn::ImportValue: !Sub '${AppName}-${EnvName}-HostedZone'\n"
        "      RecordSets:\n        - Name: !Sub '${WorkloadName}.test.demo.example.com'\n"
        "          Type: A\n          AliasTarget:\n            HostedZoneId: !GetAtt "
        "EnvControllerAction.PublicLoadBalancerHostedZone\n            DNSName: !GetAtt "
        "EnvControllerAction.PublicLoadBalancerDNSName\n"
    )
    api.resources.append(
        type(api.resources[0])("LoadBalancerDNSAlias", "AWS::Route53::RecordSetGroup", "api-alias")
    )
    oob = _oob_rows(build_plan(inv))
    assert "out-of-band:api.test.demo.example.com/A" not in oob  # the stack owns it
    assert "out-of-band:web.test.demo.example.com/A" in oob  # written by CustomDomainAction


def test_undeployed_record_set_group_does_not_claim_a_live_record() -> None:
    """A RecordSetGroup whose Condition is false (so it was never deployed) owns nothing: the
    live record it would have described is still imported out of band (review on #27)."""
    inv = app()
    _env_zone(inv)
    api = inv.stacks["demo-test-api"]
    api.template_body += (
        "  WebAlias:\n    Type: AWS::Route53::RecordSetGroup\n    Condition: Never\n"
        "    Properties:\n      HostedZoneId:\n"
        "        Fn::ImportValue: !Sub '${AppName}-${EnvName}-HostedZone'\n"
        "      RecordSets:\n        - Name: web.test.demo.example.com\n          Type: A\n"
        "          AliasTarget:\n            HostedZoneId: Z1H1FL5HABSF5\n"
        "            DNSName: lb.example\n"
    )
    never = "  Never: !Equals [a, b]\n"
    if "\nConditions:\n" in api.template_body:
        api.template_body = api.template_body.replace(
            "\nConditions:\n", "\nConditions:\n" + never, 1
        )
    else:
        api.template_body += "Conditions:\n" + never
    plan = build_plan(inv)
    oob = _oob_rows(plan)
    assert "out-of-band:web.test.demo.example.com/A" in oob
    assert plan.stacks["demo-test"].handoff and plan.stacks["demo-test-api"].handoff


def test_records_in_a_zone_ecsodus_does_not_import_are_external_references() -> None:
    """Root-zone aliases and their validation CNAMEs are written by retained handlers into a
    zone that is not Copilot's: reported, never silently dropped."""
    from ecsodus.model import OutOfBand

    inv = app()
    _env_zone(inv)
    inv.stacks["demo-test"].parameters["Aliases"] = json.dumps(
        {"api": ["web.test.demo.example.com", "www.example.com"]}
    )
    details = dict(CERT_DETAILS)
    details["DomainValidationOptions"] = [
        {
            "DomainName": "www.example.com",
            "ResourceRecord": {"Name": "_abc.www.example.com.", "Type": "CNAME", "Value": "_x."},
        }
    ]
    arn = "arn:aws:acm:us-west-2:123456789012:certificate/abc"
    inv.out_of_band.append(OutOfBand("acm_certificate", arn, "demo-test/HTTPSCert", details))
    plan = build_plan(inv)
    oob = _oob_rows(plan)
    assert oob["out-of-band:web.test.demo.example.com/A"].fate == IMPORT  # in the env zone
    for lid in ("out-of-band:www.example.com/A", "out-of-band:_abc.www.example.com/CNAME"):
        assert oob[lid].fate == EXTERNAL_REFERENCE and oob[lid].stack == "demo-test"
        assert "does not import" in oob[lid].reason
    assert plan.stacks["demo-test"].handoff
