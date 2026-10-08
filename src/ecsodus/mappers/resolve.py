"""Resolve CloudFormation intrinsic functions to concrete values.

Generated Terraform uses *literal* values (physical IDs, ARNs, parameter values) rather than
Terraform references. Literals match live state exactly, which is what an import-only first plan
needs (PLAN §2.4); references can be introduced later by the operator.

Anything that cannot be resolved exactly raises :class:`Unresolvable`, and the caller marks the
resource ``blocked``: ecsodus never guesses.
"""

from __future__ import annotations

import re
from typing import Any

from ecsodus import cfn
from ecsodus.model import Inventory, Stack

PARTITION = "aws"
URL_SUFFIX = "amazonaws.com"


class Unresolvable(Exception):
    """A value depends on something ecsodus cannot determine exactly."""


class _NoValue:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "AWS::NoValue"


NO_VALUE = _NoValue()

# GetAtt attributes that can be derived exactly from a physical ID (plus account/region).
_ARN_TEMPLATES: dict[tuple[str, str], str] = {
    ("AWS::IAM::Role", "Arn"): "arn:{p}:iam::{a}:role/{id}",
    ("AWS::IAM::ManagedPolicy", "PolicyArn"): "{id}",
    ("AWS::Logs::LogGroup", "Arn"): "arn:{p}:logs:{r}:{a}:log-group:{id}:*",
    ("AWS::ECS::Cluster", "Arn"): "arn:{p}:ecs:{r}:{a}:cluster/{id}",
    ("AWS::SNS::Topic", "TopicArn"): "{id}",
    ("AWS::SNS::Topic", "TopicName"): "{last_colon}",
    ("AWS::SQS::Queue", "Arn"): "arn:{p}:sqs:{r}:{a}:{last_slash}",
    ("AWS::SQS::Queue", "QueueName"): "{last_slash}",
    ("AWS::SQS::Queue", "QueueUrl"): "{id}",
    ("AWS::S3::Bucket", "Arn"): "arn:{p}:s3:::{id}",
    ("AWS::S3::Bucket", "DomainName"): "{id}.s3.amazonaws.com",
    ("AWS::S3::Bucket", "RegionalDomainName"): "{id}.s3.{r}.amazonaws.com",
    ("AWS::DynamoDB::Table", "Arn"): "arn:{p}:dynamodb:{r}:{a}:table/{id}",
    ("AWS::ECR::Repository", "Arn"): "arn:{p}:ecr:{r}:{a}:repository/{id}",
    ("AWS::KMS::Key", "Arn"): "arn:{p}:kms:{r}:{a}:key/{id}",
    ("AWS::KMS::Key", "KeyId"): "{id}",
    ("AWS::ElasticLoadBalancingV2::TargetGroup", "TargetGroupArn"): "{id}",
    ("AWS::ElasticLoadBalancingV2::LoadBalancer", "LoadBalancerArn"): "{id}",
    ("AWS::ElasticLoadBalancingV2::Listener", "ListenerArn"): "{id}",
    ("AWS::SecretsManager::Secret", "Id"): "{id}",
    ("AWS::EC2::SecurityGroup", "GroupId"): "{id}",
    ("AWS::EC2::VPC", "VpcId"): "{id}",
    ("AWS::EFS::FileSystem", "FileSystemId"): "{id}",
    ("AWS::EFS::AccessPoint", "AccessPointId"): "{id}",
    ("AWS::EFS::AccessPoint", "Arn"): "arn:{p}:elasticfilesystem:{r}:{a}:access-point/{id}",
    ("AWS::StepFunctions::StateMachine", "Arn"): "{id}",
    ("AWS::StepFunctions::StateMachine", "Name"): "{last_colon}",
    ("AWS::Route53::HostedZone", "Id"): "{id}",
    ("AWS::EC2::EIP", "PublicIp"): "{id}",
    ("AWS::ServiceDiscovery::PrivateDnsNamespace", "Id"): "{id}",
    (
        "AWS::ServiceDiscovery::PrivateDnsNamespace",
        "Arn",
    ): "arn:{p}:servicediscovery:{r}:{a}:namespace/{id}",
    ("AWS::ServiceDiscovery::Service", "Id"): "{id}",
    ("AWS::ServiceDiscovery::Service", "Arn"): "arn:{p}:servicediscovery:{r}:{a}:service/{id}",
    ("AWS::ECS::Service", "Name"): "{last_slash}",
    ("AWS::Lambda::Function", "Arn"): "arn:{p}:lambda:{r}:{a}:function:{id}",
    # Rules on the default event bus only (the physical id is the rule name); rules on a custom
    # bus are refused by the mapper.
    ("AWS::Events::Rule", "Arn"): "arn:{p}:events:{r}:{a}:rule/{id}",
}


# GetAtt attribute names that the describe APIs spell differently.
_LIVE_ALIASES: dict[tuple[str, str], str] = {
    ("AWS::ElasticLoadBalancingV2::LoadBalancer", "CanonicalHostedZoneID"): "CanonicalHostedZoneId",
    ("AWS::ElasticLoadBalancingV2::LoadBalancer", "DNSName"): "DNSName",
    ("AWS::ElasticLoadBalancingV2::LoadBalancer", "LoadBalancerName"): "LoadBalancerName",
    ("AWS::ElasticLoadBalancingV2::TargetGroup", "TargetGroupName"): "TargetGroupName",
}


def _derive(rtype: str, attr: str, physical_id: str) -> str | None:
    """Attributes that are exact functions of an ARN (the *FullName forms CloudWatch uses)."""
    if rtype == "AWS::ElasticLoadBalancingV2::LoadBalancer" and attr == "LoadBalancerFullName":
        _, _, tail = physical_id.partition(":loadbalancer/")
        return tail or None
    if rtype == "AWS::ElasticLoadBalancingV2::TargetGroup" and attr == "TargetGroupFullName":
        _, sep, tail = physical_id.partition(":targetgroup/")
        return f"targetgroup/{tail}" if sep else None
    return None


class Resolver:
    """Resolves intrinsics within one stack of an inventory."""

    def __init__(self, inventory: Inventory, stack: Stack, template: dict[str, Any] | None = None):
        self.inv = inventory
        self.stack = stack
        self.template = template if template is not None else cfn.load(stack.template_body)
        self._conditions: dict[str, bool] = {}
        self._param_types = {
            k: (v or {}).get("Type", "String")
            for k, v in (self.template.get("Parameters") or {}).items()
        }

    # -- public ----------------------------------------------------------------------------
    def resolve(self, value: Any) -> Any:
        """Resolve ``value`` fully; drops ``AWS::NoValue`` entries from lists and maps."""
        out = self._resolve(value)
        return None if out is NO_VALUE else out

    def condition(self, name: str) -> bool:
        if name not in self._conditions:
            expr = (self.template.get("Conditions") or {}).get(name)
            if expr is None:
                raise Unresolvable(f"unknown condition {name}")
            self._conditions[name] = bool(self._eval_condition(expr))
        return self._conditions[name]

    def resource_exists(self, logical_id: str) -> bool:
        body = (self.template.get("Resources") or {}).get(logical_id) or {}
        cond = body.get("Condition")
        return True if cond is None else self.condition(cond)

    # -- internals -------------------------------------------------------------------------
    def _resolve(self, v: Any) -> Any:
        if isinstance(v, list):
            items = [self._resolve(x) for x in v]
            return [x for x in items if x is not NO_VALUE]
        if not isinstance(v, dict):
            return v
        if len(v) == 1:
            ((k, arg),) = v.items()
            fn = _FUNCS.get(k)
            if fn is not None:
                return fn(self, arg)
        out = {}
        for k, x in v.items():
            r = self._resolve(x)
            if r is not NO_VALUE:
                out[k] = r
        return out

    def _ref(self, name: str) -> Any:
        pseudo = {
            "AWS::Region": self.inv.region,
            "AWS::AccountId": self.inv.account,
            "AWS::Partition": PARTITION,
            "AWS::URLSuffix": URL_SUFFIX,
            "AWS::StackName": self.stack.name,
            "AWS::StackId": self.stack.stack_id,
        }
        if name == "AWS::NoValue":
            return NO_VALUE
        if name in pseudo:
            if not pseudo[name]:
                raise Unresolvable(f"pseudo parameter {name} unknown")
            return pseudo[name]
        if name in self._param_types:
            if name not in self.stack.parameters:
                raise Unresolvable(f"parameter {name} has no deployed value")
            val = self.stack.parameters[name]
            ptype = self._param_types[name]
            if ptype == "CommaDelimitedList" or ptype.startswith("List<"):
                return [x.strip() for x in val.split(",")] if val else []
            return val
        res = self.stack.resource(name)
        if res is None or not res.physical_id:
            raise Unresolvable(f"Ref {name}: resource has no physical id")
        return res.physical_id

    def _getatt(self, arg: Any) -> Any:
        if isinstance(arg, str):
            arg = arg.split(".", 1)
        if not isinstance(arg, list) or len(arg) != 2:
            raise Unresolvable(f"bad GetAtt {arg!r}")
        lid, attr = arg[0], self._resolve(arg[1])
        res = self.stack.resource(lid)
        if res is None or not res.physical_id:
            raise Unresolvable(f"GetAtt {lid}.{attr}: resource has no physical id")
        if res.type == "AWS::CloudFormation::Stack" and attr.startswith("Outputs."):
            child = next(
                (s for s in self.inv.children(self.stack.name) if s.parent_logical_id == lid),
                None,
            )
            key = attr.split(".", 1)[1]
            if child is None or key not in child.outputs:
                raise Unresolvable(f"GetAtt {lid}.{attr}: nested output unknown")
            return child.outputs[key]
        live = self.inv.live.get(res.physical_id) or {}
        if attr in live:
            return live[attr]
        alias = _LIVE_ALIASES.get((res.type, attr))
        if alias and alias in live:
            return live[alias]
        derived = _derive(res.type, attr, res.physical_id)
        if derived is not None:
            return derived
        tmpl = _ARN_TEMPLATES.get((res.type, attr))
        if tmpl is None:
            raise Unresolvable(f"GetAtt {lid}.{attr} ({res.type}) not derivable")
        pid = res.physical_id
        return tmpl.format(
            p=PARTITION,
            a=self.inv.account,
            r=self.inv.region,
            id=pid,
            last_slash=pid.rsplit("/", 1)[-1],
            last_colon=pid.rsplit(":", 1)[-1],
        )

    def _sub(self, arg: Any) -> str:
        if isinstance(arg, list):
            text, variables = arg[0], {k: self._resolve(x) for k, x in (arg[1] or {}).items()}
        else:
            text, variables = arg, {}

        def repl(m: re.Match[str]) -> str:
            # CloudFormation tolerates whitespace inside ${ } (Copilot writes `${ sentinel.Arn}`).
            name = m.group(1).strip()
            if name.startswith("!"):
                return "${" + name[1:] + "}"
            if name in variables:
                return _scalar(variables[name])
            if "." in name:
                lid, attr = name.split(".", 1)
                return _scalar(self._getatt([lid, attr]))
            return _scalar(self._ref(name))

        return re.sub(r"\$\{([^}]+)\}", repl, text)

    def _eval_condition(self, expr: Any) -> Any:
        if isinstance(expr, dict) and len(expr) == 1:
            ((k, arg),) = expr.items()
            if k == "Fn::Equals":
                a, b = (self._resolve(x) for x in arg)
                return _scalar(a) == _scalar(b)
            if k == "Fn::Not":
                return not self._eval_condition(arg[0])
            if k == "Fn::And":
                return all(self._eval_condition(x) for x in arg)
            if k == "Fn::Or":
                return any(self._eval_condition(x) for x in arg)
            if k == "Condition":
                return self.condition(arg)
        return self._resolve(expr)


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        raise Unresolvable(f"non-scalar value {v!r} in string context")
    return str(v)


def _join(r: Resolver, arg: Any) -> str:
    sep, items = arg[0], r._resolve(arg[1])
    if not isinstance(items, list):
        raise Unresolvable("Fn::Join on a non-list")
    return str(sep).join(_scalar(x) for x in items)


def _select(r: Resolver, arg: Any) -> Any:
    idx, items = int(r._resolve(arg[0])), r._resolve(arg[1])
    if not isinstance(items, list) or idx >= len(items):
        raise Unresolvable("Fn::Select out of range")
    return items[idx]


def _split(r: Resolver, arg: Any) -> list[str]:
    return str(r._resolve(arg[1])).split(str(arg[0]))


def _if(r: Resolver, arg: Any) -> Any:
    name, yes, no = arg
    return r._resolve(yes if r.condition(name) else no)


def _find_in_map(r: Resolver, arg: Any) -> Any:
    m, k1, k2 = (r._resolve(x) for x in arg)
    try:
        return r.template["Mappings"][m][k1][k2]
    except (KeyError, TypeError) as exc:
        raise Unresolvable(f"FindInMap {m}/{k1}/{k2}") from exc


def _import_value(r: Resolver, arg: Any) -> Any:
    name = _scalar(r._resolve(arg))
    for s in r.inv.stacks.values():
        if name in s.exports:
            return s.exports[name]
    external = r.inv.external_exports.get(name)
    if external is not None:
        return external["value"]
    raise Unresolvable(f"ImportValue {name}: export not found in inventory")


def _unresolvable(name: str) -> Any:
    def f(r: Resolver, arg: Any) -> Any:
        raise Unresolvable(f"{name} is not resolved statically")

    return f


_FUNCS = {
    "Ref": lambda r, a: r._ref(a),
    "Fn::GetAtt": lambda r, a: r._getatt(a),
    "Fn::Sub": lambda r, a: r._sub(a),
    "Fn::Join": _join,
    "Fn::Select": _select,
    "Fn::Split": _split,
    "Fn::If": _if,
    "Fn::FindInMap": _find_in_map,
    "Fn::ImportValue": _import_value,
    "Fn::Base64": lambda r, a: _unresolvable("Fn::Base64")(r, a),
    "Fn::GetAZs": _unresolvable("Fn::GetAZs"),
    "Fn::Cidr": _unresolvable("Fn::Cidr"),
    "Fn::Transform": _unresolvable("Fn::Transform"),
    "Condition": lambda r, a: r.condition(a),
}
