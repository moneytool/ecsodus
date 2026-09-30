"""Network-family mappers (tf_network) against real Copilot env and workload templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ecsodus import cfn
from ecsodus.emit import hcl
from ecsodus.emit.hcl import Block
from ecsodus.mappers import tf_network  # noqa: F401  (registers the mappers)
from ecsodus.mappers.resolve import Resolver
from ecsodus.mappers.tfmap import BLOCKED, NotImported, TfSpec, map_resource
from ecsodus.model import Inventory, Stack
from tests.helpers import ACCOUNT, FIXTURES, REGION, inventory_from_template

ENVS = FIXTURES / "rendered" / "environments"
WORKLOADS = FIXTURES / "rendered" / "workloads"
BASIC = ENVS / "template-with-basic-manifest.yml"
FLOWLOGS = ENVS / "template-with-importedvpc-flowlogs.yml"
ACCESS_LOGS = ENVS / "template-with-default-access-log-config.yml"

NETWORK_TYPES = {
    "AWS::EC2::VPC",
    "AWS::EC2::Subnet",
    "AWS::EC2::InternetGateway",
    "AWS::EC2::VPCGatewayAttachment",
    "AWS::EC2::RouteTable",
    "AWS::EC2::Route",
    "AWS::EC2::SubnetRouteTableAssociation",
    "AWS::EC2::NatGateway",
    "AWS::EC2::EIP",
    "AWS::EC2::SecurityGroup",
    "AWS::EC2::SecurityGroupIngress",
    "AWS::EC2::SecurityGroupEgress",
    "AWS::EC2::VPCEndpoint",
    "AWS::EC2::FlowLog",
}

DEFAULT_EGRESS = [
    {
        "IpProtocol": "-1",
        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        "Ipv6Ranges": [],
        "PrefixListIds": [],
        "UserIdGroupPairs": [],
    }
]


def env_inventory(path: Path = BASIC, stack_name: str = "demo-test") -> tuple[Inventory, Stack]:
    return inventory_from_template(
        path, stack_name=stack_name, kind="env", workload=None, workload_type=None
    )


def add_live(inv: Inventory, stack: Stack) -> None:
    """The live reads the network mappers need, shaped like the EC2 API responses."""
    azs = {"1": f"{REGION}a", "2": f"{REGION}b"}
    for i, res in enumerate(stack.resources):
        pid = res.physical_id or ""
        live = inv.live.setdefault(pid, {})
        if res.type == "AWS::EC2::Subnet":
            live["AvailabilityZone"] = azs[res.logical_id[-1]]
        elif res.type == "AWS::EC2::EIP":
            live["AllocationId"] = f"eipalloc-0{i:016d}"
        elif res.type == "AWS::EC2::SecurityGroup":
            live["IpPermissionsEgress"] = DEFAULT_EGRESS
        elif res.type in ("AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress"):
            live["SecurityGroupRuleId"] = f"sgr-0{i:016d}"
        elif res.type == "AWS::EC2::FlowLog":
            live["LogDestination"] = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/copilot/vpc"


def map_all(inv: Inventory, stack: Stack) -> dict[str, Any]:
    resolver = Resolver(inv, stack)
    resources = resolver.template["Resources"]
    return {
        r.logical_id: map_resource(inv, stack, resolver, r, resources[r.logical_id])
        for r in stack.resources
    }


def pid(stack: Stack, lid: str) -> str:
    res = stack.resource(lid)
    assert res is not None and res.physical_id
    return res.physical_id


def args(spec: Any) -> dict[str, Any]:
    assert isinstance(spec, TfSpec), spec
    return dict(spec.body)


def blocks(spec: TfSpec, name: str) -> list[dict[str, Any]]:
    return [dict(v.body) for k, v in spec.body if k == name and isinstance(v, Block)]


# -- coverage -------------------------------------------------------------------------------------
def test_every_network_type_in_the_fixtures_has_a_mapper() -> None:
    from ecsodus.mappers.tfmap import MAPPERS

    used = set()
    for path in [*ENVS.glob("*.yml"), *WORKLOADS.glob("*.stack.yml")]:
        for body in cfn.load(path.read_text())["Resources"].values():
            if body["Type"].startswith("AWS::EC2::"):
                used.add(body["Type"])
    assert used <= NETWORK_TYPES
    assert set(MAPPERS) >= NETWORK_TYPES


@pytest.mark.parametrize("path", [BASIC, ACCESS_LOGS, FLOWLOGS])
def test_every_network_resource_maps_when_live_data_is_present(path: Path) -> None:
    inv, stack = env_inventory(path)
    add_live(inv, stack)
    results = map_all(inv, stack)
    network = {lid: r for lid, r in results.items() if stack.resource(lid).type in NETWORK_TYPES}
    assert network
    for lid, result in network.items():
        assert isinstance(result, TfSpec), (lid, result)
        assert result.stateful is False
        assert result.fidelity == "full", (lid, result.notes)
        hcl.block("resource", (result.tf_type, lid), result.body)  # renders


# -- VPC and subnets ------------------------------------------------------------------------------
def test_vpc_subnet_and_gateway() -> None:
    inv, stack = env_inventory()
    add_live(inv, stack)
    got = map_all(inv, stack)
    vpc_id = pid(stack, "VPC")

    assert got["VPC"].tf_type == "aws_vpc" and got["VPC"].import_id == vpc_id
    assert args(got["VPC"]) == {
        "cidr_block": "10.0.0.0/16",
        "enable_dns_support": True,
        "enable_dns_hostnames": True,
        "instance_tenancy": "default",
        "tags": {"Name": "copilot-my-app-environmentname"},
    }

    sub = got["PrivateSubnet2"]
    assert sub.tf_type == "aws_subnet" and sub.import_id == pid(stack, "PrivateSubnet2")
    a = args(sub)
    assert a["vpc_id"] == vpc_id
    assert a["cidr_block"] == "10.0.3.0/24"
    assert a["availability_zone"] == f"{REGION}b"
    assert a["map_public_ip_on_launch"] is False
    assert args(got["PublicSubnet1"])["map_public_ip_on_launch"] is True

    igw = pid(stack, "InternetGateway")
    assert got["InternetGateway"].tf_type == "aws_internet_gateway"
    assert "vpc_id" not in args(got["InternetGateway"])
    att = got["InternetGatewayAttachment"]
    assert att.tf_type == "aws_internet_gateway_attachment"
    assert att.import_id == f"{igw}:{vpc_id}"


def test_subnet_without_live_az_is_blocked() -> None:
    inv, stack = env_inventory()
    got = map_all(inv, stack)
    assert isinstance(got["PublicSubnet1"], NotImported)
    assert got["PublicSubnet1"].fate == BLOCKED
    assert "AvailabilityZone" in got["PublicSubnet1"].reason


def test_subnet_disputed_az_is_blocked(tmp_path: Path) -> None:
    tpl = tmp_path / "t.yml"
    tpl.write_text(
        "Resources:\n"
        "  Sub:\n"
        "    Type: AWS::EC2::Subnet\n"
        "    Properties: {VpcId: vpc-1, CidrBlock: 10.0.0.0/24, AvailabilityZone: us-west-2a}\n"
    )
    inv, stack = env_inventory(tpl)
    assert args(map_all(inv, stack)["Sub"])["availability_zone"] == "us-west-2a"
    inv.live[pid(stack, "Sub")] = {"AvailabilityZone": "us-west-2c"}
    got = map_all(inv, stack)["Sub"]
    assert isinstance(got, NotImported) and "disputed" in got.reason


# -- routing, NAT, EIP ----------------------------------------------------------------------------
def test_routes_associations_nat_and_eip() -> None:
    inv, stack = env_inventory()
    add_live(inv, stack)
    got = map_all(inv, stack)
    public_rtb, private_rtb = pid(stack, "PublicRouteTable"), pid(stack, "PrivateRouteTable1")

    assert got["PublicRouteTable"].tf_type == "aws_route_table"
    assert "route" not in args(got["PublicRouteTable"])

    r = got["DefaultPublicRoute"]
    assert r.tf_type == "aws_route" and r.import_id == f"{public_rtb}_0.0.0.0/0"
    assert args(r) == {
        "route_table_id": public_rtb,
        "destination_cidr_block": "0.0.0.0/0",
        "gateway_id": pid(stack, "InternetGateway"),
    }
    assert args(got["PrivateRoute1"])["nat_gateway_id"] == pid(stack, "NatGateway1")

    assoc = got["PrivateRouteTable1Association"]
    assert assoc.tf_type == "aws_route_table_association"
    assert assoc.import_id == f"{pid(stack, 'PrivateSubnet1')}/{private_rtb}"

    alloc = inv.live[pid(stack, "NatGateway1Attachment")]["AllocationId"]
    eip = got["NatGateway1Attachment"]
    assert eip.tf_type == "aws_eip" and eip.import_id == alloc
    assert args(eip) == {"domain": "vpc"}

    nat = got["NatGateway1"]
    assert nat.tf_type == "aws_nat_gateway" and nat.import_id == pid(stack, "NatGateway1")
    assert args(nat)["allocation_id"] == alloc
    assert args(nat)["subnet_id"] == pid(stack, "PublicSubnet1")
    assert args(nat)["connectivity_type"] == "public"


def test_eip_and_nat_without_allocation_id_are_blocked() -> None:
    inv, stack = env_inventory()
    got = map_all(inv, stack)
    for lid in ("NatGateway1Attachment", "NatGateway1"):
        assert isinstance(got[lid], NotImported) and got[lid].fate == BLOCKED


def test_route_prefix_list_and_instance_target(tmp_path: Path) -> None:
    tpl = tmp_path / "t.yml"
    tpl.write_text(
        "Resources:\n"
        "  PL:\n"
        "    Type: AWS::EC2::Route\n"
        "    Properties: {RouteTableId: rtb-1, DestinationPrefixListId: pl-9,"
        " VpcEndpointId: vpce-1}\n"
        "  Inst:\n"
        "    Type: AWS::EC2::Route\n"
        "    Properties: {RouteTableId: rtb-1, DestinationCidrBlock: 10.1.0.0/16,"
        " InstanceId: i-1}\n"
    )
    inv, stack = env_inventory(tpl)
    got = map_all(inv, stack)
    assert got["PL"].import_id == "rtb-1_pl-9"
    assert args(got["PL"])["vpc_endpoint_id"] == "vpce-1"
    assert isinstance(got["Inst"], NotImported) and "InstanceId" in got["Inst"].reason


# -- security groups ------------------------------------------------------------------------------
def test_security_group_inline_ingress_and_default_egress() -> None:
    inv, stack = env_inventory()
    add_live(inv, stack)
    sg = map_all(inv, stack)["PublicHTTPLoadBalancerSecurityGroup"]
    assert sg.tf_type == "aws_security_group"
    assert sg.import_id == pid(stack, "PublicHTTPLoadBalancerSecurityGroup")
    a = args(sg)
    assert "name" not in a  # CloudFormation-generated; optional+computed
    assert a["description"] == "HTTP access to the public facing load balancer"
    assert a["vpc_id"] == pid(stack, "VPC")
    assert blocks(sg, "ingress") == [
        {
            "from_port": 80,
            "to_port": 80,
            "protocol": "tcp",
            "cidr_blocks": ["0.0.0.0/0"],
            "description": "Allow from anyone on port 80",
        }
    ]
    assert blocks(sg, "egress") == [
        {"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}
    ]
    assert sg.fidelity == "full"


def test_security_group_default_egress_needs_live_and_must_match() -> None:
    inv, stack = env_inventory()
    lid = "EnvironmentSecurityGroup"
    got = map_all(inv, stack)[lid]
    assert isinstance(got, NotImported) and "IpPermissionsEgress" in got.reason

    inv.live[pid(stack, lid)] = {
        "IpPermissionsEgress": [{**DEFAULT_EGRESS[0], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}]
    }
    sg = map_all(inv, stack)[lid]
    assert blocks(sg, "egress")[0]["ipv6_cidr_blocks"] == ["::/0"]

    inv.live[pid(stack, lid)] = {
        "IpPermissionsEgress": [{**DEFAULT_EGRESS[0], "IpRanges": [{"CidrIp": "10.0.0.0/8"}]}]
    }
    got = map_all(inv, stack)[lid]
    assert isinstance(got, NotImported) and "default allow-all" in got.reason


def test_env_security_group_leaves_ingress_to_standalone_rules() -> None:
    inv, stack = env_inventory()
    add_live(inv, stack)
    sg = map_all(inv, stack)["EnvironmentSecurityGroup"]
    # Its ingress comes from AWS::EC2::SecurityGroupIngress resources: no inline ingress.
    assert blocks(sg, "ingress") == []
    assert len(blocks(sg, "egress")) == 1
    assert sg.fidelity == "full"


def test_nlb_security_group_multiple_protocols() -> None:
    inv, stack = inventory_from_template(WORKLOADS / "svc-nlb-test.stack.yml")
    inv.live[pid(stack, "NetworkLoadBalancerSecurityGroup")] = {
        "IpPermissionsEgress": DEFAULT_EGRESS
    }
    inv.stacks["demo-test"] = Stack(
        name="demo-test",
        kind="env",
        exports={
            "my-app-test-VpcId": "vpc-0abc",
            "my-app-test-EnvironmentSecurityGroup": "sg-0env",
        },
    )
    inv.live[pid(stack, "EnvironmentSecurityGroupIngressFromNetworkLoadBalancerSecurityGroup")] = {
        "SecurityGroupRuleId": "sgr-0nlb"
    }
    got = map_all(inv, stack)
    sg = got["NetworkLoadBalancerSecurityGroup"]
    assert args(sg)["vpc_id"] == "vpc-0abc"
    assert [(b["protocol"], b["from_port"]) for b in blocks(sg, "ingress")] == [
        ("tcp", 443),
        ("tcp", 8080),
        ("udp", 8081),
    ]
    rule = got["EnvironmentSecurityGroupIngressFromNetworkLoadBalancerSecurityGroup"]
    assert rule.tf_type == "aws_vpc_security_group_ingress_rule"
    assert rule.import_id == "sgr-0nlb"
    assert args(rule) == {
        "security_group_id": "sg-0env",
        "ip_protocol": "-1",
        "referenced_security_group_id": pid(stack, "NetworkLoadBalancerSecurityGroup"),
    }


def test_ingress_rule_needs_live_rule_id() -> None:
    inv, stack = env_inventory()
    got = map_all(inv, stack)["EnvironmentSecurityGroupIngressFromSelf"]
    assert isinstance(got, NotImported) and got.fate == BLOCKED
    assert "SecurityGroupRuleId" in got.reason

    add_live(inv, stack)
    rule = map_all(inv, stack)["EnvironmentSecurityGroupIngressFromSelf"]
    env_sg = pid(stack, "EnvironmentSecurityGroup")
    assert rule.import_id.startswith("sgr-")
    assert args(rule) == {
        "security_group_id": env_sg,
        "ip_protocol": "-1",
        "referenced_security_group_id": env_sg,
        "description": "Ingress from other containers in the same security group",
    }


def test_inline_rules_yield_to_standalone_rules_from_other_stacks() -> None:
    inv, env = env_inventory()
    add_live(inv, env)
    _, svc = inventory_from_template(WORKLOADS / "svc-test.stack.yml")
    inv.stacks[svc.name] = svc
    lb_sg = "PublicHTTPLoadBalancerSecurityGroup"

    # svc's rules target GetAtt EnvControllerAction.EnvironmentSecurityGroup, unknown here: they
    # might target any group, so inline ingress is not declared.
    sg = map_all(inv, env)[lb_sg]
    assert sg.fidelity == "partial"
    assert blocks(sg, "ingress") == []
    assert len(blocks(sg, "egress")) == 1
    assert any("EnvironmentSecurityGroupIngressFromImportedALB" in n for n in sg.notes)

    # Once the custom resource output is known, they target the env SG only.
    inv.live[pid(svc, "EnvControllerAction")] = {
        "EnvironmentSecurityGroup": pid(env, "EnvironmentSecurityGroup")
    }
    sg = map_all(inv, env)[lb_sg]
    assert sg.fidelity == "full" and len(blocks(sg, "ingress")) == 1
    rule = map_all(inv, svc)["EnvironmentSecurityGroupIngressFromImportedALB"]
    assert isinstance(rule, NotImported)  # no live rule ID yet
    inv.live[pid(svc, "EnvironmentSecurityGroupIngressFromImportedALB")] = {
        "SecurityGroupRuleId": "sgr-0alb"
    }
    rule = map_all(inv, svc)["EnvironmentSecurityGroupIngressFromImportedALB"]
    assert args(rule)["security_group_id"] == pid(env, "EnvironmentSecurityGroup")
    assert args(rule)["referenced_security_group_id"] == "mockImportALBSG1"


def test_egress_rules_standalone_and_inline(tmp_path: Path) -> None:
    tpl = tmp_path / "t.yml"
    tpl.write_text(
        "Resources:\n"
        "  A:\n"
        "    Type: AWS::EC2::SecurityGroup\n"
        "    Properties:\n"
        "      GroupDescription: a\n"
        "      VpcId: vpc-1\n"
        "      SecurityGroupEgress:\n"
        "        - {IpProtocol: tcp, FromPort: 443, ToPort: 443, CidrIp: 10.0.0.0/8}\n"
        "        - {IpProtocol: -1, DestinationSecurityGroupId: !Ref A}\n"
        "  B:\n"
        "    Type: AWS::EC2::SecurityGroup\n"
        "    Properties: {GroupDescription: b, GroupName: bee, VpcId: vpc-1}\n"
        "  BOut:\n"
        "    Type: AWS::EC2::SecurityGroupEgress\n"
        "    Properties: {GroupId: !Ref B, IpProtocol: tcp, FromPort: 5432, ToPort: 5432,"
        " DestinationPrefixListId: pl-1}\n"
    )
    inv, stack = env_inventory(tpl)
    inv.live[pid(stack, "BOut")] = {"SecurityGroupRuleId": "sgr-0out"}
    got = map_all(inv, stack)

    a = got["A"]  # inline egress is exact; no live egress read needed
    assert a.fidelity == "full"
    assert blocks(a, "egress") == [
        {"from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["10.0.0.0/8"]},
        {"from_port": 0, "to_port": 0, "protocol": "-1", "self": True},
    ]

    b = got["B"]  # a standalone egress rule owns B's egress: nothing inline
    assert args(b)["name"] == "bee"
    assert blocks(b, "egress") == []
    assert b.fidelity == "partial" and "BOut" in b.notes[0]

    out = got["BOut"]
    assert out.tf_type == "aws_vpc_security_group_egress_rule" and out.import_id == "sgr-0out"
    assert args(out) == {
        "security_group_id": pid(stack, "B"),
        "ip_protocol": "tcp",
        "from_port": 5432,
        "to_port": 5432,
        "prefix_list_id": "pl-1",
    }


def test_unsupported_property_blocks(tmp_path: Path) -> None:
    tpl = tmp_path / "t.yml"
    tpl.write_text(
        "Resources:\n"
        "  In:\n"
        "    Type: AWS::EC2::SecurityGroupIngress\n"
        "    Properties: {GroupId: sg-1, IpProtocol: tcp, FromPort: 1, ToPort: 1,"
        " SourceSecurityGroupId: sg-2, SourceSecurityGroupOwnerId: '111111111111'}\n"
        "  Att:\n"
        "    Type: AWS::EC2::VPCGatewayAttachment\n"
        "    Properties: {VpcId: vpc-1, VpnGatewayId: vgw-1}\n"
    )
    inv, stack = env_inventory(tpl)
    inv.live[pid(stack, "In")] = {"SecurityGroupRuleId": "sgr-1"}
    got = map_all(inv, stack)
    assert isinstance(got["In"], NotImported) and "SourceSecurityGroupOwnerId" in got["In"].reason
    assert isinstance(got["Att"], NotImported) and got["Att"].fate == BLOCKED


# -- endpoints and flow logs ----------------------------------------------------------------------
def test_vpc_endpoint() -> None:
    inv, stack = env_inventory()
    ep = map_all(inv, stack)["AppRunnerVpcEndpoint"]
    assert ep.tf_type == "aws_vpc_endpoint" and ep.import_id == pid(stack, "AppRunnerVpcEndpoint")
    a = args(ep)
    assert a["vpc_id"] == pid(stack, "VPC")
    assert a["service_name"] == f"com.amazonaws.{REGION}.apprunner.requests"
    assert a["vpc_endpoint_type"] == "Interface"
    assert a["subnet_ids"] == sorted([pid(stack, "PrivateSubnet1"), pid(stack, "PrivateSubnet2")])
    assert a["security_group_ids"] == [pid(stack, "AppRunnerVpcEndpointSecurityGroup")]
    assert a["private_dns_enabled"] is False
    assert "policy" not in a


def test_flow_log() -> None:
    inv, stack = env_inventory(FLOWLOGS)
    got = map_all(inv, stack)["FlowLog"]
    assert isinstance(got, NotImported) and "LogDestination" in got.reason

    add_live(inv, stack)
    fl = map_all(inv, stack)["FlowLog"]
    assert fl.tf_type == "aws_flow_log" and fl.import_id == pid(stack, "FlowLog")
    assert args(fl) == {
        "vpc_id": "vpc-12345",
        "traffic_type": "ALL",
        "log_destination_type": "cloud-watch-logs",
        "log_destination": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/copilot/vpc",
        "iam_role_arn": f"arn:aws:iam::{ACCOUNT}:role/{pid(stack, 'FlowLogRole')}",
        "max_aggregation_interval": 60,
    }
