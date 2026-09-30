"""Build synthetic inventories from real Copilot-rendered templates (for offline tests).

Physical IDs are synthesised in the right *shape* for each resource type, so mappers and import
IDs can be exercised without AWS. Parameter values come from the template defaults, overridden by
``params``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ecsodus import cfn
from ecsodus.model import Inventory, Resource, Stack

FIXTURES = Path(__file__).parent / "fixtures" / "copilot"
ACCOUNT = "123456789012"
REGION = "us-west-2"


def fake_physical_id(stack: str, lid: str, rtype: str) -> str:
    low = lid.lower()
    arn = f"arn:aws:{{svc}}:{REGION}:{ACCOUNT}:{{res}}"
    shapes: dict[str, str] = {
        "AWS::EC2::VPC": f"vpc-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::Subnet": f"subnet-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::SecurityGroup": f"sg-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::InternetGateway": f"igw-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::RouteTable": f"rtb-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::NatGateway": f"nat-0{abs(hash(low)) % 10**12:012d}",
        "AWS::EC2::EIP": f"52.{abs(hash(low)) % 250}.1.1",
        "AWS::ECS::Cluster": f"{stack}-Cluster-{low[:8]}",
        "AWS::ECS::Service": arn.format(svc="ecs", res=f"service/{stack}-Cluster/{stack}-{low}"),
        "AWS::ECS::TaskDefinition": arn.format(svc="ecs", res=f"task-definition/{stack}:3"),
        "AWS::IAM::Role": f"{stack}-{lid}-ABC123",
        "AWS::IAM::ManagedPolicy": f"arn:aws:iam::{ACCOUNT}:policy/{stack}-{lid}",
        "AWS::Logs::LogGroup": f"/copilot/{stack}",
        "AWS::ElasticLoadBalancingV2::LoadBalancer": arn.format(
            svc="elasticloadbalancing", res=f"loadbalancer/app/{stack[:20]}/0123456789abcdef"
        ),
        "AWS::ElasticLoadBalancingV2::TargetGroup": arn.format(
            svc="elasticloadbalancing", res=f"targetgroup/{low[:20]}/0123456789abcdef"
        ),
        "AWS::ElasticLoadBalancingV2::Listener": arn.format(
            svc="elasticloadbalancing", res=f"listener/app/{stack[:20]}/0123456789abcdef/{low[:8]}"
        ),
        "AWS::ElasticLoadBalancingV2::ListenerRule": arn.format(
            svc="elasticloadbalancing",
            res=f"listener-rule/app/{stack[:20]}/0123456789abcdef/abcd/{low[:8]}",
        ),
        "AWS::S3::Bucket": f"{stack}-{low}"[:63].lower(),
        "AWS::SNS::Topic": arn.format(svc="sns", res=f"{stack}-{lid}"),
        "AWS::DynamoDB::Table": f"{stack}-{lid}",
        "AWS::RDS::DBCluster": f"{stack}-{low}"[:63].lower(),
        "AWS::SecretsManager::Secret": arn.format(svc="secretsmanager", res=f"secret:{lid}-AbCdEf"),
        "AWS::KMS::Key": "1234abcd-12ab-34cd-56ef-1234567890ab",
        "AWS::ECR::Repository": f"{stack}/{low}",
        "AWS::Route53::HostedZone": "Z0123456789ABCDEFGHIJ",
        "AWS::ServiceDiscovery::PrivateDnsNamespace": "ns-abcdefghijklmnop",
        "AWS::ServiceDiscovery::Service": "srv-abcdefghijklmnop",
        "AWS::EFS::FileSystem": "fs-0123456789abcdef0",
        "AWS::Lambda::Function": f"{stack}-{lid}-XYZ",
        "AWS::CloudFormation::Stack": arn.format(
            svc="cloudformation", res=f"stack/{stack}-{lid}-XYZ/uuid"
        ),
    }
    return shapes.get(rtype, f"{stack}-{lid}")


def inventory_from_template(
    path: str | Path,
    *,
    stack_name: str = "demo-test-api",
    kind: str = "workload",
    env: str | None = "test",
    workload: str | None = "api",
    workload_type: str | None = "Load Balanced Web Service",
    params: dict[str, str] | None = None,
    app: str = "demo",
) -> tuple[Inventory, Stack]:
    path = Path(path)
    text = path.read_text()
    tpl = cfn.load(text)
    parameters = {k: _synth_param(k, v) for k, v in (tpl.get("Parameters") or {}).items()}
    params_file = path.with_name(path.name.replace(".stack.yml", ".params.json"))
    if params_file != path and params_file.exists():
        import json

        parameters.update(json.loads(params_file.read_text()).get("Parameters", {}))
    parameters.update(params or {})
    resources = [
        Resource(lid, body["Type"], fake_physical_id(stack_name, lid, body["Type"]))
        for lid, body in tpl["Resources"].items()
    ]
    stack = Stack(
        name=stack_name,
        kind=kind,
        stack_id=f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{stack_name}/uuid",
        status="UPDATE_COMPLETE",
        template_body=text,
        parameters=parameters,
        env=env,
        workload=workload,
        workload_type=workload_type,
        resources=resources,
        last_updated="2026-09-01T00:00:00+00:00",
    )
    inv = Inventory(
        app=app,
        account=ACCOUNT,
        region=REGION,
        captured_at="2026-09-29T00:00:00+00:00",
        envs=[env] if env else [],
        stacks={stack_name: stack},
    )
    return inv, stack


_KNOWN = {"AppName": "my-app", "EnvName": "test", "WorkloadName": "fe"}


def _synth_param(name: str, spec: dict[str, Any]) -> str:
    """A plausible deployed value for a parameter with no fixture value."""
    if spec.get("Default") is not None:
        return str(spec["Default"])
    if name in _KNOWN:
        return _KNOWN[name]
    if spec.get("AllowedValues"):
        return str(spec["AllowedValues"][0])
    ptype = spec.get("Type", "String")
    if ptype == "Number":
        return "1"
    if ptype == "CommaDelimitedList" or ptype.startswith("List<"):
        return ""
    if "arn" in name.lower():
        return f"arn:aws:iam::{ACCOUNT}:role/{name}"
    return name.lower()


def attach(inv: Inventory, stack: Stack) -> Any:
    inv.stacks[stack.name] = stack
    return inv
