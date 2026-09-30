"""Terraform mappers: tf_data family (stateful data resources; see tfmap.py).

RDS/Aurora, DynamoDB, S3, EFS, Secrets Manager, SSM (String only), KMS and ECR.

Rules specific to this family (PLAN §2.2, §2.4, §13.8):

* ``stateful=True`` on everything whose loss loses data (adds ``prevent_destroy``).
* Values the template cannot pin down exactly come from ``ctx.live`` (the inventory's live
  reads): RDS engine version, master username (the template uses a ``{{resolve:...}}`` dynamic
  reference, which is never resolved), storage encryption, DynamoDB billing mode/capacity, the
  deployed KMS key policy. Where template and live disagree, live wins and a note says so.
* ``deletion_protection`` (and DynamoDB ``deletion_protection_enabled``) is emitted only from its
  live value, and only when it is on (PLAN §2.4).
* **Secrets contract:** a Secrets Manager secret maps to ``aws_secretsmanager_secret`` only, never
  ``aws_secretsmanager_secret_version``; ``SecretString`` / ``GenerateSecretString`` are never
  resolved or emitted. RDS ``master_password`` is never emitted. SSM ``SecureString`` is never
  imported.
* A template property this module does not know is refused (``Unresolvable``) rather than
  silently dropped, so the first plan cannot hide a missing argument.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ecsodus.emit.hcl import Block
from ecsodus.mappers.tfmap import MANUAL_CLEANUP, Ctx, NotImported, TfSpec, Unresolvable, mapper

# -- helpers --------------------------------------------------------------------------------


def _only(ctx: Ctx, known: set[str]) -> None:
    """Refuse template properties this mapper does not handle."""
    unknown = sorted(set(ctx.props) - known)
    if unknown:
        raise Unresolvable(f"{ctx.resource.type}: unhandled properties {', '.join(unknown)}")


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _pick(
    ctx: Ctx,
    spec: TfSpec,
    live_key: str,
    prop: str | None,
    *,
    required: bool = False,
    live_only: bool = False,
    live: dict[str, Any] | None = None,
) -> Any:
    """Live value (wins, with a note on disagreement), else the resolved template value.

    ``live_only``: the template value is not trusted (stale, or a dynamic reference); the live
    value is required. ``live``: read from this view instead of ``ctx.live`` (for API responses
    whose fields are nested, flattened by the caller).
    """
    lv = (ctx.live if live is None else live).get(live_key)
    tv = ctx.r(prop, None) if prop and not live_only else None
    if lv is not None:
        if tv is not None and not _same(tv, lv):
            spec.notes.append(
                f"{prop}: template has {tv!r}, live has {lv!r}; the live value is used "
                "(changed since the template was deployed)"
            )
        return lv
    if live_only:
        raise Unresolvable(f"live {live_key} was not read (the template cannot express it)")
    if tv is None and required:
        raise Unresolvable(f"{prop or live_key}: no template or live value")
    return tv


def _json_doc(doc: Any) -> str:
    """A policy document as a JSON string (the provider compares policies semantically)."""
    if isinstance(doc, str):
        return doc
    return json.dumps(doc, ensure_ascii=False)


def _add_tags(ctx: Ctx, body: list, key: str = "Tags") -> None:
    tags = ctx.tags(key)
    if tags:
        body.append(("tags", tags))


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    raise Unresolvable(f"expected a boolean, got {v!r}")


def _num(v: Any) -> int | float:
    f = float(v)
    return int(f) if f.is_integer() else f


def _deletion_protection(ctx: Ctx, spec: TfSpec, live_key: str, arg: str) -> None:
    """Emit deletion protection from its live value only, and only when on (PLAN §2.4)."""
    if live_key not in ctx.live:
        raise Unresolvable(f"live {live_key} was not read")
    if _bool(ctx.live[live_key]):
        spec.body.append((arg, True))
    else:
        spec.notes.append(
            f"{arg} is off on live, so it is not emitted; the runbook turns it on out of band "
            "and re-inventories before generating (PLAN §2.4, §2.5 step 2)"
        )


def _final_snapshot(spec: TfSpec, identifier: str) -> None:
    snap = f"{identifier}-ecsodus-final"
    spec.body.append(("skip_final_snapshot", False))
    spec.body.append(("final_snapshot_identifier", snap))
    spec.notes.append(
        f'skip_final_snapshot = false with final_snapshot_identifier "{snap}" (deterministic): '
        "a destroy, if ever allowed past prevent_destroy, takes a final snapshot. The provider's "
        "importer records skip_final_snapshot = true and no identifier, so the import plan shows "
        "a state-only in-place update of these two arguments (no API call)"
    )


# -- RDS --------------------------------------------------------------------------------------

_CLUSTER_PROPS = {
    "DBClusterIdentifier", "Engine", "EngineVersion", "EngineMode", "DatabaseName",
    "MasterUsername", "MasterUserPassword", "ManageMasterUserPassword", "Port",
    "DBSubnetGroupName", "DBClusterParameterGroupName", "VpcSecurityGroupIds",
    "StorageEncrypted", "KmsKeyId", "BackupRetentionPeriod", "PreferredBackupWindow",
    "PreferredMaintenanceWindow", "DeletionProtection", "ServerlessV2ScalingConfiguration",
    "ScalingConfiguration", "EnableHttpEndpoint", "EnableIAMDatabaseAuthentication",
    "CopyTagsToSnapshot", "EnableCloudwatchLogsExports", "AvailabilityZones", "Tags",
    "SnapshotIdentifier",
}  # fmt: skip

_V1_SCALING = (
    ("AutoPause", "auto_pause", _bool),
    ("MaxCapacity", "max_capacity", int),
    ("MinCapacity", "min_capacity", int),
    ("SecondsBeforeTimeout", "seconds_before_timeout", int),
    ("SecondsUntilAutoPause", "seconds_until_auto_pause", int),
    ("TimeoutAction", "timeout_action", str),
)


@mapper("AWS::RDS::DBCluster")
def rds_cluster(ctx: Ctx) -> TfSpec:
    _only(ctx, _CLUSTER_PROPS)
    ident = ctx.pid
    spec = TfSpec("aws_rds_cluster", ident, [], stateful=True)
    body = spec.body
    body.append(("cluster_identifier", ident))
    body.append(("engine", _pick(ctx, spec, "Engine", "Engine", required=True)))
    engine_version = _pick(ctx, spec, "EngineVersion", None, live_only=True)
    tmpl_version = ctx.r("EngineVersion", None)
    if tmpl_version is not None and str(tmpl_version) != str(engine_version):
        spec.notes.append(
            f"EngineVersion: template has {tmpl_version!r}, live has {engine_version!r}; the "
            "live value is used (the cluster was upgraded since the template was deployed)"
        )
    body.append(("engine_version", engine_version))
    mode = _pick(ctx, spec, "EngineMode", "EngineMode") or "provisioned"
    body.append(("engine_mode", mode))
    db_name = _pick(ctx, spec, "DatabaseName", "DatabaseName")
    if db_name:
        body.append(("database_name", db_name))
    # Copilot's MasterUsername is a {{resolve:secretsmanager:...}} dynamic reference: never
    # resolved here; the username (not a secret) comes from DescribeDBClusters.
    body.append(("master_username", _pick(ctx, spec, "MasterUsername", None, live_only=True)))
    if ctx.has("MasterUserPassword"):
        spec.notes.append(
            "master_password is never emitted (secrets contract); the provider does not read it "
            "back, so omitting it keeps the import plan clean"
        )
    if ctx.r("ManageMasterUserPassword", False):
        body.append(("manage_master_user_password", True))
        spec.notes.append(
            "manage_master_user_password is not read back by the provider on import; expect a "
            "state-only update on the first plan"
        )
    port = _pick(ctx, spec, "Port", "Port")
    if port is not None:
        body.append(("port", int(port)))
    subnet_group = _pick(ctx, spec, "DBSubnetGroup", "DBSubnetGroupName")
    if subnet_group:
        body.append(("db_subnet_group_name", subnet_group))
    pgroup = _pick(ctx, spec, "DBClusterParameterGroup", "DBClusterParameterGroupName")
    if pgroup:
        body.append(("db_cluster_parameter_group_name", pgroup))
    sgs = _pick(ctx, spec, "VpcSecurityGroupIds", "VpcSecurityGroupIds")
    if sgs:
        body.append(("vpc_security_group_ids", sorted(sgs)))
    encrypted = _bool(_pick(ctx, spec, "StorageEncrypted", "StorageEncrypted", live_only=True))
    body.append(("storage_encrypted", encrypted))
    if encrypted:
        kms = _pick(ctx, spec, "KmsKeyId", "KmsKeyId")
        if kms:
            body.append(("kms_key_id", kms))
    retention = _pick(ctx, spec, "BackupRetentionPeriod", "BackupRetentionPeriod")
    if retention is not None:
        body.append(("backup_retention_period", int(retention)))
    for key, arg in (
        ("PreferredBackupWindow", "preferred_backup_window"),
        ("PreferredMaintenanceWindow", "preferred_maintenance_window"),
    ):
        v = _pick(ctx, spec, key, key)
        if v:
            body.append((arg, v))
    for prop, arg in (
        ("EnableHttpEndpoint", "enable_http_endpoint"),
        ("EnableIAMDatabaseAuthentication", "iam_database_authentication_enabled"),
        ("CopyTagsToSnapshot", "copy_tags_to_snapshot"),
    ):
        v = ctx.r(prop, None)
        if v is not None:
            body.append((arg, _bool(v)))
    logs = ctx.r("EnableCloudwatchLogsExports", None)
    if logs:
        body.append(("enabled_cloudwatch_logs_exports", sorted(logs)))
    _deletion_protection(ctx, spec, "DeletionProtection", "deletion_protection")
    _final_snapshot(spec, ident)

    if mode == "serverless":
        sc = ctx.live.get("ScalingConfigurationInfo") or ctx.r("ScalingConfiguration", None)
        if not sc:
            raise Unresolvable("serverless (v1) cluster without a scaling configuration")
        blk: list = [
            (arg, conv(sc[key])) for key, arg, conv in _V1_SCALING if sc.get(key) is not None
        ]
        body.append(("scaling_configuration", Block(blk)))
    else:
        if ctx.has("ScalingConfiguration"):
            spec.notes.append(
                f"template ScalingConfiguration (Aurora Serverless v1) is ignored: live engine "
                f"mode is {mode!r} (Serverless v1 clusters were upgraded by AWS)"
            )
        lv2 = ctx.live.get("ServerlessV2ScalingConfiguration")
        tv2 = ctx.r("ServerlessV2ScalingConfiguration", None)
        if lv2 and tv2:
            for key in ("MinCapacity", "MaxCapacity"):
                if key in tv2 and key in lv2 and not _same(tv2[key], lv2[key]):
                    spec.notes.append(
                        f"ServerlessV2ScalingConfiguration.{key}: template has {tv2[key]!r}, "
                        f"live has {lv2[key]!r}; the live value is used"
                    )
        v2 = lv2 or tv2
        if v2:
            blk = [
                ("max_capacity", _num(v2["MaxCapacity"])),
                ("min_capacity", _num(v2["MinCapacity"])),
            ]
            if v2.get("SecondsUntilAutoPause") is not None:
                blk.append(("seconds_until_auto_pause", int(v2["SecondsUntilAutoPause"])))
            body.append(("serverlessv2_scaling_configuration", Block(blk)))
    if ctx.has("SnapshotIdentifier"):
        spec.notes.append(
            "SnapshotIdentifier (creation-time restore source) is not emitted: it forces "
            "replacement in Terraform and is not read back"
        )
    _add_tags(ctx, body)
    return spec


_INSTANCE_PROPS = {
    "DBInstanceIdentifier", "DBClusterIdentifier", "DBInstanceClass", "Engine", "EngineVersion",
    "PromotionTier", "AvailabilityZone", "PubliclyAccessible", "DBParameterGroupName",
    "AutoMinorVersionUpgrade", "MonitoringInterval", "MonitoringRoleArn",
    "EnablePerformanceInsights", "PerformanceInsightsRetentionPeriod",
    "PerformanceInsightsKMSKeyId", "CACertificateIdentifier", "DBSubnetGroupName", "Tags",
    # standalone instances
    "AllocatedStorage", "StorageType", "Iops", "StorageThroughput", "DBName", "MasterUsername",
    "MasterUserPassword", "ManageMasterUserPassword", "Port", "VPCSecurityGroups", "MultiAZ",
    "StorageEncrypted", "KmsKeyId", "BackupRetentionPeriod", "PreferredBackupWindow",
    "PreferredMaintenanceWindow", "DeletionProtection", "CopyTagsToSnapshot",
    "EnableCloudwatchLogsExports", "EnableIAMDatabaseAuthentication", "MaxAllocatedStorage",
}  # fmt: skip


def _instance_common(ctx: Ctx, spec: TfSpec) -> None:
    body = spec.body
    pgroup = _pick(ctx, spec, "DBParameterGroupName", "DBParameterGroupName")
    if pgroup:
        arg = (
            "db_parameter_group_name"
            if spec.tf_type == "aws_rds_cluster_instance"
            else "parameter_group_name"
        )
        body.append((arg, pgroup))
    for live_key, prop, arg in (
        ("AutoMinorVersionUpgrade", "AutoMinorVersionUpgrade", "auto_minor_version_upgrade"),
        ("PerformanceInsightsEnabled", "EnablePerformanceInsights", "performance_insights_enabled"),
    ):
        v = _pick(ctx, spec, live_key, prop)
        if v is not None:
            body.append((arg, _bool(v)))
    interval = _pick(ctx, spec, "MonitoringInterval", "MonitoringInterval")
    if interval is not None:
        body.append(("monitoring_interval", int(interval)))
        role = _pick(ctx, spec, "MonitoringRoleArn", "MonitoringRoleArn")
        if role:
            body.append(("monitoring_role_arn", role))
    key = "PerformanceInsightsRetentionPeriod"
    pi_ret = _pick(ctx, spec, key, key)
    if pi_ret is not None:
        body.append(("performance_insights_retention_period", int(pi_ret)))
    pi_kms = _pick(ctx, spec, "PerformanceInsightsKMSKeyId", "PerformanceInsightsKMSKeyId")
    if pi_kms:
        body.append(("performance_insights_kms_key_id", pi_kms))
    ca = _pick(ctx, spec, "CACertificateIdentifier", "CACertificateIdentifier")
    if ca and ctx.has("CACertificateIdentifier"):
        body.append(("ca_cert_identifier", ca))


@mapper("AWS::RDS::DBInstance")
def rds_instance(ctx: Ctx) -> TfSpec:
    _only(ctx, _INSTANCE_PROPS)
    ident = ctx.pid
    if ctx.has("DBClusterIdentifier"):
        return _aurora_instance(ctx, ident)
    spec = TfSpec("aws_db_instance", ident, [], stateful=True)
    body = spec.body
    body.append(("identifier", ident))
    body.append(("engine", _pick(ctx, spec, "Engine", "Engine", required=True)))
    body.append(("engine_version", _pick(ctx, spec, "EngineVersion", None, live_only=True)))
    body.append(
        ("instance_class", _pick(ctx, spec, "DBInstanceClass", "DBInstanceClass", required=True))
    )
    storage = _pick(ctx, spec, "AllocatedStorage", "AllocatedStorage", live_only=True)
    body.append(("allocated_storage", int(storage)))
    storage_type = _pick(ctx, spec, "StorageType", "StorageType")
    if storage_type:
        body.append(("storage_type", storage_type))
    for key, arg in (
        ("Iops", "iops"),
        ("StorageThroughput", "storage_throughput"),
        ("MaxAllocatedStorage", "max_allocated_storage"),
    ):
        v = _pick(ctx, spec, key, key)
        if v is not None:
            body.append((arg, int(v)))
    db_name = _pick(ctx, spec, "DBName", "DBName")
    if db_name:
        body.append(("db_name", db_name))
    body.append(("username", _pick(ctx, spec, "MasterUsername", None, live_only=True)))
    if ctx.has("MasterUserPassword"):
        spec.notes.append("password is never emitted (secrets contract)")
    if ctx.r("ManageMasterUserPassword", False):
        body.append(("manage_master_user_password", True))
    port = _pick(ctx, spec, "Port", "Port")
    if port is not None:
        body.append(("port", int(port)))
    subnet_group = _pick(ctx, spec, "DBSubnetGroupName", "DBSubnetGroupName")
    if subnet_group:
        body.append(("db_subnet_group_name", subnet_group))
    sgs = _pick(ctx, spec, "VpcSecurityGroupIds", "VPCSecurityGroups")
    if sgs:
        body.append(("vpc_security_group_ids", sorted(sgs)))
    for live_key, prop, arg in (
        ("MultiAZ", "MultiAZ", "multi_az"),
        ("PubliclyAccessible", "PubliclyAccessible", "publicly_accessible"),
        ("CopyTagsToSnapshot", "CopyTagsToSnapshot", "copy_tags_to_snapshot"),
        (
            "IAMDatabaseAuthenticationEnabled",
            "EnableIAMDatabaseAuthentication",
            "iam_database_authentication_enabled",
        ),
    ):
        v = _pick(ctx, spec, live_key, prop)
        if v is not None:
            body.append((arg, _bool(v)))
    encrypted = _bool(_pick(ctx, spec, "StorageEncrypted", "StorageEncrypted", live_only=True))
    body.append(("storage_encrypted", encrypted))
    if encrypted:
        kms = _pick(ctx, spec, "KmsKeyId", "KmsKeyId")
        if kms:
            body.append(("kms_key_id", kms))
    retention = _pick(ctx, spec, "BackupRetentionPeriod", "BackupRetentionPeriod")
    if retention is not None:
        body.append(("backup_retention_period", int(retention)))
    for key, arg in (
        ("PreferredBackupWindow", "backup_window"),
        ("PreferredMaintenanceWindow", "maintenance_window"),
    ):
        v = _pick(ctx, spec, key, key)
        if v:
            body.append((arg, v))
    logs = ctx.r("EnableCloudwatchLogsExports", None)
    if logs:
        body.append(("enabled_cloudwatch_logs_exports", sorted(logs)))
    _instance_common(ctx, spec)
    _deletion_protection(ctx, spec, "DeletionProtection", "deletion_protection")
    _final_snapshot(spec, ident)
    _add_tags(ctx, body)
    return spec


def _aurora_instance(ctx: Ctx, ident: str) -> TfSpec:
    spec = TfSpec("aws_rds_cluster_instance", ident, [], stateful=True)
    body = spec.body
    body.append(("identifier", ident))
    body.append(("cluster_identifier", ctx.r("DBClusterIdentifier")))
    body.append(("engine", _pick(ctx, spec, "Engine", "Engine", required=True)))
    body.append(
        ("instance_class", _pick(ctx, spec, "DBInstanceClass", "DBInstanceClass", required=True))
    )
    # Copilot writes AvailabilityZone as !Select [0, !GetAZs ...]: take it from live.
    body.append(("availability_zone", _pick(ctx, spec, "AvailabilityZone", None, live_only=True)))
    tier = _pick(ctx, spec, "PromotionTier", "PromotionTier")
    if tier is not None:
        body.append(("promotion_tier", int(tier)))
    public = _pick(ctx, spec, "PubliclyAccessible", "PubliclyAccessible", required=True)
    body.append(("publicly_accessible", _bool(public)))
    subnet_group = _pick(ctx, spec, "DBSubnetGroupName", "DBSubnetGroupName")
    if subnet_group:
        body.append(("db_subnet_group_name", subnet_group))
    _instance_common(ctx, spec)
    spec.notes.append(
        "Aurora cluster member: engine version, storage, credentials and deletion protection are "
        "cluster-level (aws_rds_cluster)"
    )
    _add_tags(ctx, body)
    return spec


@mapper("AWS::RDS::DBSubnetGroup")
def db_subnet_group(ctx: Ctx) -> TfSpec:
    _only(ctx, {"DBSubnetGroupName", "DBSubnetGroupDescription", "SubnetIds", "Tags"})
    body: list = [
        ("name", ctx.pid),
        ("description", ctx.r("DBSubnetGroupDescription")),
        ("subnet_ids", sorted(ctx.r("SubnetIds"))),
    ]
    _add_tags(ctx, body)
    return TfSpec("aws_db_subnet_group", ctx.pid, body)


def _parameter_group(ctx: Ctx, tf_type: str, name_key: str) -> TfSpec:
    _only(ctx, {name_key, "Description", "Family", "Parameters", "Tags"})
    body: list = [
        ("name", ctx.pid),
        ("family", ctx.r("Family")),
        ("description", ctx.r("Description")),
    ]
    params = ctx.r("Parameters", {}) or {}
    for k in sorted(params):
        v = params[k]
        value = ("1" if v else "0") if isinstance(v, bool) else str(v)
        body.append(("parameter", Block([("name", k), ("value", value)])))
    _add_tags(ctx, body)
    return TfSpec(tf_type, ctx.pid, body)


@mapper("AWS::RDS::DBClusterParameterGroup")
def rds_cluster_parameter_group(ctx: Ctx) -> TfSpec:
    return _parameter_group(ctx, "aws_rds_cluster_parameter_group", "DBClusterParameterGroupName")


@mapper("AWS::RDS::DBParameterGroup")
def db_parameter_group(ctx: Ctx) -> TfSpec:
    return _parameter_group(ctx, "aws_db_parameter_group", "DBParameterGroupName")


# -- DynamoDB ---------------------------------------------------------------------------------

_DDB_PROPS = {
    "TableName", "AttributeDefinitions", "KeySchema", "BillingMode", "ProvisionedThroughput",
    "LocalSecondaryIndexes", "GlobalSecondaryIndexes", "StreamSpecification", "SSESpecification",
    "PointInTimeRecoverySpecification", "TimeToLiveSpecification", "TableClass",
    "DeletionProtectionEnabled", "Tags",
}  # fmt: skip


def _projection(p: dict[str, Any]) -> list:
    out: list = [("projection_type", p.get("ProjectionType", "ALL"))]
    if p.get("NonKeyAttributes"):
        out.append(("non_key_attributes", sorted(p["NonKeyAttributes"])))
    return out


def _keys(schema: list[dict[str, str]]) -> dict[str, str]:
    return {k["KeyType"]: k["AttributeName"] for k in schema}


def _ddb_live(table: dict[str, Any]) -> dict[str, Any]:
    """DescribeTable's nested fields (as ``sources/live.py`` records them), flattened.

    ``BillingModeSummary`` and ``TableClassSummary`` are absent for tables that never changed
    mode or class; the template value (or the AWS default) then applies.
    """
    out: dict[str, Any] = {}
    billing = (table.get("BillingModeSummary") or {}).get("BillingMode")
    if billing:
        out["BillingMode"] = billing
    table_class = (table.get("TableClassSummary") or {}).get("TableClass")
    if table_class:
        out["TableClass"] = table_class
    pt = table.get("ProvisionedThroughput") or {}
    for key in ("ReadCapacityUnits", "WriteCapacityUnits"):
        if pt.get(key) is not None:
            out[key] = pt[key]
    kms_arn = (table.get("SSEDescription") or {}).get("KMSMasterKeyArn")
    if kms_arn:
        out["KMSMasterKeyArn"] = kms_arn
    return out


@mapper("AWS::DynamoDB::Table")
def dynamodb_table(ctx: Ctx) -> TfSpec:
    _only(ctx, _DDB_PROPS)
    name = ctx.pid
    spec = TfSpec("aws_dynamodb_table", name, [], stateful=True)
    body = spec.body
    body.append(("name", name))
    live = _ddb_live(ctx.live)
    billing = _pick(ctx, spec, "BillingMode", "BillingMode", live=live) or "PROVISIONED"
    body.append(("billing_mode", billing))
    keys = _keys(ctx.r("KeySchema"))
    body.append(("hash_key", keys["HASH"]))
    if "RANGE" in keys:
        body.append(("range_key", keys["RANGE"]))
    if billing == "PROVISIONED":
        # Capacity drifts under autoscaling: live only.
        for live_key, arg in (
            ("ReadCapacityUnits", "read_capacity"),
            ("WriteCapacityUnits", "write_capacity"),
        ):
            body.append((arg, int(_pick(ctx, spec, live_key, None, live_only=True, live=live))))
    for attr in sorted(ctx.r("AttributeDefinitions"), key=lambda a: a["AttributeName"]):
        attr_body = [("name", attr["AttributeName"]), ("type", attr["AttributeType"])]
        body.append(("attribute", Block(attr_body)))
    for lsi in ctx.r("LocalSecondaryIndexes", []) or []:
        lsi_body = [("name", lsi["IndexName"]), ("range_key", _keys(lsi["KeySchema"])["RANGE"])]
        lsi_body += _projection(lsi.get("Projection") or {})
        body.append(("local_secondary_index", Block(lsi_body)))
    live_gsis = {g["IndexName"]: g for g in ctx.live.get("GlobalSecondaryIndexes") or []}
    for gsi in ctx.r("GlobalSecondaryIndexes", []) or []:
        blk: list = [("name", gsi["IndexName"])]
        for k in gsi["KeySchema"]:
            ks = [("attribute_name", k["AttributeName"]), ("key_type", k["KeyType"])]
            blk.append(("key_schema", Block(ks)))
        blk += _projection(gsi.get("Projection") or {})
        if billing == "PROVISIONED":
            lg = live_gsis.get(gsi["IndexName"])
            if not lg or "ProvisionedThroughput" not in lg:
                raise Unresolvable(f"live capacity of GSI {gsi['IndexName']} was not read")
            pt = lg["ProvisionedThroughput"]
            blk.append(("read_capacity", int(pt["ReadCapacityUnits"])))
            blk.append(("write_capacity", int(pt["WriteCapacityUnits"])))
        body.append(("global_secondary_index", Block(blk)))
    stream = ctx.r("StreamSpecification", None)
    if stream:
        body.append(("stream_enabled", True))
        body.append(("stream_view_type", stream["StreamViewType"]))
    sse = ctx.r("SSESpecification", None)
    if sse:
        blk = [("enabled", _bool(sse.get("SSEEnabled", False)))]
        if sse.get("KMSMasterKeyId"):
            arn = live.get("KMSMasterKeyArn")
            if not arn:
                raise Unresolvable(
                    "live SSEDescription.KMSMasterKeyArn was not read (the template key id/alias "
                    "is not the ARN Terraform stores)"
                )
            blk.append(("kms_key_arn", arn))
        body.append(("server_side_encryption", Block(blk)))
    pitr = ctx.r("PointInTimeRecoverySpecification", None)
    if pitr:
        blk = [("enabled", _bool(pitr.get("PointInTimeRecoveryEnabled", False)))]
        if pitr.get("RecoveryPeriodInDays") is not None:
            blk.append(("recovery_period_in_days", int(pitr["RecoveryPeriodInDays"])))
        body.append(("point_in_time_recovery", Block(blk)))
    ttl = ctx.r("TimeToLiveSpecification", None)
    if ttl:
        ttl_body = [
            ("attribute_name", ttl.get("AttributeName", "")),
            ("enabled", _bool(ttl.get("Enabled", False))),
        ]
        body.append(("ttl", Block(ttl_body)))
    table_class = _pick(ctx, spec, "TableClass", "TableClass", live=live)
    if table_class:
        body.append(("table_class", table_class))
    _deletion_protection(ctx, spec, "DeletionProtectionEnabled", "deletion_protection_enabled")
    _add_tags(ctx, body)
    return spec


# -- S3 ---------------------------------------------------------------------------------------

# Bucket sub-configurations are separate resources in provider 6.x. One TfSpec per CFN resource,
# so they are listed in notes (resource type + import id) and the bucket is fidelity "partial".
_S3_SUBRESOURCES: dict[str, str] = {
    "VersioningConfiguration": "aws_s3_bucket_versioning",
    "BucketEncryption": "aws_s3_bucket_server_side_encryption_configuration",
    "PublicAccessBlockConfiguration": "aws_s3_bucket_public_access_block",
    "OwnershipControls": "aws_s3_bucket_ownership_controls",
    "LifecycleConfiguration": "aws_s3_bucket_lifecycle_configuration",
    "CorsConfiguration": "aws_s3_bucket_cors_configuration",
    "WebsiteConfiguration": "aws_s3_bucket_website_configuration",
    "LoggingConfiguration": "aws_s3_bucket_logging",
    "NotificationConfiguration": "aws_s3_bucket_notification",
    "ReplicationConfiguration": "aws_s3_bucket_replication_configuration",
    "AccelerateConfiguration": "aws_s3_bucket_accelerate_configuration",
    "ObjectLockConfiguration": "aws_s3_bucket_object_lock_configuration",
}
# List-valued configurations: one resource per entry, import id "<bucket>:<Id>".
_S3_LISTED: dict[str, str] = {
    "IntelligentTieringConfigurations": "aws_s3_bucket_intelligent_tiering_configuration",
    "AnalyticsConfigurations": "aws_s3_bucket_analytics_configuration",
    "InventoryConfigurations": "aws_s3_bucket_inventory",
    "MetricsConfigurations": "aws_s3_bucket_metric",
}


@mapper("AWS::S3::Bucket")
def s3_bucket(ctx: Ctx) -> TfSpec:
    known = {"BucketName", "Tags", "ObjectLockEnabled", "AccessControl"}
    _only(ctx, known | set(_S3_SUBRESOURCES) | set(_S3_LISTED))
    bucket = ctx.pid
    spec = TfSpec("aws_s3_bucket", bucket, [("bucket", bucket)], stateful=True)
    if ctx.r("ObjectLockEnabled", False):
        spec.body.append(("object_lock_enabled", True))
    _add_tags(ctx, spec.body)
    subs: list[str] = []
    for prop, tf_type in _S3_SUBRESOURCES.items():
        if ctx.has(prop):
            subs.append(f'{tf_type} (import id "{bucket}") for {prop}')
    for prop, tf_type in _S3_LISTED.items():
        for item in ctx.r(prop, []) or []:
            subs.append(f'{tf_type} (import id "{bucket}:{item["Id"]}") for {prop}')
    acl = ctx.r("AccessControl", None)
    if acl and acl != "Private":
        canned = re.sub(r"(?<!^)(?=[A-Z])", "-", acl).lower()  # PublicRead -> public-read
        subs.append(f'aws_s3_bucket_acl (import id "{bucket},{canned}") for AccessControl')
    elif acl:
        spec.notes.append(
            "AccessControl: Private is the default canned ACL (and ACLs are disabled under "
            "BucketOwnerEnforced); no aws_s3_bucket_acl is needed"
        )
    if subs:
        spec.fidelity = "partial"
        spec.notes.append(
            "bucket sub-configurations are separate resources in provider 6.x and are not "
            "generated in v0.1; import them to manage them: " + "; ".join(subs)
        )
    return spec


@mapper("AWS::S3::BucketPolicy")
def s3_bucket_policy(ctx: Ctx) -> TfSpec:
    _only(ctx, {"Bucket", "PolicyDocument"})
    bucket = ctx.r("Bucket")
    body: list = [("bucket", bucket), ("policy", _json_doc(ctx.r("PolicyDocument")))]
    return TfSpec("aws_s3_bucket_policy", bucket, body)


# -- EFS --------------------------------------------------------------------------------------

_EFS_LIFECYCLE = {
    "TransitionToIA": "transition_to_ia",
    "TransitionToPrimaryStorageClass": "transition_to_primary_storage_class",
    "TransitionToArchive": "transition_to_archive",
}


@mapper("AWS::EFS::FileSystem")
def efs_file_system(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "Encrypted", "KmsKeyId", "PerformanceMode", "ThroughputMode",
        "ProvisionedThroughputInMibps", "LifecyclePolicies", "AvailabilityZoneName",
        "FileSystemTags", "BackupPolicy", "FileSystemPolicy", "ReplicationConfiguration",
        "FileSystemProtection", "BypassPolicyLockoutSafetyCheck",
    })  # fmt: skip
    fs = ctx.pid
    spec = TfSpec("aws_efs_file_system", fs, [], stateful=True)
    body = spec.body
    encrypted = _pick(ctx, spec, "Encrypted", "Encrypted")
    encrypted = _bool(encrypted) if encrypted is not None else False
    body.append(("encrypted", encrypted))
    if encrypted:
        kms = _pick(ctx, spec, "KmsKeyId", "KmsKeyId")
        if kms:
            body.append(("kms_key_id", kms))
    for key, arg in (
        ("PerformanceMode", "performance_mode"),
        ("ThroughputMode", "throughput_mode"),
    ):
        v = _pick(ctx, spec, key, key)
        if v:
            body.append((arg, v))
    key = "ProvisionedThroughputInMibps"
    mibps = _pick(ctx, spec, key, key)
    if mibps is not None:
        body.append(("provisioned_throughput_in_mibps", _num(mibps)))
    az = ctx.r("AvailabilityZoneName", None)
    if az:
        body.append(("availability_zone_name", az))
    for pol in ctx.r("LifecyclePolicies", []) or []:
        blk = []
        for k, v in pol.items():
            if k not in _EFS_LIFECYCLE:
                raise Unresolvable(f"unknown EFS lifecycle policy key {k}")
            blk.append((_EFS_LIFECYCLE[k], v))
        body.append(("lifecycle_policy", Block(blk)))
    prot = ctx.r("FileSystemProtection", None)
    if prot and prot.get("ReplicationOverwriteProtection"):
        overwrite = prot["ReplicationOverwriteProtection"]
        body.append(("protection", Block([("replication_overwrite", overwrite)])))
    _add_tags(ctx, body, "FileSystemTags")
    subs = []
    if ctx.has("BackupPolicy"):
        status = (ctx.r("BackupPolicy") or {}).get("Status")
        subs.append(f'aws_efs_backup_policy (import id "{fs}", status {status})')
    if ctx.has("FileSystemPolicy"):
        subs.append(f'aws_efs_file_system_policy (import id "{fs}")')
    if ctx.has("ReplicationConfiguration"):
        subs.append(f'aws_efs_replication_configuration (import id "{fs}")')
    if subs:
        spec.fidelity = "partial"
        spec.notes.append(
            "file-system sub-configurations are separate resources and are not generated in "
            "v0.1: " + "; ".join(subs)
        )
    return spec


@mapper("AWS::EFS::MountTarget")
def efs_mount_target(ctx: Ctx) -> TfSpec:
    _only(
        ctx,
        {"FileSystemId", "SubnetId", "SecurityGroups", "IpAddress", "IpAddressType", "Ipv6Address"},
    )
    body: list = [
        ("file_system_id", ctx.r("FileSystemId")),
        ("subnet_id", ctx.r("SubnetId")),
        ("security_groups", sorted(ctx.r("SecurityGroups"))),
    ]
    for prop, arg in (
        ("IpAddress", "ip_address"),
        ("IpAddressType", "ip_address_type"),
        ("Ipv6Address", "ipv6_address"),
    ):
        v = ctx.r(prop, None)
        if v:
            body.append((arg, v))
    return TfSpec("aws_efs_mount_target", ctx.pid, body)


@mapper("AWS::EFS::AccessPoint")
def efs_access_point(ctx: Ctx) -> TfSpec:
    _only(ctx, {"FileSystemId", "PosixUser", "RootDirectory", "AccessPointTags", "ClientToken"})
    spec = TfSpec("aws_efs_access_point", ctx.pid, [("file_system_id", ctx.r("FileSystemId"))])
    body = spec.body
    posix = ctx.r("PosixUser", None)
    if posix:
        blk: list = [("gid", int(posix["Gid"])), ("uid", int(posix["Uid"]))]
        if posix.get("SecondaryGids"):
            blk.append(("secondary_gids", sorted(int(g) for g in posix["SecondaryGids"])))
        body.append(("posix_user", Block(blk)))
    root = ctx.r("RootDirectory", None)
    if root:
        blk = []
        if root.get("Path"):
            blk.append(("path", root["Path"]))
        ci = root.get("CreationInfo")
        if ci:
            ci_body = [
                ("owner_gid", int(ci["OwnerGid"])),
                ("owner_uid", int(ci["OwnerUid"])),
                ("permissions", str(ci["Permissions"])),
            ]
            blk.append(("creation_info", Block(ci_body)))
        body.append(("root_directory", Block(blk)))
    _add_tags(ctx, body, "AccessPointTags")
    if ctx.has("ClientToken"):
        spec.notes.append(
            "ClientToken is a creation-time idempotency token with no Terraform argument"
        )
    return spec


# -- Secrets Manager --------------------------------------------------------------------------


@mapper("AWS::SecretsManager::Secret")
def secretsmanager_secret(ctx: Ctx) -> TfSpec:
    # SecretString / GenerateSecretString are checked for presence only: never resolved.
    _only(
        ctx,
        {"Name", "Description", "KmsKeyId", "Tags", "ReplicaRegions", "SecretString",
         "GenerateSecretString"},
    )  # fmt: skip
    arn = ctx.pid
    if not arn.startswith("arn:"):
        raise Unresolvable(f"secret physical id {arn!r} is not an ARN")
    spec = TfSpec("aws_secretsmanager_secret", arn, [], stateful=True)
    body = spec.body
    name = ctx.live.get("Name") or ctx.r("Name", None)
    if not name:
        # Secrets Manager ARNs end in "<name>-<6 random characters>".
        tail = arn.split(":secret:", 1)[-1]
        if len(tail) < 8 or tail[-7] != "-":
            raise Unresolvable(f"cannot derive the secret name from {arn}")
        name = tail[:-7]
    body.append(("name", name))
    desc = ctx.r("Description", None)
    if desc:
        body.append(("description", desc))
    kms = ctx.r("KmsKeyId", None)
    if kms:
        body.append(("kms_key_id", kms))
    for rep in ctx.r("ReplicaRegions", []) or []:
        blk: list = [("region", rep["Region"])]
        if rep.get("KmsKeyId"):
            blk.append(("kms_key_id", rep["KmsKeyId"]))
        body.append(("replica", Block(blk)))
    _add_tags(ctx, body)
    for which in ("GenerateSecretString", "SecretString"):
        if ctx.has(which):
            spec.notes.append(
                f"{which} is not emitted: the value stays in Secrets Manager. Only the secret "
                "resource is imported, never an aws_secretsmanager_secret_version, so Terraform "
                "never reads the value (secrets contract, PLAN §2.2)"
            )
    spec.notes.append(
        "recovery_window_in_days / force_overwrite_replica_secret are not read back on import; "
        "the first plan may show a state-only update of their defaults"
    )
    return spec


@mapper("AWS::SecretsManager::SecretTargetAttachment")
def secret_target_attachment(ctx: Ctx) -> NotImported:
    return NotImported(
        MANUAL_CLEANUP,
        "SecretTargetAttachment has no Terraform resource: it only wrote the DB endpoint into "
        "the secret. Retained by the patch, then listed for manual cleanup (PLAN §13.8)",
    )


@mapper("AWS::SecretsManager::RotationSchedule")
def secret_rotation(ctx: Ctx) -> TfSpec:
    _only(
        ctx,
        {"SecretId", "RotationLambdaARN", "HostedRotationLambda", "RotationRules",
         "RotateImmediatelyOnUpdate"},
    )  # fmt: skip
    secret = ctx.r("SecretId")
    if not str(secret).startswith("arn:"):
        raise Unresolvable(f"rotation SecretId {secret!r} is not an ARN")
    spec = TfSpec("aws_secretsmanager_secret_rotation", secret, [("secret_id", secret)])
    body = spec.body
    if ctx.has("HostedRotationLambda"):
        lam = ctx.live.get("RotationLambdaARN")
        if not lam:
            raise Unresolvable("HostedRotationLambda: live RotationLambdaARN was not read")
        spec.notes.append(
            "the hosted rotation Lambda is created by the AWS::SecretsManager transform's nested "
            "application; it is not imported here and is owned outside this resource"
        )
    else:
        lam = ctx.r("RotationLambdaARN", None)
    if lam:
        body.append(("rotation_lambda_arn", lam))
    rules = ctx.r("RotationRules", None) or {}
    blk: list = []
    if rules.get("AutomaticallyAfterDays") is not None:
        blk.append(("automatically_after_days", int(rules["AutomaticallyAfterDays"])))
    if rules.get("Duration"):
        blk.append(("duration", rules["Duration"]))
    if rules.get("ScheduleExpression"):
        blk.append(("schedule_expression", rules["ScheduleExpression"]))
    if not blk:
        raise Unresolvable("RotationRules has no schedule")
    body.append(("rotation_rules", Block(blk)))
    spec.notes.append(
        "rotate_immediately is not read back by the provider on import (default true); the first "
        "plan shows a state-only update of it (the update path makes no API call for it alone)"
    )
    return spec


# -- SSM --------------------------------------------------------------------------------------


@mapper("AWS::SSM::Parameter")
def ssm_parameter(ctx: Ctx) -> TfSpec:
    _only(
        ctx,
        {"Name", "Type", "Value", "Description", "Tier", "AllowedPattern", "DataType", "Tags",
         "Policies"},
    )  # fmt: skip
    ptype = ctx.r("Type")
    if ptype == "SecureString":
        # CloudFormation cannot create SecureString parameters; refuse rather than import one.
        raise Unresolvable("SecureString parameters are never imported (secrets contract)")
    if ptype not in ("String", "StringList"):
        raise Unresolvable(f"unknown SSM parameter type {ptype!r}")
    if ctx.has("Policies"):
        raise Unresolvable("parameter Policies (advanced tier) are not supported")
    name = ctx.pid
    spec = TfSpec("aws_ssm_parameter", name, [("name", name), ("type", ptype)])
    body = spec.body
    body.append(("value", str(ctx.r("Value"))))
    for prop, arg in (
        ("Description", "description"),
        ("AllowedPattern", "allowed_pattern"),
        ("DataType", "data_type"),
    ):
        v = ctx.r(prop, None)
        if v:
            body.append((arg, v))
    tier = _pick(ctx, spec, "Tier", "Tier")
    if tier and tier != "Intelligent-Tiering":
        body.append(("tier", tier))
    _add_tags(ctx, body)
    spec.notes.append(
        "value is the template's literal; ecsodus does not read parameter values, so a value "
        "changed out of band shows as an update"
    )
    return spec


# -- KMS --------------------------------------------------------------------------------------


@mapper("AWS::KMS::Key")
def kms_key(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "Description", "KeyPolicy", "KeyUsage", "KeySpec", "EnableKeyRotation",
        "RotationPeriodInDays", "Enabled", "MultiRegion", "PendingWindowInDays", "Tags",
        "BypassPolicyLockoutSafetyCheck", "Origin",
    })  # fmt: skip
    if ctx.r("Origin", "AWS_KMS") != "AWS_KMS":
        raise Unresolvable("external/custom key stores are not supported")
    key_id = ctx.pid
    spec = TfSpec("aws_kms_key", key_id, [], stateful=True)
    body = spec.body
    desc = _pick(ctx, spec, "Description", "Description")
    body.append(("description", desc or ""))
    usage = ctx.r("KeyUsage", None)
    if usage:
        body.append(("key_usage", usage))
    keyspec = ctx.r("KeySpec", None)
    if keyspec:
        body.append(("customer_master_key_spec", keyspec))
    rotation = _pick(ctx, spec, "KeyRotationEnabled", "EnableKeyRotation")
    if rotation is not None:
        body.append(("enable_key_rotation", _bool(rotation)))
    period = ctx.r("RotationPeriodInDays", None)
    if period is not None:
        body.append(("rotation_period_in_days", int(period)))
    enabled = ctx.r("Enabled", None)
    if enabled is not None:
        body.append(("is_enabled", _bool(enabled)))
    if ctx.r("MultiRegion", False):
        body.append(("multi_region", True))
    window = ctx.r("PendingWindowInDays", None)
    if window is not None:
        body.append(("deletion_window_in_days", int(window)))
    # The key policy as deployed (GetKeyPolicy, recorded by sources/live.py as "Policy"); the
    # template form is a fallback.
    live_policy = ctx.live.get("Policy")
    if live_policy is not None:
        body.append(("policy", _json_doc(live_policy)))
    elif ctx.has("KeyPolicy"):
        body.append(("policy", _json_doc(ctx.r("KeyPolicy"))))
        spec.notes.append("key policy taken from the template: live KeyPolicy was not read")
    _add_tags(ctx, body)
    return spec


@mapper("AWS::KMS::Alias")
def kms_alias(ctx: Ctx) -> TfSpec:
    _only(ctx, {"AliasName", "TargetKeyId"})
    name = ctx.r("AliasName")
    body: list = [("name", name), ("target_key_id", ctx.r("TargetKeyId"))]
    return TfSpec("aws_kms_alias", name, body)


# -- ECR --------------------------------------------------------------------------------------


@mapper("AWS::ECR::Repository")
def ecr_repository(ctx: Ctx) -> TfSpec:
    _only(ctx, {
        "RepositoryName", "ImageTagMutability", "ImageScanningConfiguration",
        "EncryptionConfiguration", "RepositoryPolicyText", "LifecyclePolicy", "Tags",
        "EmptyOnDelete",
    })  # fmt: skip
    name = ctx.pid
    spec = TfSpec("aws_ecr_repository", name, [("name", name)], stateful=True)
    body = spec.body
    mut = _pick(ctx, spec, "ImageTagMutability", "ImageTagMutability")
    if mut:
        body.append(("image_tag_mutability", mut))
    scan = ctx.r("ImageScanningConfiguration", None)
    if scan and "ScanOnPush" in scan:
        scan_body = [("scan_on_push", _bool(scan["ScanOnPush"]))]
        body.append(("image_scanning_configuration", Block(scan_body)))
    enc = ctx.r("EncryptionConfiguration", None)
    if enc:
        blk: list = [("encryption_type", enc.get("EncryptionType", "AES256"))]
        if enc.get("KmsKey"):
            blk.append(("kms_key", enc["KmsKey"]))
        body.append(("encryption_configuration", Block(blk)))
    _add_tags(ctx, body)
    subs = []
    if ctx.has("RepositoryPolicyText"):
        subs.append(f'aws_ecr_repository_policy (import id "{name}")')
    if ctx.has("LifecyclePolicy"):
        subs.append(f'aws_ecr_lifecycle_policy (import id "{name}")')
    if subs:
        spec.fidelity = "partial"
        spec.notes.append(
            "repository policies are separate resources and are not generated in v0.1: "
            + "; ".join(subs)
        )
    if ctx.has("EmptyOnDelete"):
        spec.notes.append("EmptyOnDelete is delete-time behaviour; force_delete is not emitted")
    return spec
