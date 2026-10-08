"""A realistic Copilot app built from real rendered fixtures, with synthesised live reads.

The templates are the verbatim Copilot renders under ``tests/fixtures/copilot/rendered`` (plus the
concrete addons renders under ``tests/fixtures/synthetic``). Only deployment inputs are chosen
here: parameter values, physical IDs, and the live reads ``ecsodus inventory`` would record.

Live reads have the shape ``ecsodus.sources.live`` stores (the AWS API response for each resource,
keyed by physical ID), so the test exercises the real inventory -> mapper contract. Everything is
mutually consistent, the way one real account would look:

* listener-rule ARNs extend their listener's ARN, which extends the load balancer's;
* target-group ARNs carry the live ``TargetGroupName``;
* the service ARN names the env cluster, and ``taskDefinition`` is the TaskDefinition's ARN;
* EIPs are keyed by public IP (the CloudFormation physical ID) and carry the ``AllocationId``
  the NAT gateways use (``Fn::GetAtt <EIP>.AllocationId``);
* security-group rule IDs appear both on the group (``SecurityGroupRules``) and under the
  standalone rule resources' physical IDs;
* tags are the stack tags plus the template's own tags (plus the ``aws:cloudformation:*`` tags
  CloudFormation adds, which ecsodus must ignore);
* custom-resource outputs (``Fn::GetAtt EnvControllerAction.HTTPSListenerArn``, rule priorities)
  are keyed by the custom resource's physical ID, as the resolver reads them, and agree with the
  env stack's own resources;
* the task definition's ``containerDefinitions`` are the template's (resolved, ECS API
  camelCase) plus the defaults DescribeTaskDefinition adds.

App layout (app ``my-app``, env ``test``):

* ``my-app-test``: env stack (template-with-basic-manifest) with a public ALB, HTTPS listener,
  NAT gateways, delegated DNS and managed aliases, all turned on through its own parameters.
  Its ``HTTPSCert`` custom resource created an ACM certificate and a validation CNAME in the env
  hosted zone (out-of-band objects).
* ``my-app-test-fe``: Load Balanced Web Service (the svc-staging render: HTTPS on the env ALB,
  an alias record, two target groups, SNS topics; Service Connect is ``Enabled: False``).
* ``my-app-test-fe-AddonsStack-1ABCDEFGHIJKL``: its nested addons stack, either the S3 bucket +
  DynamoDB table render (``addons="s3-ddb"``) or the Aurora Serverless v2 render
  (``addons="aurora"``).
* ``my-app-test-dogworker``: Worker Service (the worker-test render: an events queue and four
  topic queues with their SNS subscriptions, five topics of its own, the backlog-per-task
  Lambda with its every-minute Events rule, queue-depth autoscaling, rollback alarms, Service
  Connect, and two EFS volumes from a file system another stack exports as
  ``stack-fs-12345``). Copilot uploads custom-resource code at deploy time, so the deployed
  template's Lambdas carry ``Code`` (S3) that the render lacks; it is added here.
* ``my-app-test-job``: Scheduled Job (the job-test render: a cron Events rule that assumes a
  role to start a Step Functions state machine, which runs the task; an nginx sidecar; an EFS
  access point on the environment's managed file system, which the env creates because
  ``EFSWorkloads`` names the job; secrets and a value imported from other stacks' exports).
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from ecsodus import cfn
from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.mappers.tf_compute import cfn_to_ecs_api
from ecsodus.model import Inventory, OutOfBand, Stack, Workload, now_iso
from tests.helpers import ACCOUNT, FIXTURES, REGION, inventory_from_template

SYNTHETIC = FIXTURES.parent / "synthetic"
APP, ENV, SVC = "my-app", "test", "fe"
ENV_STACK = f"{APP}-{ENV}"
SVC_STACK = f"{APP}-{ENV}-{SVC}"
ADDONS_STACK = f"{SVC_STACK}-AddonsStack-1ABCDEFGHIJKL"
ARN = f"{REGION}:{ACCOUNT}"


def _stack_arn(name: str, uid: str) -> str:
    return f"arn:aws:cloudformation:{ARN}:stack/{name}/{uid}"


ENV_STACK_ID = _stack_arn(ENV_STACK, "11111111-aaaa-4bbb-8ccc-000000000001")
SVC_STACK_ID = _stack_arn(SVC_STACK, "11111111-aaaa-4bbb-8ccc-000000000002")
ADDONS_STACK_ID = _stack_arn(ADDONS_STACK, "11111111-aaaa-4bbb-8ccc-000000000003")

# -- shared identifiers ------------------------------------------------------------------------
VPC = "vpc-0a1b2c3d4e5f60001"
SUBNETS = {  # logical id -> (subnet id, AZ, CIDR, public)
    "PublicSubnet1": ("subnet-0a1b2c3d4e5f60011", "us-west-2a", "10.0.0.0/24", True),
    "PublicSubnet2": ("subnet-0a1b2c3d4e5f60012", "us-west-2b", "10.0.1.0/24", True),
    "PrivateSubnet1": ("subnet-0a1b2c3d4e5f60021", "us-west-2a", "10.0.2.0/24", False),
    "PrivateSubnet2": ("subnet-0a1b2c3d4e5f60022", "us-west-2b", "10.0.3.0/24", False),
}
PUBLIC_SUBNETS = [SUBNETS["PublicSubnet1"][0], SUBNETS["PublicSubnet2"][0]]
SG_PUBLIC_HTTP = "sg-0a1b2c3d4e5f60101"
SG_PUBLIC_HTTPS = "sg-0a1b2c3d4e5f60102"
SG_ENV = "sg-0a1b2c3d4e5f60103"
CLUSTER = f"{ENV_STACK}-Cluster-Q1w2E3r4T5y6"
CLUSTER_ARN = f"arn:aws:ecs:{ARN}:cluster/{CLUSTER}"
NAMESPACE = "ns-0a1b2c3d4e5f6a7b8"
IGW = "igw-0a1b2c3d4e5f60041"
EIPS = {  # EIP logical id -> (public ip = CFN physical id, allocation id, NAT gateway id)
    "NatGateway1Attachment": ("52.10.20.31", "eipalloc-0a1b2c3d4e5f60071", "nat-0a1b2c3d4e5f60061"),
    "NatGateway2Attachment": ("52.10.20.32", "eipalloc-0a1b2c3d4e5f60072", "nat-0a1b2c3d4e5f60062"),
}

LB_NAME = "my-app-Publi-1A2B3C4D5E6F7"
LB_ID = "0a1b2c3d4e5f6a7b"
LB_ARN = f"arn:aws:elasticloadbalancing:{ARN}:loadbalancer/app/{LB_NAME}/{LB_ID}"
LB_DNS = f"{LB_NAME}-1234567890.{REGION}.elb.amazonaws.com"
LB_ZONE = "Z1H1FL5HABSF5"  # the ALB canonical hosted zone in us-west-2
_LISTENER = f"arn:aws:elasticloadbalancing:{ARN}:listener/app/{LB_NAME}/{LB_ID}"
HTTP_LISTENER = f"{_LISTENER}/1111aaaa2222bbbb"
HTTPS_LISTENER = f"{_LISTENER}/3333cccc4444dddd"
CERT_ARN = f"arn:aws:acm:{ARN}:certificate/11111111-2222-3333-4444-555555555555"
ENV_DOMAIN = f"{ENV}.{APP}.example.com"
ENV_ZONE = "Z0ENVZONE1234567890AB"
VALIDATION_NAME = f"_0123456789abcdef0123456789abcdef.{ENV_DOMAIN}."
VALIDATION_VALUE = "_fedcba9876543210fedcba9876543210.abcdefghij.acm-validations.aws."


def tg_arn(name: str, tg_id: str) -> str:
    return f"arn:aws:elasticloadbalancing:{ARN}:targetgroup/{name}/{tg_id}"


def rule_arn(listener: str, rule_id: str) -> str:
    head, _, path = listener.partition(":listener/")
    return f"{head}:listener-rule/{path}/{rule_id}"


DEFAULT_TG = ("my-app-Defau-7H8J9K0L1M2N", "1a2b3c4d5e6f7a8b")
FE_TG = ("my-app-Targe-3P4Q5R6S7T8U", "2b3c4d5e6f7a8b9c")
FE_TG1 = ("my-app-Targe-9V0W1X2Y3Z4A", "3c4d5e6f7a8b9c0d")

TD_ARN = f"arn:aws:ecs:{ARN}:task-definition/{APP}-{ENV}-{SVC}:7"
SVC_NAME = f"{SVC_STACK}-Service-Zx9Yw8Vu7Ts6"
SVC_ARN = f"arn:aws:ecs:{ARN}:service/{CLUSTER}/{SVC_NAME}"
SRV_ID = "srv-0a1b2c3d4e5f6a7b8"
SRV_ARN = f"arn:aws:servicediscovery:{ARN}:service/{SRV_ID}"
ENV_CONTROLLER = f"{SVC_STACK}-EnvControllerAction-1Q2W3E4R5T6Y"
HTTPS_PRIORITY = f"{SVC_STACK}-HTTPSRulePriorityAction-7U8I9O0P1A2S"
HTTP_PRIORITY = f"{SVC_STACK}-HTTPRuleWithDomainPriorityAction-3D4F5G6H7J8K"

# Parameter values the env was deployed with: the template's own Conditions turn each feature on.
ENV_PARAMS = {
    "AppName": APP,
    "EnvironmentName": ENV,
    "ALBWorkloads": SVC,
    "InternalALBWorkloads": "",
    "EFSWorkloads": "job",
    "NATWorkloads": SVC,
    "AppRunnerPrivateWorkloads": "",
    "ToolsAccountPrincipalARN": f"arn:aws:iam::{ACCOUNT}:root",
    "AppDNSName": "example.com",
    "AppDNSDelegationRole": f"arn:aws:iam::{ACCOUNT}:role/{APP}-DNSDelegationRole",
    "Aliases": '{"fe":["example.com"]}',
    "CreateHTTPSListener": "true",
    "CreateInternalHTTPSListener": "false",
    "ServiceDiscoveryEndpoint": f"{ENV}.{APP}.local",
}
SVC_PARAMS = {
    "EnvName": ENV,
    "ContainerImage": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{APP}/{SVC}@sha256:"
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "AddonsTemplateURL": (
        f"https://stackset-{APP}-infra-pipelinebuiltartifactbuc-1a2b3c4d5e6f.s3.{REGION}"
        f".amazonaws.com/manual/addons/{SVC}/0123abcd.yml"
    ),
}

ENV_IDS: dict[str, str] = {
    "CloudformationExecutionRole": f"{ENV_STACK}-CFNExecutionRole",
    "EnvironmentManagerRole": f"{ENV_STACK}-EnvManagerRole",
    "VPC": VPC,
    "PublicRouteTable": "rtb-0a1b2c3d4e5f60031",
    "DefaultPublicRoute": "rtb-0a1b2c3d4e5f60031|0.0.0.0/0",
    "InternetGateway": IGW,
    "InternetGatewayAttachment": f"IGW|{VPC}",
    **{lid: sub[0] for lid, sub in SUBNETS.items()},
    "PublicSubnet1RouteTableAssociation": "rtbassoc-0a1b2c3d4e5f60051",
    "PublicSubnet2RouteTableAssociation": "rtbassoc-0a1b2c3d4e5f60052",
    "NatGateway1Attachment": EIPS["NatGateway1Attachment"][0],
    "NatGateway1": EIPS["NatGateway1Attachment"][2],
    "PrivateRouteTable1": "rtb-0a1b2c3d4e5f60032",
    "PrivateRoute1": "rtb-0a1b2c3d4e5f60032|0.0.0.0/0",
    "PrivateRouteTable1Association": "rtbassoc-0a1b2c3d4e5f60053",
    "NatGateway2Attachment": EIPS["NatGateway2Attachment"][0],
    "NatGateway2": EIPS["NatGateway2Attachment"][2],
    "PrivateRouteTable2": "rtb-0a1b2c3d4e5f60033",
    "PrivateRoute2": "rtb-0a1b2c3d4e5f60033|0.0.0.0/0",
    "PrivateRouteTable2Association": "rtbassoc-0a1b2c3d4e5f60054",
    "ServiceDiscoveryNamespace": NAMESPACE,
    "Cluster": CLUSTER,
    "PublicHTTPLoadBalancerSecurityGroup": SG_PUBLIC_HTTP,
    "PublicHTTPSLoadBalancerSecurityGroup": SG_PUBLIC_HTTPS,
    "EnvironmentSecurityGroup": SG_ENV,
    "EnvironmentHTTPSecurityGroupIngressFromPublicALB": "sgr-0a1b2c3d4e5f60201",
    "EnvironmentHTTPSSecurityGroupIngressFromPublicALB": "sgr-0a1b2c3d4e5f60202",
    "EnvironmentSecurityGroupIngressFromSelf": "sgr-0a1b2c3d4e5f60203",
    "PublicLoadBalancer": LB_ARN,
    "DefaultHTTPTargetGroup": tg_arn(*DEFAULT_TG),
    "HTTPListener": HTTP_LISTENER,
    "HTTPSListener": HTTPS_LISTENER,
    "CustomResourceRole": f"{ENV_STACK}-CustomResourceRole-1Z2X3C4V5B6N",
    "EnvironmentHostedZone": ENV_ZONE,
    "CertificateValidationFunction": f"{ENV_STACK}-CertificateValidationFunction-AbC1",
    "CustomDomainFunction": f"{ENV_STACK}-CustomDomainFunction-DeF2",
    "DNSDelegationFunction": f"{ENV_STACK}-DNSDelegationFunction-GhI3",
    "DelegateDNSAction": f"{ENV_STACK}-DelegateDNSAction-JkL4",
    # A Copilot HTTPSCert custom resource's physical id is the certificate ARN it validated.
    "HTTPSCert": CERT_ARN,
    "CustomDomainAction": f"{ENV_STACK}-CustomDomainAction-MnO5",
    "LogResourcePolicy": f"{ENV_STACK}-LogResourcePolicy",
    "FileSystem": "fs-0a1b2c3d4e5f60081",
    "EFSSecurityGroup": "sg-0a1b2c3d4e5f60104",
    "EFSSecurityGroupIngressFromEnvironment": "sgr-0a1b2c3d4e5f60204",
    "MountTarget1": "fsmt-0a1b2c3d4e5f60091",
    "MountTarget2": "fsmt-0a1b2c3d4e5f60092",
}

SVC_IDS: dict[str, str] = {
    "LogGroup": f"/copilot/{SVC_STACK}",
    "TaskDefinition": TD_ARN,
    "ExecutionRole": f"{SVC_STACK}-ExecutionRole-1A2B3C4D5E6F",
    "TaskRole": f"{SVC_STACK}-TaskRole-7G8H9I0J1K2L",
    "DiscoveryService": SRV_ID,
    "EnvControllerAction": ENV_CONTROLLER,
    "EnvControllerFunction": f"{SVC_STACK}-EnvControllerFunction-M3N4",
    "EnvControllerRole": f"{SVC_STACK}-EnvControllerRole-O5P6Q7R8S9T0",
    "Service": SVC_ARN,
    "TargetGroup": tg_arn(*FE_TG),
    "TargetGroup1": tg_arn(*FE_TG1),
    "RulePriorityFunction": f"{SVC_STACK}-RulePriorityFunction-U1V2",
    "RulePriorityFunctionRole": f"{SVC_STACK}-RulePriorityFunctionRole-W3X4Y5Z6A7B8",
    "LoadBalancerDNSAliasmockHostedZone": f"{SVC_STACK}-LoadB-C9D0E1F2G3H4",
    "HTTPSRulePriorityAction": HTTPS_PRIORITY,
    "HTTPRuleWithDomainPriorityAction": HTTP_PRIORITY,
    "HTTPListenerRuleWithDomain": rule_arn(HTTP_LISTENER, "a1a1a1a1a1a1a1a1"),
    "HTTPListenerRuleWithDomain1": rule_arn(HTTP_LISTENER, "b2b2b2b2b2b2b2b2"),
    "HTTPSListenerRule": rule_arn(HTTPS_LISTENER, "c3c3c3c3c3c3c3c3"),
    "HTTPSListenerRule1": rule_arn(HTTPS_LISTENER, "d4d4d4d4d4d4d4d4"),
    "AddonsStack": ADDONS_STACK_ID,
    "givesdogsSNSTopic": f"arn:aws:sns:{ARN}:{SVC_STACK}-givesdogs",
    "givesdogsSNSTopicPolicy": f"{SVC_STACK}-givesdogsSNSTopicPolicy-E5F6G7H8",
    "mytopicfifoSNSTopic": f"arn:aws:sns:{ARN}:{SVC_STACK}-mytopic.fifo",
    "mytopicfifoSNSTopicPolicy": f"{SVC_STACK}-mytopicfifoSNSTopicPolicy-I9J0K1L2",
}

BUCKET = "my-app-test-fe-addonsstack-1ab-assetsbucket-1q2w3e4r5t6y"
TABLE = f"{APP}-{ENV}-{SVC}-orders"
S3_DDB_IDS: dict[str, str] = {
    "assetsBucket": BUCKET,
    "assetsBucketPolicy": f"{ADDONS_STACK}-assetsBucketPolicy-1U2I3O4P",
    "assetsAccessPolicy": (
        f"arn:aws:iam::{ACCOUNT}:policy/{ADDONS_STACK}-assetsAccessPolicy-5A6S7D8F"
    ),
    "orders": TABLE,
}

DB_CLUSTER = "my-app-test-fe-addonsstack-1-dbdbcluster-1a2b3c4d5e6f"
DB_INSTANCE = "my-app-test-fe-addonsstack-1-dbdbwriterinstance-2z3x4c5v6b7n"
DB_SUBNET_GROUP = "my-app-test-fe-addonsstack-1abcdefghijkl-dbdbsubnetgroup-1q2w3e4r5t6y"
DB_PARAMS = "my-app-test-fe-addonsstack-1abcdefghijkl-dbdbclusterparametergroup-7u8i9o0p"
DB_SECRET_NAME = "dbAuroraSecret-AbCdEfGhIjKl"
DB_SECRET = f"arn:aws:secretsmanager:{ARN}:secret:{DB_SECRET_NAME}-q1W2e3"
SG_DB_CLIENT = "sg-0a1b2c3d4e5f60301"
SG_DB_CLUSTER = "sg-0a1b2c3d4e5f60302"
AURORA_IDS: dict[str, str] = {
    "dbDBSubnetGroup": DB_SUBNET_GROUP,
    "dbSecurityGroup": SG_DB_CLIENT,
    "dbDBClusterSecurityGroup": SG_DB_CLUSTER,
    "dbAuroraSecret": DB_SECRET,
    "dbDBClusterParameterGroup": DB_PARAMS,
    "dbDBCluster": DB_CLUSTER,
    "dbDBWriterInstance": DB_INSTANCE,
    # Ref on a SecretTargetAttachment returns the secret's ARN.
    "dbSecretAuroraClusterAttachment": DB_SECRET,
}

ADDONS = {
    "s3-ddb": (SYNTHETIC / "s3-ddb-addons.yml", S3_DDB_IDS),
    "aurora": (SYNTHETIC / "aurora-serverlessv2.yml", AURORA_IDS),
}


# -- tags --------------------------------------------------------------------------------------
def _resolved_props(inv: Inventory, stack: Stack, lid: str) -> dict[str, Any]:
    body = cfn.load(stack.template_body)["Resources"][lid]
    return Resolver(inv, stack).resolve(body.get("Properties") or {}) or {}


def tag_map(inv: Inventory, stack: Stack, lid: str, *, system: bool = True) -> dict[str, str]:
    """The tags CloudFormation put on a resource: stack tags, the template's own tags, and (for
    services that allow them) CloudFormation's ``aws:cloudformation:*`` system tags."""
    tags = dict(stack.tags)
    body = cfn.load(stack.template_body)["Resources"][lid]
    for t in Resolver(inv, stack).resolve((body.get("Properties") or {}).get("Tags")) or []:
        tags[str(t["Key"])] = str(t["Value"])
    if system:
        tags.update(
            {
                "aws:cloudformation:stack-name": stack.name,
                "aws:cloudformation:stack-id": stack.stack_id,
                "aws:cloudformation:logical-id": lid,
            }
        )
    return tags


def api_tags(tags: dict[str, str], *, lower: bool = False) -> list[dict[str, str]]:
    k, v = ("key", "value") if lower else ("Key", "Value")
    return [{k: key, v: value} for key, value in tags.items()]


# -- live reads (shapes as ecsodus.sources.live stores them) -----------------------------------
_DEFAULT_EGRESS = [
    {
        "IpProtocol": "-1",
        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        "Ipv6Ranges": [],
        "PrefixListIds": [],
        "UserIdGroupPairs": [],
    }
]


def _egress_rule(rule_id: str, group: str) -> dict[str, Any]:
    return {
        "SecurityGroupRuleId": rule_id,
        "GroupId": group,
        "GroupOwnerId": ACCOUNT,
        "IsEgress": True,
        "IpProtocol": "-1",
        "FromPort": -1,
        "ToPort": -1,
        "CidrIpv4": "0.0.0.0/0",
    }


def _cidr_rule(rule_id: str, group: str, port: int, description: str) -> dict[str, Any]:
    return {
        "SecurityGroupRuleId": rule_id,
        "GroupId": group,
        "GroupOwnerId": ACCOUNT,
        "IsEgress": False,
        "IpProtocol": "tcp",
        "FromPort": port,
        "ToPort": port,
        "CidrIpv4": "0.0.0.0/0",
        "Description": description,
    }


def _peer_rule(
    rule_id: str, group: str, peer: str, description: str, protocol: str = "-1", port: int = -1
) -> dict[str, Any]:
    return {
        "SecurityGroupRuleId": rule_id,
        "GroupId": group,
        "GroupOwnerId": ACCOUNT,
        "IsEgress": False,
        "IpProtocol": protocol,
        "FromPort": port,
        "ToPort": port,
        "ReferencedGroupInfo": {"GroupId": peer, "UserId": ACCOUNT},
        "Description": description,
    }


def _ip_permissions(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DescribeSecurityGroups' IpPermissions view of the same ingress rules."""
    perms: dict[tuple[str, int], dict[str, Any]] = {}
    for r in rules:
        all_ports = r["IpProtocol"] == "-1"
        ports = {} if all_ports else {"FromPort": r["FromPort"], "ToPort": r["ToPort"]}
        perm = perms.setdefault(
            (r["IpProtocol"], r["FromPort"]),
            {
                "IpProtocol": r["IpProtocol"],
                **ports,
                "IpRanges": [],
                "Ipv6Ranges": [],
                "PrefixListIds": [],
                "UserIdGroupPairs": [],
            },
        )
        if "CidrIpv4" in r:
            perm["IpRanges"].append({"CidrIp": r["CidrIpv4"], "Description": r["Description"]})
        else:
            peer = r["ReferencedGroupInfo"]["GroupId"]
            pair = {"GroupId": peer, "UserId": ACCOUNT, "Description": r["Description"]}
            perm["UserIdGroupPairs"].append(pair)
    return list(perms.values())


def _sg(
    group: str,
    name: str,
    description: str,
    tags: dict[str, str],
    ingress_rules: list[dict[str, Any]],
    egress_rule_id: str,
) -> dict[str, Any]:
    return {
        "GroupId": group,
        "GroupName": name,
        "Description": description,
        "OwnerId": ACCOUNT,
        "VpcId": VPC,
        "IpPermissions": _ip_permissions(ingress_rules),
        "IpPermissionsEgress": _DEFAULT_EGRESS,
        "Tags": api_tags(tags),
        "SecurityGroupRules": [*ingress_rules, _egress_rule(egress_rule_id, group)],
    }


LB_ATTRIBUTES = {
    "access_logs.s3.enabled": "false",
    "access_logs.s3.bucket": "",
    "access_logs.s3.prefix": "",
    "connection_logs.s3.enabled": "false",
    "connection_logs.s3.bucket": "",
    "connection_logs.s3.prefix": "",
    "health_check_logs.s3.enabled": "false",
    "health_check_logs.s3.bucket": "",
    "health_check_logs.s3.prefix": "",
    "idle_timeout.timeout_seconds": "60",
    "deletion_protection.enabled": "false",
    "routing.http2.enabled": "true",
    "routing.http.drop_invalid_header_fields.enabled": "false",
    "routing.http.xff_client_port.enabled": "false",
    "routing.http.preserve_host_header.enabled": "false",
    "routing.http.xff_header_processing.mode": "append",
    "load_balancing.cross_zone.enabled": "true",
    "routing.http.desync_mitigation_mode": "defensive",
    "client_keep_alive.seconds": "3600",
    "waf.fail_open.enabled": "false",
    "routing.http.x_amzn_tls_version_and_cipher_suite.enabled": "false",
    "zonal_shift.config.enabled": "false",
}


def _tg_attributes(dereg: str) -> dict[str, str]:
    return {
        "stickiness.enabled": "false",
        "deregistration_delay.timeout_seconds": dereg,
        "stickiness.app_cookie.cookie_name": "",
        "stickiness.type": "lb_cookie",
        "stickiness.lb_cookie.duration_seconds": "86400",
        "slow_start.duration_seconds": "0",
        "stickiness.app_cookie.duration_seconds": "86400",
        "load_balancing.algorithm.type": "round_robin",
        "load_balancing.algorithm.anomaly_mitigation": "off",
        "load_balancing.cross_zone.enabled": "use_load_balancer_configuration",
        "target_group_health.dns_failover.minimum_healthy_targets.count": "1",
        "target_group_health.dns_failover.minimum_healthy_targets.percentage": "off",
        "target_group_health.unhealthy_state_routing.minimum_healthy_targets.count": "1",
        "target_group_health.unhealthy_state_routing.minimum_healthy_targets.percentage": "off",
    }


def _tg(arn: str, name: str, port: int, dereg: str, *, interval: int, healthy: int) -> dict:
    """DescribeTargetGroups (+ attributes as a map, as sources/live.py stores them)."""
    return {
        "TargetGroupArn": arn,
        "TargetGroupName": name,
        "Protocol": "HTTP",
        "Port": port,
        "VpcId": VPC,
        "HealthCheckProtocol": "HTTP",
        "HealthCheckPort": "traffic-port",
        "HealthCheckEnabled": True,
        "HealthCheckIntervalSeconds": interval,
        "HealthCheckTimeoutSeconds": 5,
        "HealthyThresholdCount": healthy,
        "UnhealthyThresholdCount": 2,
        "HealthCheckPath": "/",
        "Matcher": {"HttpCode": "200"},
        "LoadBalancerArns": [LB_ARN],
        "TargetType": "ip",
        "ProtocolVersion": "HTTP1",
        "IpAddressType": "ipv4",
        "Attributes": _tg_attributes(dereg),
    }


def _role(inv: Inventory, stack: Stack, lid: str) -> dict[str, Any]:
    """GetRole + ListAttachedRolePolicies + ListRolePolicies for a template role."""
    props = _resolved_props(inv, stack, lid)
    name = next(r.physical_id for r in stack.resources if r.logical_id == lid) or ""
    path = props.get("Path", "/")
    managed = props.get("ManagedPolicyArns") or []
    return {
        "Path": path,
        "RoleName": name,
        "RoleId": "AROA" + name.upper().replace("-", "")[:17],
        "Arn": f"arn:aws:iam::{ACCOUNT}:role{path}{name}",
        "AssumeRolePolicyDocument": props["AssumeRolePolicyDocument"],
        "MaxSessionDuration": 3600,
        # IAM refuses aws: tags, so CloudFormation adds no system tags to roles.
        "Tags": api_tags(tag_map(inv, stack, lid, system=False)),
        "AttachedPolicies": [
            {"PolicyName": arn.rsplit("/", 1)[-1], "PolicyArn": arn} for arn in managed
        ],
        "InlinePolicyNames": [p["PolicyName"] for p in props.get("Policies") or [] if p],
    }


def _rule(inv: Inventory, stack: Stack, lid: str, arn: str, priority: str) -> dict[str, Any]:
    """DescribeRules for a template listener rule (the priority came from a custom resource)."""
    props = _resolved_props(inv, stack, lid)
    return {
        "RuleArn": arn,
        "Priority": priority,
        "Conditions": props["Conditions"],
        "Actions": props["Actions"],
        "IsDefault": False,
    }


def env_live(inv: Inventory, env: Stack) -> dict[str, dict[str, Any]]:
    def tags(lid: str) -> list[dict[str, str]]:
        return api_tags(tag_map(inv, env, lid))

    default_forward = [{"Type": "forward", "TargetGroupArn": ENV_IDS["DefaultHTTPTargetGroup"]}]
    live: dict[str, dict[str, Any]] = {
        VPC: {
            "VpcId": VPC,
            "CidrBlock": "10.0.0.0/16",
            "InstanceTenancy": "default",
            "IsDefault": False,
            "State": "available",
            "EnableDnsSupport": True,
            "EnableDnsHostnames": True,
            "Tags": tags("VPC"),
        },
        IGW: {
            "InternetGatewayId": IGW,
            "Attachments": [{"State": "available", "VpcId": VPC}],
            "OwnerId": ACCOUNT,
            "Tags": tags("InternetGateway"),
        },
        SG_PUBLIC_HTTP: _sg(
            SG_PUBLIC_HTTP,
            f"{ENV_STACK}-PublicHTTPLoadBalancerSecurityGroup-1QAZ2WSX3EDC",
            "HTTP access to the public facing load balancer",
            tag_map(inv, env, "PublicHTTPLoadBalancerSecurityGroup"),
            [
                _cidr_rule(
                    "sgr-0a1b2c3d4e5f60211", SG_PUBLIC_HTTP, 80, "Allow from anyone on port 80"
                )
            ],
            "sgr-0a1b2c3d4e5f60221",
        ),
        SG_PUBLIC_HTTPS: _sg(
            SG_PUBLIC_HTTPS,
            f"{ENV_STACK}-PublicHTTPSLoadBalancerSecurityGroup-4RFV5TGB6YHN",
            "HTTPS access to the public facing load balancer",
            tag_map(inv, env, "PublicHTTPSLoadBalancerSecurityGroup"),
            [
                _cidr_rule(
                    "sgr-0a1b2c3d4e5f60212", SG_PUBLIC_HTTPS, 443, "Allow from anyone on port 443"
                )
            ],
            "sgr-0a1b2c3d4e5f60222",
        ),
        LB_ARN: {
            "LoadBalancerArn": LB_ARN,
            "DNSName": LB_DNS,
            "CanonicalHostedZoneId": LB_ZONE,
            "LoadBalancerName": LB_NAME,
            "Scheme": "internet-facing",
            "VpcId": VPC,
            "State": {"Code": "active"},
            "Type": "application",
            "AvailabilityZones": [
                {"ZoneName": SUBNETS[lid][1], "SubnetId": SUBNETS[lid][0]}
                for lid in ("PublicSubnet1", "PublicSubnet2")
            ],
            "SecurityGroups": [SG_PUBLIC_HTTP, SG_PUBLIC_HTTPS],
            "IpAddressType": "ipv4",
            "Attributes": dict(LB_ATTRIBUTES),
        },
        ENV_IDS["DefaultHTTPTargetGroup"]: _tg(
            ENV_IDS["DefaultHTTPTargetGroup"], DEFAULT_TG[0], 80, "60", interval=10, healthy=2
        ),
        HTTP_LISTENER: {
            "ListenerArn": HTTP_LISTENER,
            "LoadBalancerArn": LB_ARN,
            "Port": 80,
            "Protocol": "HTTP",
            "DefaultActions": default_forward,
        },
        HTTPS_LISTENER: {
            "ListenerArn": HTTPS_LISTENER,
            "LoadBalancerArn": LB_ARN,
            "Port": 443,
            "Protocol": "HTTPS",
            "Certificates": [{"CertificateArn": CERT_ARN}],
            "SslPolicy": "ELBSecurityPolicy-2016-08",
            "DefaultActions": default_forward,
        },
        CLUSTER: {
            "clusterArn": CLUSTER_ARN,
            "clusterName": CLUSTER,
            "status": "ACTIVE",
            "settings": [{"name": "containerInsights", "value": "disabled"}],
            "configuration": {"executeCommandConfiguration": {"logging": "DEFAULT"}},
            "capacityProviders": ["FARGATE", "FARGATE_SPOT"],
            "tags": api_tags(tag_map(inv, env, "Cluster"), lower=True),
        },
        NAMESPACE: {
            "Id": NAMESPACE,
            "Arn": f"arn:aws:servicediscovery:{ARN}:namespace/{NAMESPACE}",
            "Name": ENV_PARAMS["ServiceDiscoveryEndpoint"],
            "Type": "DNS_PRIVATE",
        },
        ENV_ZONE: {
            "HostedZone": {
                "Id": f"/hostedzone/{ENV_ZONE}",
                "Name": f"{ENV_DOMAIN}.",
                "Config": {
                    "Comment": f"HostedZone for environment {ENV} - {ENV_DOMAIN}",
                    "PrivateZone": False,
                },
                "ResourceRecordSetCount": 3,
            },
            "NameServers": ["ns-1.awsdns-01.org", "ns-2.awsdns-02.co.uk"],
            "RecordSets": [
                {
                    "Name": f"{ENV_DOMAIN}.",
                    "Type": "NS",
                    "TTL": 172800,
                    "ResourceRecords": [
                        {"Value": "ns-1.awsdns-01.org."},
                        {"Value": "ns-2.awsdns-02.co.uk."},
                    ],
                },
                {
                    "Name": f"{ENV_DOMAIN}.",
                    "Type": "SOA",
                    "TTL": 900,
                    "ResourceRecords": [
                        {
                            "Value": "ns-1.awsdns-01.org. awsdns-hostmaster.amazon.com. "
                            "1 7200 900 1209600 86400"
                        }
                    ],
                },
                # The ACM validation record the HTTPSCert custom resource wrote (out of band).
                {
                    "Name": VALIDATION_NAME,
                    "Type": "CNAME",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": VALIDATION_VALUE}],
                },
            ],
        },
    }
    for lid, (sub, az, cidr, public) in SUBNETS.items():
        live[sub] = {
            "SubnetId": sub,
            "VpcId": VPC,
            "CidrBlock": cidr,
            "AvailabilityZone": az,
            "MapPublicIpOnLaunch": public,
            "State": "available",
            "Tags": tags(lid),
        }
    for lid, (ip, alloc, nat) in EIPS.items():
        address = {
            "PublicIp": ip,
            "AllocationId": alloc,
            "Domain": "vpc",
            "NetworkBorderGroup": REGION,
            "PublicIpv4Pool": "amazon",
            "Tags": tags(lid),
        }
        live[ip] = address  # sources/live.py keys an address by both of its ids
        live[alloc] = address
        nat_lid = lid.removesuffix("Attachment")
        subnet = PUBLIC_SUBNETS[0 if nat_lid.endswith("1") else 1]
        live[nat] = {
            "NatGatewayId": nat,
            "SubnetId": subnet,
            "VpcId": VPC,
            "State": "available",
            "ConnectivityType": "public",
            "NatGatewayAddresses": [{"AllocationId": alloc, "PublicIp": ip}],
            "Tags": tags(nat_lid),
        }
    for lid in ("PublicRouteTable", "PrivateRouteTable1", "PrivateRouteTable2"):
        live[ENV_IDS[lid]] = {"RouteTableId": ENV_IDS[lid], "VpcId": VPC, "Tags": tags(lid)}

    env_rules = [
        _peer_rule(
            ENV_IDS["EnvironmentHTTPSecurityGroupIngressFromPublicALB"],
            SG_ENV,
            SG_PUBLIC_HTTP,
            "HTTP ingress from the public ALB",
        ),
        _peer_rule(
            ENV_IDS["EnvironmentHTTPSSecurityGroupIngressFromPublicALB"],
            SG_ENV,
            SG_PUBLIC_HTTPS,
            "HTTPS ingress from the public ALB",
        ),
        _peer_rule(
            ENV_IDS["EnvironmentSecurityGroupIngressFromSelf"],
            SG_ENV,
            SG_ENV,
            "Ingress from other containers in the same security group",
        ),
    ]
    live[SG_ENV] = _sg(
        SG_ENV,
        f"{ENV_STACK}-EnvironmentSecurityGroup-7UJM8IK9OL0P",
        f"{APP}-{ENV}EnvironmentSecurityGroup",
        tag_map(inv, env, "EnvironmentSecurityGroup"),
        env_rules,
        "sgr-0a1b2c3d4e5f60223",
    )
    for rule in env_rules:
        live[rule["SecurityGroupRuleId"]] = rule
    for lid in ("CloudformationExecutionRole", "EnvironmentManagerRole", "CustomResourceRole"):
        live[ENV_IDS[lid]] = _role(inv, env, lid)
    efs_rule = _peer_rule(
        ENV_IDS["EFSSecurityGroupIngressFromEnvironment"],
        ENV_IDS["EFSSecurityGroup"],
        SG_ENV,
        "Ingress from containers in the Environment Security Group.",
    )
    live[ENV_IDS["EFSSecurityGroup"]] = _sg(
        ENV_IDS["EFSSecurityGroup"],
        f"{ENV_STACK}-EFSSecurityGroup-2WSX3EDC4RFV",
        f"{APP}-{ENV}EFSSecurityGroup",
        tag_map(inv, env, "EFSSecurityGroup"),
        [efs_rule],
        "sgr-0a1b2c3d4e5f60224",
    )
    live[efs_rule["SecurityGroupRuleId"]] = efs_rule
    live[ENV_IDS["FileSystem"]] = {
        "FileSystemId": ENV_IDS["FileSystem"],
        "Encrypted": True,
        "KmsKeyId": f"arn:aws:kms:{ARN}:key/3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f",
        "PerformanceMode": "generalPurpose",
        "ThroughputMode": "bursting",
        "LifeCycleState": "available",
        "Tags": tags("FileSystem"),
    }
    return live


def task_definition_live(inv: Inventory, stack: Stack, arn: str = TD_ARN) -> dict[str, Any]:
    """DescribeTaskDefinition as ECS returns it for the deployed template (plus its tags)."""
    props = _resolved_props(inv, stack, "TaskDefinition")
    defs = cfn_to_ecs_api(props["ContainerDefinitions"])
    for d in defs:
        d.setdefault("cpu", 0)
        d.setdefault("essential", True)
        for pm in d.get("portMappings", []):
            pm.setdefault("hostPort", pm["containerPort"])
        if not d.get("environmentFiles"):
            d.pop("environmentFiles", None)
        d.setdefault("volumesFrom", [])
        d.setdefault("systemControls", [])
    return {
        "taskDefinitionArn": arn,
        "family": props["Family"],
        "revision": 7,
        "status": "ACTIVE",
        "containerDefinitions": defs,
        "cpu": props["Cpu"],
        "memory": props["Memory"],
        "networkMode": props["NetworkMode"],
        "requiresCompatibilities": props["RequiresCompatibilities"],
        "compatibilities": ["EC2", "FARGATE"],
        "executionRoleArn": props["ExecutionRoleArn"],
        "taskRoleArn": props["TaskRoleArn"],
        "volumes": [
            cfn_to_ecs_api(v) if "EFSVolumeConfiguration" in v else {"name": v["Name"], "host": {}}
            for v in props.get("Volumes", [])
        ],
        "tags": api_tags(tag_map(inv, stack, "TaskDefinition"), lower=True),
    }


def svc_live(inv: Inventory, svc: Stack) -> dict[str, dict[str, Any]]:
    raw = cfn.load(svc.template_body)["Resources"]["Service"]["Properties"]
    resolver = Resolver(inv, svc)
    dc = resolver.resolve(raw["DeploymentConfiguration"])
    target_groups = resolver.resolve(raw["LoadBalancers"])
    live: dict[str, dict[str, Any]] = {
        # Outputs of the env controller: the env stack's own listeners and load balancer.
        ENV_CONTROLLER: {
            "PublicLoadBalancerDNSName": LB_DNS,
            "PublicLoadBalancerHostedZone": LB_ZONE,
            "HTTPListenerArn": HTTP_LISTENER,
            "HTTPSListenerArn": HTTPS_LISTENER,
        },
        HTTPS_PRIORITY: {"Priority": "1", "Priority1": "2"},
        HTTP_PRIORITY: {"Priority": "1", "Priority1": "2"},
        SVC_IDS["TargetGroup"]: _tg(
            SVC_IDS["TargetGroup"], FE_TG[0], 4000, "30", interval=30, healthy=5
        ),
        SVC_IDS["TargetGroup1"]: _tg(
            SVC_IDS["TargetGroup1"], FE_TG1[0], 4001, "60", interval=30, healthy=5
        ),
        SRV_ID: {
            "Id": SRV_ID,
            "Arn": SRV_ARN,
            "Name": SVC,
            "NamespaceId": NAMESPACE,
            "Description": "Discovery Service for the Copilot services",
            "DnsConfig": {
                "NamespaceId": NAMESPACE,
                "RoutingPolicy": "MULTIVALUE",
                "DnsRecords": [{"Type": "A", "TTL": 10}, {"Type": "SRV", "TTL": 10}],
            },
            "HealthCheckCustomConfig": {"FailureThreshold": 1},
            "Type": "DNS_HTTP",
        },
        SVC_ARN: {
            "serviceArn": SVC_ARN,
            "serviceName": SVC_NAME,
            "clusterArn": CLUSTER_ARN,
            "status": "ACTIVE",
            "desiredCount": int(svc.parameters["TaskCount"]),
            "runningCount": int(svc.parameters["TaskCount"]),
            "pendingCount": 0,
            "platformVersion": "LATEST",
            "platformFamily": "Linux",
            "taskDefinition": TD_ARN,
            "capacityProviderStrategy": [
                {"capacityProvider": "FARGATE_SPOT", "weight": 1, "base": 0}
            ],
            "deploymentConfiguration": {
                "deploymentCircuitBreaker": {"enable": True, "rollback": True},
                "maximumPercent": dc["MaximumPercent"],
                "minimumHealthyPercent": dc["MinimumHealthyPercent"],
                "alarms": {"alarmNames": [], "enable": False, "rollback": True},
            },
            "loadBalancers": [
                {
                    "targetGroupArn": lb["TargetGroupArn"],
                    "containerName": lb["ContainerName"],
                    "containerPort": lb["ContainerPort"],
                }
                for lb in target_groups
            ],
            "serviceRegistries": [{"registryArn": SRV_ARN, "port": 4000}],
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": PUBLIC_SUBNETS,
                    "securityGroups": [SG_ENV],
                    "assignPublicIp": "ENABLED",
                }
            },
            "healthCheckGracePeriodSeconds": 30,
            "schedulingStrategy": "REPLICA",
            "enableECSManagedTags": False,
            "propagateTags": "SERVICE",
            "enableExecuteCommand": False,
            "availabilityZoneRebalancing": "ENABLED",
            "tags": api_tags(tag_map(inv, svc, "Service"), lower=True),
        },
        SVC_IDS["LogGroup"]: {
            "logGroupName": SVC_IDS["LogGroup"],
            "retentionInDays": 30,
            "arn": f"arn:aws:logs:{ARN}:log-group:{SVC_IDS['LogGroup']}:*",
        },
    }
    priorities = {
        "HTTPListenerRuleWithDomain": (HTTP_PRIORITY, "Priority"),
        "HTTPListenerRuleWithDomain1": (HTTP_PRIORITY, "Priority1"),
        "HTTPSListenerRule": (HTTPS_PRIORITY, "Priority"),
        "HTTPSListenerRule1": (HTTPS_PRIORITY, "Priority1"),
    }
    inv.live.update(live)  # the rules below resolve the env controller's outputs
    for lid, (action, attr) in priorities.items():
        live[SVC_IDS[lid]] = _rule(inv, svc, lid, SVC_IDS[lid], live[action][attr])
    for lid in ("ExecutionRole", "TaskRole", "EnvControllerRole", "RulePriorityFunctionRole"):
        live[SVC_IDS[lid]] = _role(inv, svc, lid)
    return live


def s3_ddb_live(inv: Inventory, addons: Stack) -> dict[str, dict[str, Any]]:
    return {
        BUCKET: {
            "Versioning": {"Status": "Enabled", "MFADelete": "Disabled"},
            "Encryption": {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                            "BucketKeyEnabled": False,
                        }
                    ]
                }
            },
            "PublicAccessBlock": {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            },
            "OwnershipControls": {
                "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
            },
        },
        TABLE: {
            "TableName": TABLE,
            "TableArn": f"arn:aws:dynamodb:{ARN}:table/{TABLE}",
            "TableStatus": "ACTIVE",
            "AttributeDefinitions": [
                {"AttributeName": "created", "AttributeType": "N"},
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            "ProvisionedThroughput": {
                "NumberOfDecreasesToday": 0,
                "ReadCapacityUnits": 0,
                "WriteCapacityUnits": 0,
            },
            "LocalSecondaryIndexes": [
                {
                    "IndexName": "byCreated",
                    "KeySchema": [
                        {"AttributeName": "pk", "KeyType": "HASH"},
                        {"AttributeName": "created", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "DeletionProtectionEnabled": False,
            "ContinuousBackups": {
                "ContinuousBackupsStatus": "ENABLED",
                "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"},
            },
        },
    }


def aurora_live(inv: Inventory, addons: Stack) -> dict[str, dict[str, Any]]:
    def tags(lid: str) -> list[dict[str, str]]:
        return api_tags(tag_map(inv, addons, lid))

    ingress = _peer_rule(
        "sgr-0a1b2c3d4e5f60311",
        SG_DB_CLUSTER,
        SG_DB_CLIENT,
        f"From the Aurora Security Group of the workload {SVC}.",
        protocol="tcp",
        port=5432,
    )
    return {
        SG_DB_CLIENT: _sg(
            SG_DB_CLIENT,
            f"{ADDONS_STACK}-dbSecurityGroup-1A2S3D4F5G6H",
            f"The Security Group for {SVC} to access Aurora Serverless v2 cluster db.",
            tag_map(inv, addons, "dbSecurityGroup"),
            [],
            "sgr-0a1b2c3d4e5f60321",
        ),
        SG_DB_CLUSTER: _sg(
            SG_DB_CLUSTER,
            f"{ADDONS_STACK}-dbDBClusterSecurityGroup-7J8K9L0Z1X2C",
            "The Security Group for the Aurora Serverless v2 cluster.",
            tag_map(inv, addons, "dbDBClusterSecurityGroup"),
            [ingress],
            "sgr-0a1b2c3d4e5f60322",
        ),
        DB_SECRET: {
            "ARN": DB_SECRET,
            "Name": DB_SECRET_NAME,
            "Description": f"Aurora main user secret for {ADDONS_STACK}",
            "Tags": tags("dbAuroraSecret"),
        },
        DB_CLUSTER: {
            "DBClusterIdentifier": DB_CLUSTER,
            "DBClusterArn": f"arn:aws:rds:{ARN}:cluster:{DB_CLUSTER}",
            "Status": "available",
            "Engine": "aurora-postgresql",
            "EngineVersion": "16.2",
            "EngineMode": "provisioned",
            "DatabaseName": "main",
            "MasterUsername": "postgres",
            "Port": 5432,
            "DBSubnetGroup": DB_SUBNET_GROUP,
            "DBClusterParameterGroup": DB_PARAMS,
            "VpcSecurityGroups": [{"VpcSecurityGroupId": SG_DB_CLUSTER, "Status": "active"}],
            "StorageEncrypted": False,
            "BackupRetentionPeriod": 1,
            "PreferredBackupWindow": "07:04-07:34",
            "PreferredMaintenanceWindow": "sun:10:15-sun:10:45",
            "DeletionProtection": False,
            "IAMDatabaseAuthenticationEnabled": False,
            "HttpEndpointEnabled": False,
            "CopyTagsToSnapshot": False,
            "ServerlessV2ScalingConfiguration": {"MinCapacity": 0.5, "MaxCapacity": 8.0},
            "DBClusterMembers": [{"DBInstanceIdentifier": DB_INSTANCE, "IsClusterWriter": True}],
            "TagList": tags("dbDBCluster"),
        },
        DB_INSTANCE: {
            "DBInstanceIdentifier": DB_INSTANCE,
            "DBInstanceClass": "db.serverless",
            "Engine": "aurora-postgresql",
            "DBInstanceStatus": "available",
            "AvailabilityZone": "us-west-2a",
            "DBClusterIdentifier": DB_CLUSTER,
            "PromotionTier": 1,
            "PubliclyAccessible": False,
            "AutoMinorVersionUpgrade": True,
            "MonitoringInterval": 0,
            "PerformanceInsightsEnabled": False,
            "CACertificateIdentifier": "rds-ca-rsa2048-g1",
            "DBSubnetGroup": {"DBSubnetGroupName": DB_SUBNET_GROUP, "VpcId": VPC},
            "DBParameterGroups": [
                {
                    "DBParameterGroupName": "default.aurora-postgresql16",
                    "ParameterApplyStatus": "in-sync",
                }
            ],
            "TagList": tags("dbDBWriterInstance"),
        },
    }


# -- Worker Service ----------------------------------------------------------------------------
WORKER = "dogworker"
WORKER_STACK = f"{APP}-{ENV}-{WORKER}"
WORKER_STACK_ID = _stack_arn(WORKER_STACK, "11111111-aaaa-4bbb-8ccc-000000000004")
EFS_EXPORT = "stack-fs-12345"
SHARED_FS = "fs-0a1b2c3d4e5f6a7b9"
WORKER_TD_ARN = f"arn:aws:ecs:{ARN}:task-definition/{WORKER_STACK}:3"
WORKER_SVC_NAME = f"{WORKER_STACK}-Service-Ab1Cd2Ef3Gh4"
WORKER_SVC_ARN = f"arn:aws:ecs:{ARN}:service/{CLUSTER}/{WORKER_SVC_NAME}"
BACKLOG_FN = f"{WORKER_STACK}-BacklogPerTaskCalculatorF-Kq7Zr2"
BACKLOG_RULE = f"{WORKER_STACK}-BacklogPerTaskScheduledRule-1QAZ2WSX"
BACKLOG_SID = f"{WORKER_STACK}-PermissionToInvokeBacklogPerTask-3EDC4RFV"
EVENTS_KEY = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CUSTOM_RESOURCE_CODE = {  # what `copilot deploy` writes into each Lambda's Code
    "DynamicDesiredCountFunction": "dynamicdesiredcountfunction",
    "BacklogPerTaskCalculatorFunction": "backlogpertaskcalculatorfunction",
    "EnvControllerFunction": "envcontrollerfunction",
}
CODE_BUCKET = f"stackset-{APP}-infrastru-pipelinebuiltartifactbuc-1a2b3c4d5e6f"
WORKER_PARAMS = {
    "ArtifactKeyARN": f"arn:aws:kms:{ARN}:key/2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e",
    "ContainerImage": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{APP}/{WORKER}@sha256:"
    "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
}
_QUEUES = {  # logical id -> FIFO
    "EventsQueue": False,
    "DeadLetterQueue": False,
    "dogsvcgiveshuskiesEventsQueue": False,
    "mytopicmytopicfifoEventsQueue": True,
    "yourtopicyourtopicfifoEventsQueue": True,
    "nonfifotopicnonfifotopicEventsQueue": False,
}
_SUBSCRIPTIONS = (
    "dogsvcgivesdogsSNSTopicSubscription",
    "dogsvcgiveshuskiesSNSTopicSubscription",
    "mytopicmytopicfifoSNSTopicSubscription",
    "yourtopicyourtopicfifoSNSTopicSubscription",
    "nonfifotopicnonfifotopicSNSTopicSubscription",
)
_WORKER_ROLES = (
    "ExecutionRole",
    "TaskRole",
    "DynamicDesiredCountFunctionRole",
    "AutoScalingRole",
    "BacklogPerTaskCalculatorRole",
    "EnvControllerRole",
)


def _with_lambda_code(text: str, functions: tuple[str, ...] = tuple(CUSTOM_RESOURCE_CODE)) -> str:
    """The deployed template: Copilot fills each custom-resource Lambda's ``Code`` with the S3
    object it uploaded (internal/pkg/deploy/cloudformation, ``CustomResources``)."""
    for lid in functions:
        folder = CUSTOM_RESOURCE_CODE[lid]
        head = f"  {lid}:\n"
        start = text.index(head)
        props = text.index("    Properties:\n", start) + len("    Properties:\n")
        code = (
            "      Code:\n"
            f"        S3Bucket: {CODE_BUCKET}\n"
            f"        S3Key: manual/scripts/custom-resources/{folder}/"
            "0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9.zip\n"
        )
        text = text[:props] + code + text[props:]
    return text


def worker_ids(inv: Inventory, stack: Stack) -> dict[str, str]:
    r = Resolver(inv, stack)
    body = cfn.load(stack.template_body)["Resources"]
    ids: dict[str, str] = {
        "LogGroup": f"/copilot/{WORKER_STACK}",
        "TaskDefinition": WORKER_TD_ARN,
        "DynamicDesiredCountAction": f"{WORKER_STACK}-DynamicDesiredCountAction-5TGB6YHN",
        "DynamicDesiredCountFunction": f"{WORKER_STACK}-DynamicDesiredCountFunct-Mn8Bv4",
        "AutoScalingTarget": f"service/{CLUSTER}/{WORKER_SVC_NAME}|ecs:service:DesiredCount|ecs",
        "BacklogPerTaskCalculatorLogGroup": f"/aws/lambda/{BACKLOG_FN}",
        "BacklogPerTaskCalculatorFunction": BACKLOG_FN,
        "BacklogPerTaskScheduledRule": BACKLOG_RULE,
        "PermissionToInvokeBacklogPerTaskCalculatorLambda": BACKLOG_SID,
        "Service": WORKER_SVC_ARN,
        "EventsKMSKey": EVENTS_KEY,
        "EnvControllerAction": f"{WORKER_STACK}-EnvControllerAction-7UJM8IK9",
        "EnvControllerFunction": f"{WORKER_STACK}-EnvControllerFunction-Pq1Ws3",
    }
    for lid in _WORKER_ROLES:
        ids[lid] = f"{WORKER_STACK}-{lid}-{zlib.crc32(lid.encode()):010d}"[:64]
    sqs = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}"
    for i, (lid, fifo) in enumerate(_QUEUES.items()):
        ids[lid] = f"{sqs}/{WORKER_STACK}-{lid}-1A2B3C4D5E6F{i}" + (".fifo" if fifo else "")
    for lid, b in body.items():
        rtype = b["Type"]
        if rtype == "AWS::SQS::QueuePolicy":
            ids[lid] = f"{WORKER_STACK}-{lid}-9OL0P1AZ"
        elif rtype == "AWS::SNS::Topic":
            name = r.resolve(b["Properties"]["TopicName"])
            ids[lid] = f"arn:aws:sns:{ARN}:{name}"
        elif rtype == "AWS::SNS::TopicPolicy":
            ids[lid] = f"{WORKER_STACK}-{lid}-2WSX3EDC"
        elif rtype == "AWS::CloudWatch::Alarm":
            ids[lid] = r.resolve(b["Properties"]["AlarmName"])
        elif rtype == "AWS::ApplicationAutoScaling::ScalingPolicy":
            ids[lid] = (
                f"arn:aws:autoscaling:{ARN}:scalingPolicy:0a1b2c3d-{len(ids):04d}-4e5f-8a9b-"
                f"0c1d2e3f4a5b:resource/ecs/service/{CLUSTER}/{WORKER_SVC_NAME}:policyName/{lid}"
            )
    return ids


def worker_live(inv: Inventory, stack: Stack) -> dict[str, dict[str, Any]]:
    """Live reads for the worker, after its physical ids are placed."""
    resolver = Resolver(inv, stack)
    body = cfn.load(stack.template_body)["Resources"]
    raw = body["Service"]["Properties"]
    dc = resolver.resolve(raw["DeploymentConfiguration"])
    sc = resolver.resolve(raw["ServiceConnectConfiguration"])
    pid = {r.logical_id: r.physical_id or "" for r in stack.resources}
    task_count = int(stack.parameters["TaskCount"])
    live: dict[str, dict[str, Any]] = {
        WORKER_SVC_ARN: {
            "serviceArn": WORKER_SVC_ARN,
            "serviceName": WORKER_SVC_NAME,
            "clusterArn": CLUSTER_ARN,
            "status": "ACTIVE",
            "desiredCount": task_count,
            "runningCount": task_count,
            "pendingCount": 0,
            "platformVersion": "LATEST",
            "platformFamily": "Linux",
            "taskDefinition": WORKER_TD_ARN,
            "capacityProviderStrategy": [
                {"capacityProvider": "FARGATE_SPOT", "weight": 1, "base": 0},
                {"capacityProvider": "FARGATE", "weight": 0, "base": 5},
            ],
            "deploymentConfiguration": {
                "deploymentCircuitBreaker": {"enable": True, "rollback": True},
                "maximumPercent": dc["MaximumPercent"],
                "minimumHealthyPercent": dc["MinimumHealthyPercent"],
                "alarms": {
                    "alarmNames": dc["Alarms"]["AlarmNames"],
                    "enable": True,
                    "rollback": True,
                },
            },
            "deployments": [
                {
                    "status": "PRIMARY",
                    "taskDefinition": WORKER_TD_ARN,
                    "serviceConnectConfiguration": {
                        "enabled": True,
                        "namespace": sc["Namespace"],
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": dict(sc["LogConfiguration"]["Options"]),
                        },
                    },
                }
            ],
            "loadBalancers": [],
            "serviceRegistries": [],
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": PUBLIC_SUBNETS,
                    "securityGroups": [SG_ENV],
                    "assignPublicIp": "ENABLED",
                }
            },
            "schedulingStrategy": "REPLICA",
            "enableECSManagedTags": False,
            "propagateTags": "SERVICE",
            "enableExecuteCommand": True,
            "availabilityZoneRebalancing": "ENABLED",
            "tags": api_tags(tag_map(inv, stack, "Service"), lower=True),
        },
        pid["AutoScalingTarget"]: {
            "ServiceNamespace": "ecs",
            "ResourceId": f"service/{CLUSTER}/{WORKER_SVC_NAME}",
            "ScalableDimension": "ecs:service:DesiredCount",
            "MinCapacity": 1,
            "MaxCapacity": 10,
            "RoleARN": f"arn:aws:iam::{ACCOUNT}:role/{pid['AutoScalingRole']}",
        },
        EVENTS_KEY: {
            "KeyId": EVENTS_KEY,
            "Arn": f"arn:aws:kms:{ARN}:key/{EVENTS_KEY}",
            "Description": "",
            "KeyUsage": "ENCRYPT_DECRYPT",
            "KeySpec": "SYMMETRIC_DEFAULT",
            "KeyState": "Enabled",
            "Enabled": True,
            "Origin": "AWS_KMS",
            "MultiRegion": False,
            "KeyRotationEnabled": False,
            "Policy": json.dumps(_resolved_props(inv, stack, "EventsKMSKey")["KeyPolicy"]),
        },
        BACKLOG_FN: {
            "Tags": tag_map(inv, stack, "BacklogPerTaskCalculatorFunction"),
            "PolicySids": [BACKLOG_SID],
        },
        BACKLOG_RULE: {
            "Name": BACKLOG_RULE,
            "Arn": f"arn:aws:events:{ARN}:rule/{BACKLOG_RULE}",
            "ScheduleExpression": "rate(1 minute)",
            "State": "ENABLED",
            "EventBusName": "default",
            "Targets": [
                {
                    "Id": "BacklogPerTaskCalculatorFunctionTrigger",
                    "Arn": f"arn:aws:lambda:{ARN}:function:{BACKLOG_FN}",
                }
            ],
            "Tags": api_tags(tag_map(inv, stack, "BacklogPerTaskScheduledRule")),
        },
    }
    for lid, retention in (("LogGroup", 30), ("BacklogPerTaskCalculatorLogGroup", 3)):
        live[pid[lid]] = {"logGroupName": pid[lid], "retentionInDays": retention}
    for lid in _SUBSCRIPTIONS:
        props = _resolved_props(inv, stack, lid)
        attrs = {
            "SubscriptionArn": pid[lid],
            "TopicArn": props["TopicArn"],
            "Protocol": "sqs",
            "Endpoint": props["Endpoint"],
            "Owner": ACCOUNT,
            "PendingConfirmation": "false",
            "ConfirmationWasAuthenticated": "true",
            "RawMessageDelivery": "false",
        }
        if "FilterPolicy" in props:
            attrs["FilterPolicy"] = json.dumps(props["FilterPolicy"])
            attrs["FilterPolicyScope"] = "MessageAttributes"
        live[pid[lid]] = attrs
    for lid in _WORKER_ROLES:
        live[pid[lid]] = _role(inv, stack, lid)
    return live


def add_worker(inv: Inventory) -> Stack:
    _, worker = inventory_from_template(
        FIXTURES / "rendered/workloads/worker-test.stack.yml",
        stack_name=WORKER_STACK,
        env=ENV,
        workload=WORKER,
        workload_type="Worker Service",
        params=WORKER_PARAMS,
        app=APP,
    )
    worker.template_body = _with_lambda_code(worker.template_body)
    worker.stack_id = WORKER_STACK_ID
    worker.tags = _copilot_tags(ENV, WORKER)
    worker.capabilities = ["CAPABILITY_IAM"]
    inv.stacks[worker.name] = worker
    inv.external_exports[EFS_EXPORT] = {"value": SHARED_FS, "stack": "shared-efs"}
    ids = worker_ids(inv, worker)
    sub_ids = {}
    for i, lid in enumerate(_SUBSCRIPTIONS):
        topic = _resolved_props(inv, worker, lid)["TopicArn"]
        sub_ids[lid] = f"{topic}:0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c{i:02d}"
    _place(inv, worker, {**ids, **sub_ids})
    inv.live.update(worker_live(inv, worker))
    inv.live[WORKER_TD_ARN] = task_definition_live(inv, worker, WORKER_TD_ARN)
    inv.workloads.append(Workload(WORKER, "Worker Service", ENV))
    return worker


# -- Scheduled Job -----------------------------------------------------------------------------
JOB = "job"
JOB_STACK = f"{APP}-{ENV}-{JOB}"
JOB_STACK_ID = _stack_arn(JOB_STACK, "11111111-aaaa-4bbb-8ccc-000000000005")
JOB_TD_ARN = f"arn:aws:ecs:{ARN}:task-definition/{JOB_STACK}:2"
JOB_RULE = f"{JOB_STACK}-Rule-1A2S3D4F5G6H"
STATE_MACHINE = f"arn:aws:states:{ARN}:stateMachine:{JOB_STACK}"
ACCESS_POINT = "fsap-0a1b2c3d4e5f6a7b8"
JOB_ENV_CONTROLLER = f"{JOB_STACK}-EnvControllerAction-8IK9OL0P"
JOB_PARAMS = {
    "ArtifactKeyARN": WORKER_PARAMS["ArtifactKeyARN"],
    "ContainerImage": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{APP}/{JOB}@sha256:"
    "2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
}
# Exports of stacks outside the app that the job's template imports by literal name.
JOB_EXTERNAL_EXPORTS = {
    "stack-SSMGHUserName": f"arn:aws:ssm:{ARN}:parameter/gh-user",
    "MYDB": "orders",
    "MyUserDBAccessSecurityGroup1": "sg-0a1b2c3d4e5f60401",
    "MyUserDBAccessSecurityGroup2": "sg-0a1b2c3d4e5f60402",
}
_JOB_ROLES = ("ExecutionRole", "TaskRole", "EnvControllerRole", "RuleRole", "StateMachineRole")


def job_ids() -> dict[str, str]:
    ids = {
        "LogGroup": f"/copilot/{JOB_STACK}",
        "EnvControllerAction": JOB_ENV_CONTROLLER,
        "EnvControllerFunction": f"{JOB_STACK}-EnvControllerFunction-Zx9Cv8",
        "TaskDefinition": JOB_TD_ARN,
        "Rule": JOB_RULE,
        "StateMachine": STATE_MACHINE,
        "AccessPoint": ACCESS_POINT,
        "mytopicfifoSNSTopic": f"arn:aws:sns:{ARN}:{JOB_STACK}-mytopic.fifo",
        "mytopicfifoSNSTopicPolicy": f"{JOB_STACK}-mytopicfifoSNSTopicPolicy-3EDC4RFV",
    }
    for lid in _JOB_ROLES:
        ids[lid] = f"{JOB_STACK}-{lid}-{zlib.crc32(lid.encode()):010d}"[:64]
    return ids


def job_live(inv: Inventory, stack: Stack) -> dict[str, dict[str, Any]]:
    pid = {r.logical_id: r.physical_id or "" for r in stack.resources}
    sm = _resolved_props(inv, stack, "StateMachine")
    definition = sm["DefinitionString"]
    for key, val in sm["DefinitionSubstitutions"].items():
        definition = definition.replace("${" + key + "}", str(val))
    group_arn = sm["LoggingConfiguration"]["Destinations"][0]["CloudWatchLogsLogGroup"]
    rule = _resolved_props(inv, stack, "Rule")
    live: dict[str, dict[str, Any]] = {
        STATE_MACHINE: {
            "stateMachineArn": STATE_MACHINE,
            "name": JOB_STACK,
            "status": "ACTIVE",
            "definition": definition,
            "roleArn": sm["RoleArn"],
            "type": "STANDARD",
            "loggingConfiguration": {
                "level": "ALL",
                "includeExecutionData": True,
                "destinations": [
                    {"cloudWatchLogsLogGroup": {"logGroupArn": group_arn["LogGroupArn"]}}
                ],
            },
            "tracingConfiguration": {"enabled": False},
            "tags": api_tags(tag_map(inv, stack, "StateMachine"), lower=True),
        },
        JOB_RULE: {
            "Name": JOB_RULE,
            "Arn": f"arn:aws:events:{ARN}:rule/{JOB_RULE}",
            "ScheduleExpression": stack.parameters["Schedule"],
            "State": "ENABLED",
            "EventBusName": "default",
            "Targets": rule["Targets"],
            "Tags": api_tags(tag_map(inv, stack, "Rule")),
        },
        pid["LogGroup"]: {"logGroupName": pid["LogGroup"], "retentionInDays": 30},
    }
    for lid in _JOB_ROLES:
        live[pid[lid]] = _role(inv, stack, lid)
    return live


def add_job(inv: Inventory) -> Stack:
    _, job = inventory_from_template(
        FIXTURES / "rendered/workloads/job-test.stack.yml",
        stack_name=JOB_STACK,
        env=ENV,
        workload=JOB,
        workload_type="Scheduled Job",
        params=JOB_PARAMS,
        app=APP,
    )
    job.template_body = _with_lambda_code(job.template_body, ("EnvControllerFunction",))
    job.stack_id = JOB_STACK_ID
    job.tags = _copilot_tags(ENV, JOB)
    job.capabilities = ["CAPABILITY_IAM"]
    inv.stacks[job.name] = job
    for name, value in JOB_EXTERNAL_EXPORTS.items():
        inv.external_exports[name] = {"value": value, "stack": "shared-config"}
    _place(inv, job, job_ids())
    # The env controller's outputs are the env stack's own (ManagedFileSystemID here).
    inv.live[JOB_ENV_CONTROLLER] = {"ManagedFileSystemID": ENV_IDS["FileSystem"]}
    inv.live.update(job_live(inv, job))
    inv.live[JOB_TD_ARN] = task_definition_live(inv, job, JOB_TD_ARN)
    inv.workloads.append(Workload(JOB, "Scheduled Job", ENV))
    return job


# -- assembly ----------------------------------------------------------------------------------
def _place(inv: Inventory, stack: Stack, ids: dict[str, str]) -> None:
    """Give every created resource its physical ID; drop resources whose Condition is false.

    DescribeStackResources does not list resources that were never created, so they are removed
    rather than left without a physical ID.
    """
    resolver = Resolver(inv, stack)
    kept = []
    for res in stack.resources:
        if not resolver.resource_exists(res.logical_id):
            continue
        if res.logical_id not in ids:
            raise KeyError(f"{stack.name}/{res.logical_id}: no synthesised physical id")
        res.physical_id = ids[res.logical_id]
        res.status = "CREATE_COMPLETE"
        kept.append(res)
    stack.resources = kept


def _copilot_tags(env: str, svc: str | None = None) -> dict[str, str]:
    tags = {"copilot-application": APP, "copilot-environment": env}
    if svc:
        tags["copilot-service"] = svc
    return tags


def stack_outputs(inv: Inventory, stack: Stack) -> tuple[dict[str, str], dict[str, str]]:
    """(outputs, exports) as DescribeStacks reports them.

    An output whose value is a GetAtt attribute that live reads spell differently (the load
    balancer's ``CanonicalHostedZoneID`` is ``CanonicalHostedZoneId`` in the API) or cannot
    express (``LoadBalancerFullName``) is left out: nothing in this app imports those.
    """
    r = Resolver(inv, stack)
    outputs, exports = {}, {}
    for key, spec in (r.template.get("Outputs") or {}).items():
        if "Condition" in spec and not r.condition(spec["Condition"]):
            continue
        try:
            value = str(r.resolve(spec["Value"]))
        except Unresolvable:
            continue
        outputs[key] = value
        if "Export" in spec:
            exports[r.resolve(spec["Export"]["Name"])] = value
    return outputs, exports


def _certificate() -> OutOfBand:
    """The ACM certificate env's HTTPSCert custom resource requested (as inventory reads it)."""
    return OutOfBand(
        "acm_certificate",
        CERT_ARN,
        f"{ENV_STACK}/HTTPSCert",
        {
            "DomainName": ENV_DOMAIN,
            "SubjectAlternativeNames": [ENV_DOMAIN, f"*.{ENV_DOMAIN}", "example.com"],
            "InUseBy": [LB_ARN],
            "DomainValidationOptions": [
                {
                    "DomainName": ENV_DOMAIN,
                    "ResourceRecord": {
                        "Name": VALIDATION_NAME,
                        "Type": "CNAME",
                        "Value": VALIDATION_VALUE,
                    },
                }
            ],
        },
    )


def build_app(addons: str = "s3-ddb") -> Inventory:
    rendered = FIXTURES / "rendered"
    inv, env = inventory_from_template(
        rendered / "environments/template-with-basic-manifest.yml",
        stack_name=ENV_STACK,
        kind="env",
        env=ENV,
        workload=None,
        workload_type=None,
        params=ENV_PARAMS,
        app=APP,
    )
    inv.captured_at = now_iso()
    env.stack_id = ENV_STACK_ID
    env.tags = _copilot_tags(ENV)
    env.capabilities = ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"]
    _place(inv, env, ENV_IDS)
    inv.live.update(env_live(inv, env))
    env.outputs, env.exports = stack_outputs(inv, env)
    inv.out_of_band.append(_certificate())

    _, svc = inventory_from_template(
        rendered / "workloads/svc-staging.stack.yml",
        stack_name=SVC_STACK,
        env=ENV,
        workload=SVC,
        workload_type="Load Balanced Web Service",
        params=SVC_PARAMS,
        app=APP,
    )
    svc.stack_id = SVC_STACK_ID
    svc.tags = _copilot_tags(ENV, SVC)
    svc.capabilities = ["CAPABILITY_IAM"]
    inv.stacks[svc.name] = svc
    _place(inv, svc, SVC_IDS)
    inv.live.update(svc_live(inv, svc))
    inv.live[TD_ARN] = task_definition_live(inv, svc)
    inv.workloads.append(Workload(SVC, "Load Balanced Web Service", ENV))

    template, ids = ADDONS[addons]
    _, child = inventory_from_template(
        template,
        stack_name=ADDONS_STACK,
        kind="addons",
        env=ENV,
        workload=SVC,
        workload_type=None,
        params={"App": APP, "Env": ENV, "Name": SVC},
        app=APP,
    )
    child.stack_id = ADDONS_STACK_ID
    child.parent = SVC_STACK
    child.parent_logical_id = "AddonsStack"
    child.tags = _copilot_tags(ENV, SVC)
    inv.stacks[child.name] = child
    _place(inv, child, ids)
    inv.live.update((s3_ddb_live if addons == "s3-ddb" else aurora_live)(inv, child))
    child.outputs, child.exports = stack_outputs(inv, child)
    svc.outputs, svc.exports = stack_outputs(inv, svc)
    add_worker(inv)
    add_job(inv)
    return inv
