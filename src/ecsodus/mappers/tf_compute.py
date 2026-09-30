"""Terraform mappers: compute family (ECS, load balancing, autoscaling, logs, discovery).

Reference examples for the mapper contract (see tfmap.py):

* read exact values: resolved template properties via ``ctx.r(...)``, and values the template
  cannot express (custom-resource outputs, AZs, generated names) from ``ctx.live``;
* raise ``Unresolvable`` rather than guess; the resource becomes ``blocked``;
* set ``stateful=True`` for anything whose loss loses data (adds ``prevent_destroy``).

Live keys are AWS API response field names, stored in ``inventory.live[<physical id>]`` by the
inventory step. Each mapper's docstring lists the keys it requires; a missing required key
raises ``Unresolvable``.

Import ID formats were checked against the provider docs
(github.com/hashicorp/terraform-provider-aws/blob/main/website/docs/r/<name>.html.markdown).
"""

from __future__ import annotations

from typing import Any

from ecsodus.emit.hcl import Block, Raw, value
from ecsodus.mappers.resolve import Unresolvable
from ecsodus.mappers.tfmap import MANUAL_CLEANUP, Ctx, NotImported, TfSpec, _live_tags, mapper

# -- shared helpers -------------------------------------------------------------------------


def _need(ctx: Ctx, key: str) -> Any:
    """A required live value (AWS API field name) for this resource."""
    live = ctx.live
    if key not in live:
        raise Unresolvable(f"live value {key} not in inventory for {ctx.resource.logical_id}")
    return live[key]


def _int(v: Any) -> int:
    if isinstance(v, bool):
        raise Unresolvable(f"expected an integer, got {v!r}")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    raise Unresolvable(f"expected an integer, got {v!r}")


def _num(v: Any) -> int | float:
    if isinstance(v, bool):
        raise Unresolvable(f"expected a number, got {v!r}")
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v))
    except ValueError as exc:
        raise Unresolvable(f"expected a number, got {v!r}") from exc
    return int(f) if f.is_integer() else f


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    raise Unresolvable(f"expected a boolean, got {v!r}")


def _only(ctx: Ctx, allowed: set[str]) -> None:
    """Fail closed on template properties this mapper does not translate."""
    extra = sorted(k for k in ctx.props if k not in allowed)
    if extra:
        raise Unresolvable(f"unsupported properties: {', '.join(extra)}")


def _json(doc: Any) -> Raw:
    """``jsonencode(<doc>)``: exact JSON, written as an HCL object for readability."""
    return Raw(f"jsonencode({value(doc, 1)})")


def _add_tags(ctx: Ctx, body: list, key: str = "Tags") -> None:
    tags = ctx.tags(key)
    if tags:
        body.append(("tags", tags))


def _one(items: Any, what: str) -> str:
    if not isinstance(items, list) or len(items) != 1:
        raise Unresolvable(f"{what}: expected exactly one entry, got {items!r}")
    return str(items[0])


def _lifecycle_ignore(*attrs: str) -> tuple[str, Block]:
    return ("lifecycle", Block([("ignore_changes", Raw(f"[{', '.join(attrs)}]"))]))


# -- Lambda (custom-resource handlers) ------------------------------------------------------


@mapper("AWS::Lambda::Function", "AWS::Lambda::Permission")
def lambda_handler(ctx: Ctx) -> NotImported:
    """Every Lambda in a Copilot stack is a custom-resource handler (PLAN §2.2)."""
    return NotImported(
        MANUAL_CLEANUP,
        "Copilot custom-resource handler: retained by the patch, deleted manually after teardown",
    )


# -- logs, cluster --------------------------------------------------------------------------


@mapper("AWS::Logs::LogGroup")
def log_group(ctx: Ctx) -> TfSpec:
    _only(ctx, {"LogGroupName", "RetentionInDays", "KmsKeyId", "Tags"})
    body: list = [("name", ctx.pid)]
    retention = ctx.r("RetentionInDays", None)
    if retention is not None:
        body.append(("retention_in_days", int(retention)))
    kms = ctx.r("KmsKeyId", None)
    if kms:
        body.append(("kms_key_id", kms))
    tags = ctx.tags()
    if tags:
        body.append(("tags", tags))
    return TfSpec("aws_cloudwatch_log_group", ctx.pid, body)


@mapper("AWS::Logs::ResourcePolicy")
def log_resource_policy(ctx: Ctx) -> TfSpec:
    """aws_cloudwatch_log_resource_policy, import id = policy name (the physical id).

    Every Copilot env stack has one (``LogResourcePolicy``). No live keys. Resource-scoped
    policies (``ResourceArn``) are refused by the allowlist.
    """
    _only(ctx, {"PolicyName", "PolicyDocument"})
    name = ctx.r("PolicyName")
    if name != ctx.pid:
        raise Unresolvable(f"PolicyName {name} != physical id {ctx.pid}")
    doc = ctx.r("PolicyDocument")
    body: list = [
        ("policy_name", name),
        ("policy_document", doc if isinstance(doc, str) else _json(doc)),
    ]
    return TfSpec("aws_cloudwatch_log_resource_policy", name, body)


_EXEC_CMD_KEYS = {"KmsKeyId", "Logging", "LogConfiguration"}
_EXEC_LOG_KEYS = {
    "CloudWatchEncryptionEnabled": ("cloud_watch_encryption_enabled", "bool"),
    "CloudWatchLogGroupName": ("cloud_watch_log_group_name", "str"),
    "S3BucketName": ("s3_bucket_name", "str"),
    "S3EncryptionEnabled": ("s3_bucket_encryption_enabled", "bool"),
    "S3KeyPrefix": ("s3_key_prefix", "str"),
}
_MANAGED_STORAGE_KEYS = {
    "KmsKeyId": "kms_key_id",
    "FargateEphemeralStorageKmsKeyId": "fargate_ephemeral_storage_kms_key_id",
}


def _cluster_configuration(cfg: dict[str, Any]) -> Block:
    """ClusterConfiguration -> the ``configuration`` block (every key mapped or refused)."""
    extra = set(cfg) - {"ExecuteCommandConfiguration", "ManagedStorageConfiguration"}
    if extra:
        raise Unresolvable(f"cluster Configuration keys not supported: {sorted(extra)}")
    body: list = []
    ecc = cfg.get("ExecuteCommandConfiguration")
    if ecc:
        extra = set(ecc) - _EXEC_CMD_KEYS
        if extra:
            raise Unresolvable(f"ExecuteCommandConfiguration keys not supported: {sorted(extra)}")
        eb: list = []
        if ecc.get("KmsKeyId"):
            eb.append(("kms_key_id", ecc["KmsKeyId"]))
        if ecc.get("Logging"):
            eb.append(("logging", ecc["Logging"]))
        logc = ecc.get("LogConfiguration")
        if logc:
            extra = set(logc) - set(_EXEC_LOG_KEYS)
            if extra:
                raise Unresolvable(f"LogConfiguration keys not supported: {sorted(extra)}")
            lb_: list = [
                (arg, _attr_value(logc[k], kind))
                for k, (arg, kind) in _EXEC_LOG_KEYS.items()
                if k in logc
            ]
            eb.append(("log_configuration", Block(lb_)))
        body.append(("execute_command_configuration", Block(eb)))
    msc = cfg.get("ManagedStorageConfiguration")
    if msc:
        extra = set(msc) - set(_MANAGED_STORAGE_KEYS)
        if extra:
            raise Unresolvable(f"ManagedStorageConfiguration keys not supported: {sorted(extra)}")
        mb: list = [(arg, msc[k]) for k, arg in _MANAGED_STORAGE_KEYS.items() if msc.get(k)]
        body.append(("managed_storage_configuration", Block(mb)))
    return Block(body)


@mapper("AWS::ECS::Cluster")
def ecs_cluster(ctx: Ctx) -> TfSpec:
    """aws_ecs_cluster, import id = cluster name (the physical id). No live keys.

    ``Configuration`` becomes the ``configuration`` block: it is not computed, so leaving it out
    would make the first plan remove the live execute-command settings. Capacity providers are a
    separate resource (noted, fidelity partial); ``ServiceConnectDefaults`` is refused.
    """
    _only(
        ctx,
        {"ClusterName", "ClusterSettings", "CapacityProviders", "DefaultCapacityProviderStrategy",
         "Configuration", "Tags"},
    )  # fmt: skip
    name = ctx.r("ClusterName", ctx.pid)
    if name != ctx.pid:
        raise Unresolvable(f"ClusterName {name} != physical id {ctx.pid}")
    body: list = [("name", ctx.pid)]
    for setting in ctx.r("ClusterSettings", []):
        body.append(("setting", Block([("name", setting["Name"]), ("value", setting["Value"])])))
    cfg = ctx.r("Configuration", None)
    if cfg:
        body.append(("configuration", _cluster_configuration(cfg)))
    tags = ctx.tags()
    if tags:
        body.append(("tags", tags))
    spec = TfSpec("aws_ecs_cluster", ctx.pid, body)
    if ctx.r("CapacityProviders", None) or ctx.r("DefaultCapacityProviderStrategy", None):
        spec.notes.append(
            "capacity providers are a separate resource (aws_ecs_cluster_capacity_providers, "
            f'import id "{ctx.pid}"); not generated in v0.1'
        )
        spec.fidelity = "partial"
    return spec


# -- ECS task definition --------------------------------------------------------------------

# CloudFormation -> ECS API spellings that are not a plain lower-casing of the first letter.
_RENAME = {
    "EFSVolumeConfiguration": "efsVolumeConfiguration",
    "FilesystemId": "fileSystemId",
    "IAM": "iam",
    "SizeInGiB": "sizeInGiB",
}
# Maps whose keys are user data and must not be re-cased; values are strings in the ECS API.
_FREEFORM = {"Options", "DockerLabels", "Labels", "DriverOpts"}
# Keys the converter knows (container definitions and the task-level blocks it converts).
_KNOWN = {
    # container definition
    "Name", "Image", "Essential", "Cpu", "Memory", "MemoryReservation", "Command", "EntryPoint",
    "WorkingDirectory", "User", "Environment", "EnvironmentFiles", "Secrets", "LogConfiguration",
    "MountPoints", "PortMappings", "HealthCheck", "DependsOn", "DockerLabels",
    "FirelensConfiguration", "Ulimits", "StopTimeout", "StartTimeout", "ReadonlyRootFilesystem",
    "Privileged", "VolumesFrom", "Interactive", "PseudoTerminal", "Hostname", "DnsServers",
    "DnsSearchDomains", "ExtraHosts", "DisableNetworking",
    # nested
    "Value", "Type", "ValueFrom", "LogDriver", "Options", "SecretOptions", "ContainerPath",
    "SourceVolume", "ReadOnly", "ContainerPort", "HostPort", "Protocol", "AppProtocol",
    "ContainerPortRange", "Interval", "Retries", "StartPeriod", "Timeout", "Condition",
    "ContainerName", "SoftLimit", "HardLimit", "SourceContainer", "IpAddress",
    # volumes / ephemeral storage / runtime platform
    "Host", "SourcePath", "EFSVolumeConfiguration", "FilesystemId", "RootDirectory",
    "TransitEncryption", "TransitEncryptionPort", "AuthorizationConfig", "AccessPointId", "IAM",
    "SizeInGiB", "CpuArchitecture", "OperatingSystemFamily",
}  # fmt: skip
_INTS = {
    "Cpu", "Memory", "MemoryReservation", "ContainerPort", "HostPort", "Interval", "Retries",
    "StartPeriod", "Timeout", "StopTimeout", "StartTimeout", "SoftLimit", "HardLimit",
    "TransitEncryptionPort", "SizeInGiB",
}  # fmt: skip
_BOOLS = {
    "Essential", "ReadOnly", "ReadonlyRootFilesystem", "Privileged", "Interactive",
    "PseudoTerminal", "DisableNetworking",
}  # fmt: skip


def _api_key(key: str) -> str:
    return _RENAME.get(key) or key[:1].lower() + key[1:]


def _freeform(v: Any) -> dict[str, str]:
    if not isinstance(v, dict):
        raise Unresolvable(f"expected a map, got {v!r}")
    out = {}
    for k, x in v.items():
        if isinstance(x, bool):
            out[str(k)] = "true" if x else "false"
        elif isinstance(x, (str, int, float)):
            out[str(k)] = str(x)
        else:
            raise Unresolvable(f"non-scalar option value {x!r}")
    return out


def cfn_to_ecs_api(v: Any) -> Any:
    """Convert resolved CloudFormation ECS properties (PascalCase) to ECS API camelCase.

    Only keys in a known table are converted; any other key raises ``Unresolvable``.
    """
    if isinstance(v, list):
        return [cfn_to_ecs_api(x) for x in v]
    if not isinstance(v, dict):
        return v
    out: dict[str, Any] = {}
    for k, x in v.items():
        if k not in _KNOWN:
            raise Unresolvable(f"task definition property {k} not converted exactly")
        if k in _FREEFORM:
            out[_api_key(k)] = _freeform(x)
        elif k in _INTS:
            out[_api_key(k)] = _int(x)
        elif k in _BOOLS:
            out[_api_key(k)] = _bool(x)
        else:
            out[_api_key(k)] = cfn_to_ecs_api(x)
    return out


_EFS_KEYS = {
    "fileSystemId", "rootDirectory", "transitEncryption", "transitEncryptionPort",
    "authorizationConfig",
}  # fmt: skip


def _efs_block(cfg: dict[str, Any]) -> Block:
    extra = set(cfg) - _EFS_KEYS
    if extra:
        raise Unresolvable(f"EFS volume keys not supported: {sorted(extra)}")
    body: list = [("file_system_id", cfg["fileSystemId"])]
    if "rootDirectory" in cfg:
        body.append(("root_directory", cfg["rootDirectory"]))
    if "transitEncryption" in cfg:
        body.append(("transit_encryption", cfg["transitEncryption"]))
    if "transitEncryptionPort" in cfg:
        body.append(("transit_encryption_port", _int(cfg["transitEncryptionPort"])))
    auth = cfg.get("authorizationConfig")
    if auth:
        a: list = []
        if "accessPointId" in auth:
            a.append(("access_point_id", auth["accessPointId"]))
        if "iam" in auth:
            a.append(("iam", auth["iam"]))
        body.append(("authorization_config", Block(a)))
    return Block(body)


def _volume_block(vol: dict[str, Any]) -> Block:
    body: list = [("name", vol["name"])]
    for k, x in vol.items():
        if k == "name":
            continue
        if k == "host":
            if x and x.get("sourcePath"):
                body.append(("host_path", x["sourcePath"]))
        elif k == "efsVolumeConfiguration":
            body.append(("efs_volume_configuration", _efs_block(x)))
        elif k == "configuredAtLaunch":
            body.append(("configure_at_launch", _bool(x)))
        else:
            raise Unresolvable(f"task definition volume type {k} not supported in v0.1")
    return Block(body)


_TD_PROPS = {
    "Family", "NetworkMode", "RequiresCompatibilities", "Cpu", "Memory", "ExecutionRoleArn",
    "TaskRoleArn", "ContainerDefinitions", "Volumes", "EphemeralStorage", "RuntimePlatform",
    "PidMode", "IpcMode", "Tags",
}  # fmt: skip


@mapper("AWS::ECS::TaskDefinition")
def ecs_task_definition(ctx: Ctx) -> TfSpec:
    """aws_ecs_task_definition, imported by revision ARN (the physical id).

    Live keys (DescribeTaskDefinition ``taskDefinition``): ``containerDefinitions`` is strongly
    preferred; without it the template's ContainerDefinitions are converted to ECS API
    camelCase and the result is marked partial (the API adds defaults the template omits).
    Optional, used when present: ``family``, ``cpu``, ``memory``, ``networkMode``,
    ``requiresCompatibilities``, ``executionRoleArn``, ``taskRoleArn``, ``volumes``,
    ``ephemeralStorage``, ``runtimePlatform``, ``pidMode``, ``ipcMode``.
    """
    _only(ctx, _TD_PROPS)
    live = ctx.live
    notes: list[str] = []
    fidelity = "full"

    def pick(api: str, cfn: str) -> Any:
        return live[api] if api in live else ctx.r(cfn, None)

    if "containerDefinitions" in live:
        defs = live["containerDefinitions"]
    else:
        defs = cfn_to_ecs_api(ctx.r("ContainerDefinitions"))
        fidelity = "partial"
        notes.append(
            "container_definitions converted from the template; ECS API defaults may differ. "
            "Re-run inventory with task-definition live reads for an exact value."
        )

    family = pick("family", "Family")
    if not family:
        raise Unresolvable("task definition family unknown")
    body: list = [("family", family), ("container_definitions", _json(defs))]
    for api, cfn, tf in (
        ("cpu", "Cpu", "cpu"),
        ("memory", "Memory", "memory"),
        ("networkMode", "NetworkMode", "network_mode"),
        ("executionRoleArn", "ExecutionRoleArn", "execution_role_arn"),
        ("taskRoleArn", "TaskRoleArn", "task_role_arn"),
        ("pidMode", "PidMode", "pid_mode"),
        ("ipcMode", "IpcMode", "ipc_mode"),
    ):
        v = pick(api, cfn)
        if v is not None and v != "":
            body.append((tf, str(v)))
    compat = pick("requiresCompatibilities", "RequiresCompatibilities")
    if compat:
        body.append(("requires_compatibilities", list(compat)))

    volumes = live["volumes"] if "volumes" in live else cfn_to_ecs_api(ctx.r("Volumes", []))
    for vol in volumes:
        body.append(("volume", _volume_block(vol)))

    eph = live.get("ephemeralStorage") or cfn_to_ecs_api(ctx.r("EphemeralStorage", None))
    if eph:
        body.append(("ephemeral_storage", Block([("size_in_gib", _int(eph["sizeInGiB"]))])))

    rp = live.get("runtimePlatform") or cfn_to_ecs_api(ctx.r("RuntimePlatform", None))
    if rp:
        rpb: list = []
        if rp.get("operatingSystemFamily"):
            rpb.append(("operating_system_family", rp["operatingSystemFamily"]))
        if rp.get("cpuArchitecture"):
            rpb.append(("cpu_architecture", rp["cpuArchitecture"]))
        body.append(("runtime_platform", Block(rpb)))

    _add_tags(ctx, body)
    return TfSpec("aws_ecs_task_definition", ctx.pid, body, fidelity=fidelity, notes=notes)


# -- ECS service ----------------------------------------------------------------------------

_SVC_PROPS = {
    "ServiceName", "Cluster", "TaskDefinition", "DesiredCount", "DeploymentConfiguration",
    "PropagateTags", "LaunchType", "CapacityProviderStrategy", "PlatformVersion",
    "ServiceConnectConfiguration", "NetworkConfiguration", "HealthCheckGracePeriodSeconds",
    "LoadBalancers", "ServiceRegistries", "EnableExecuteCommand", "EnableECSManagedTags",
    "Tags",
}  # fmt: skip
_DEPLOY_KEYS = {"MaximumPercent", "MinimumHealthyPercent", "DeploymentCircuitBreaker", "Alarms"}


def _service_names(ctx: Ctx) -> tuple[str, str]:
    """(cluster name, service name) from the service ARN, cross-checked with the template."""
    arn = ctx.pid
    parts = arn.split(":", 5)
    if len(parts) != 6 or not parts[5].startswith("service/"):
        raise Unresolvable(f"service physical id {arn!r} is not a service ARN")
    path = parts[5].split("/")
    tmpl_cluster = str(ctx.r("Cluster")).rsplit("/", 1)[-1]
    if len(path) == 3:
        cluster, name = path[1], path[2]
        if cluster != tmpl_cluster:
            raise Unresolvable(f"service ARN cluster {cluster} != template cluster {tmpl_cluster}")
    elif len(path) == 2:  # old ARN format without the cluster
        cluster, name = tmpl_cluster, path[1]
    else:
        raise Unresolvable(f"unrecognised service ARN {arn!r}")
    return cluster, name


@mapper("AWS::ECS::Service")
def ecs_service(ctx: Ctx) -> TfSpec:
    """aws_ecs_service, import id ``<cluster-name>/<service-name>``.

    ``task_definition`` is the literal revision ARN and the service ignores changes to
    ``task_definition`` and ``desired_count`` (PLAN §2.4, §13.7).

    Live keys (DescribeServices): ``desiredCount`` (required). Optional: ``taskDefinition``
    (the current revision, preferred over the template), ``clusterArn``,
    ``availabilityZoneRebalancing``.
    """
    _only(ctx, _SVC_PROPS)
    sc = ctx.r("ServiceConnectConfiguration", None)
    if sc and _bool(sc.get("Enabled", False)):
        raise Unresolvable("Service Connect is blocked in v0.1")

    cluster, name = _service_names(ctx)
    svc_name = ctx.r("ServiceName", None)
    if svc_name is not None and svc_name != name:
        raise Unresolvable(f"ServiceName {svc_name} != service ARN name {name}")
    cluster_arn = ctx.live.get("clusterArn") or (
        f"arn:aws:ecs:{ctx.inv.region}:{ctx.inv.account}:cluster/{cluster}"
    )
    task_def = str(ctx.live.get("taskDefinition") or ctx.r("TaskDefinition"))
    if not task_def.startswith("arn:"):
        raise Unresolvable(f"task definition {task_def!r} is not a revision ARN")
    desired = _int(_need(ctx, "desiredCount"))

    body: list = [
        ("name", name),
        ("cluster", cluster_arn),
        ("task_definition", task_def),
        ("desired_count", desired),
    ]
    launch = ctx.r("LaunchType", None)
    if launch:
        body.append(("launch_type", launch))
    for cps in ctx.r("CapacityProviderStrategy", []):
        b: list = [("capacity_provider", cps["CapacityProvider"])]
        if "Weight" in cps:
            b.append(("weight", _int(cps["Weight"])))
        if "Base" in cps:
            b.append(("base", _int(cps["Base"])))
        body.append(("capacity_provider_strategy", Block(b)))
    pv = ctx.r("PlatformVersion", None)
    if pv:
        body.append(("platform_version", pv))
    if ctx.has("PropagateTags"):
        body.append(("propagate_tags", ctx.r("PropagateTags")))
    if ctx.has("EnableECSManagedTags"):
        body.append(("enable_ecs_managed_tags", _bool(ctx.r("EnableECSManagedTags"))))
    if ctx.has("EnableExecuteCommand"):
        body.append(("enable_execute_command", _bool(ctx.r("EnableExecuteCommand"))))
    if ctx.has("HealthCheckGracePeriodSeconds"):
        grace = _int(ctx.r("HealthCheckGracePeriodSeconds"))
        body.append(("health_check_grace_period_seconds", grace))
    if "availabilityZoneRebalancing" in ctx.live:
        body.append(("availability_zone_rebalancing", ctx.live["availabilityZoneRebalancing"]))

    dc = ctx.r("DeploymentConfiguration", None) or {}
    extra = set(dc) - _DEPLOY_KEYS
    if extra:
        raise Unresolvable(f"DeploymentConfiguration keys not supported: {sorted(extra)}")
    if "MaximumPercent" in dc:
        body.append(("deployment_maximum_percent", _int(dc["MaximumPercent"])))
    if "MinimumHealthyPercent" in dc:
        body.append(("deployment_minimum_healthy_percent", _int(dc["MinimumHealthyPercent"])))
    cb = dc.get("DeploymentCircuitBreaker")
    if cb:
        cbb = Block([("enable", _bool(cb["Enable"])), ("rollback", _bool(cb["Rollback"]))])
        body.append(("deployment_circuit_breaker", cbb))
    alarms = dc.get("Alarms")
    if alarms:
        ab = Block(
            [
                ("alarm_names", list(alarms.get("AlarmNames", []))),
                ("enable", _bool(alarms["Enable"])),
                ("rollback", _bool(alarms["Rollback"])),
            ]
        )
        body.append(("alarms", ab))

    net = ctx.r("NetworkConfiguration", None)
    if net:
        aws = net.get("AwsvpcConfiguration")
        if not aws or set(net) != {"AwsvpcConfiguration"}:
            raise Unresolvable("only awsvpc network configuration is supported")
        nb: list = [("subnets", list(aws.get("Subnets", [])))]
        if aws.get("SecurityGroups"):
            nb.append(("security_groups", list(aws["SecurityGroups"])))
        if "AssignPublicIp" in aws:
            if aws["AssignPublicIp"] not in ("ENABLED", "DISABLED"):
                raise Unresolvable(f"AssignPublicIp {aws['AssignPublicIp']!r}")
            nb.append(("assign_public_ip", aws["AssignPublicIp"] == "ENABLED"))
        body.append(("network_configuration", Block(nb)))

    for lb in ctx.r("LoadBalancers", []):
        if "TargetGroupArn" not in lb:
            raise Unresolvable("classic load balancer attachments are not supported")
        lbb = Block(
            [
                ("target_group_arn", lb["TargetGroupArn"]),
                ("container_name", lb["ContainerName"]),
                ("container_port", _int(lb["ContainerPort"])),
            ]
        )
        body.append(("load_balancer", lbb))
    for reg in ctx.r("ServiceRegistries", []):
        rb: list = [("registry_arn", reg["RegistryArn"])]
        if "Port" in reg:
            rb.append(("port", _int(reg["Port"])))
        if "ContainerName" in reg:
            rb.append(("container_name", reg["ContainerName"]))
        if "ContainerPort" in reg:
            rb.append(("container_port", _int(reg["ContainerPort"])))
        body.append(("service_registries", Block(rb)))

    _add_tags(ctx, body)
    body.append(_lifecycle_ignore("task_definition", "desired_count"))
    spec = TfSpec("aws_ecs_service", f"{cluster}/{name}", body)
    if sc is not None:
        spec.notes.append("ServiceConnectConfiguration {Enabled: false} is not emitted")
    return spec


# -- load balancing -------------------------------------------------------------------------

# DescribeLoadBalancerAttributes key -> (aws_lb argument, kind).
_LB_ATTRS: dict[str, tuple[str, str]] = {
    "idle_timeout.timeout_seconds": ("idle_timeout", "int"),
    "routing.http2.enabled": ("enable_http2", "bool"),
    "routing.http.drop_invalid_header_fields.enabled": ("drop_invalid_header_fields", "bool"),
    "routing.http.desync_mitigation_mode": ("desync_mitigation_mode", "str"),
    "routing.http.preserve_host_header.enabled": ("preserve_host_header", "bool"),
    "routing.http.x_amzn_tls_version_and_cipher_suite.enabled": (
        "enable_tls_version_and_cipher_suite_headers",
        "bool",
    ),
    "routing.http.xff_client_port.enabled": ("enable_xff_client_port", "bool"),
    "routing.http.xff_header_processing.mode": ("xff_header_processing_mode", "str"),
    "waf.fail_open.enabled": ("enable_waf_fail_open", "bool"),
    "client_keep_alive.seconds": ("client_keep_alive", "int"),
    "zonal_shift.config.enabled": ("enable_zonal_shift", "bool"),
    "load_balancing.cross_zone.enabled": ("enable_cross_zone_load_balancing", "bool"),
    "dns_record.client_routing_policy": ("dns_record_client_routing_policy", "str"),
}
# Log blocks: attribute prefix -> aws_lb block. Emitted only when enabled on live (the
# provider suppresses a missing block that is disabled).
_LB_LOGS = {
    "access_logs.s3": "access_logs",
    "connection_logs.s3": "connection_logs",
    "health_check_logs.s3": "health_check_logs",
}


def _attr_value(raw: Any, kind: str) -> Any:
    if kind == "int":
        return _int(raw)
    if kind == "bool":
        return _bool(raw)
    return str(raw)


def _attrs_map(attrs: Any) -> dict[str, str]:
    if isinstance(attrs, dict):
        return {str(k): str(v) for k, v in attrs.items()}
    return {str(a["Key"]): str(a["Value"]) for a in attrs}


@mapper("AWS::ElasticLoadBalancingV2::LoadBalancer")
def lb(ctx: Ctx) -> TfSpec:
    """aws_lb, imported by ARN. Never recreatable (DNS name and ARN are referenced widely).

    Live keys (DescribeLoadBalancers / DescribeLoadBalancerAttributes): ``LoadBalancerName``
    and ``Attributes`` (list of ``{Key, Value}``) are required. Optional cross-checks:
    ``Scheme``, ``Type``; optional ``IpAddressType``.
    """
    _only(
        ctx,
        {"Name", "Scheme", "Type", "Subnets", "SecurityGroups", "LoadBalancerAttributes",
         "IpAddressType", "Tags"},
    )  # fmt: skip
    live_name = _need(ctx, "LoadBalancerName")
    attrs = _attrs_map(_need(ctx, "Attributes"))
    tmpl_name = ctx.r("Name", None)
    if tmpl_name and tmpl_name != live_name:
        raise Unresolvable(f"load balancer name {tmpl_name} != live {live_name}")
    scheme = ctx.r("Scheme", "internet-facing")
    lb_type = ctx.r("Type", "application")
    if lb_type != "application":
        raise Unresolvable(f"load balancer type {lb_type} is blocked in v0.1")
    for key, tmpl in (("Scheme", scheme), ("Type", lb_type)):
        if key in ctx.live and ctx.live[key] != tmpl:
            raise Unresolvable(f"{key} {tmpl} != live {ctx.live[key]}")

    body: list = [
        ("name", live_name),
        ("internal", scheme == "internal"),
        ("load_balancer_type", lb_type),
        ("subnets", list(ctx.r("Subnets"))),
    ]
    sgs = ctx.r("SecurityGroups", None)
    if sgs:
        body.append(("security_groups", list(sgs)))
    ip_type = ctx.live.get("IpAddressType") or ctx.r("IpAddressType", None)
    if ip_type:
        body.append(("ip_address_type", ip_type))

    notes = ["never recreatable: a replacement changes the DNS name every alias points at"]
    fidelity = "full"
    handled: set[str] = set()
    for key, (arg, kind) in _LB_ATTRS.items():
        if key in attrs:
            handled.add(key)
            body.append((arg, _attr_value(attrs[key], kind)))
    if "deletion_protection.enabled" in attrs:
        handled.add("deletion_protection.enabled")
        if _bool(attrs["deletion_protection.enabled"]):  # only where already on (PLAN §2.4)
            body.append(("enable_deletion_protection", True))
    for prefix, block in _LB_LOGS.items():
        handled |= {f"{prefix}.enabled", f"{prefix}.bucket", f"{prefix}.prefix"} & set(attrs)
        if _bool(attrs.get(f"{prefix}.enabled", "false")):
            log: list = [("bucket", attrs.get(f"{prefix}.bucket", "")), ("enabled", True)]
            if attrs.get(f"{prefix}.prefix"):
                log.append(("prefix", attrs[f"{prefix}.prefix"]))
            body.append((block, Block(log)))
    unknown = sorted(set(attrs) - handled)
    if unknown:
        fidelity = "partial"
        notes.append(f"load balancer attributes not mapped: {', '.join(unknown)}")
    _add_tags(ctx, body)
    return TfSpec("aws_lb", ctx.pid, body, fidelity=fidelity, notes=notes)


_ACTION_KEYS = {"Type", "Order", "TargetGroupArn", "RedirectConfig", "FixedResponseConfig"}
_REDIRECT_KEYS = (
    ("Host", "host"),
    ("Path", "path"),
    ("Port", "port"),
    ("Protocol", "protocol"),
    ("Query", "query"),
)


def _action_block(a: dict[str, Any]) -> Block:
    extra = set(a) - _ACTION_KEYS
    if extra:
        raise Unresolvable(f"listener action keys not supported: {sorted(extra)}")
    atype = a["Type"]
    body: list = [("type", atype)]
    if "Order" in a:
        body.append(("order", _int(a["Order"])))
    if atype == "forward":
        if "TargetGroupArn" not in a:
            raise Unresolvable("weighted forward actions are not supported in v0.1")
        body.append(("target_group_arn", a["TargetGroupArn"]))
    elif atype == "redirect":
        rc = a["RedirectConfig"]
        rb: list = [(tf, str(rc[k])) for k, tf in _REDIRECT_KEYS if k in rc]
        rb.append(("status_code", rc["StatusCode"]))
        body.append(("redirect", Block(rb)))
    elif atype == "fixed-response":
        fc = a["FixedResponseConfig"]
        fb: list = [("content_type", fc["ContentType"])]
        if "MessageBody" in fc:
            fb.append(("message_body", fc["MessageBody"]))
        if "StatusCode" in fc:
            fb.append(("status_code", str(fc["StatusCode"])))
        body.append(("fixed_response", Block(fb)))
    else:
        raise Unresolvable(f"listener action type {atype} not supported in v0.1")
    return Block(body)


@mapper("AWS::ElasticLoadBalancingV2::Listener")
def lb_listener(ctx: Ctx) -> TfSpec:
    """aws_lb_listener, imported by ARN.

    Live keys (DescribeListeners), optional: ``SslPolicy`` (AWS assigns a default when the
    template has none; the argument is computed, so it is omitted when unknown).
    """
    _only(
        ctx,
        {"LoadBalancerArn", "Port", "Protocol", "SslPolicy", "Certificates", "DefaultActions",
         "AlpnPolicy"},
    )  # fmt: skip
    body: list = [
        ("load_balancer_arn", ctx.r("LoadBalancerArn")),
        ("port", _int(ctx.r("Port"))),
        ("protocol", ctx.r("Protocol")),
    ]
    ssl = ctx.live.get("SslPolicy") or ctx.r("SslPolicy", None)
    if ssl:
        body.append(("ssl_policy", ssl))
    certs = ctx.r("Certificates", [])
    if certs:
        body.append(("certificate_arn", _one([c["CertificateArn"] for c in certs], "Certificates")))
    alpn = ctx.r("AlpnPolicy", None)
    if alpn:
        body.append(("alpn_policy", _one(alpn, "AlpnPolicy")))
    for a in ctx.r("DefaultActions"):
        body.append(("default_action", _action_block(a)))
    return TfSpec("aws_lb_listener", ctx.pid, body)


_CONDITION_CONFIGS = {
    "host-header": ("HostHeaderConfig", "host_header"),
    "path-pattern": ("PathPatternConfig", "path_pattern"),
    "source-ip": ("SourceIpConfig", "source_ip"),
    "http-request-method": ("HttpRequestMethodConfig", "http_request_method"),
}


def _condition_block(c: dict[str, Any]) -> Block:
    field = c["Field"]
    if field == "http-header":
        cfg = c["HttpHeaderConfig"]
        inner = Block(
            [("http_header_name", cfg["HttpHeaderName"]), ("values", list(cfg["Values"]))]
        )
        return Block([("http_header", inner)])
    if field == "query-string":
        pairs: list = []
        for kv in c["QueryStringConfig"]["Values"]:
            qb: list = [("key", kv["Key"])] if "Key" in kv else []
            qb.append(("value", kv["Value"]))
            pairs.append(("query_string", Block(qb)))
        return Block(pairs)
    if field not in _CONDITION_CONFIGS:
        raise Unresolvable(f"listener rule condition {field} not supported")
    cfg_key, tf = _CONDITION_CONFIGS[field]
    if cfg_key in c:
        values = c[cfg_key]["Values"]
    elif "Values" in c:
        values = c["Values"]
    else:
        raise Unresolvable(f"listener rule condition {field} has no values")
    return Block([(tf, Block([("values", list(values))]))])


def _listener_from_rule_arn(arn: str) -> str | None:
    head, sep, path = arn.partition(":listener-rule/")
    parts = path.split("/")
    if not sep or len(parts) != 5:
        return None
    return f"{head}:listener/{'/'.join(parts[:4])}"


@mapper("AWS::ElasticLoadBalancingV2::ListenerRule")
def lb_listener_rule(ctx: Ctx) -> TfSpec:
    """aws_lb_listener_rule, imported by ARN.

    Live keys (DescribeRules): ``Priority`` (required: Copilot computes it with a custom
    resource). The listener ARN comes from the template, cross-checked against the rule ARN
    (or derived from the rule ARN when the template value cannot be resolved).
    """
    _only(ctx, {"ListenerArn", "Priority", "Actions", "Conditions", "Tags"})
    derived = _listener_from_rule_arn(ctx.pid)
    try:
        listener = ctx.r("ListenerArn")
    except Unresolvable:
        if derived is None:
            raise
        listener = derived
    if derived is not None and listener != derived:
        raise Unresolvable(f"template listener {listener} != rule ARN listener {derived}")
    priority = _need(ctx, "Priority")
    if priority == "default":
        raise Unresolvable("default listener rules are part of the listener")
    body: list = [("listener_arn", listener), ("priority", _int(priority))]
    for a in ctx.r("Actions"):
        body.append(("action", _action_block(a)))
    for c in ctx.r("Conditions"):
        body.append(("condition", _condition_block(c)))
    # CloudFormation's ListenerRule has no Tags property, so stack-level tags are never
    # propagated to it: merging them in (ctx.tags()) would add tags on the first plan. Tags
    # are emitted only from a live read (or a template Tags property, should one appear).
    if ctx.has("Tags") or _live_tags(ctx.live) is not None:
        _add_tags(ctx, body)
    return TfSpec("aws_lb_listener_rule", ctx.pid, body)


@mapper("AWS::ElasticLoadBalancingV2::ListenerCertificate")
def lb_listener_certificate(ctx: Ctx) -> TfSpec:
    """aws_lb_listener_certificate, import id ``<listener-arn>_<certificate-arn>``.

    Exactly one certificate per resource (one Terraform resource per certificate).
    """
    _only(ctx, {"ListenerArn", "Certificates"})
    listener = ctx.r("ListenerArn")
    cert = _one([c["CertificateArn"] for c in ctx.r("Certificates")], "Certificates")
    body: list = [("listener_arn", listener), ("certificate_arn", cert)]
    return TfSpec("aws_lb_listener_certificate", f"{listener}_{cert}", body)


# DescribeTargetGroupAttributes key -> (aws_lb_target_group argument, kind).
_TG_ATTRS: dict[str, tuple[str, str]] = {
    "deregistration_delay.timeout_seconds": ("deregistration_delay", "str"),
    "slow_start.duration_seconds": ("slow_start", "int"),
    "load_balancing.algorithm.type": ("load_balancing_algorithm_type", "str"),
    "load_balancing.algorithm.anomaly_mitigation": ("load_balancing_anomaly_mitigation", "str"),
    "load_balancing.cross_zone.enabled": ("load_balancing_cross_zone_enabled", "str"),
    "lambda.multi_value_headers.enabled": ("lambda_multi_value_headers_enabled", "bool"),
    "preserve_client_ip.enabled": ("preserve_client_ip", "str"),
    "proxy_protocol_v2.enabled": ("proxy_protocol_v2", "bool"),
    "deregistration_delay.connection_termination.enabled": ("connection_termination", "bool"),
}
_TG_STICKY = {
    "stickiness.enabled",
    "stickiness.type",
    "stickiness.lb_cookie.duration_seconds",
    "stickiness.app_cookie.cookie_name",
    "stickiness.app_cookie.duration_seconds",
}
# Target-group health attributes the provider exposes as a block we do not generate; ignored
# only while they hold the AWS default.
_TG_DEFAULTS = {
    "target_group_health.dns_failover.minimum_healthy_targets.count": "1",
    "target_group_health.dns_failover.minimum_healthy_targets.percentage": "off",
    "target_group_health.unhealthy_state_routing.minimum_healthy_targets.count": "1",
    "target_group_health.unhealthy_state_routing.minimum_healthy_targets.percentage": "off",
}
_TG_PROPS = {
    "Name", "Port", "Protocol", "ProtocolVersion", "TargetType", "VpcId", "HealthCheckEnabled",
    "HealthCheckIntervalSeconds", "HealthCheckPath", "HealthCheckPort", "HealthCheckProtocol",
    "HealthCheckTimeoutSeconds", "HealthyThresholdCount", "UnhealthyThresholdCount", "Matcher",
    "TargetGroupAttributes", "IpAddressType", "Tags",
}  # fmt: skip


@mapper("AWS::ElasticLoadBalancingV2::TargetGroup")
def lb_target_group(ctx: Ctx) -> TfSpec:
    """aws_lb_target_group, imported by ARN.

    Live keys (DescribeTargetGroups / DescribeTargetGroupAttributes), all required:
    ``TargetGroupName``, ``Attributes`` (list of ``{Key, Value}``), and the health check
    fields ``HealthCheckEnabled``, ``HealthCheckIntervalSeconds``, ``HealthCheckPort``,
    ``HealthCheckProtocol``, ``HealthCheckTimeoutSeconds``, ``HealthyThresholdCount``,
    ``UnhealthyThresholdCount``, plus ``HealthCheckPath`` and ``Matcher`` for HTTP/HTTPS. The
    provider's health-check defaults differ from AWS's, so the template alone is not exact.
    Optional: ``ProtocolVersion``.
    """
    _only(ctx, _TG_PROPS)
    name = _need(ctx, "TargetGroupName")
    attrs = _attrs_map(_need(ctx, "Attributes"))
    tmpl_name = ctx.r("Name", None)
    if tmpl_name and tmpl_name != name:
        raise Unresolvable(f"target group name {tmpl_name} != live {name}")
    target_type = ctx.r("TargetType", "instance")
    protocol = ctx.r("Protocol", None)
    body: list = [("name", name), ("target_type", target_type)]
    if target_type != "lambda":
        body += [("port", _int(ctx.r("Port"))), ("protocol", protocol), ("vpc_id", ctx.r("VpcId"))]
    pver = ctx.live.get("ProtocolVersion") or ctx.r("ProtocolVersion", None)
    if pver:
        body.append(("protocol_version", pver))
    ipt = ctx.r("IpAddressType", None)
    if ipt:
        body.append(("ip_address_type", ipt))

    hc: list = [
        ("enabled", _bool(_need(ctx, "HealthCheckEnabled"))),
        ("interval", _int(_need(ctx, "HealthCheckIntervalSeconds"))),
        ("port", str(_need(ctx, "HealthCheckPort"))),
        ("protocol", _need(ctx, "HealthCheckProtocol")),
        ("timeout", _int(_need(ctx, "HealthCheckTimeoutSeconds"))),
        ("healthy_threshold", _int(_need(ctx, "HealthyThresholdCount"))),
        ("unhealthy_threshold", _int(_need(ctx, "UnhealthyThresholdCount"))),
    ]
    if protocol in ("HTTP", "HTTPS"):
        hc.append(("path", _need(ctx, "HealthCheckPath")))
        matcher = _need(ctx, "Matcher")
        code = matcher.get("HttpCode") or matcher.get("GrpcCode")
        if code is None:
            raise Unresolvable(f"target group matcher {matcher!r}")
        hc.append(("matcher", str(code)))
    body.append(("health_check", Block(hc)))

    notes: list[str] = []
    fidelity = "full"
    handled: set[str] = set()
    for key, (arg, kind) in _TG_ATTRS.items():
        if key in attrs:
            handled.add(key)
            body.append((arg, _attr_value(attrs[key], kind)))
    if "stickiness.type" in attrs:
        stype = attrs["stickiness.type"]
        sb: list = [("enabled", _bool(attrs.get("stickiness.enabled", "false"))), ("type", stype)]
        if stype == "lb_cookie" and "stickiness.lb_cookie.duration_seconds" in attrs:
            sb.append(("cookie_duration", _int(attrs["stickiness.lb_cookie.duration_seconds"])))
        if stype == "app_cookie":
            sb.append(("cookie_name", attrs["stickiness.app_cookie.cookie_name"]))
            sb.append(("cookie_duration", _int(attrs["stickiness.app_cookie.duration_seconds"])))
        body.append(("stickiness", Block(sb)))
    handled |= _TG_STICKY & set(attrs)
    handled |= {k for k, d in _TG_DEFAULTS.items() if attrs.get(k) == d}
    unknown = sorted(set(attrs) - handled)
    if unknown:
        fidelity = "partial"
        notes.append(f"target group attributes not mapped: {', '.join(unknown)}")
    _add_tags(ctx, body)
    return TfSpec("aws_lb_target_group", ctx.pid, body, fidelity=fidelity, notes=notes)


# -- application autoscaling ----------------------------------------------------------------


def _split_target_id(target_id: Any) -> tuple[str, str, str]:
    """(namespace, resource id, dimension) from a ScalableTarget physical id.

    CloudFormation's ScalableTarget physical id is ``<resource-id>|<dimension>|<namespace>``.
    """
    s = str(target_id)
    if s.count("|") != 2:
        raise Unresolvable(f"scalable target id {s!r} not in resource|dimension|namespace form")
    rid, dim, ns = s.split("|")
    return ns, rid, dim


@mapper("AWS::ApplicationAutoScaling::ScalableTarget")
def appautoscaling_target(ctx: Ctx) -> TfSpec:
    """aws_appautoscaling_target, import id ``<namespace>/<resource-id>/<dimension>``.

    Live keys (DescribeScalableTargets), optional: ``RoleARN`` (AWS may substitute the
    service-linked role; the argument is computed, so it is omitted when unknown).
    """
    _only(
        ctx,
        {"ServiceNamespace", "ResourceId", "ScalableDimension", "MinCapacity", "MaxCapacity",
         "RoleARN"},
    )  # fmt: skip
    ns, rid, dim = ctx.r("ServiceNamespace"), ctx.r("ResourceId"), ctx.r("ScalableDimension")
    if ctx.pid.count("|") == 2 and _split_target_id(ctx.pid) != (ns, rid, dim):
        raise Unresolvable(f"scalable target id {ctx.pid} != template {ns}/{rid}/{dim}")
    body: list = [
        ("service_namespace", ns),
        ("resource_id", rid),
        ("scalable_dimension", dim),
        ("min_capacity", _int(ctx.r("MinCapacity"))),
        ("max_capacity", _int(ctx.r("MaxCapacity"))),
    ]
    notes: list[str] = []
    if "RoleARN" in ctx.live:
        body.append(("role_arn", ctx.live["RoleARN"]))
    elif ctx.has("RoleARN"):
        notes.append("role_arn omitted (computed): AWS may use the service-linked role")
    return TfSpec("aws_appautoscaling_target", f"{ns}/{rid}/{dim}", body, notes=notes)


_TT_KEYS = {
    "TargetValue", "ScaleInCooldown", "ScaleOutCooldown", "DisableScaleIn",
    "PredefinedMetricSpecification", "CustomizedMetricSpecification",
}  # fmt: skip


def _target_tracking(cfg: dict[str, Any]) -> Block:
    extra = set(cfg) - _TT_KEYS
    if extra:
        raise Unresolvable(f"target tracking keys not supported: {sorted(extra)}")
    body: list = [("target_value", _num(cfg["TargetValue"]))]
    if "DisableScaleIn" in cfg:
        body.append(("disable_scale_in", _bool(cfg["DisableScaleIn"])))
    if "ScaleInCooldown" in cfg:
        body.append(("scale_in_cooldown", _int(cfg["ScaleInCooldown"])))
    if "ScaleOutCooldown" in cfg:
        body.append(("scale_out_cooldown", _int(cfg["ScaleOutCooldown"])))
    pre = cfg.get("PredefinedMetricSpecification")
    if pre:
        pb: list = [("predefined_metric_type", pre["PredefinedMetricType"])]
        if pre.get("ResourceLabel"):
            pb.append(("resource_label", pre["ResourceLabel"]))
        body.append(("predefined_metric_specification", Block(pb)))
    cust = cfg.get("CustomizedMetricSpecification")
    if cust:
        if "Metrics" in cust:
            raise Unresolvable("metric-math target tracking is not supported in v0.1")
        cb: list = [
            ("metric_name", cust["MetricName"]),
            ("namespace", cust["Namespace"]),
            ("statistic", cust["Statistic"]),
        ]
        if cust.get("Unit"):
            cb.append(("unit", cust["Unit"]))
        for d in cust.get("Dimensions", []):
            cb.append(("dimensions", Block([("name", d["Name"]), ("value", str(d["Value"]))])))
        body.append(("customized_metric_specification", Block(cb)))
    return Block(body)


@mapper("AWS::ApplicationAutoScaling::ScalingPolicy")
def appautoscaling_policy(ctx: Ctx) -> TfSpec:
    """aws_appautoscaling_policy, import id ``<namespace>/<resource-id>/<dimension>/<name>``.

    No live keys: the target comes from ``ScalingTargetId`` (the target's physical id) or the
    explicit ResourceId/ScalableDimension/ServiceNamespace properties.
    """
    _only(
        ctx,
        {"PolicyName", "PolicyType", "ScalingTargetId", "ResourceId", "ScalableDimension",
         "ServiceNamespace", "TargetTrackingScalingPolicyConfiguration"},
    )  # fmt: skip
    if ctx.has("ScalingTargetId"):
        ns, rid, dim = _split_target_id(ctx.r("ScalingTargetId"))
    else:
        ns, rid, dim = ctx.r("ServiceNamespace"), ctx.r("ResourceId"), ctx.r("ScalableDimension")
    name = ctx.r("PolicyName")
    ptype = ctx.r("PolicyType")
    if ptype != "TargetTrackingScaling":
        raise Unresolvable(f"scaling policy type {ptype} not supported in v0.1")
    tt = _target_tracking(ctx.r("TargetTrackingScalingPolicyConfiguration"))
    body: list = [
        ("name", name),
        ("policy_type", ptype),
        ("service_namespace", ns),
        ("resource_id", rid),
        ("scalable_dimension", dim),
        ("target_tracking_scaling_policy_configuration", tt),
    ]
    return TfSpec("aws_appautoscaling_policy", f"{ns}/{rid}/{dim}/{name}", body)


# -- CloudWatch alarm -----------------------------------------------------------------------

_ALARM_ARGS = (
    ("AlarmDescription", "alarm_description", str),
    ("ComparisonOperator", "comparison_operator", str),
    ("EvaluationPeriods", "evaluation_periods", _int),
    ("DatapointsToAlarm", "datapoints_to_alarm", _int),
    ("MetricName", "metric_name", str),
    ("Namespace", "namespace", str),
    ("Period", "period", _int),
    ("Statistic", "statistic", str),
    ("ExtendedStatistic", "extended_statistic", str),
    ("Threshold", "threshold", _num),
    ("Unit", "unit", str),
    ("TreatMissingData", "treat_missing_data", str),
    ("EvaluateLowSampleCountPercentile", "evaluate_low_sample_count_percentiles", str),
    ("ActionsEnabled", "actions_enabled", _bool),
    ("AlarmActions", "alarm_actions", list),
    ("OKActions", "ok_actions", list),
    ("InsufficientDataActions", "insufficient_data_actions", list),
)


@mapper("AWS::CloudWatch::Alarm")
def cloudwatch_alarm(ctx: Ctx) -> TfSpec:
    """aws_cloudwatch_metric_alarm, import id = alarm name (the physical id). No live keys."""
    _only(ctx, {"AlarmName", "Dimensions", "Tags", *(k for k, _, _ in _ALARM_ARGS)})
    name = ctx.r("AlarmName", ctx.pid)
    if name != ctx.pid:
        raise Unresolvable(f"AlarmName {name} != physical id {ctx.pid}")
    body: list = [("alarm_name", name)]
    for cfn, tf, conv in _ALARM_ARGS:
        if ctx.has(cfn):
            body.append((tf, conv(ctx.r(cfn))))
    dims = ctx.r("Dimensions", [])
    if dims:
        body.append(("dimensions", {d["Name"]: str(d["Value"]) for d in dims}))
    _add_tags(ctx, body)
    return TfSpec("aws_cloudwatch_metric_alarm", name, body)


# -- Cloud Map ------------------------------------------------------------------------------


@mapper("AWS::ServiceDiscovery::PrivateDnsNamespace")
def sd_private_dns_namespace(ctx: Ctx) -> TfSpec:
    """aws_service_discovery_private_dns_namespace, import id ``<namespace-id>:<vpc-id>``."""
    _only(ctx, {"Name", "Vpc", "Description", "Tags"})
    vpc = ctx.r("Vpc")
    body: list = [("name", ctx.r("Name")), ("vpc", vpc)]
    desc = ctx.r("Description", None)
    if desc:
        body.append(("description", desc))
    _add_tags(ctx, body)
    return TfSpec("aws_service_discovery_private_dns_namespace", f"{ctx.pid}:{vpc}", body)


@mapper("AWS::ServiceDiscovery::Service")
def sd_service(ctx: Ctx) -> TfSpec:
    """aws_service_discovery_service, import id = service id (the physical id)."""
    _only(
        ctx,
        {"Name", "NamespaceId", "Description", "DnsConfig", "HealthCheckCustomConfig", "Type",
         "Tags"},
    )  # fmt: skip
    namespace = ctx.r("NamespaceId")
    body: list = [("name", ctx.r("Name")), ("namespace_id", namespace)]
    desc = ctx.r("Description", None)
    if desc:
        body.append(("description", desc))
    stype = ctx.r("Type", None)
    if stype:
        body.append(("type", stype))
    dns = ctx.r("DnsConfig", None)
    if dns:
        extra = set(dns) - {"RoutingPolicy", "DnsRecords", "NamespaceId"}
        if extra:
            raise Unresolvable(f"DnsConfig keys not supported: {sorted(extra)}")
        db: list = [("namespace_id", dns.get("NamespaceId", namespace))]
        if "RoutingPolicy" in dns:
            db.append(("routing_policy", dns["RoutingPolicy"]))
        for rec in dns.get("DnsRecords", []):
            db.append(("dns_records", Block([("ttl", _int(rec["TTL"])), ("type", rec["Type"])])))
        body.append(("dns_config", Block(db)))
    hc = ctx.r("HealthCheckCustomConfig", None)
    if hc is not None:
        hb: list = []
        if "FailureThreshold" in hc:
            hb.append(("failure_threshold", _int(hc["FailureThreshold"])))
        body.append(("health_check_custom_config", Block(hb)))
    _add_tags(ctx, body)
    return TfSpec("aws_service_discovery_service", ctx.pid, body)


# -- SNS / SQS ------------------------------------------------------------------------------

_SNS_ARGS = (
    ("DisplayName", "display_name", str),
    ("FifoTopic", "fifo_topic", _bool),
    ("ContentBasedDeduplication", "content_based_deduplication", _bool),
    ("KmsMasterKeyId", "kms_master_key_id", str),
    ("SignatureVersion", "signature_version", _int),
    ("TracingConfig", "tracing_config", str),
)


@mapper("AWS::SNS::Topic")
def sns_topic(ctx: Ctx) -> TfSpec:
    """aws_sns_topic, imported by topic ARN (the physical id). No live keys."""
    _only(ctx, {"TopicName", "Tags", *(k for k, _, _ in _SNS_ARGS)})
    name = ctx.pid.rsplit(":", 1)[-1]
    tmpl = ctx.r("TopicName", None)
    if tmpl is not None and tmpl != name:
        raise Unresolvable(f"TopicName {tmpl} != topic ARN name {name}")
    body: list = [("name", name)]
    for cfn, tf, conv in _SNS_ARGS:
        if ctx.has(cfn):
            body.append((tf, conv(ctx.r(cfn))))
    _add_tags(ctx, body)
    return TfSpec("aws_sns_topic", ctx.pid, body)


@mapper("AWS::SNS::TopicPolicy")
def sns_topic_policy(ctx: Ctx) -> TfSpec:
    """aws_sns_topic_policy, import id = topic ARN (exactly one topic per resource)."""
    _only(ctx, {"Topics", "PolicyDocument"})
    topic = _one(ctx.r("Topics"), "Topics")
    body: list = [("arn", topic), ("policy", _json(ctx.r("PolicyDocument")))]
    return TfSpec("aws_sns_topic_policy", topic, body)


_SQS_ARGS = (
    ("FifoQueue", "fifo_queue", _bool),
    ("ContentBasedDeduplication", "content_based_deduplication", _bool),
    ("DeduplicationScope", "deduplication_scope", str),
    ("FifoThroughputLimit", "fifo_throughput_limit", str),
    ("DelaySeconds", "delay_seconds", _int),
    ("MaximumMessageSize", "max_message_size", _int),
    ("MessageRetentionPeriod", "message_retention_seconds", _int),
    ("ReceiveMessageWaitTimeSeconds", "receive_wait_time_seconds", _int),
    ("VisibilityTimeout", "visibility_timeout_seconds", _int),
    ("KmsMasterKeyId", "kms_master_key_id", str),
    ("KmsDataKeyReusePeriodSeconds", "kms_data_key_reuse_period_seconds", _int),
    ("SqsManagedSseEnabled", "sqs_managed_sse_enabled", _bool),
)
_SQS_JSON = (("RedrivePolicy", "redrive_policy"), ("RedriveAllowPolicy", "redrive_allow_policy"))


@mapper("AWS::SQS::Queue")
def sqs_queue(ctx: Ctx) -> TfSpec:
    """aws_sqs_queue, imported by queue URL (the physical id). No live keys."""
    _only(ctx, {"QueueName", "Tags", *(k for k, _, _ in _SQS_ARGS), *(k for k, _ in _SQS_JSON)})
    url = ctx.pid
    name = url.rstrip("/").rsplit("/", 1)[-1]
    tmpl = ctx.r("QueueName", None)
    if tmpl is not None and tmpl != name:
        raise Unresolvable(f"QueueName {tmpl} != queue URL name {name}")
    body: list = [("name", name)]
    for cfn, tf, conv in _SQS_ARGS:
        if ctx.has(cfn):
            body.append((tf, conv(ctx.r(cfn))))
    for cfn, tf in _SQS_JSON:
        if ctx.has(cfn):
            body.append((tf, _json(ctx.r(cfn))))
    _add_tags(ctx, body)
    return TfSpec("aws_sqs_queue", url, body, stateful=True)


@mapper("AWS::SQS::QueuePolicy")
def sqs_queue_policy(ctx: Ctx) -> TfSpec:
    """aws_sqs_queue_policy, import id = queue URL (exactly one queue per resource)."""
    _only(ctx, {"Queues", "PolicyDocument"})
    url = _one(ctx.r("Queues"), "Queues")
    body: list = [("queue_url", url), ("policy", _json(ctx.r("PolicyDocument")))]
    return TfSpec("aws_sqs_queue_policy", url, body)
