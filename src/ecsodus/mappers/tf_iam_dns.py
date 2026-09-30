"""Terraform mappers: tf_iam_dns family (IAM, Route 53, ACM; see tfmap.py).

Notes specific to this family:

* Provider 6.x deprecates ``aws_iam_role.inline_policy`` and ``managed_policy_arns`` in favour of
  ``aws_iam_role_policy`` / ``aws_iam_role_policy_attachment``. One TfSpec per CloudFormation
  resource means those separate resources cannot be emitted here, so:

  - inline ``Policies`` become ``inline_policy`` blocks **only** when the live role carries exactly
    the template's set of inline policies (``inline_policy`` is exclusive: an extra inline policy
    added by another stack's ``AWS::IAM::Policy`` would be deleted by the first apply). Otherwise
    each is listed in notes with its ``aws_iam_role_policy`` import id, fidelity "partial";
  - ``ManagedPolicyArns`` are listed in notes with their ``aws_iam_role_policy_attachment``
    import ids, fidelity "partial".
* Route 53 record import ids are ``<zone id>_<record name>_<type>[_<set identifier>]`` with the
  record name lower-cased and without the trailing dot (the provider's canonical form).
"""

from __future__ import annotations

import json
from typing import Any

from ecsodus.emit.hcl import Block
from ecsodus.mappers.tfmap import Ctx, TfSpec, Unresolvable, mapper

# -- helpers --------------------------------------------------------------------------------


def _only(ctx: Ctx, known: set[str]) -> None:
    unknown = sorted(set(ctx.props) - known)
    if unknown:
        raise Unresolvable(f"{ctx.resource.type}: unhandled properties {', '.join(unknown)}")


def _json_doc(doc: Any) -> str:
    """A policy document as a JSON string (the provider compares policies semantically)."""
    if isinstance(doc, str):
        return doc
    return json.dumps(doc, ensure_ascii=False)


def _add_tags(ctx: Ctx, body: list, key: str = "Tags") -> None:
    tags = ctx.tags(key)
    if tags:
        body.append(("tags", tags))


def _role_name(ref: str) -> str:
    """A role name from a name or a role ARN (CloudFormation accepts names)."""
    if ref.startswith("arn:"):
        return ref.rsplit("/", 1)[-1]
    return ref


# -- IAM --------------------------------------------------------------------------------------


@mapper("AWS::IAM::Role")
def iam_role(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "AssumeRolePolicyDocument", "Policies", "ManagedPolicyArns", "Path", "RoleName",
        "PermissionsBoundary", "Description", "MaxSessionDuration", "Tags",
    })  # fmt: skip
    name = ctx.pid
    spec = TfSpec("aws_iam_role", name, [("name", name)])
    body = spec.body
    body.append(("assume_role_policy", _json_doc(ctx.r("AssumeRolePolicyDocument"))))
    path = ctx.r("Path", None)
    if path:
        body.append(("path", path))
    desc = ctx.r("Description", None)
    if desc:
        body.append(("description", desc))
    duration = ctx.r("MaxSessionDuration", None)
    if duration is not None:
        body.append(("max_session_duration", int(duration)))
    boundary = ctx.r("PermissionsBoundary", None)
    if boundary:
        body.append(("permissions_boundary", boundary))

    policies = [p for p in (ctx.r("Policies", []) or []) if p]
    if policies:
        names = [p["PolicyName"] for p in policies]
        # ListRolePolicies' PolicyNames, recorded by sources/live.py as "InlinePolicyNames".
        live_names = ctx.live.get("InlinePolicyNames")
        ids = "; ".join(f'"{name}:{n}"' for n in names)
        if live_names is not None and sorted(live_names) == sorted(names):
            for p in policies:
                inline = [("name", p["PolicyName"]), ("policy", _json_doc(p["PolicyDocument"]))]
                body.append(("inline_policy", Block(inline)))
            spec.notes.append(
                "inline policies are emitted as inline_policy blocks (deprecated in provider 6.x "
                "but exact: the live role has exactly these inline policies). To move to "
                f"aws_iam_role_policy later, import ids: {ids}"
            )
        else:
            why = (
                "live inline policy names were not read"
                if live_names is None
                else f"the live role also has other inline policies ({sorted(live_names)})"
            )
            spec.fidelity = "partial"
            spec.notes.append(
                f"inline policies are not emitted ({why}; inline_policy is exclusive and would "
                "remove the others). Import each as aws_iam_role_policy, import ids: " + ids
            )
    managed = ctx.r("ManagedPolicyArns", []) or []
    if managed:
        spec.fidelity = "partial"
        ids = "; ".join(f'"{name}/{arn}"' for arn in managed)
        spec.notes.append(
            "managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are "
            "separate aws_iam_role_policy_attachment resources, not generated in v0.1; import "
            "ids: " + ids
        )
    _add_tags(ctx, body)
    return spec


@mapper("AWS::IAM::Policy")
def iam_role_policy(ctx: Ctx) -> TfSpec:
    _only(ctx, {"PolicyName", "PolicyDocument", "Roles", "Users", "Groups"})
    if ctx.r("Users", []) or ctx.r("Groups", []):
        raise Unresolvable("inline policy attached to users or groups is not supported")
    roles = ctx.r("Roles", []) or []
    if len(roles) != 1:
        raise Unresolvable(
            f"inline policy attached to {len(roles)} roles; Terraform needs one "
            "aws_iam_role_policy per role"
        )
    role = _role_name(str(roles[0]))
    name = ctx.r("PolicyName")
    body: list = [
        ("name", name),
        ("role", role),
        ("policy", _json_doc(ctx.r("PolicyDocument"))),
    ]
    return TfSpec("aws_iam_role_policy", f"{role}:{name}", body)


@mapper("AWS::IAM::ManagedPolicy")
def iam_managed_policy(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "ManagedPolicyName", "Description", "Path", "PolicyDocument", "Roles", "Users", "Groups",
    })  # fmt: skip
    arn = ctx.pid
    if ":policy/" not in arn:
        raise Unresolvable(f"managed policy physical id {arn!r} is not a policy ARN")
    # arn:aws:iam::<account>:policy<path><name>
    path_and_name = arn.split(":policy", 1)[1]
    path, name = path_and_name.rsplit("/", 1)
    path = path + "/"
    spec = TfSpec("aws_iam_policy", arn, [("name", name)])
    body = spec.body
    if path != "/":
        body.append(("path", path))
    desc = ctx.r("Description", None)
    if desc:
        body.append(("description", desc))
    body.append(("policy", _json_doc(ctx.r("PolicyDocument"))))
    attach = []
    for role in ctx.r("Roles", []) or []:
        attach.append(f'aws_iam_role_policy_attachment (import id "{_role_name(str(role))}/{arn}")')
    for kind in ("Users", "Groups"):
        for who in ctx.r(kind, []) or []:
            attach.append(f"{kind[:-1].lower()} {who}")
    if attach:
        spec.fidelity = "partial"
        spec.notes.append(
            "attachments are separate resources, not generated in v0.1: " + "; ".join(attach)
        )
    return spec


@mapper("AWS::IAM::InstanceProfile")
def iam_instance_profile(ctx: Ctx) -> TfSpec:
    _only(ctx, {"InstanceProfileName", "Path", "Roles"})
    roles = ctx.r("Roles", []) or []
    if len(roles) != 1:
        raise Unresolvable(f"instance profile with {len(roles)} roles")
    name = ctx.pid
    body: list = [("name", name)]
    path = ctx.r("Path", None)
    if path:
        body.append(("path", path))
    body.append(("role", _role_name(str(roles[0]))))
    return TfSpec("aws_iam_instance_profile", name, body)


# -- Route 53 ---------------------------------------------------------------------------------


@mapper("AWS::Route53::HostedZone")
def route53_zone(ctx: Ctx) -> TfSpec:
    _only(ctx, {"Name", "HostedZoneConfig", "VPCs", "HostedZoneTags", "QueryLoggingConfig"})
    zone_id = ctx.pid
    spec = TfSpec("aws_route53_zone", zone_id, [], stateful=True)
    body = spec.body
    body.append(("name", str(ctx.r("Name")).rstrip(".")))
    # The provider defaults comment to "Managed by Terraform": always emit the live comment.
    comment = (ctx.r("HostedZoneConfig", None) or {}).get("Comment", "")
    body.append(("comment", comment))
    for vpc in ctx.r("VPCs", []) or []:
        body.append(("vpc", Block([("vpc_id", vpc["VPCId"]), ("vpc_region", vpc["VPCRegion"])])))
    _add_tags(ctx, body, "HostedZoneTags")
    if ctx.has("QueryLoggingConfig"):
        spec.fidelity = "partial"
        spec.notes.append(
            "query logging is a separate aws_route53_query_log resource, not generated in v0.1"
        )
    spec.notes.append("stateful: replacing the zone changes its name servers and breaks delegation")
    return spec


_RR_TYPES = {
    "A", "AAAA", "CAA", "CNAME", "DS", "HTTPS", "MX", "NAPTR", "NS", "PTR", "SOA", "SPF", "SRV",
    "SSHFP", "SVCB", "TLSA", "TXT",
}  # fmt: skip
_RECORD_KEYS = {
    "Name", "Type", "TTL", "ResourceRecords", "AliasTarget", "SetIdentifier", "Weight", "Region",
    "Failover", "MultiValueAnswer", "HealthCheckId", "Comment",
}  # fmt: skip


def _record(ctx: Ctx, rec: dict[str, Any], zone_id: str) -> TfSpec:
    unknown = sorted(set(rec) - _RECORD_KEYS - {"HostedZoneId", "HostedZoneName"})
    if unknown:
        raise Unresolvable(f"record set: unhandled properties {', '.join(unknown)}")
    name = str(rec["Name"]).rstrip(".").lower()
    rtype = rec["Type"]
    if any(part in _RR_TYPES for part in name.split("_")):
        raise Unresolvable(f"record name {name!r} would make an ambiguous import id")
    set_id = rec.get("SetIdentifier")
    import_id = f"{zone_id}_{name}_{rtype}" + (f"_{set_id}" if set_id else "")
    spec = TfSpec("aws_route53_record", import_id, [])
    body = spec.body
    body += [("zone_id", zone_id), ("name", name), ("type", rtype)]
    alias = rec.get("AliasTarget")
    if alias:
        if rec.get("TTL") is not None or rec.get("ResourceRecords"):
            raise Unresolvable("record has both an alias target and TTL/records")
        body.append(("alias", Block([
            ("name", str(alias["DNSName"])),
            ("zone_id", str(alias["HostedZoneId"])),
            ("evaluate_target_health", bool(alias.get("EvaluateTargetHealth", False))),
        ])))  # fmt: skip
    else:
        if rec.get("TTL") is None or not rec.get("ResourceRecords"):
            raise Unresolvable("non-alias record without TTL and records")
        body.append(("ttl", int(rec["TTL"])))
        records = rec["ResourceRecords"]
        if not isinstance(records, list):
            raise Unresolvable("ResourceRecords is not a list")
        body.append(("records", [str(r) for r in records]))
    if set_id:
        body.append(("set_identifier", set_id))
    policies = [k for k in ("Weight", "Region", "Failover", "MultiValueAnswer") if k in rec]
    if len(policies) > 1:
        raise Unresolvable(f"record has several routing policies: {policies}")
    if policies and not set_id:
        raise Unresolvable("routing policy without SetIdentifier")
    if "Weight" in rec:
        body.append(("weighted_routing_policy", Block([("weight", int(rec["Weight"]))])))
    elif "Region" in rec:
        body.append(("latency_routing_policy", Block([("region", rec["Region"])])))
    elif "Failover" in rec:
        body.append(("failover_routing_policy", Block([("type", rec["Failover"])])))
    elif rec.get("MultiValueAnswer"):
        body.append(("multivalue_answer_routing_policy", True))
    if rec.get("HealthCheckId"):
        body.append(("health_check_id", rec["HealthCheckId"]))
    return spec


def _zone_id(ctx: Ctx, holder: dict[str, Any]) -> str:
    zone = holder.get("HostedZoneId")
    if not zone:
        raise Unresolvable("record set addressed by HostedZoneName; the zone id is not known")
    return str(zone).rsplit("/", 1)[-1]  # accept "/hostedzone/Z..." too


@mapper("AWS::Route53::RecordSet")
def route53_record_set(ctx: Ctx) -> TfSpec:
    rec = ctx.resolver.resolve(ctx.props)
    return _record(ctx, rec, _zone_id(ctx, rec))


@mapper("AWS::Route53::RecordSetGroup")
def route53_record_set_group(ctx: Ctx) -> TfSpec:
    _only(ctx, {"HostedZoneId", "HostedZoneName", "Comment", "RecordSets"})
    raw = ctx.props.get("RecordSets") or []
    if len(raw) != 1:
        raise Unresolvable(
            f"RecordSetGroup with {len(raw)} records; one TfSpec per CloudFormation resource "
            "cannot hold several aws_route53_record resources"
        )
    rec = ctx.resolver.resolve(raw[0])
    holder = rec if rec.get("HostedZoneId") else {"HostedZoneId": ctx.r("HostedZoneId", None)}
    return _record(ctx, rec, _zone_id(ctx, holder))


# -- ACM --------------------------------------------------------------------------------------


@mapper("AWS::CertificateManager::Certificate")
def acm_certificate(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "DomainName", "SubjectAlternativeNames", "ValidationMethod", "DomainValidationOptions",
        "CertificateAuthorityArn", "CertificateTransparencyLoggingPreference", "KeyAlgorithm",
        "Tags",
    })  # fmt: skip
    arn = ctx.pid
    spec = TfSpec("aws_acm_certificate", arn, [("domain_name", ctx.r("DomainName"))])
    body = spec.body
    sans = ctx.r("SubjectAlternativeNames", None)
    if sans:
        body.append(("subject_alternative_names", sorted(sans)))
    ca = ctx.r("CertificateAuthorityArn", None)
    if ca:
        body.append(("certificate_authority_arn", ca))
    else:
        method = ctx.r("ValidationMethod", None) or ctx.live.get("ValidationMethod")
        if not method:
            raise Unresolvable("ValidationMethod: not in the template and not read live")
        body.append(("validation_method", method))
    algo = ctx.r("KeyAlgorithm", None)
    if algo:
        body.append(("key_algorithm", algo))
    pref = ctx.r("CertificateTransparencyLoggingPreference", None)
    if pref:
        opts = [("certificate_transparency_logging_preference", pref)]
        body.append(("options", Block(opts)))
    dns_zones = []
    for opt in ctx.r("DomainValidationOptions", []) or []:
        if opt.get("ValidationDomain"):
            vo = [
                ("domain_name", opt["DomainName"]),
                ("validation_domain", opt["ValidationDomain"]),
            ]
            body.append(("validation_option", Block(vo)))
        if opt.get("HostedZoneId"):
            dns_zones.append(f"{opt['DomainName']} in {opt['HostedZoneId']}")
    if dns_zones:
        spec.notes.append(
            "DNS validation records were written by CloudFormation outside any stack resource ("
            + "; ".join(dns_zones)
            + "); they are not modelled here"
        )
    _add_tags(ctx, body)
    return spec
