"""Inventory a Copilot application (PLAN §2.1). Read-only.

Discovery walks the whole Copilot layering (docs/knowledge/copilot-stacks.md):

* stacks tagged ``copilot-application=<app>``: env stacks (``copilot-environment``), workload
  stacks (``copilot-service``), the app stack ``<app>-infrastructure-roles``;
* nested stacks (addons) found through ``ParentId``;
* the app StackSet ``<app>-infrastructure`` and its instance stacks;
* Copilot's SSM metadata under ``/copilot/applications/<app>/`` (workload types, envs);
* live state for everything the Terraform mappers need (see ``live.py``);
* objects that custom resources created outside CloudFormation (ACM certificates, alias and
  validation records).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ecsodus.model import (
    ADDONS,
    APP,
    ENV,
    ENV_ADDONS,
    STACKSET_INSTANCE,
    WORKLOAD,
    Inventory,
    OutOfBand,
    Resource,
    Stack,
    StackSet,
    Workload,
    now_iso,
)
from ecsodus.sources import live as live_reads
from ecsodus.sources.aws import Clients, paginate

TAG_APP = "copilot-application"
TAG_ENV = "copilot-environment"
TAG_SVC = "copilot-service"
LIVE_STATUSES = [
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
    "IMPORT_COMPLETE",
    "IMPORT_ROLLBACK_COMPLETE",
    "ROLLBACK_COMPLETE",
    "UPDATE_IN_PROGRESS",
    "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
    "UPDATE_ROLLBACK_IN_PROGRESS",
    "UPDATE_ROLLBACK_FAILED",
    "DELETE_FAILED",
    "CREATE_IN_PROGRESS",
    "REVIEW_IN_PROGRESS",
]


def inventory(
    clients: Clients,
    app: str,
    envs: Iterable[str] | None = None,
    keep_on_copilot: Iterable[str] = (),
) -> Inventory:
    """Build the inventory for ``app``. ``envs`` limits environments (default: all).

    ``keep_on_copilot`` lists workloads ("env/name" or "name") that stay on Copilot (partial
    migration); their stacks and everything they depend on are kept.
    """
    sts = clients("sts").get_caller_identity()
    inv = Inventory(app=app, account=sts["Account"], region=clients.region, captured_at=now_iso())
    cfn = clients("cloudformation")

    summaries = paginate(cfn, "list_stacks", "StackSummaries", StackStatusFilter=LIVE_STATUSES)
    described = _describe_all(cfn, [s["StackName"] for s in summaries])
    by_id = {d["StackId"]: d for d in described}

    wanted_envs = set(envs) if envs else None
    roots: list[dict[str, Any]] = []
    for d in described:
        tags = {t["Key"]: t["Value"] for t in d.get("Tags") or []}
        if tags.get(TAG_APP) != app or d.get("ParentId"):
            continue
        env = tags.get(TAG_ENV)
        if wanted_envs is not None and env and env not in wanted_envs:
            continue
        roots.append(d)

    meta = _ssm_metadata(clients, app)
    for d in roots:
        stack = _stack_from(cfn, d)
        stack.env = stack.tags.get(TAG_ENV)
        stack.workload = stack.tags.get(TAG_SVC)
        if stack.workload:
            stack.kind = WORKLOAD
            stack.workload_type = meta["types"].get(stack.workload)
        elif stack.env:
            stack.kind = ENV
        elif d["StackName"] == f"{app}-infrastructure-roles":
            stack.kind = APP
        else:
            inv.unavailable.append(
                {"stack": d["StackName"], "reason": "unrecognised Copilot stack"}
            )
            continue
        inv.stacks[stack.name] = stack

    # Nested stacks (addons), any depth.
    for d in described:
        root_id = d.get("RootId")
        parent_id = d.get("ParentId")
        if not parent_id or root_id not in by_id:
            continue
        root_name = by_id[root_id]["StackName"]
        parent_name = by_id.get(parent_id, {}).get("StackName")
        if root_name not in inv.stacks or parent_name is None:
            continue
        stack = _stack_from(cfn, d)
        parent = inv.stacks.get(parent_name)
        stack.parent = parent_name
        stack.env = parent.env if parent else None
        stack.workload = parent.workload if parent else None
        stack.kind = ADDONS if parent and parent.kind == WORKLOAD else ENV_ADDONS
        if parent:
            for r in parent.resources:
                if r.type == "AWS::CloudFormation::Stack" and r.physical_id == d["StackId"]:
                    stack.parent_logical_id = r.logical_id
        inv.stacks[stack.name] = stack

    _stackset(clients, inv, app)

    inv.envs = sorted({s.env for s in inv.stacks.values() if s.kind == ENV and s.env})
    keep = set(keep_on_copilot)
    for s in inv.stacks.values():
        if s.kind == WORKLOAD and s.workload and s.env:
            migrate = not ({s.workload, f"{s.env}/{s.workload}"} & keep)
            inv.workloads.append(Workload(s.workload, s.workload_type or "unknown", s.env, migrate))
    inv.ssm_parameters = _ssm_parameter_names(clients, app)
    live_reads.read_live(clients, inv)
    inv.out_of_band = _out_of_band(clients, inv)
    return inv


def _describe_all(cfn: Any, names: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        out.extend(cfn.describe_stacks(StackName=name).get("Stacks") or [])
    return out


def _stack_from(cfn: Any, d: dict[str, Any]) -> Stack:
    name = d["StackName"]
    body = cfn.get_template(StackName=d["StackId"], TemplateStage="Original")["TemplateBody"]
    if not isinstance(body, str):
        body = json.dumps(body, indent=2)
    resources = [
        Resource(
            r["LogicalResourceId"],
            r["ResourceType"],
            r.get("PhysicalResourceId"),
            r.get("ResourceStatus", ""),
        )
        for r in paginate(
            cfn, "list_stack_resources", "StackResourceSummaries", StackName=d["StackId"]
        )
    ]
    outputs, exports = {}, {}
    for o in d.get("Outputs") or []:
        outputs[o["OutputKey"]] = o.get("OutputValue", "")
        if o.get("ExportName"):
            exports[o["ExportName"]] = o.get("OutputValue", "")
    last = d.get("LastUpdatedTime") or d.get("CreationTime")
    return Stack(
        name=name,
        kind="",
        stack_id=d["StackId"],
        status=d.get("StackStatus", ""),
        template_body=body,
        parameters={
            p["ParameterKey"]: p.get("ResolvedValue", p.get("ParameterValue", ""))
            for p in d.get("Parameters") or []
        },
        outputs=outputs,
        exports=exports,
        tags={t["Key"]: t["Value"] for t in d.get("Tags") or []},
        capabilities=list(d.get("Capabilities") or []),
        last_updated=last.isoformat() if hasattr(last, "isoformat") else str(last or ""),
        resources=resources,
    )


def _stackset(clients: Clients, inv: Inventory, app: str) -> None:
    cfn = clients("cloudformation")
    name = f"{app}-infrastructure"
    try:
        ss = cfn.describe_stack_set(StackSetName=name)["StackSet"]
    except Exception as exc:  # noqa: BLE001 - absent StackSet is normal for some apps
        if "StackSetNotFound" in type(exc).__name__ or "NotFound" in str(exc):
            return
        inv.unavailable.append({"stackset": name, "reason": str(exc)})
        return
    body = ss.get("TemplateBody", "")
    instances = paginate(cfn, "list_stack_instances", "Summaries", StackSetName=name)
    admin_arn = ss.get("AdministrationRoleARN", "")
    inv.stacksets[name] = StackSet(
        name=name,
        template_body=body if isinstance(body, str) else json.dumps(body, indent=2),
        administration_role_arn=admin_arn,
        execution_role_name=ss.get("ExecutionRoleName", ""),
        parameters={
            p["ParameterKey"]: p.get("ParameterValue", "") for p in ss.get("Parameters") or []
        },
        capabilities=list(ss.get("Capabilities") or []),
        instances=[
            {
                "account": i.get("Account", ""),
                "region": i.get("Region", ""),
                "stack_id": i.get("StackId", ""),
            }
            for i in instances
        ],
    )
    for inst in instances:
        if inst.get("Account") != inv.account or inst.get("Region") != inv.region:
            inv.unavailable.append(
                {
                    "stackset_instance": f"{inst.get('Account')}/{inst.get('Region')}",
                    "reason": "instance in another account/region: multi-account is blocked in v0.1",
                }
            )
            continue
        sid = inst.get("StackId")
        if not sid:
            continue
        for d in cfn.describe_stacks(StackName=sid).get("Stacks") or []:
            stack = _stack_from(cfn, d)
            stack.kind = STACKSET_INSTANCE
            inv.stacks[stack.name] = stack


def _ssm_metadata(clients: Clients, app: str) -> dict[str, Any]:
    """Copilot's own metadata (String parameters under /copilot/applications/<app>/)."""
    ssm = clients("ssm")
    types: dict[str, str] = {}
    envs: list[str] = []
    for p in paginate(
        ssm,
        "get_parameters_by_path",
        "Parameters",
        Path=f"/copilot/applications/{app}/",
        Recursive=True,
        WithDecryption=False,
    ):
        if p.get("Type") != "String":
            continue
        name = p["Name"]
        try:
            value = json.loads(p.get("Value") or "{}")
        except ValueError:
            continue
        if "/components/" in name and isinstance(value, dict):
            types[value.get("name", name.rsplit("/", 1)[-1])] = value.get("type", "unknown")
        elif "/environments/" in name:
            envs.append(name.rsplit("/", 1)[-1])
    return {"types": types, "envs": envs}


def _ssm_parameter_names(clients: Clients, app: str) -> list[dict[str, str]]:
    """Names and types of `copilot secret init` parameters: metadata only, never values."""
    ssm = clients("ssm")
    out = []
    for p in paginate(
        ssm,
        "describe_parameters",
        "Parameters",
        ParameterFilters=[{"Key": "tag:copilot-application", "Values": [app]}],
    ):
        out.append({"name": p["Name"], "type": p.get("Type", "")})
    return out


def _out_of_band(clients: Clients, inv: Inventory) -> list[OutOfBand]:
    """ACM certificates and Route 53 records created by Copilot custom resources."""
    found: list[OutOfBand] = []
    acm = clients("acm")
    creators = {
        s.name: [
            r.logical_id for r in s.resources if "Cert" in r.type and r.type.startswith("Custom::")
        ]
        for s in inv.stacks.values()
    }
    for cert in paginate(acm, "list_certificates", "CertificateSummaryList"):
        arn = cert["CertificateArn"]
        tags = {
            t["Key"]: t["Value"]
            for t in acm.list_tags_for_certificate(CertificateArn=arn).get("Tags") or []
        }
        if tags.get(TAG_APP) != inv.app:
            continue
        stack = next(
            (
                s
                for s in inv.stacks.values()
                if s.env == tags.get(TAG_ENV) and s.workload == tags.get(TAG_SVC)
            ),
            None,
        )
        by = f"{stack.name}/{(creators.get(stack.name) or ['?'])[0]}" if stack else "unknown"
        detail = acm.describe_certificate(CertificateArn=arn)["Certificate"]
        found.append(
            OutOfBand(
                "acm_certificate",
                arn,
                by,
                {
                    "DomainName": detail.get("DomainName"),
                    "SubjectAlternativeNames": detail.get("SubjectAlternativeNames", []),
                    "InUseBy": detail.get("InUseBy", []),
                    "DomainValidationOptions": [
                        {k: o.get(k) for k in ("DomainName", "ResourceRecord")}
                        for o in detail.get("DomainValidationOptions") or []
                    ],
                },
            )
        )
    return found
