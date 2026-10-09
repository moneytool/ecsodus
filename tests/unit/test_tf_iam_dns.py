"""tf_iam_dns mappers: IAM roles/policies/profiles, Route 53 zones/records, ACM certificates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ecsodus.mappers.tf_iam_dns  # noqa: F401  (registers the mappers)
from ecsodus import cfn
from ecsodus.emit import hcl
from ecsodus.mappers.resolve import Resolver
from ecsodus.mappers.tfmap import BLOCKED, NotImported, TfSpec, map_resource
from ecsodus.model import Inventory, Stack
from tests.helpers import ACCOUNT, FIXTURES, inventory_from_template

SYN = Path(__file__).parents[1] / "fixtures" / "synthetic"
RENDERED = FIXTURES / "rendered"

IAM_DNS_TYPES = {
    "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy", "AWS::IAM::InstanceProfile",
    "AWS::Route53::HostedZone", "AWS::Route53::RecordSet", "AWS::Route53::RecordSetGroup",
    "AWS::CertificateManager::Certificate",
}  # fmt: skip


def _map(inv: Inventory, stack: Stack, lid: str) -> TfSpec | NotImported:
    tpl = cfn.load(stack.template_body)
    return map_resource(
        inv, stack, Resolver(inv, stack, tpl), stack.resource(lid), tpl["Resources"][lid]
    )


def _spec(inv: Inventory, stack: Stack, lid: str) -> TfSpec:
    out = _map(inv, stack, lid)
    assert isinstance(out, TfSpec), out
    return out


def _args(spec: TfSpec) -> dict:
    return dict(spec.body)


def _blocks(spec: TfSpec, name: str) -> list[dict]:
    return [dict(v.body) for k, v in spec.body if k == name and isinstance(v, hcl.Block)]


def _pid(stack: Stack, lid: str) -> str:
    return stack.resource(lid).physical_id


def _svc() -> tuple[Inventory, Stack]:
    return inventory_from_template(RENDERED / "workloads" / "svc-test.stack.yml")


# -- IAM roles --------------------------------------------------------------------------------


def test_execution_role_without_live_policy_names_lists_policies_in_notes():
    inv, stack = _svc()
    role = _pid(stack, "ExecutionRole")
    spec = _spec(inv, stack, "ExecutionRole")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_iam_role", role, False)
    assert a["name"] == role
    trust = json.loads(a["assume_role_policy"])
    assert trust["Statement"][0]["Principal"] == {"Service": "ecs-tasks.amazonaws.com"}
    assert "inline_policy" not in a and "managed_policy_arns" not in a
    assert spec.fidelity == "partial"
    notes = " ".join(spec.notes)
    # EnvFileARN is empty, so only the secrets policy exists (the !If drops the env-file one).
    assert f'"{role}:my-app-test-feSecretsPolicy"' in notes
    assert "GetEnvFilePolicy" not in notes
    policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    assert f'"{role}/{policy_arn}"' in notes


def test_task_role_inline_policies_emitted_when_live_matches_exactly():
    inv, stack = _svc()
    role = _pid(stack, "TaskRole")
    inv.live[role] = {"InlinePolicyNames": ["Publish2SNS", "DenyIAM"]}
    spec = _spec(inv, stack, "TaskRole")
    inline = _blocks(spec, "inline_policy")
    assert [b["name"] for b in inline] == ["DenyIAM", "Publish2SNS"]
    deny = json.loads(inline[0]["policy"])
    assert deny["Statement"][0] == {"Effect": "Deny", "Action": "iam:*", "Resource": "*"}
    assert spec.fidelity == "full"

    # Another stack attached an extra inline policy: inline_policy (exclusive) would delete it.
    inv.live[role] = {"InlinePolicyNames": ["Publish2SNS", "DenyIAM", "fe-S3Access"]}
    spec = _spec(inv, stack, "TaskRole")
    assert not _blocks(spec, "inline_policy") and spec.fidelity == "partial"
    assert any("fe-S3Access" in n and f'"{role}:DenyIAM"' in n for n in spec.notes)


def test_every_rendered_role_maps():
    for path in sorted(RENDERED.rglob("*.yml")):
        if path.name.endswith("manifest.yml"):
            continue
        inv, stack = inventory_from_template(path)
        for res in stack.resources:
            if res.type != "AWS::IAM::Role":
                continue
            out = _map(inv, stack, res.logical_id)
            if isinstance(out, NotImported):
                assert "unhandled properties" not in out.reason, (path.name, out.reason)
            else:
                assert out.tf_type == "aws_iam_role" and out.import_id == res.physical_id


# -- IAM policies / profiles ------------------------------------------------------------------


def test_inline_policy_on_env_manager_role():
    inv, stack = inventory_from_template(RENDERED / "workloads" / "static-site-test.stack.yml")
    spec = _spec(inv, stack, "EnvManagerS3Access")
    assert spec.tf_type == "aws_iam_role_policy"
    assert spec.import_id == "my-app-test-EnvManagerRole:static-S3Access"
    a = _args(spec)
    assert (a["role"], a["name"]) == ("my-app-test-EnvManagerRole", "static-S3Access")
    doc = json.loads(a["policy"])
    assert doc["Version"] == "2012-10-17"  # an unquoted YAML date stays a string
    bucket = _pid(stack, "Bucket")
    assert doc["Statement"][0]["Resource"] == [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]


def test_inline_policy_on_several_roles_is_blocked():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    out = _map(inv, stack, "SharedPolicy")
    assert isinstance(out, NotImported) and out.fate == BLOCKED
    assert "2 roles" in out.reason


def test_managed_policy_name_and_path_from_arn():
    inv, stack = inventory_from_template(SYN / "s3-ddb-addons.yml", kind="addons")
    arn = _pid(stack, "assetsAccessPolicy")
    spec = _spec(inv, stack, "assetsAccessPolicy")
    assert (spec.tf_type, spec.import_id) == ("aws_iam_policy", arn)
    a = _args(spec)
    assert a["name"] == arn.rsplit("/", 1)[1] and "path" not in a
    assert a["description"] == f"Grants CRUD access to the S3 bucket {_pid(stack, 'assetsBucket')}"
    assert spec.fidelity == "full"

    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    arn = f"arn:aws:iam::{ACCOUNT}:policy/copilot/demo-attached"
    stack.resource("AttachedManaged").physical_id = arn
    stack.resource("Role").physical_id = "demo-worker"
    spec = _spec(inv, stack, "AttachedManaged")
    assert (_args(spec)["name"], _args(spec)["path"]) == ("demo-attached", "/copilot/")
    assert spec.fidelity == "partial"
    assert any(f'(import id "demo-worker/{arn}")' in n for n in spec.notes)


def test_instance_profile():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    stack.resource("Role").physical_id = "demo-worker"
    stack.resource("Profile").physical_id = "demo-worker-profile"
    spec = _spec(inv, stack, "Profile")
    assert (spec.tf_type, spec.import_id) == ("aws_iam_instance_profile", "demo-worker-profile")
    assert _args(spec) == {"name": "demo-worker-profile", "path": "/", "role": "demo-worker"}


# -- Route 53 ---------------------------------------------------------------------------------


def _dns() -> tuple[Inventory, Stack]:
    return inventory_from_template(
        SYN / "app-dns.yml",
        stack_name="demo-infrastructure-roles",
        kind="app",
        env=None,
        workload=None,
        workload_type=None,
        params={
            "AppName": "demo",
            "AppDomainName": "example.com",
            "AppDomainHostedZoneID": "ZPARENT",
        },
    )


def test_app_hosted_zone_keeps_its_comment():
    inv, stack = _dns()
    zone = _pid(stack, "AppHostedZone")
    spec = _spec(inv, stack, "AppHostedZone")
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_route53_zone", zone, True)
    assert _args(spec) == {
        "name": "demo.example.com",
        "comment": "Hosted zone for copilot application demo: demo.example.com",
    }


def test_hosted_zone_tags_come_from_the_live_read():
    """Live zone tags win over the stack-tag guess (whether CloudFormation copies stack tags
    onto a hosted zone is not assumed)."""
    inv, stack = _dns()
    stack.tags = {"copilot-application": "demo"}
    zone = _pid(stack, "AppHostedZone")
    inv.live[zone] = {"Tags": [{"Key": "owner", "Value": "dns-team"}]}
    assert _args(_spec(inv, stack, "AppHostedZone"))["tags"] == {"owner": "dns-team"}
    inv.live[zone] = {"Tags": []}
    assert "tags" not in _args(_spec(inv, stack, "AppHostedZone"))


def test_private_env_hosted_zone_without_comment():
    inv, stack = inventory_from_template(
        RENDERED / "environments" / "template-with-basic-manifest.yml",
        stack_name="demo-test", kind="env", workload=None, workload_type=None,
    )  # fmt: skip
    spec = _spec(inv, stack, "InternalWorkloadsHostedZone")
    a = _args(spec)
    assert a["comment"] == ""  # not the provider default "Managed by Terraform"
    assert _blocks(spec, "vpc") == [{"vpc_id": _pid(stack, "VPC"), "vpc_region": "us-west-2"}]


def test_delegation_record_uses_live_name_servers():
    inv, stack = _dns()
    out = _map(inv, stack, "AppDomainDelegationRecordSet")
    assert isinstance(out, NotImported) and "NameServers" in out.reason
    ns = ["ns-1.awsdns-01.org", "ns-2.awsdns-02.com"]
    inv.live[_pid(stack, "AppHostedZone")] = {"NameServers": ns}
    spec = _spec(inv, stack, "AppDomainDelegationRecordSet")
    assert (spec.tf_type, spec.import_id) == ("aws_route53_record", "ZPARENT_demo.example.com_NS")
    assert _args(spec) == {
        "zone_id": "ZPARENT",
        "name": "demo.example.com",
        "type": "NS",
        "ttl": 900,
        "records": ns,
    }


def test_single_record_set_group_is_an_alias_record():
    inv, stack = _svc()
    spec = _spec(inv, stack, "LoadBalancerDNSAliasZ08230443CW11KE6JBNUA")
    assert spec.import_id == "Z08230443CW11KE6JBNUA_example.com_A"
    assert _blocks(spec, "alias") == [
        {"name": "mockImportALBDNSName", "zone_id": "mockHostedZoneID",
         "evaluate_target_health": False}
    ]  # fmt: skip
    assert "ttl" not in _args(spec)


def test_multi_record_set_group_is_blocked():
    inv, stack = inventory_from_template(RENDERED / "backend" / "https-path-alias-template.yml")
    out = _map(inv, stack, "LoadBalancerDNSAliasmockHostedZone1")
    assert isinstance(out, NotImported) and out.fate == BLOCKED and "2 records" in out.reason
    single = _map(inv, stack, "LoadBalancerDNSAliasmockHostedZone2")
    assert isinstance(single, NotImported)  # alias target is a custom-resource output
    inv.live[_pid(stack, "EnvControllerAction")] = {
        "InternalLoadBalancerHostedZone": "Z1H1FL5HABSF5",
        "InternalLoadBalancerDNSName": "internal-demo-123.us-west-2.elb.amazonaws.com",
    }
    spec = _spec(inv, stack, "LoadBalancerDNSAliasmockHostedZone2")
    assert spec.import_id == "mockHostedZone2_example.com_A"
    assert _blocks(spec, "alias")[0]["zone_id"] == "Z1H1FL5HABSF5"


def test_weighted_record_import_id_has_set_identifier():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    spec = _spec(inv, stack, "Weighted")
    assert spec.import_id == "Z0123456789ABCDEFGHIJ_api.demo.example.com_CNAME_blue"
    assert _args(spec)["set_identifier"] == "blue"
    assert _blocks(spec, "weighted_routing_policy") == [{"weight": 10}]
    out = _map(inv, stack, "ByZoneName")
    assert isinstance(out, NotImported) and "HostedZoneName" in out.reason


# -- ACM --------------------------------------------------------------------------------------


def test_acm_certificate():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    arn = f"arn:aws:acm:us-west-2:{ACCOUNT}:certificate/7e7a28d2-163f-4b8f-b9cd-822f96c08d6a"
    stack.resource("Cert").physical_id = arn
    spec = _spec(inv, stack, "Cert")
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_acm_certificate", arn, False)
    a = _args(spec)
    assert a["domain_name"] == "api.demo.example.com"
    assert a["subject_alternative_names"] == ["*.api.demo.example.com"]
    assert a["validation_method"] == "DNS"
    assert any("validation records" in n for n in spec.notes)


# -- coverage ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        RENDERED / "backend" / "http-autoscaling-template.yml",
        RENDERED / "backend" / "http-only-path-template.yml",
        RENDERED / "backend" / "http-full-config-template.yml",
        RENDERED / "workloads" / "svc-nlb-test.stack.yml",
        RENDERED / "workloads" / "svc-staging.stack.yml",
    ],
    ids=lambda p: p.name,
)
def test_rendered_record_set_groups_never_hit_unknown_properties(path):
    inv, stack = inventory_from_template(path)
    for res in stack.resources:
        if res.type in IAM_DNS_TYPES:
            out = _map(inv, stack, res.logical_id)
            if isinstance(out, NotImported):
                assert "unhandled properties" not in out.reason, (res.logical_id, out.reason)


def test_all_iam_dns_types_are_covered():
    used: set[str] = set()
    for p in list(RENDERED.rglob("*.yml")) + list(SYN.glob("*.yml")):
        if p.name.endswith("manifest.yml"):
            continue
        used |= {b["Type"] for b in cfn.load(p.read_text())["Resources"].values()}
    assert used & IAM_DNS_TYPES == IAM_DNS_TYPES
