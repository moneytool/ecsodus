"""Terraform mappers: network family (VPC, subnets, gateways, routing, security groups, endpoints).

Every argument is a literal that matches live state: resolved template properties via
``ctx.r(...)``, and values the template cannot express exactly (AZs from ``Fn::GetAZs``, EIP
allocation IDs, security-group rule IDs, the live default egress rule) from ``ctx.live``, keyed by
the resource's physical ID and named after the EC2 API response fields. A missing live value, or
any CloudFormation property without an exact Terraform equivalent here, raises ``Unresolvable``.

None of these resources hold data (``stateful=False``), but none may ever be recreated either:
ForceNew arguments (``cidr_block``, ``availability_zone``, ``vpc_id``, ``description``, ...) are
always taken from the deployed template or live reads, never defaulted.

Import ID formats follow the AWS provider 6.x docs
(``website/docs/r/<name>.html.markdown`` in hashicorp/terraform-provider-aws).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ecsodus import cfn
from ecsodus.emit.hcl import Block, Body
from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.mappers.tfmap import Ctx, TfSpec, mapper

_ALL_IPV4 = "0.0.0.0/0"
_ALL_IPV6 = "::/0"


# -- helpers --------------------------------------------------------------------------------------
def _only(ctx: Ctx, supported: Iterable[str]) -> None:
    """Refuse any set property this mapper does not translate exactly."""
    allowed = set(supported)
    for key in ctx.props:
        if key not in allowed and ctx.r(key, None) is not None:
            raise Unresolvable(f"property {key} has no exact Terraform mapping in ecsodus")


def _live(ctx: Ctx, key: str) -> Any:
    value = ctx.live.get(key)
    if value is None or value == "":
        raise Unresolvable(f"live {key} for {ctx.pid} not in inventory")
    return value


def _optional(ctx: Ctx, body: Body, pairs: Iterable[tuple[str, str]]) -> None:
    """Append ``(tf_arg, value)`` for each CFN property that is set."""
    for key, arg in pairs:
        v = ctx.r(key, None)
        if v is not None:
            body.append((arg, v))


def _tags(ctx: Ctx, body: Body) -> None:
    tags = ctx.tags()
    if tags:
        body.append(("tags", tags))


def _protocol(value: Any) -> str:
    # EC2 stores protocol names lower-case; CloudFormation accepts "TCP" and the integer -1.
    return str(value).lower()


# -- VPC, subnets, gateways -----------------------------------------------------------------------
@mapper("AWS::EC2::VPC")
def vpc(ctx: Ctx) -> TfSpec:
    """aws_vpc; import ID is the VPC ID (the physical ID). Needs no live keys."""
    _only(ctx, ("CidrBlock", "EnableDnsHostnames", "EnableDnsSupport", "InstanceTenancy", "Tags"))
    lid = ctx.resource.logical_id
    for other in (ctx.resolver.template.get("Resources") or {}).values():
        props = (other or {}).get("Properties") or {}
        if other.get("Type") == "AWS::EC2::VPCCidrBlock" and props.get("VpcId") == {"Ref": lid}:
            # An extra CIDR (notably an Amazon IPv6 block) changes aws_vpc's own arguments.
            raise Unresolvable("VPC has an AWS::EC2::VPCCidrBlock association")
    body: Body = [
        ("cidr_block", ctx.r("CidrBlock")),
        # CloudFormation's defaults are EC2's: DNS support on, DNS hostnames off.
        ("enable_dns_support", bool(ctx.r("EnableDnsSupport", True))),
        ("enable_dns_hostnames", bool(ctx.r("EnableDnsHostnames", False))),
        ("instance_tenancy", ctx.r("InstanceTenancy", "default")),
    ]
    _tags(ctx, body)
    return TfSpec("aws_vpc", ctx.pid, body)


@mapper("AWS::EC2::Subnet")
def subnet(ctx: Ctx) -> TfSpec:
    """aws_subnet; import ID is the subnet ID.

    Live keys: ``live["AvailabilityZone"]`` (DescribeSubnets) when the template's
    ``AvailabilityZone`` is not a literal (Copilot uses ``Fn::Select``/``Fn::GetAZs``). If both
    are known and differ, the value is disputed and the subnet is blocked.
    """
    _only(
        ctx,
        (
            "CidrBlock",
            "VpcId",
            "AvailabilityZone",
            "AvailabilityZoneId",
            "MapPublicIpOnLaunch",
            "Tags",
        ),
    )
    body: Body = [("vpc_id", ctx.r("VpcId")), ("cidr_block", ctx.r("CidrBlock"))]
    if ctx.has("AvailabilityZoneId"):
        body.append(("availability_zone_id", ctx.r("AvailabilityZoneId")))
    else:
        live_az = ctx.live.get("AvailabilityZone")
        try:
            az = ctx.r("AvailabilityZone", None)
        except Unresolvable:
            az = None
        if az is not None and live_az is not None and az != live_az:
            raise Unresolvable(f"AvailabilityZone disputed: template {az}, live {live_az}")
        az = az or live_az
        if not az:
            raise Unresolvable(f"live AvailabilityZone for {ctx.pid} not in inventory")
        body.append(("availability_zone", az))
    body.append(("map_public_ip_on_launch", bool(ctx.r("MapPublicIpOnLaunch", False))))
    _tags(ctx, body)
    return TfSpec("aws_subnet", ctx.pid, body)


@mapper("AWS::EC2::InternetGateway")
def internet_gateway(ctx: Ctx) -> TfSpec:
    """aws_internet_gateway; import ID is the IGW ID. Needs no live keys.

    ``vpc_id`` is left out on purpose: the attachment is its own resource
    (aws_internet_gateway_attachment), and declaring both would fight over it.
    """
    _only(ctx, ("Tags",))
    body: Body = []
    _tags(ctx, body)
    return TfSpec("aws_internet_gateway", ctx.pid, body)


@mapper("AWS::EC2::VPCGatewayAttachment")
def gateway_attachment(ctx: Ctx) -> TfSpec:
    """aws_internet_gateway_attachment; import ID ``<igw-id>:<vpc-id>``. Needs no live keys.

    VPN gateway attachments (``VpnGatewayId``) are blocked: aws_vpn_gateway_attachment cannot be
    imported.
    """
    _only(ctx, ("InternetGatewayId", "VpcId"))
    igw, vpc_id = ctx.r("InternetGatewayId"), ctx.r("VpcId")
    body: Body = [("internet_gateway_id", igw), ("vpc_id", vpc_id)]
    return TfSpec("aws_internet_gateway_attachment", f"{igw}:{vpc_id}", body)


@mapper("AWS::EC2::EIP")
def eip(ctx: Ctx) -> TfSpec:
    """aws_eip; import ID is the allocation ID (the CFN physical ID is the public IP).

    Live keys: ``live["AllocationId"]`` (DescribeAddresses).
    """
    _only(ctx, ("Domain", "PublicIpv4Pool", "NetworkBorderGroup", "Tags"))
    allocation_id = _live(ctx, "AllocationId")
    body: Body = []
    _optional(
        ctx,
        body,
        (
            ("Domain", "domain"),
            ("PublicIpv4Pool", "public_ipv4_pool"),
            ("NetworkBorderGroup", "network_border_group"),
        ),
    )
    _tags(ctx, body)
    return TfSpec("aws_eip", allocation_id, body)


@mapper("AWS::EC2::NatGateway")
def nat_gateway(ctx: Ctx) -> TfSpec:
    """aws_nat_gateway (zonal); import ID is the NAT gateway ID.

    Live keys: none of its own. ``AllocationId`` is ``Fn::GetAtt <EIP>.AllocationId``, which the
    resolver reads from the EIP's ``live["AllocationId"]``. Regional NAT gateways
    (``AvailabilityMode``) are blocked.
    """
    _only(
        ctx,
        (
            "AllocationId",
            "SubnetId",
            "ConnectivityType",
            "PrivateIpAddress",
            "SecondaryAllocationIds",
            "SecondaryPrivateIpAddresses",
            "Tags",
        ),
    )
    connectivity = ctx.r("ConnectivityType", "public")
    body: Body = []
    if connectivity == "public" or ctx.has("AllocationId"):
        body.append(("allocation_id", ctx.r("AllocationId")))
    body += [("subnet_id", ctx.r("SubnetId")), ("connectivity_type", connectivity)]
    _optional(
        ctx,
        body,
        (
            ("PrivateIpAddress", "private_ip"),
            ("SecondaryAllocationIds", "secondary_allocation_ids"),
            ("SecondaryPrivateIpAddresses", "secondary_private_ip_addresses"),
        ),
    )
    _tags(ctx, body)
    return TfSpec("aws_nat_gateway", ctx.pid, body)


# -- routing --------------------------------------------------------------------------------------
@mapper("AWS::EC2::RouteTable")
def route_table(ctx: Ctx) -> TfSpec:
    """aws_route_table; import ID is the route table ID. Needs no live keys.

    No inline ``route`` blocks: routes are separate aws_route resources. ``route`` is an
    attributes-as-blocks argument, so leaving it out means this resource does not manage routes.
    """
    _only(ctx, ("VpcId", "Tags"))
    body: Body = [("vpc_id", ctx.r("VpcId"))]
    _tags(ctx, body)
    return TfSpec("aws_route_table", ctx.pid, body)


_ROUTE_DESTINATIONS = (
    ("DestinationCidrBlock", "destination_cidr_block"),
    ("DestinationIpv6CidrBlock", "destination_ipv6_cidr_block"),
    ("DestinationPrefixListId", "destination_prefix_list_id"),
)
_ROUTE_TARGETS = (
    ("GatewayId", "gateway_id"),
    ("NatGatewayId", "nat_gateway_id"),
    ("TransitGatewayId", "transit_gateway_id"),
    ("VpcPeeringConnectionId", "vpc_peering_connection_id"),
    ("NetworkInterfaceId", "network_interface_id"),
    ("VpcEndpointId", "vpc_endpoint_id"),
    ("EgressOnlyInternetGatewayId", "egress_only_gateway_id"),
    ("CarrierGatewayId", "carrier_gateway_id"),
    ("LocalGatewayId", "local_gateway_id"),
    ("CoreNetworkArn", "core_network_arn"),
)


@mapper("AWS::EC2::Route")
def route(ctx: Ctx) -> TfSpec:
    """aws_route; import ID ``<rtb-id>_<destination>`` (IPv4/IPv6 CIDR or prefix-list ID).

    Needs no live keys. ``InstanceId`` targets are blocked (aws_route 6.x has no such argument).
    """
    _only(
        ctx,
        ("RouteTableId", *(k for k, _ in _ROUTE_DESTINATIONS), *(k for k, _ in _ROUTE_TARGETS)),
    )
    rtb = ctx.r("RouteTableId")
    dests: Body = []
    targets: Body = []
    _optional(ctx, dests, _ROUTE_DESTINATIONS)
    _optional(ctx, targets, _ROUTE_TARGETS)
    if len(dests) != 1:
        raise Unresolvable(f"route needs exactly one destination, found {len(dests)}")
    if len(targets) != 1:
        raise Unresolvable(f"route needs exactly one target, found {len(targets)}")
    body: Body = [("route_table_id", rtb), *dests, *targets]
    return TfSpec("aws_route", f"{rtb}_{dests[0][1]}", body)


@mapper("AWS::EC2::SubnetRouteTableAssociation")
def route_table_association(ctx: Ctx) -> TfSpec:
    """aws_route_table_association; import ID ``<subnet-id>/<rtb-id>``.

    Needs no live keys: both IDs come from the template (the ``rtbassoc-`` ID is not needed).
    """
    _only(ctx, ("SubnetId", "RouteTableId"))
    sub, rtb = ctx.r("SubnetId"), ctx.r("RouteTableId")
    body: Body = [("subnet_id", sub), ("route_table_id", rtb)]
    return TfSpec("aws_route_table_association", f"{sub}/{rtb}", body)


# -- security groups ------------------------------------------------------------------------------
_RULE_TYPES = {
    "ingress": "AWS::EC2::SecurityGroupIngress",
    "egress": "AWS::EC2::SecurityGroupEgress",
}


def _peer_keys(direction: str) -> tuple[str, str]:
    if direction == "ingress":
        return "SourceSecurityGroupId", "SourcePrefixListId"
    return "DestinationSecurityGroupId", "DestinationPrefixListId"


def _standalone_rules_for(ctx: Ctx, direction: str) -> list[str]:
    """Standalone rule resources, in any inventoried stack, that target or may target this group.

    A rule whose ``GroupId`` (or condition) cannot be resolved counts: ecsodus cannot rule it out.
    """
    rtype, found = _RULE_TYPES[direction], []
    for stack in ctx.inv.stacks.values():
        if stack.name == ctx.stack.name:
            resolver = ctx.resolver
        else:
            try:
                resolver = Resolver(ctx.inv, stack, cfn.load(stack.template_body))
            except cfn.TemplateError:
                continue
        for lid, res in (resolver.template.get("Resources") or {}).items():
            if (res or {}).get("Type") != rtype:
                continue
            try:
                if not resolver.resource_exists(lid):
                    continue
                group = resolver.resolve((res.get("Properties") or {}).get("GroupId"))
            except Unresolvable:
                group = None
            if group is None or group == ctx.pid:
                found.append(f"{stack.name}/{lid}")
    return found


def _inline_rule(ctx: Ctx, rule: dict[str, Any], direction: str) -> Block:
    peer_sg, peer_pl = _peer_keys(direction)
    known = {"IpProtocol", "FromPort", "ToPort", "CidrIp", "CidrIpv6", "Description"}
    extra = sorted(set(rule) - known - {peer_sg, peer_pl})
    if extra:
        raise Unresolvable(f"inline {direction} rule property {extra[0]} not supported")
    proto = _protocol(rule["IpProtocol"])
    all_ports = proto == "-1"  # the provider wants from_port = to_port = 0 for -1
    body: Body = [
        ("from_port", 0 if all_ports else int(rule["FromPort"])),
        ("to_port", 0 if all_ports else int(rule["ToPort"])),
        ("protocol", proto),
    ]
    if "CidrIp" in rule:
        body.append(("cidr_blocks", [rule["CidrIp"]]))
    if "CidrIpv6" in rule:
        body.append(("ipv6_cidr_blocks", [rule["CidrIpv6"]]))
    if peer_pl in rule:
        body.append(("prefix_list_ids", [rule[peer_pl]]))
    if peer_sg in rule:
        if rule[peer_sg] == ctx.pid:
            body.append(("self", True))
        else:
            body.append(("security_groups", [rule[peer_sg]]))
    if len(body) != 4:
        raise Unresolvable(f"inline {direction} rule needs exactly one peer")
    if rule.get("Description") is not None:
        body.append(("description", rule["Description"]))
    return Block(body)


def _is_default_egress(perm: dict[str, Any]) -> tuple[bool, bool]:
    """(is the default allow-all rule, includes ::/0)."""
    v4 = perm.get("IpRanges") or []
    v6 = perm.get("Ipv6Ranges") or []
    ok = (
        str(perm.get("IpProtocol")) == "-1"
        and [r.get("CidrIp") for r in v4] == [_ALL_IPV4]
        and [r.get("CidrIpv6") for r in v6] in ([], [_ALL_IPV6])
        and not any(r.get("Description") for r in v4 + v6)
        and not perm.get("UserIdGroupPairs")
        and not perm.get("PrefixListIds")
    )
    return ok, bool(v6)


def _default_egress(ctx: Ctx) -> Block:
    """The default allow-all egress rule, declared inline after checking it against live.

    EC2 gives every new VPC security group an allow-all egress rule, and CloudFormation keeps it
    when the template has no ``SecurityGroupEgress``. Terraform's aws_security_group removes that
    rule unless it is declared, so it is declared here: the first plan neither drops it nor adds
    anything. Live must hold exactly that one rule; anything else is drift and blocks.
    """
    perms = ctx.live.get("IpPermissionsEgress")
    if perms is None:
        raise Unresolvable(f"live IpPermissionsEgress for {ctx.pid} not in inventory")
    ok, has_v6 = _is_default_egress(perms[0]) if len(perms) == 1 else (False, False)
    if not ok:
        raise Unresolvable("live egress is not exactly the default allow-all rule")
    body: Body = [
        ("from_port", 0),
        ("to_port", 0),
        ("protocol", "-1"),
        ("cidr_blocks", [_ALL_IPV4]),
    ]
    if has_v6:
        body.append(("ipv6_cidr_blocks", [_ALL_IPV6]))
    return Block(body)


@mapper("AWS::EC2::SecurityGroup")
def security_group(ctx: Ctx) -> TfSpec:
    """aws_security_group; import ID is the group ID (``sg-...``).

    Live keys: ``live["IpPermissionsEgress"]`` (DescribeSecurityGroups) when the template has no
    ``SecurityGroupEgress`` and no standalone egress rule targets the group; it confirms live
    egress is exactly the default allow-all rule, which is then declared (see _default_egress).

    Inline ``ingress``/``egress`` are attributes-as-blocks: once declared, Terraform owns *all*
    rules in that direction and would delete rules made by standalone rule resources. So when a
    standalone AWS::EC2::SecurityGroupIngress/Egress targets (or might target) this group, that
    direction is left undeclared (Terraform leaves it alone) and fidelity is ``partial``. Inline
    and standalone rules are never both emitted for one group.
    """
    _only(
        ctx,
        (
            "GroupDescription",
            "GroupName",
            "VpcId",
            "SecurityGroupIngress",
            "SecurityGroupEgress",
            "Tags",
        ),
    )
    body: Body = []
    # Without GroupName CloudFormation generated the name; `name` is optional+computed, so leaving
    # it out imports the live name without a diff.
    _optional(ctx, body, (("GroupName", "name"),))
    body.append(("description", ctx.r("GroupDescription")))
    _optional(ctx, body, (("VpcId", "vpc_id"),))
    spec = TfSpec("aws_security_group", ctx.pid, body)

    rules_by_direction = {
        "ingress": ctx.r("SecurityGroupIngress", None),
        "egress": ctx.r("SecurityGroupEgress", None),
    }
    for direction, rules in rules_by_direction.items():
        standalone = _standalone_rules_for(ctx, direction)
        if standalone:
            if rules or direction == "egress":
                what = f"inline {direction} rules" if rules else "the default egress rule"
                spec.fidelity = "partial"
                spec.notes.append(
                    f"{direction} not declared on the group: standalone rules also target it "
                    f"({', '.join(standalone)}); {what} stay unmanaged by Terraform"
                )
            continue
        if direction == "egress" and rules is None:
            body.append(("egress", _default_egress(ctx)))
        else:
            for rule in rules or []:
                body.append((direction, _inline_rule(ctx, rule, direction)))
    _tags(ctx, body)
    return spec


def _rule(ctx: Ctx, direction: str) -> TfSpec:
    peer_sg, peer_pl = _peer_keys(direction)
    _only(
        ctx,
        (
            "GroupId",
            "IpProtocol",
            "FromPort",
            "ToPort",
            "CidrIp",
            "CidrIpv6",
            "Description",
            peer_sg,
            peer_pl,
        ),
    )
    rule_id = ctx.live.get("SecurityGroupRuleId")
    if not rule_id and ctx.pid.startswith("sgr-"):
        rule_id = ctx.pid
    if not rule_id:
        raise Unresolvable(f"live SecurityGroupRuleId for {ctx.pid} not in inventory")
    proto = _protocol(ctx.r("IpProtocol"))
    body: Body = [("security_group_id", ctx.r("GroupId")), ("ip_protocol", proto)]
    if proto != "-1":
        # For -1 (all protocols, all ports) the provider wants from_port/to_port omitted.
        for key, arg in (("FromPort", "from_port"), ("ToPort", "to_port")):
            v = ctx.r(key, None)
            if v is not None:
                body.append((arg, int(v)))
    peers: Body = []
    _optional(
        ctx,
        peers,
        (
            ("CidrIp", "cidr_ipv4"),
            ("CidrIpv6", "cidr_ipv6"),
            (peer_pl, "prefix_list_id"),
            (peer_sg, "referenced_security_group_id"),
        ),
    )
    if len(peers) != 1:
        raise Unresolvable(f"{direction} rule needs exactly one peer, found {len(peers)}")
    body += peers
    _optional(ctx, body, (("Description", "description"),))
    return TfSpec(f"aws_vpc_security_group_{direction}_rule", rule_id, body)


@mapper("AWS::EC2::SecurityGroupIngress")
def security_group_ingress(ctx: Ctx) -> TfSpec:
    """aws_vpc_security_group_ingress_rule; import ID is the rule ID (``sgr-...``).

    Live keys: ``live["SecurityGroupRuleId"]`` (DescribeSecurityGroupRules), unless the physical
    ID already is the ``sgr-`` ID. Cross-account (``SourceSecurityGroupOwnerId``) and name-based
    (``GroupName``, ``SourceSecurityGroupName``) rules are blocked.
    """
    return _rule(ctx, "ingress")


@mapper("AWS::EC2::SecurityGroupEgress")
def security_group_egress(ctx: Ctx) -> TfSpec:
    """aws_vpc_security_group_egress_rule; import ID is the rule ID (``sgr-...``).

    Live keys: ``live["SecurityGroupRuleId"]`` (DescribeSecurityGroupRules), unless the physical
    ID already is the ``sgr-`` ID.
    """
    return _rule(ctx, "egress")


# -- endpoints and flow logs ----------------------------------------------------------------------
@mapper("AWS::EC2::VPCEndpoint")
def vpc_endpoint(ctx: Ctx) -> TfSpec:
    """aws_vpc_endpoint; import ID is the endpoint ID (``vpce-...``). Needs no live keys.

    Without a ``PolicyDocument`` AWS attaches its default full-access policy; ``policy`` is
    optional+computed, so it is left out and imported as-is.
    """
    _only(
        ctx,
        (
            "VpcId",
            "ServiceName",
            "VpcEndpointType",
            "SecurityGroupIds",
            "SubnetIds",
            "RouteTableIds",
            "PrivateDnsEnabled",
            "PolicyDocument",
            "Tags",
        ),
    )
    etype = ctx.r("VpcEndpointType", "Gateway")
    body: Body = [
        ("vpc_id", ctx.r("VpcId")),
        ("service_name", ctx.r("ServiceName")),
        ("vpc_endpoint_type", etype),
    ]
    for key, arg in (
        ("SubnetIds", "subnet_ids"),
        ("SecurityGroupIds", "security_group_ids"),
        ("RouteTableIds", "route_table_ids"),
    ):
        ids = ctx.r(key, None)
        if ids:
            body.append((arg, sorted(ids)))  # sets in Terraform; sorted for stable output
    if etype == "Interface":
        body.append(("private_dns_enabled", bool(ctx.r("PrivateDnsEnabled", False))))
    elif ctx.r("PrivateDnsEnabled", None) is not None:
        raise Unresolvable(f"PrivateDnsEnabled on a {etype} endpoint")
    policy = ctx.r("PolicyDocument", None)
    if policy is not None:
        body.append(("policy", policy if isinstance(policy, str) else json.dumps(policy)))
    _tags(ctx, body)
    return TfSpec("aws_vpc_endpoint", ctx.pid, body)


_FLOW_LOG_TARGETS = {
    "VPC": "vpc_id",
    "Subnet": "subnet_id",
    "NetworkInterface": "eni_id",
    "TransitGateway": "transit_gateway_id",
    "TransitGatewayAttachment": "transit_gateway_attachment_id",
}
_FLOW_LOG_DEST_OPTIONS = {
    "FileFormat": "file_format",
    "HiveCompatiblePartitions": "hive_compatible_partitions",
    "PerHourPartition": "per_hour_partition",
}


@mapper("AWS::EC2::FlowLog")
def flow_log(ctx: Ctx) -> TfSpec:
    """aws_flow_log; import ID is the flow log ID (``fl-...``).

    Live keys: ``live["LogDestination"]`` (DescribeFlowLogs) when the template names a log group
    (``LogGroupName``) instead of a ``LogDestination`` ARN; provider 6.x only takes the ARN.
    """
    _only(
        ctx,
        (
            "DeliverLogsPermissionArn",
            "DeliverCrossAccountRole",
            "LogDestinationType",
            "LogDestination",
            "LogGroupName",
            "LogFormat",
            "MaxAggregationInterval",
            "ResourceId",
            "ResourceType",
            "TrafficType",
            "DestinationOptions",
            "Tags",
        ),
    )
    rtype = ctx.r("ResourceType")
    target = _FLOW_LOG_TARGETS.get(rtype)
    if target is None:
        raise Unresolvable(f"flow log ResourceType {rtype} not supported")
    destination = ctx.r("LogDestination", None)
    if destination is None:
        if ctx.r("LogGroupName", None) is None:
            raise Unresolvable("flow log has neither LogDestination nor LogGroupName")
        destination = _live(ctx, "LogDestination")
    body: Body = [(target, ctx.r("ResourceId"))]
    _optional(ctx, body, (("TrafficType", "traffic_type"),))
    body += [
        ("log_destination_type", ctx.r("LogDestinationType", "cloud-watch-logs")),
        ("log_destination", destination),
    ]
    _optional(
        ctx,
        body,
        (
            ("DeliverLogsPermissionArn", "iam_role_arn"),
            ("DeliverCrossAccountRole", "deliver_cross_account_role"),
            ("LogFormat", "log_format"),
        ),
    )
    body.append(("max_aggregation_interval", int(ctx.r("MaxAggregationInterval", 600))))
    opts = ctx.r("DestinationOptions", None)
    if opts:
        unknown = sorted(set(opts) - set(_FLOW_LOG_DEST_OPTIONS))
        if unknown:
            raise Unresolvable(f"DestinationOptions keys {unknown} not supported")
        items: Body = [(_FLOW_LOG_DEST_OPTIONS[k], v) for k, v in opts.items()]
        body.append(("destination_options", Block(items)))
    _tags(ctx, body)
    return TfSpec("aws_flow_log", ctx.pid, body)
