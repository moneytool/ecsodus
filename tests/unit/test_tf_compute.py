"""Compute-family mappers against real Copilot-rendered templates (no AWS calls)."""

from __future__ import annotations

import re
from typing import Any

import pytest

import ecsodus.mappers.tf_compute  # noqa: F401  (registers the mappers)
from ecsodus import cfn
from ecsodus.emit import hcl
from ecsodus.mappers.resolve import Resolver
from ecsodus.mappers.tfmap import BLOCKED, MANUAL_CLEANUP, NotImported, TfSpec, map_resource
from ecsodus.model import Inventory, Resource, Stack
from tests.helpers import ACCOUNT, FIXTURES, REGION, inventory_from_template

R = FIXTURES / "rendered"
ARN = f"{REGION}:{ACCOUNT}"
ELB = f"arn:aws:elasticloadbalancing:{ARN}"
CLUSTER = "my-app-test-Cluster-abc"
LISTENER = f"{ELB}:listener/app/my-app-test-pub/0123456789abcdef/1111aaaa2222bbbb"
TD_ARN = f"arn:aws:ecs:{ARN}:task-definition/my-app-test-fe:7"
SVC_ARN = f"arn:aws:ecs:{ARN}:service/{CLUSTER}/my-app-test-fe-Service-XYZ"
SRV_ARN = f"arn:aws:servicediscovery:{ARN}:service/srv-abcdefghijklmnop"


def add_env_exports(inv: Inventory, app: str = "my-app", env: str = "test") -> None:
    """A fake env stack carrying the exports workload templates import."""
    p = f"{app}-{env}"
    inv.stacks[p] = Stack(
        name=p,
        kind="env",
        env=env,
        exports={
            f"{p}-ClusterId": CLUSTER,
            f"{p}-PublicSubnets": "subnet-0aaa,subnet-0bbb",
            f"{p}-PrivateSubnets": "subnet-0ccc,subnet-0ddd",
            f"{p}-EnvironmentSecurityGroup": "sg-0env",
            f"{p}-VpcId": "vpc-0abc",
            f"{p}-ServiceDiscoveryNamespaceID": "ns-abcdefghijklmnop",
            "MyUserDBAccessSecurityGroup1": "sg-0db1",
            "MyUserDBAccessSecurityGroup2": "sg-0db2",
            "MyDB": "mydb",
            "stack-SSMGHUserName": f"arn:aws:ssm:{ARN}:parameter/gh-user",
            "stack-MongoUserName": f"arn:aws:ssm:{ARN}:parameter/mongo-user",
        },
    )


def set_pid(stack: Stack, lid: str, pid: str) -> None:
    res = stack.resource(lid)
    assert res is not None, lid
    res.physical_id = pid


def load(name: str, stack_name: str = "my-app-test-fe", **kw: Any) -> tuple[Inventory, Stack]:
    inv, stack = inventory_from_template(R / name, stack_name=stack_name, **kw)
    add_env_exports(inv)
    return inv, stack


def run(inv: Inventory, stack: Stack, lid: str) -> TfSpec | NotImported:
    tpl = cfn.load(stack.template_body)
    res = stack.resource(lid)
    assert res is not None, lid
    return map_resource(inv, stack, Resolver(inv, stack, tpl), res, tpl["Resources"][lid])


def spec_of(result: TfSpec | NotImported) -> TfSpec:
    assert isinstance(result, TfSpec), result
    return result


def args(spec: TfSpec) -> dict[str, Any]:
    """Attributes and blocks by name (repeated blocks become lists)."""
    out: dict[str, Any] = {}
    for k, v in spec.body:
        if k in out:
            out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
        else:
            out[k] = v
    return out


def block_args(b: hcl.Block) -> dict[str, Any]:
    return dict(b.body)


def render(spec: TfSpec) -> str:
    return hcl.block("resource", (spec.tf_type, "x"), spec.body)


def blocked(result: TfSpec | NotImported, fragment: str) -> None:
    assert isinstance(result, NotImported), result
    assert result.fate == BLOCKED
    assert fragment in result.reason, result.reason


# -- svc-test (Load Balanced Web Service on an imported ALB) --------------------------------


@pytest.fixture
def svc() -> tuple[Inventory, Stack]:
    inv, stack = load("workloads/svc-test.stack.yml")
    set_pid(stack, "TaskDefinition", TD_ARN)
    set_pid(stack, "Service", SVC_ARN)
    inv.live["srv-abcdefghijklmnop"] = {"Arn": SRV_ARN}
    return inv, stack


LIVE_DEFS = [
    {
        "name": "fe",
        "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/fe@sha256:abc",
        "cpu": 0,
        "essential": True,
        "portMappings": [{"containerPort": 4000, "hostPort": 4000, "protocol": "tcp"}],
        "environment": [{"name": "LOG_LEVEL", "value": "info"}],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {"awslogs-group": "/copilot/my-app-test-fe", "awslogs-region": REGION},
        },
    }
]


def test_task_definition_uses_live_container_definitions(svc):
    inv, stack = svc
    inv.live[TD_ARN] = {"containerDefinitions": LIVE_DEFS}
    spec = spec_of(run(inv, stack, "TaskDefinition"))
    assert spec.tf_type == "aws_ecs_task_definition"
    assert spec.import_id == TD_ARN
    assert spec.fidelity == "full"
    a = args(spec)
    assert a["family"] == "my-app-test-fe"
    assert a["cpu"] == "256" and a["memory"] == "512"
    assert a["network_mode"] == "awsvpc"
    assert a["requires_compatibilities"] == ["FARGATE"]
    assert a["execution_role_arn"].endswith(":role/my-app-test-fe-ExecutionRole-ABC123")
    assert a["task_role_arn"].endswith(":role/my-app-test-fe-TaskRole-ABC123")
    assert isinstance(a["container_definitions"], hcl.Raw)
    expr = a["container_definitions"].expr
    assert expr.startswith("jsonencode(") and "sha256:abc" in expr and "hostPort" in expr
    assert block_args(a["volume"]) == {"name": "persistence"}
    render(spec)


def test_task_definition_converts_template_when_live_absent(svc):
    inv, stack = svc
    spec = spec_of(run(inv, stack, "TaskDefinition"))
    assert spec.fidelity == "partial" and spec.notes
    expr = args(spec)["container_definitions"].expr
    for camel in (
        "portMappings",
        "containerPort = 4000",
        "logConfiguration",
        "mountPoints",
        "sourceVolume",
        "readOnly = true",
        'awslogs-group = "/copilot/my-app-test-fe"',
    ):
        assert camel in expr, camel
    assert "PortMappings" not in expr


def test_task_definition_conversion_is_fail_closed(svc):
    inv, stack = svc
    tpl = cfn.load(stack.template_body)
    tpl["Resources"]["TaskDefinition"]["Properties"]["ContainerDefinitions"][0][
        "LinuxParameters"
    ] = {"InitProcessEnabled": True}
    res = stack.resource("TaskDefinition")
    body = tpl["Resources"]["TaskDefinition"]
    blocked(map_resource(inv, stack, Resolver(inv, stack, tpl), res, body), "LinuxParameters")


def test_service_literal_task_definition_and_lifecycle(svc):
    inv, stack = svc
    inv.live[SVC_ARN] = {"desiredCount": 2}
    spec = spec_of(run(inv, stack, "Service"))
    assert spec.tf_type == "aws_ecs_service"
    assert spec.import_id == f"{CLUSTER}/my-app-test-fe-Service-XYZ"
    a = args(spec)
    assert a["name"] == "my-app-test-fe-Service-XYZ"
    assert a["cluster"] == f"arn:aws:ecs:{ARN}:cluster/{CLUSTER}"
    assert a["task_definition"] == TD_ARN and isinstance(a["task_definition"], str)
    assert a["desired_count"] == 2
    life = block_args(a["lifecycle"])
    assert life["ignore_changes"] == hcl.Raw("[task_definition, desired_count]")
    assert a["launch_type"] == "FARGATE"
    assert a["platform_version"] == "LATEST"
    assert a["propagate_tags"] == "SERVICE"
    assert a["health_check_grace_period_seconds"] == 60
    assert a["deployment_maximum_percent"] == 200
    assert a["deployment_minimum_healthy_percent"] == 100
    assert block_args(a["deployment_circuit_breaker"]) == {"enable": True, "rollback": True}
    assert block_args(a["alarms"]) == {"alarm_names": [], "enable": False, "rollback": True}
    net = block_args(a["network_configuration"])
    assert net["subnets"] == ["subnet-0aaa", "subnet-0bbb"]
    assert net["security_groups"] == [
        "sg-0env",
        "sg-0c10c4fe23f5e5361",
        "sg-09295097b2a41b59d",
        "sg-0db1",
        "sg-0db2",
    ]
    assert net["assign_public_ip"] is True
    lbs = a["load_balancer"]
    assert len(lbs) == 2
    assert block_args(lbs[0])["container_port"] == 4000
    assert block_args(a["service_registries"]) == {"registry_arn": SRV_ARN, "port": 4000}
    text = render(spec)
    assert re.search(rf'task_definition +=  *"{re.escape(TD_ARN)}"', text)
    assert "ignore_changes = [task_definition, desired_count]" in text


def test_service_prefers_live_task_definition_revision(svc):
    inv, stack = svc
    current = TD_ARN.replace(":7", ":9")
    inv.live[SVC_ARN] = {"desiredCount": 3, "taskDefinition": current}
    a = args(spec_of(run(inv, stack, "Service")))
    assert a["task_definition"] == current and a["desired_count"] == 3


def test_service_without_live_desired_count_is_blocked(svc):
    inv, stack = svc
    blocked(run(inv, stack, "Service"), "desiredCount")


@pytest.mark.parametrize("unsupported", ["tls", "testTrafficRules", "unknownTimeout"])
def test_service_connect_imported_from_live_primary_deployment(unsupported: str):
    """ADR-0011: Copilot enables Service Connect by default; adopt-in-place imports it as is."""
    inv, stack = load("workloads/svc-prod.stack.yml", stack_name="my-app-prod-fe", env="prod")
    add_env_exports(inv, env="prod")
    pid = f"arn:aws:ecs:{ARN}:service/{CLUSTER}/my-app-prod-fe-Service-XYZ"
    set_pid(stack, "Service", pid)
    inv.stacks["my-app-prod"].exports["my-app-prod-ClusterId"] = CLUSTER
    inv.live[pid] = {"desiredCount": 3}
    blocked(run(inv, stack, "Service"), "PRIMARY deployment")
    sc = {
        "enabled": True,
        "namespace": "prod.my-app.local",
        "services": [
            {
                "portName": "target",
                "discoveryName": "fe-sc",
                "clientAliases": [{"port": 80, "dnsName": "fe"}],
                "timeout": {"idleTimeoutSeconds": 60, "perRequestTimeoutSeconds": 0},
            }
        ],
        "logConfiguration": {"logDriver": "awslogs", "options": {"awslogs-group": "/copilot/x"}},
    }
    inv.live[pid] = {
        "desiredCount": 3,
        "deployments": [{"status": "PRIMARY", "serviceConnectConfiguration": sc}],
    }
    spec = spec_of(run(inv, stack, "Service"))
    text = render(spec)
    assert "service_connect_configuration {" in text
    assert 'namespace = "prod.my-app.local"' in text
    assert 'discovery_name = "fe-sc"' in text and "client_alias {" in text
    config = block_args(args(spec)["service_connect_configuration"])
    timeout = block_args(block_args(config["service"])["timeout"])
    assert timeout == {"idle_timeout_seconds": 60, "per_request_timeout_seconds": 0}
    if unsupported == "tls":
        sc["services"][0]["tls"] = {"issuerCertificateAuthority": {}}
        reason = "Service Connect service keys not supported"
    elif unsupported == "testTrafficRules":
        sc["services"][0]["clientAliases"][0]["testTrafficRules"] = {
            "header": {"name": "x-test", "value": "canary"}
        }
        reason = "Service Connect client alias keys not supported"
    else:
        sc["services"][0]["timeout"] = {"idleTimeoutSeconds": 60, "unknownTimeout": 30}
        reason = "Service Connect timeout keys not supported"
    blocked(run(inv, stack, "Service"), reason)


def test_backend_service_enable_execute_command():
    inv, stack = load("backend/http-full-config-template.yml")
    set_pid(stack, "Service", SVC_ARN)
    inv.live[SVC_ARN] = {"desiredCount": 1}
    inv.live["srv-abcdefghijklmnop"] = {"Arn": SRV_ARN}
    stack.parameters.update(AppName="my-app", EnvName="test")
    a = args(spec_of(run(inv, stack, "Service")))
    assert a["enable_execute_command"] is True


def test_lambda_is_manual_cleanup(svc):
    inv, stack = svc
    for lid in ("DynamicDesiredCountFunction", "EnvControllerFunction", "RulePriorityFunction"):
        result = run(inv, stack, lid)
        assert isinstance(result, NotImported) and result.fate == MANUAL_CLEANUP


def test_lambda_permission_is_manual_cleanup():
    inv, stack = load("workloads/worker-test.stack.yml")
    lid = next(r.logical_id for r in stack.resources if r.type == "AWS::Lambda::Permission")
    result = run(inv, stack, lid)
    assert isinstance(result, NotImported) and result.fate == MANUAL_CLEANUP


# -- load balancing ---------------------------------------------------------------------------

TG_LIVE = {
    "TargetGroupName": "my-app-Targe-ABCDEF123456",
    "HealthCheckEnabled": True,
    "HealthCheckIntervalSeconds": 30,
    "HealthCheckPath": "/",
    "HealthCheckPort": "traffic-port",
    "HealthCheckProtocol": "HTTP",
    "HealthCheckTimeoutSeconds": 5,
    "HealthyThresholdCount": 5,
    "UnhealthyThresholdCount": 2,
    "Matcher": {"HttpCode": "200"},
    "Attributes": [
        {"Key": "deregistration_delay.timeout_seconds", "Value": "60"},
        {"Key": "stickiness.enabled", "Value": "false"},
        {"Key": "stickiness.type", "Value": "lb_cookie"},
        {"Key": "stickiness.lb_cookie.duration_seconds", "Value": "86400"},
        {"Key": "slow_start.duration_seconds", "Value": "0"},
        {"Key": "load_balancing.algorithm.type", "Value": "round_robin"},
    ],
}


def test_target_group_from_template_and_live(svc):
    inv, stack = svc
    pid = stack.resource("TargetGroupForImportedALB").physical_id
    inv.live[pid] = dict(TG_LIVE)
    spec = spec_of(run(inv, stack, "TargetGroupForImportedALB"))
    assert spec.tf_type == "aws_lb_target_group" and spec.import_id == pid
    assert spec.fidelity == "full"
    a = args(spec)
    assert a["name"] == "my-app-Targe-ABCDEF123456"
    assert (a["port"], a["protocol"], a["target_type"], a["vpc_id"]) == (
        4000,
        "HTTP",
        "ip",
        "vpc-0abc",
    )
    hc = block_args(a["health_check"])
    assert hc["healthy_threshold"] == 5 and hc["unhealthy_threshold"] == 2
    assert hc["path"] == "/" and hc["matcher"] == "200" and hc["port"] == "traffic-port"
    assert a["deregistration_delay"] == "60"
    assert block_args(a["stickiness"]) == {
        "enabled": False,
        "type": "lb_cookie",
        "cookie_duration": 86400,
    }


def test_target_group_unmapped_attribute_is_partial(svc):
    inv, stack = svc
    pid = stack.resource("TargetGroupForImportedALB").physical_id
    inv.live[pid] = dict(TG_LIVE, Attributes=[*TG_LIVE["Attributes"], {"Key": "x.y", "Value": "1"}])
    spec = spec_of(run(inv, stack, "TargetGroupForImportedALB"))
    assert spec.fidelity == "partial" and "x.y" in spec.notes[0]


def test_target_group_missing_live_is_blocked(svc):
    inv, stack = svc
    blocked(run(inv, stack, "TargetGroupForImportedALB"), "TargetGroupName")
    pid = stack.resource("TargetGroupForImportedALB").physical_id
    inv.live[pid] = {k: v for k, v in TG_LIVE.items() if k != "HealthyThresholdCount"}
    blocked(run(inv, stack, "TargetGroupForImportedALB"), "HealthyThresholdCount")


def test_listener_rule_priority_from_live():
    inv, stack = load("backend/https-path-alias-template.yml")
    rule = f"{LISTENER.replace(':listener/', ':listener-rule/')}/9999cccc0000dddd"
    set_pid(stack, "HTTPSListenerRule", rule)
    inv.live[stack.resource("EnvControllerAction").physical_id] = {
        "InternalHTTPSListenerArn": LISTENER
    }
    inv.live[rule] = {"Priority": "12"}
    spec = spec_of(run(inv, stack, "HTTPSListenerRule"))
    assert spec.tf_type == "aws_lb_listener_rule" and spec.import_id == rule
    a = args(spec)
    assert a["listener_arn"] == LISTENER
    assert a["priority"] == 12
    action = block_args(a["action"])
    assert action["type"] == "forward"
    assert action["target_group_arn"] == stack.resource("TargetGroup").physical_id
    host, path = (block_args(c) for c in a["condition"])
    assert block_args(host["host_header"])["values"] == [
        "example.com",
        "foobar.com",
        "*.foobar.com",
    ]
    assert block_args(path["path_pattern"])["values"][0] == "/https-path-alias-path"
    render(spec)


def test_listener_rule_listener_derived_from_rule_arn_when_template_unresolvable():
    inv, stack = load("backend/https-path-alias-template.yml")
    rule = f"{LISTENER.replace(':listener/', ':listener-rule/')}/9999cccc0000dddd"
    set_pid(stack, "HTTPSListenerRule", rule)
    inv.live[rule] = {"Priority": "3"}
    a = args(spec_of(run(inv, stack, "HTTPSListenerRule")))
    assert a["listener_arn"] == LISTENER


def test_listener_rule_without_live_priority_is_blocked():
    inv, stack = load("backend/https-path-alias-template.yml")
    blocked(run(inv, stack, "HTTPSListenerRule"), "Priority")


def test_listener_rule_redirect_and_source_ip(svc):
    inv, stack = svc
    # The fixture's listener is the literal "MockListenerARN1", which disagrees with any rule
    # ARN: fail closed.
    lid = "HTTPListenerRedirectRuleForImportedALB"
    inv.live[stack.resource(lid).physical_id] = {"Priority": "5"}
    blocked(run(inv, stack, lid), "MockListenerARN1")
    # Treat the rule as belonging to that listener to exercise the action/condition mapping.
    set_pid(stack, lid, "MockListenerARN1-rule")
    inv.live["MockListenerARN1-rule"] = {"Priority": "5"}
    a = args(spec_of(run(inv, stack, lid)))
    redirect = block_args(block_args(a["action"])["redirect"])
    assert redirect == {
        "host": "#{host}",
        "path": "/#{path}",
        "port": "443",
        "protocol": "HTTPS",
        "query": "#{query}",
        "status_code": "HTTP_301",
    }
    src = block_args(a["condition"][0])["source_ip"]
    assert "192.0.2.0/24" in block_args(src)["values"]


def test_listener_certificate_import_id(svc):
    inv, stack = svc
    cert = f"arn:aws:acm:{ARN}:certificate/abcd"
    res = Resource("ExtraCert", "AWS::ElasticLoadBalancingV2::ListenerCertificate", "whatever")
    body = {
        "Type": res.type,
        "Properties": {"ListenerArn": LISTENER, "Certificates": [{"CertificateArn": cert}]},
    }
    spec = spec_of(map_resource(inv, stack, Resolver(inv, stack), res, body))
    assert spec.tf_type == "aws_lb_listener_certificate"
    assert spec.import_id == f"{LISTENER}_{cert}"
    two = {
        **body,
        "Properties": {
            **body["Properties"],
            "Certificates": [{"CertificateArn": cert}, {"CertificateArn": cert + "2"}],
        },
    }
    blocked(map_resource(inv, stack, Resolver(inv, stack), res, two), "exactly one")


# -- env stack: ALB, listeners, namespace ---------------------------------------------------


@pytest.fixture
def env() -> tuple[Inventory, Stack]:
    inv, stack = inventory_from_template(
        R / "environments/template-with-basic-manifest.yml",
        stack_name="my-app-test",
        kind="env",
        workload=None,
        workload_type=None,
        params={"CreateHTTPSListener": "true", "ALBWorkloads": "fe"},
    )
    return inv, stack


LB_ATTRS = [
    {"Key": "access_logs.s3.enabled", "Value": "false"},
    {"Key": "access_logs.s3.bucket", "Value": ""},
    {"Key": "access_logs.s3.prefix", "Value": ""},
    {"Key": "deletion_protection.enabled", "Value": "false"},
    {"Key": "idle_timeout.timeout_seconds", "Value": "60"},
    {"Key": "routing.http2.enabled", "Value": "true"},
    {"Key": "routing.http.drop_invalid_header_fields.enabled", "Value": "false"},
    {"Key": "routing.http.desync_mitigation_mode", "Value": "defensive"},
]


def test_load_balancer(env):
    inv, stack = env
    pid = stack.resource("PublicLoadBalancer").physical_id
    inv.live[pid] = {
        "LoadBalancerName": "my-app-Publi-1A2B3C",
        "Attributes": LB_ATTRS,
        "Scheme": "internet-facing",
        "Type": "application",
    }
    spec = spec_of(run(inv, stack, "PublicLoadBalancer"))
    assert spec.tf_type == "aws_lb" and spec.import_id == pid
    assert spec.stateful is False and spec.fidelity == "full"
    a = args(spec)
    assert a["name"] == "my-app-Publi-1A2B3C"
    assert a["internal"] is False and a["load_balancer_type"] == "application"
    assert a["subnets"] == [
        stack.resource("PublicSubnet1").physical_id,
        stack.resource("PublicSubnet2").physical_id,
    ]
    assert len(a["security_groups"]) == 2
    assert a["idle_timeout"] == 60 and a["enable_http2"] is True
    assert a["desync_mitigation_mode"] == "defensive"
    assert "enable_deletion_protection" not in a  # only emitted where on (PLAN §2.4)
    assert "access_logs" not in a
    inv.live[pid]["Attributes"] = [
        {"Key": "deletion_protection.enabled", "Value": "true"},
        {"Key": "access_logs.s3.enabled", "Value": "true"},
        {"Key": "access_logs.s3.bucket", "Value": "logs"},
        {"Key": "brand.new.attribute", "Value": "1"},
    ]
    spec = spec_of(run(inv, stack, "PublicLoadBalancer"))
    a = args(spec)
    assert a["enable_deletion_protection"] is True
    assert block_args(a["access_logs"]) == {"bucket": "logs", "enabled": True}
    assert spec.fidelity == "partial"


def test_load_balancer_scheme_mismatch_and_missing_live(env):
    inv, stack = env
    blocked(run(inv, stack, "PublicLoadBalancer"), "LoadBalancerName")
    pid = stack.resource("PublicLoadBalancer").physical_id
    inv.live[pid] = {"LoadBalancerName": "n", "Attributes": [], "Scheme": "internal"}
    blocked(run(inv, stack, "PublicLoadBalancer"), "Scheme")


def test_listeners(env):
    inv, stack = env
    http = spec_of(run(inv, stack, "HTTPListener"))
    assert http.tf_type == "aws_lb_listener"
    assert http.import_id == stack.resource("HTTPListener").physical_id
    a = args(http)
    assert a["port"] == 80 and a["protocol"] == "HTTP"
    assert a["load_balancer_arn"] == stack.resource("PublicLoadBalancer").physical_id
    da = block_args(a["default_action"])
    assert da == {
        "type": "forward",
        "target_group_arn": stack.resource("DefaultHTTPTargetGroup").physical_id,
    }
    https = args(spec_of(run(inv, stack, "HTTPSListener")))
    assert https["certificate_arn"] == stack.resource("HTTPSCert").physical_id
    assert "ssl_policy" not in https
    inv.live[stack.resource("HTTPSListener").physical_id] = {"SslPolicy": "ELBSecurityPolicy-X"}
    assert args(spec_of(run(inv, stack, "HTTPSListener")))["ssl_policy"] == "ELBSecurityPolicy-X"


def test_private_dns_namespace_import_id(env):
    inv, stack = env
    spec = spec_of(run(inv, stack, "ServiceDiscoveryNamespace"))
    vpc = stack.resource("VPC").physical_id
    assert spec.tf_type == "aws_service_discovery_private_dns_namespace"
    assert spec.import_id == f"ns-abcdefghijklmnop:{vpc}"
    assert args(spec)["vpc"] == vpc


# -- discovery, autoscaling, alarms ---------------------------------------------------------


def test_discovery_service(svc):
    inv, stack = svc
    spec = spec_of(run(inv, stack, "DiscoveryService"))
    assert spec.tf_type == "aws_service_discovery_service"
    assert spec.import_id == "srv-abcdefghijklmnop"
    a = args(spec)
    assert a["name"] == "fe" and a["namespace_id"] == "ns-abcdefghijklmnop"
    dns = block_args(a["dns_config"])
    assert dns["routing_policy"] == "MULTIVALUE"
    records = [block_args(v) for k, v in a["dns_config"].body if k == "dns_records"]
    assert records == [{"ttl": 10, "type": "A"}, {"ttl": 10, "type": "SRV"}]
    assert block_args(a["health_check_custom_config"]) == {"failure_threshold": 1}


def autoscaling(svc_fixture):
    inv, stack = svc_fixture
    target = f"service/{CLUSTER}/my-app-test-fe-Service-XYZ|ecs:service:DesiredCount|ecs"
    set_pid(stack, "AutoScalingTarget", target)
    return inv, stack


def test_scalable_target(svc):
    inv, stack = autoscaling(svc)
    spec = spec_of(run(inv, stack, "AutoScalingTarget"))
    assert spec.tf_type == "aws_appautoscaling_target"
    rid = f"service/{CLUSTER}/my-app-test-fe-Service-XYZ"
    assert spec.import_id == f"ecs/{rid}/ecs:service:DesiredCount"
    a = args(spec)
    assert (a["min_capacity"], a["max_capacity"], a["resource_id"]) == (2, 10, rid)
    assert "role_arn" not in a


def test_scaling_policies(svc):
    inv, stack = autoscaling(svc)
    rid = f"service/{CLUSTER}/my-app-test-fe-Service-XYZ"
    cpu = spec_of(run(inv, stack, "AutoScalingPolicyECSServiceAverageCPUUtilization"))
    name = "fe-ECSServiceAverageCPUUtilization-ScalingPolicy"
    assert cpu.tf_type == "aws_appautoscaling_policy"
    assert cpu.import_id == f"ecs/{rid}/ecs:service:DesiredCount/{name}"
    tt = block_args(args(cpu)["target_tracking_scaling_policy_configuration"])
    assert tt["target_value"] == 70 and tt["scale_in_cooldown"] == 120
    pre = block_args(tt["predefined_metric_specification"])
    assert pre == {"predefined_metric_type": "ECSServiceAverageCPUUtilization"}

    # The ALB policy needs the target group's full name, derived exactly from its ARN
    # (arn:...:targetgroup/<name>/<id> -> targetgroup/<name>/<id>).
    lid = "AutoScalingPolicyALBAverageResponseTime"
    tt = block_args(
        args(spec_of(run(inv, stack, lid)))["target_tracking_scaling_policy_configuration"]
    )
    cust = block_args(tt["customized_metric_specification"])
    assert cust["metric_name"] == "TargetResponseTime"
    assert cust["namespace"] == "AWS/ApplicationELB"


def test_alarm():
    inv, stack = load("workloads/svc-prod.stack.yml", stack_name="my-app-prod-fe", env="prod")
    add_env_exports(inv, env="prod")
    set_pid(stack, "CPURollbackAlarm", "my-app-prod-fe-CopilotRollbackCPUAlarm")
    set_pid(stack, "Service", f"arn:aws:ecs:{ARN}:service/{CLUSTER}/my-app-prod-fe-Svc")
    spec = spec_of(run(inv, stack, "CPURollbackAlarm"))
    assert spec.tf_type == "aws_cloudwatch_metric_alarm"
    assert spec.import_id == "my-app-prod-fe-CopilotRollbackCPUAlarm"
    a = args(spec)
    assert a["dimensions"] == {"ClusterName": CLUSTER, "ServiceName": "my-app-prod-fe-Svc"}
    assert (a["threshold"], a["period"], a["datapoints_to_alarm"]) == (70, 60, 2)
    assert a["comparison_operator"] == "GreaterThanOrEqualToThreshold"


# -- SNS / SQS ------------------------------------------------------------------------------


def test_sns_topic_and_policy(svc):
    inv, stack = svc
    topic = f"arn:aws:sns:{ARN}:my-app-test-fe-givesdogs"
    set_pid(stack, "givesdogsSNSTopic", topic)
    spec = spec_of(run(inv, stack, "givesdogsSNSTopic"))
    assert spec.tf_type == "aws_sns_topic" and spec.import_id == topic
    assert args(spec) == {"name": "my-app-test-fe-givesdogs", "kms_master_key_id": "alias/aws/sns"}
    pol = spec_of(run(inv, stack, "givesdogsSNSTopicPolicy"))
    assert pol.tf_type == "aws_sns_topic_policy" and pol.import_id == topic
    expr = args(pol)["policy"].expr
    assert expr.startswith("jsonencode(") and '"sns:Protocol" = "sqs"' in expr
    assert f"arn:aws:iam::{ACCOUNT}:root" in expr


def test_sns_topic_name_mismatch_is_blocked(svc):
    inv, stack = svc
    blocked(run(inv, stack, "givesdogsSNSTopic"), "TopicName")


def test_sqs_queue_and_policy():
    inv, stack = load("workloads/worker-test.stack.yml")
    base = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}"
    set_pid(stack, "EventsQueue", f"{base}/my-app-test-fe-EventsQueue-ABC")
    set_pid(stack, "DeadLetterQueue", f"{base}/my-app-test-fe-DeadLetterQueue-DEF")
    spec = spec_of(run(inv, stack, "EventsQueue"))
    assert spec.tf_type == "aws_sqs_queue"
    assert spec.import_id == f"{base}/my-app-test-fe-EventsQueue-ABC"
    assert spec.stateful is True
    a = args(spec)
    assert a["name"] == "my-app-test-fe-EventsQueue-ABC" and a["delay_seconds"] == 1
    assert a["kms_master_key_id"] == stack.resource("EventsKMSKey").physical_id
    assert f"arn:aws:sqs:{ARN}:my-app-test-fe-DeadLetterQueue-DEF" in a["redrive_policy"].expr
    pol = spec_of(run(inv, stack, "QueuePolicy"))
    assert pol.tf_type == "aws_sqs_queue_policy"
    assert pol.import_id == f"{base}/my-app-test-fe-EventsQueue-ABC"


# -- everything in the LBWS fixture renders -------------------------------------------------


def test_all_svc_test_resources_map_and_render(svc):
    inv, stack = svc
    inv.live[TD_ARN] = {"containerDefinitions": LIVE_DEFS}
    inv.live[SVC_ARN] = {"desiredCount": 2}
    for lid in ("TargetGroupForImportedALB", "TargetGroupForImportedALB1"):
        inv.live[stack.resource(lid).physical_id] = dict(TG_LIVE)
    for r in stack.resources:
        if r.type.startswith("Custom::") or r.type.startswith("AWS::IAM"):
            continue
        result = run(inv, stack, r.logical_id)
        if isinstance(result, TfSpec):
            render(result)


# -- fixes found by the full hand-off golden test (tests/golden/test_full_handoff.py) --------


def test_log_resource_policy(env):
    inv, stack = env
    stack.parameters["EnvironmentName"] = "test"
    spec = spec_of(run(inv, stack, "LogResourcePolicy"))
    assert spec.tf_type == "aws_cloudwatch_log_resource_policy"
    assert spec.import_id == "my-app-test-LogResourcePolicy"
    a = args(spec)
    assert a["policy_name"] == "my-app-test-LogResourcePolicy"
    assert '"Sid": "StateMachineToCloudWatchLogs"' in a["policy_document"]
    assert "log-group:/copilot/my-app-test-*" in a["policy_document"]
    render(spec)
    set_pid(stack, "LogResourcePolicy", "something-else")
    blocked(run(inv, stack, "LogResourcePolicy"), "PolicyName")


def test_log_resource_policy_resource_scoped_is_blocked(env):
    inv, stack = env
    res = stack.resource("LogResourcePolicy")
    body = {
        "Type": res.type,
        "Properties": {"PolicyName": res.physical_id, "PolicyDocument": "{}", "ResourceArn": "a"},
    }
    blocked(map_resource(inv, stack, Resolver(inv, stack), res, body), "ResourceArn")


def test_cluster_configuration_is_emitted(env):
    # Copilot's env cluster sets Configuration.ExecuteCommandConfiguration.Logging. The block is
    # not computed in the provider, so dropping it made the first plan remove the setting.
    inv, stack = env
    spec = spec_of(run(inv, stack, "Cluster"))
    a = args(spec)
    assert block_args(a["setting"]) == {"name": "containerInsights", "value": "disabled"}
    ecc = block_args(block_args(a["configuration"])["execute_command_configuration"])
    assert ecc == {"logging": "DEFAULT"}
    assert spec.fidelity == "partial"  # CapacityProviders: a separate resource
    assert "configuration {" in render(spec)


def test_cluster_unknown_properties_are_blocked(env):
    inv, stack = env
    res = stack.resource("Cluster")
    for props, fragment in (
        ({"ServiceConnectDefaults": {"Namespace": "x"}}, "ServiceConnectDefaults"),
        ({"Configuration": {"Future": {}}}, "Future"),
        (
            {"Configuration": {"ExecuteCommandConfiguration": {"Logging": "OVERRIDE", "X": 1}}},
            "ExecuteCommandConfiguration",
        ),
        ({"ClusterName": "other"}, "ClusterName"),
    ):
        body = {"Type": res.type, "Properties": props}
        blocked(map_resource(inv, stack, Resolver(inv, stack), res, body), fragment)


def test_cluster_execute_command_log_configuration(env):
    inv, stack = env
    res = stack.resource("Cluster")
    body = {
        "Type": res.type,
        "Properties": {
            "Configuration": {
                "ExecuteCommandConfiguration": {
                    "Logging": "OVERRIDE",
                    "KmsKeyId": "k",
                    "LogConfiguration": {
                        "CloudWatchLogGroupName": "/ecs/exec",
                        "CloudWatchEncryptionEnabled": "true",
                        "S3BucketName": "b",
                    },
                }
            }
        },
    }
    a = args(spec_of(map_resource(inv, stack, Resolver(inv, stack), res, body)))
    ecc = block_args(block_args(a["configuration"])["execute_command_configuration"])
    assert ecc["kms_key_id"] == "k" and ecc["logging"] == "OVERRIDE"
    assert block_args(ecc["log_configuration"]) == {
        "cloud_watch_encryption_enabled": True,
        "cloud_watch_log_group_name": "/ecs/exec",
        "s3_bucket_name": "b",
    }


def test_log_group_unknown_property_is_blocked(svc):
    inv, stack = svc
    res = stack.resource("LogGroup")
    body = {"Type": res.type, "Properties": {"LogGroupName": res.physical_id, "Future": 1}}
    blocked(map_resource(inv, stack, Resolver(inv, stack), res, body), "Future")


def test_listener_rule_does_not_inherit_stack_tags():
    # AWS::ElasticLoadBalancingV2::ListenerRule has no Tags property, so CloudFormation never
    # propagates stack tags to it; emitting them made the first plan add tags to every rule.
    inv, stack = load("backend/https-path-alias-template.yml")
    stack.tags = {"copilot-application": "my-app", "copilot-environment": "test"}
    rule = f"{LISTENER.replace(':listener/', ':listener-rule/')}/9999cccc0000dddd"
    set_pid(stack, "HTTPSListenerRule", rule)
    inv.live[rule] = {"Priority": "3"}
    assert "tags" not in args(spec_of(run(inv, stack, "HTTPSListenerRule")))
    inv.live[rule]["Tags"] = [{"Key": "team", "Value": "web"}]
    assert args(spec_of(run(inv, stack, "HTTPSListenerRule")))["tags"] == {"team": "web"}


def test_network_load_balancer_is_blocked():
    """An LBWS with an `nlb` section stays on Copilot (pinned: the docs promise it)."""
    inv, stack = load("workloads/svc-nlb-test.stack.yml")
    pid = stack.resource("PublicNetworkLoadBalancerV2").physical_id  # type: ignore[union-attr]
    inv.live[pid or ""] = {"LoadBalancerName": "my-app-test-fe-nlb", "Attributes": []}
    blocked(run(inv, stack, "PublicNetworkLoadBalancerV2"), "type network is not supported")
