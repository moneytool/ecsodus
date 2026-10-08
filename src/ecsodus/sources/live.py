"""Live reads for the Terraform mappers (PLAN §2.1). Read-only.

``inv.live`` maps a resource's physical ID to the AWS API response for that resource, using the
API's own field names. Mappers read values the template cannot express exactly: custom-resource
outputs (listener-rule priorities), generated names, AZs, rule IDs, the task definition as
registered, and settings changed since the template was written (for example RDS engine version
and deletion protection).

Where the deployed template and live state disagree on something the template sets explicitly,
the inventory records it in ``inv.disputed`` and never picks one silently.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from typing import Any

from ecsodus.model import Inventory
from ecsodus.sources.aws import Clients, paginate

Reader = Callable[[Clients, Inventory, list[str]], None]
READERS: dict[str, Reader] = {}


def reader(*types: str) -> Callable[[Reader], Reader]:
    def register(fn: Reader) -> Reader:
        for t in types:
            READERS[t] = fn
        return fn

    return register


def read_live(clients: Clients, inv: Inventory) -> None:
    by_type: dict[str, list[str]] = {}
    for stack in inv.stacks.values():
        for r in stack.resources:
            if r.physical_id:
                by_type.setdefault(r.type, []).append(r.physical_id)
    for rtype, ids in sorted(by_type.items()):
        fn = READERS.get(rtype)
        if fn is None:
            continue
        try:
            fn(clients, inv, sorted(set(ids)))
        except Exception as exc:  # noqa: BLE001 - record and continue; mappers will block
            inv.unavailable.append({"type": rtype, "reason": f"live read failed: {exc}"})


def _chunks(ids: list[str], n: int) -> list[list[str]]:
    return [ids[i : i + n] for i in range(0, len(ids), n)]


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k != "ResponseMetadata"}


# -- ECS -----------------------------------------------------------------------------------
@reader("AWS::ECS::Service")
def _ecs_services(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ecs = clients("ecs")
    by_cluster: dict[str, list[str]] = {}
    for arn in ids:
        parts = arn.split("/")
        if len(parts) >= 3:
            by_cluster.setdefault(parts[-2], []).append(arn)
    for cluster, arns in by_cluster.items():
        for chunk in _chunks(arns, 10):
            resp = ecs.describe_services(cluster=cluster, services=chunk, include=["TAGS"])
            for svc in resp.get("services") or []:
                inv.live[svc["serviceArn"]] = _clean(svc)


@reader("AWS::ECS::TaskDefinition")
def _task_definitions(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ecs = clients("ecs")
    for arn in ids:
        resp = ecs.describe_task_definition(taskDefinition=arn, include=["TAGS"])
        td = dict(resp["taskDefinition"])
        td["tags"] = resp.get("tags", [])
        inv.live[arn] = td


@reader("AWS::ECS::Cluster")
def _clusters(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ecs = clients("ecs")
    for chunk in _chunks(ids, 100):
        resp = ecs.describe_clusters(clusters=chunk, include=["SETTINGS", "CONFIGURATIONS", "TAGS"])
        for c in resp.get("clusters") or []:
            inv.live[c["clusterName"]] = _clean(c)
            inv.live[c["clusterArn"]] = _clean(c)


# -- Load balancing --------------------------------------------------------------------------
@reader("AWS::ElasticLoadBalancingV2::LoadBalancer")
def _load_balancers(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    elb = clients("elbv2")
    for chunk in _chunks(ids, 20):
        for lb in elb.describe_load_balancers(LoadBalancerArns=chunk).get("LoadBalancers") or []:
            arn = lb["LoadBalancerArn"]
            attrs = elb.describe_load_balancer_attributes(LoadBalancerArn=arn)["Attributes"]
            lb["Attributes"] = {a["Key"]: a["Value"] for a in attrs}
            inv.live[arn] = lb


@reader("AWS::ElasticLoadBalancingV2::TargetGroup")
def _target_groups(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    elb = clients("elbv2")
    for chunk in _chunks(ids, 20):
        for tg in elb.describe_target_groups(TargetGroupArns=chunk).get("TargetGroups") or []:
            arn = tg["TargetGroupArn"]
            attrs = elb.describe_target_group_attributes(TargetGroupArn=arn)["Attributes"]
            tg["Attributes"] = {a["Key"]: a["Value"] for a in attrs}
            inv.live[arn] = tg


@reader("AWS::ElasticLoadBalancingV2::Listener")
def _listeners(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    elb = clients("elbv2")
    for chunk in _chunks(ids, 20):
        for li in elb.describe_listeners(ListenerArns=chunk).get("Listeners") or []:
            inv.live[li["ListenerArn"]] = li


@reader("AWS::ElasticLoadBalancingV2::ListenerRule")
def _rules(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    elb = clients("elbv2")
    for chunk in _chunks(ids, 20):
        for rule in elb.describe_rules(RuleArns=chunk).get("Rules") or []:
            inv.live[rule["RuleArn"]] = rule


# -- EC2 networking ------------------------------------------------------------------------
@reader("AWS::EC2::Subnet")
def _subnets(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for s in paginate(ec2, "describe_subnets", "Subnets", SubnetIds=ids):
        inv.live[s["SubnetId"]] = s


@reader("AWS::EC2::VPC")
def _vpcs(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for v in paginate(ec2, "describe_vpcs", "Vpcs", VpcIds=ids):
        for attr, key in (
            ("enableDnsSupport", "EnableDnsSupport"),
            ("enableDnsHostnames", "EnableDnsHostnames"),
        ):
            resp = ec2.describe_vpc_attribute(VpcId=v["VpcId"], Attribute=attr)
            v[key] = resp.get(key, {}).get("Value")
        inv.live[v["VpcId"]] = v


@reader("AWS::EC2::EIP")
def _eips(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    ips = [i for i in ids if not i.startswith("eipalloc-")]
    allocs = [i for i in ids if i.startswith("eipalloc-")]
    addrs: list[dict[str, Any]] = []
    if ips:
        addrs += ec2.describe_addresses(PublicIps=ips).get("Addresses") or []
    if allocs:
        addrs += ec2.describe_addresses(AllocationIds=allocs).get("Addresses") or []
    for a in addrs:
        inv.live[a["PublicIp"]] = a
        inv.live[a["AllocationId"]] = a


@reader("AWS::EC2::NatGateway")
def _nats(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for n in paginate(ec2, "describe_nat_gateways", "NatGateways", NatGatewayIds=ids):
        inv.live[n["NatGatewayId"]] = n


@reader("AWS::EC2::RouteTable")
def _route_tables(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for rt in paginate(ec2, "describe_route_tables", "RouteTables", RouteTableIds=ids):
        inv.live[rt["RouteTableId"]] = rt


@reader("AWS::EC2::SecurityGroup")
def _security_groups(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    groups = paginate(ec2, "describe_security_groups", "SecurityGroups", GroupIds=ids)
    rules = paginate(
        ec2,
        "describe_security_group_rules",
        "SecurityGroupRules",
        Filters=[{"Name": "group-id", "Values": ids}],
    )
    for g in groups:
        g["SecurityGroupRules"] = [r for r in rules if r["GroupId"] == g["GroupId"]]
        inv.live[g["GroupId"]] = g


@reader("AWS::EC2::InternetGateway")
def _igws(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for g in paginate(
        ec2, "describe_internet_gateways", "InternetGateways", InternetGatewayIds=ids
    ):
        inv.live[g["InternetGatewayId"]] = g


@reader("AWS::EC2::VPCEndpoint")
def _endpoints(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for e in paginate(ec2, "describe_vpc_endpoints", "VpcEndpoints", VpcEndpointIds=ids):
        inv.live[e["VpcEndpointId"]] = e


# -- Data ----------------------------------------------------------------------------------
@reader("AWS::RDS::DBCluster")
def _db_clusters(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    rds = clients("rds")
    for cid in ids:
        for c in rds.describe_db_clusters(DBClusterIdentifier=cid).get("DBClusters") or []:
            inv.live[cid] = c


@reader("AWS::RDS::DBInstance")
def _db_instances(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    rds = clients("rds")
    for iid in ids:
        for i in rds.describe_db_instances(DBInstanceIdentifier=iid).get("DBInstances") or []:
            inv.live[iid] = i


@reader("AWS::DynamoDB::Table")
def _tables(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ddb = clients("dynamodb")
    for name in ids:
        t = ddb.describe_table(TableName=name)["Table"]
        try:
            pitr = ddb.describe_continuous_backups(TableName=name)
            t["ContinuousBackups"] = pitr.get("ContinuousBackupsDescription", {})
        except Exception:  # noqa: BLE001
            pass
        inv.live[name] = t


@reader("AWS::S3::Bucket")
def _buckets(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    s3 = clients("s3")
    for name in ids:
        info: dict[str, Any] = {}
        for op, key in (
            ("get_bucket_versioning", "Versioning"),
            ("get_bucket_encryption", "Encryption"),
            ("get_public_access_block", "PublicAccessBlock"),
            ("get_bucket_ownership_controls", "OwnershipControls"),
        ):
            try:
                info[key] = _clean(getattr(s3, op)(Bucket=name))
            except Exception:  # noqa: BLE001 - absent configuration raises
                info[key] = None
        with contextlib.suppress(Exception):  # a bucket without a policy raises
            info["Policy"] = s3.get_bucket_policy(Bucket=name).get("Policy")
        inv.live[name] = info


@reader("AWS::EFS::FileSystem")
def _filesystems(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    efs = clients("efs")
    for fid in ids:
        for fs in efs.describe_file_systems(FileSystemId=fid).get("FileSystems") or []:
            inv.live[fid] = fs


@reader("AWS::SecretsManager::Secret")
def _secrets(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sm = clients("secretsmanager")
    for arn in ids:
        d = _clean(sm.describe_secret(SecretId=arn))  # metadata only; never the value
        inv.live[arn] = d


@reader("AWS::KMS::Key")
def _keys(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    kms = clients("kms")
    for kid in ids:
        meta = kms.describe_key(KeyId=kid)["KeyMetadata"]
        meta["Policy"] = kms.get_key_policy(KeyId=kid, PolicyName="default").get("Policy")
        with contextlib.suppress(Exception):
            rotation = kms.get_key_rotation_status(KeyId=kid)
            meta["KeyRotationEnabled"] = rotation.get("KeyRotationEnabled")
        inv.live[kid] = meta


@reader("AWS::ECR::Repository")
def _repos(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ecr = clients("ecr")
    for repo in paginate(ecr, "describe_repositories", "repositories", repositoryNames=ids):
        inv.live[repo["repositoryName"]] = repo


# -- IAM, DNS, discovery -----------------------------------------------------------------------
@reader("AWS::IAM::Role")
def _roles(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    iam = clients("iam")
    for name in ids:
        role = iam.get_role(RoleName=name)["Role"]
        role["AttachedPolicies"] = paginate(
            iam, "list_attached_role_policies", "AttachedPolicies", RoleName=name
        )
        role["InlinePolicyNames"] = paginate(
            iam, "list_role_policies", "PolicyNames", RoleName=name
        )
        inv.live[name] = role


@reader("AWS::Route53::HostedZone")
def _zones(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    r53 = clients("route53")
    for zid in ids:
        z = r53.get_hosted_zone(Id=zid)
        info = {
            "HostedZone": z["HostedZone"],
            "NameServers": (z.get("DelegationSet") or {}).get("NameServers", []),
        }
        info["RecordSets"] = paginate(
            r53, "list_resource_record_sets", "ResourceRecordSets", HostedZoneId=zid
        )
        inv.live[zid] = info


@reader("AWS::ServiceDiscovery::Service")
def _sd_services(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sd = clients("servicediscovery")
    for sid in ids:
        inv.live[sid] = sd.get_service(Id=sid)["Service"]


@reader("AWS::ServiceDiscovery::PrivateDnsNamespace")
def _namespaces(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sd = clients("servicediscovery")
    for nid in ids:
        inv.live[nid] = sd.get_namespace(Id=nid)["Namespace"]


@reader("AWS::ApplicationAutoScaling::ScalableTarget")
def _scalable_targets(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    aas = clients("application-autoscaling")
    for t in paginate(aas, "describe_scalable_targets", "ScalableTargets", ServiceNamespace="ecs"):
        key = f"{t['ResourceId']}|{t['ScalableDimension']}|{t['ServiceNamespace']}"
        if t.get("ScalableTargetARN"):
            # CloudFormation propagates stack tags onto scalable targets.
            tags = aas.list_tags_for_resource(ResourceARN=t["ScalableTargetARN"]).get("Tags", {})
            t["Tags"] = tags
            inv.live[t["ScalableTargetARN"]] = t
        inv.live[key] = t


@reader("AWS::SQS::Queue")
def _queues(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sqs = clients("sqs")
    for url in ids:
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])
        inv.live[url] = attrs.get("Attributes", {})


@reader("AWS::ApplicationAutoScaling::ScalingPolicy")
def _scaling_policies(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    aas = clients("application-autoscaling")
    for p in paginate(aas, "describe_scaling_policies", "ScalingPolicies", ServiceNamespace="ecs"):
        inv.live[p["PolicyARN"]] = p


@reader("AWS::CloudWatch::Alarm")
def _alarms(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    cw = clients("cloudwatch")
    for chunk in _chunks(ids, 100):
        for a in cw.describe_alarms(AlarmNames=chunk).get("MetricAlarms") or []:
            inv.live[a["AlarmName"]] = a


@reader("AWS::Lambda::Function")
def _functions(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    """Tags and resource-policy statement ids only. GetFunction and GetFunctionConfiguration
    return environment variables and are forbidden (sources/aws.py)."""
    lam = clients("lambda")
    for name in ids:
        arn = f"arn:aws:lambda:{inv.region}:{inv.account}:function:{name}"
        entry: dict[str, Any] = {"Tags": lam.list_tags(Resource=arn).get("Tags", {})}
        try:
            policy = json.loads(lam.get_policy(FunctionName=name).get("Policy") or "{}")
            entry["PolicySids"] = [st.get("Sid") for st in policy.get("Statement") or []]
        except Exception as exc:  # noqa: BLE001 - a function without a policy is normal
            if "ResourceNotFound" not in f"{type(exc).__name__} {exc}":
                raise
            entry["PolicySids"] = []
        inv.live[name] = entry


@reader("AWS::Events::Rule")
def _event_rules(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ev = clients("events")
    for name in ids:
        rule = _clean(ev.describe_rule(Name=name))
        rule["Targets"] = paginate(ev, "list_targets_by_rule", "Targets", Rule=name)
        rule["Tags"] = ev.list_tags_for_resource(ResourceARN=rule["Arn"]).get("Tags", [])
        inv.live[name] = rule


@reader("AWS::StepFunctions::StateMachine")
def _state_machines(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sfn = clients("stepfunctions")
    for arn in ids:
        sm = _clean(sfn.describe_state_machine(stateMachineArn=arn))
        sm["tags"] = sfn.list_tags_for_resource(resourceArn=arn).get("tags", [])
        inv.live[arn] = sm


@reader("AWS::SNS::Subscription")
def _subscriptions(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    sns = clients("sns")
    for arn in ids:
        if arn.startswith("arn:"):
            inv.live[arn] = sns.get_subscription_attributes(SubscriptionArn=arn)["Attributes"]


@reader("AWS::Logs::LogGroup")
def _log_groups(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    logs = clients("logs")
    for name in ids:
        for g in paginate(logs, "describe_log_groups", "logGroups", logGroupNamePrefix=name):
            if g["logGroupName"] == name:
                inv.live[name] = g


@reader("AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress")
def _sg_rules(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    """Standalone rules. Only physical IDs that are already rule IDs (sgr-) can be matched
    exactly; anything else stays unreadable and the mapper blocks the rule."""
    ec2 = clients("ec2")
    rule_ids = [i for i in ids if i.startswith("sgr-")]
    for chunk in _chunks(rule_ids, 100):
        for r in (
            ec2.describe_security_group_rules(SecurityGroupRuleIds=chunk).get("SecurityGroupRules")
            or []
        ):
            inv.live[r["SecurityGroupRuleId"]] = r


@reader("AWS::EC2::FlowLog")
def _flow_logs(clients: Clients, inv: Inventory, ids: list[str]) -> None:
    ec2 = clients("ec2")
    for fl in paginate(ec2, "describe_flow_logs", "FlowLogs", FlowLogIds=ids):
        inv.live[fl["FlowLogId"]] = fl


def _elbv2_tags(clients: Clients, inv: Inventory, arns: list[str]) -> None:
    """Live tags for ELBv2 resources (CloudFormation propagates stack tags onto them)."""
    elb = clients("elbv2")
    for chunk in _chunks(arns, 20):
        for d in elb.describe_tags(ResourceArns=chunk).get("TagDescriptions") or []:
            entry = inv.live.setdefault(d["ResourceArn"], {})
            entry["Tags"] = d.get("Tags", [])


_LB_TYPES = (
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::ElasticLoadBalancingV2::TargetGroup",
    "AWS::ElasticLoadBalancingV2::Listener",
    "AWS::ElasticLoadBalancingV2::ListenerRule",
)
_base_read_live = read_live


def read_live(clients: Clients, inv: Inventory) -> None:  # type: ignore[no-redef]
    _base_read_live(clients, inv)
    arns = sorted(
        {
            r.physical_id
            for st in inv.stacks.values()
            for r in st.resources
            if r.type in _LB_TYPES and r.physical_id and r.physical_id.startswith("arn:")
        }
    )
    if arns:
        try:
            _elbv2_tags(clients, inv, arns)
        except Exception as exc:  # noqa: BLE001
            inv.unavailable.append({"type": "elbv2 tags", "reason": f"live read failed: {exc}"})
