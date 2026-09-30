"""Out-of-band objects: things Copilot custom resources created outside CloudFormation.

They appear in no stack's resource list, so without this module they would get no fate at all
(council code review, finding 12). Certificates follow the hand-off of the stack whose custom
resource created them. Records inside an imported hosted zone that no ``AWS::Route53::RecordSet``
owns are imported alongside the zone.
"""

from __future__ import annotations

import re
from typing import Any

from ecsodus.emit.hcl import Block
from ecsodus.mappers import fates as F
from ecsodus.mappers.tfmap import TfSpec
from ecsodus.model import OutOfBand

SUPPORTED_RECORD_TYPES = {"A", "AAAA", "CNAME", "NS", "MX"}


def _unique(base: str, names: set[str]) -> str:
    name, n = base, 1
    while name in names:
        n += 1
        name = f"{base}_{n}"
    names.add(name)
    return name


def _snake(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def plan_certificate(obj: OutOfBand, stack: str, handoff: bool, names: set[str]) -> F.ResourcePlan:
    lid = f"out-of-band:{obj.id.rsplit('/', 1)[-1]}"
    rtype = "OutOfBand::ACM::Certificate"
    if obj.kind != "acm_certificate":
        return F.ResourcePlan(stack, lid, rtype, obj.id, F.BLOCKED, f"unknown kind {obj.kind}")
    if not handoff:
        return F.ResourcePlan(
            stack,
            lid,
            rtype,
            obj.id,
            F.RETAIN_UNDER_EXISTING_OWNER,
            f"created by {obj.created_by}; its stack is kept",
        )
    d = obj.details
    domain = d.get("DomainName")
    if not domain:
        return F.ResourcePlan(stack, lid, rtype, obj.id, F.BLOCKED, "certificate domain unknown")
    sans = [s for s in d.get("SubjectAlternativeNames") or [] if s != domain]
    body: list = [("domain_name", domain), ("validation_method", "DNS")]
    if sans:
        body.append(("subject_alternative_names", sans))
    spec = TfSpec(
        "aws_acm_certificate",
        obj.id,
        body,
        stateful=True,
        fidelity="partial",
        notes=[
            f"created out of band by Copilot custom resource {obj.created_by}; "
            "the custom resource is retained, so it never deletes this certificate"
        ],
    )
    address = "aws_acm_certificate." + _unique(f"oob_cert_{_snake(domain)}", names)
    return F.ResourcePlan(
        stack, lid, rtype, obj.id, F.IMPORT, "out-of-band certificate", address, spec
    )


def _record_name(raw: str) -> str:
    return raw.rstrip(".").replace("\\052", "*").lower()


def plan_zone_records(
    zone: F.ResourcePlan,
    live: dict[str, Any],
    owned: set[tuple[str, str, str]],
    names: set[str],
) -> list[F.ResourcePlan]:
    zone_id = (zone.physical_id or "").rsplit("/", 1)[-1]
    zone_name = _record_name((live.get("HostedZone") or {}).get("Name", ""))
    out: list[F.ResourcePlan] = []
    for rr in live.get("RecordSets") or []:
        name, rtype = _record_name(rr.get("Name", "")), rr.get("Type", "")
        if name == zone_name and rtype in ("SOA", "NS"):
            continue  # managed by the zone itself
        if (zone_id.lower(), name, rtype) in owned or (zone_name, name, rtype) in owned:
            continue  # a CloudFormation RecordSet in this zone owns it (mapped with its stack)
        lid = f"out-of-band:{name}/{rtype}"
        rtype_label = "OutOfBand::Route53::Record"
        set_id = rr.get("SetIdentifier")
        routing = [
            k
            for k in (
                "Weight",
                "Region",
                "Failover",
                "GeoLocation",
                "MultiValueAnswer",
                "CidrRoutingConfig",
                "GeoProximityLocation",
            )
            if k in rr
        ]
        if rtype not in SUPPORTED_RECORD_TYPES or routing or set_id:
            out.append(
                F.ResourcePlan(
                    zone.stack,
                    lid,
                    rtype_label,
                    None,
                    F.BLOCKED,
                    f"record {name} {rtype} with routing {routing or '-'} is "
                    "not supported for out-of-band import in v0.1",
                )
            )
            continue
        body: list = [("zone_id", zone_id), ("name", name), ("type", rtype)]
        alias = rr.get("AliasTarget")
        if alias:
            body.append(
                (
                    "alias",
                    Block(
                        [
                            ("name", str(alias.get("DNSName", "")).rstrip(".").lower()),
                            ("zone_id", alias.get("HostedZoneId")),
                            ("evaluate_target_health", bool(alias.get("EvaluateTargetHealth"))),
                        ]
                    ),
                )
            )
        else:
            if "TTL" not in rr:
                out.append(
                    F.ResourcePlan(
                        zone.stack,
                        lid,
                        rtype_label,
                        None,
                        F.BLOCKED,
                        f"record {name} {rtype} has no TTL",
                    )
                )
                continue
            body.append(("ttl", int(rr["TTL"])))
            body.append(("records", [v["Value"] for v in rr.get("ResourceRecords") or []]))
        import_id = f"{zone_id}_{name}_{rtype}"
        spec = TfSpec(
            "aws_route53_record",
            import_id,
            body,
            notes=["created out of band by a Copilot custom resource"],
        )
        address = "aws_route53_record." + _unique(f"oob_{_snake(name)}_{rtype.lower()}", names)
        out.append(
            F.ResourcePlan(
                zone.stack,
                lid,
                rtype_label,
                import_id,
                F.IMPORT,
                "out-of-band record",
                address,
                spec,
            )
        )
    return out
