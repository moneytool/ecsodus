"""tf_data mappers: RDS/Aurora, DynamoDB, S3, EFS, Secrets Manager, SSM, KMS, ECR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ecsodus.mappers.tf_data  # noqa: F401  (registers the mappers)
from ecsodus import cfn
from ecsodus.emit import hcl
from ecsodus.mappers.resolve import Resolver
from ecsodus.mappers.tfmap import (
    BLOCKED,
    MANUAL_CLEANUP,
    NotImported,
    TfSpec,
    map_resource,
)
from ecsodus.model import Inventory, Stack
from tests.helpers import ACCOUNT, FIXTURES, REGION, inventory_from_template

SYN = Path(__file__).parents[1] / "fixtures" / "synthetic"
RENDERED = FIXTURES / "rendered"
ADDON = {"App": "demo", "Env": "test", "Name": "api"}

DATA_TYPES = {
    "AWS::RDS::DBCluster", "AWS::RDS::DBInstance", "AWS::RDS::DBSubnetGroup",
    "AWS::RDS::DBClusterParameterGroup", "AWS::RDS::DBParameterGroup", "AWS::DynamoDB::Table",
    "AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::EFS::FileSystem", "AWS::EFS::MountTarget",
    "AWS::EFS::AccessPoint", "AWS::SecretsManager::Secret",
    "AWS::SecretsManager::SecretTargetAttachment", "AWS::SecretsManager::RotationSchedule",
    "AWS::SSM::Parameter", "AWS::KMS::Key", "AWS::KMS::Alias", "AWS::ECR::Repository",
}  # fmt: skip


def _map(inv: Inventory, stack: Stack, lid: str) -> TfSpec | NotImported:
    tpl = cfn.load(stack.template_body)
    return map_resource(
        inv, stack, Resolver(inv, stack, tpl), stack.resource(lid), tpl["Resources"][lid]
    )


def _spec(inv: Inventory, stack: Stack, lid: str) -> TfSpec:
    out = _map(inv, stack, lid)
    assert isinstance(out, TfSpec), out
    return out


def _args(spec: TfSpec) -> dict:
    return dict(spec.body)


def _blocks(spec: TfSpec, name: str) -> list[dict]:
    return [dict(v.body) for k, v in spec.body if k == name and isinstance(v, hcl.Block)]


def _hcl(spec: TfSpec) -> str:
    return hcl.block("resource", (spec.tf_type, "x"), spec.body)


def _pid(stack: Stack, lid: str) -> str:
    return stack.resource(lid).physical_id


def _aurora(name: str = "aurora-serverlessv2.yml") -> tuple[Inventory, Stack]:
    inv, stack = inventory_from_template(SYN / name, kind="addons", params=ADDON)
    stack.exports["demo-test-PrivateSubnets"] = "subnet-0bbb,subnet-0aaa"
    stack.exports["demo-test-VpcId"] = "vpc-0123"
    return inv, stack


def _cluster_live(**over: object) -> dict:
    live = {
        "Engine": "aurora-postgresql",
        "EngineVersion": "16.4",
        "MasterUsername": "postgres",
        "StorageEncrypted": True,
        "KmsKeyId": f"arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd",
        "DeletionProtection": True,
        "BackupRetentionPeriod": 1,
    }
    live.update(over)
    return live


# -- RDS / Aurora ---------------------------------------------------------------------------


def test_aurora_serverless_v2_cluster_uses_live_values_and_never_a_password():
    inv, stack = _aurora()
    pid = _pid(stack, "dbDBCluster")
    inv.live[pid] = _cluster_live()
    spec = _spec(inv, stack, "dbDBCluster")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_rds_cluster", pid, True)
    assert a["cluster_identifier"] == pid
    assert a["engine_version"] == "16.4"  # live wins over the template's 16.2
    assert any("16.2" in n and "16.4" in n for n in spec.notes)
    assert a["master_username"] == "postgres"
    assert "master_password" not in a and "resolve:secretsmanager" not in _hcl(spec)
    assert a["database_name"] == "main"
    assert a["port"] == 5432
    assert a["db_subnet_group_name"] == _pid(stack, "dbDBSubnetGroup")
    assert a["db_cluster_parameter_group_name"] == _pid(stack, "dbDBClusterParameterGroup")
    assert a["vpc_security_group_ids"] == [_pid(stack, "dbDBClusterSecurityGroup")]
    assert a["storage_encrypted"] is True
    assert a["deletion_protection"] is True
    assert a["skip_final_snapshot"] is False
    assert a["final_snapshot_identifier"] == f"{pid}-ecsodus-final"
    assert _blocks(spec, "serverlessv2_scaling_configuration") == [
        {"max_capacity": 8, "min_capacity": 0.5}
    ]


def test_deletion_protection_mirrors_live():
    inv, stack = _aurora()
    pid = _pid(stack, "dbDBCluster")
    inv.live[pid] = _cluster_live(DeletionProtection=False)
    spec = _spec(inv, stack, "dbDBCluster")
    assert "deletion_protection" not in _args(spec)
    assert any("deletion_protection is off on live" in n for n in spec.notes)

    del inv.live[pid]["DeletionProtection"]
    out = _map(inv, stack, "dbDBCluster")
    assert isinstance(out, NotImported) and out.fate == BLOCKED
    assert "DeletionProtection" in out.reason


@pytest.mark.parametrize("missing", ["EngineVersion", "MasterUsername", "StorageEncrypted"])
def test_cluster_blocks_without_required_live_values(missing):
    inv, stack = _aurora()
    live = _cluster_live()
    del live[missing]
    inv.live[_pid(stack, "dbDBCluster")] = live
    out = _map(inv, stack, "dbDBCluster")
    assert isinstance(out, NotImported) and out.fate == BLOCKED
    assert missing in out.reason


def test_live_serverless_v2_capacity_wins_over_template():
    inv, stack = _aurora()
    inv.live[_pid(stack, "dbDBCluster")] = _cluster_live(
        ServerlessV2ScalingConfiguration={"MinCapacity": 1.0, "MaxCapacity": 16.0}
    )
    spec = _spec(inv, stack, "dbDBCluster")
    assert _blocks(spec, "serverlessv2_scaling_configuration") == [
        {"max_capacity": 16, "min_capacity": 1}
    ]
    assert any("MaxCapacity" in n for n in spec.notes)


def test_serverless_v1_template_upgraded_to_v2_on_live():
    inv, stack = _aurora("aurora-serverless-v1.yml")
    inv.live[_pid(stack, "dbDBCluster")] = _cluster_live(
        Engine="aurora-mysql",
        EngineVersion="8.0.mysql_aurora.3.08.0",
        MasterUsername="admin",
        EngineMode="provisioned",
        ServerlessV2ScalingConfiguration={"MinCapacity": 0.5, "MaxCapacity": 8},
    )
    spec = _spec(inv, stack, "dbDBCluster")
    a = _args(spec)
    assert a["engine_mode"] == "provisioned"
    assert "scaling_configuration" not in a
    assert _blocks(spec, "serverlessv2_scaling_configuration")
    assert any("ScalingConfiguration" in n and "ignored" in n for n in spec.notes)


def test_serverless_v1_still_serverless_on_live():
    inv, stack = _aurora("aurora-serverless-v1.yml")
    inv.live[_pid(stack, "dbDBCluster")] = _cluster_live(
        Engine="aurora-mysql", EngineVersion="5.7.mysql_aurora.2.11.4", MasterUsername="admin"
    )
    spec = _spec(inv, stack, "dbDBCluster")
    assert _args(spec)["engine_mode"] == "serverless"
    assert _blocks(spec, "scaling_configuration") == [
        {"auto_pause": True, "max_capacity": 8, "min_capacity": 1,
         "seconds_until_auto_pause": 1000}
    ]  # fmt: skip


def test_aurora_writer_instance():
    inv, stack = _aurora()
    pid = "demo-test-api-dbwriter"
    stack.resource("dbDBWriterInstance").physical_id = pid
    inv.live[pid] = {"AvailabilityZone": "us-west-2a", "PubliclyAccessible": False}
    spec = _spec(inv, stack, "dbDBWriterInstance")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_rds_cluster_instance", pid, True)
    assert a["cluster_identifier"] == _pid(stack, "dbDBCluster")
    assert a["instance_class"] == "db.serverless"
    assert a["availability_zone"] == "us-west-2a"
    assert a["promotion_tier"] == 1
    assert a["publicly_accessible"] is False

    del inv.live[pid]["AvailabilityZone"]  # the template's !GetAZs is not resolvable
    assert isinstance(_map(inv, stack, "dbDBWriterInstance"), NotImported)


def test_subnet_group_and_cluster_parameter_group():
    inv, stack = _aurora()
    sg = _spec(inv, stack, "dbDBSubnetGroup")
    assert (sg.tf_type, sg.import_id, sg.stateful) == (
        "aws_db_subnet_group", _pid(stack, "dbDBSubnetGroup"), False,
    )  # fmt: skip
    assert _args(sg)["subnet_ids"] == ["subnet-0aaa", "subnet-0bbb"]
    pg = _spec(inv, stack, "dbDBClusterParameterGroup")
    assert pg.tf_type == "aws_rds_cluster_parameter_group"
    assert pg.import_id == _pid(stack, "dbDBClusterParameterGroup")
    assert _args(pg)["family"] == "aurora-postgresql16"
    assert _args(pg)["description"] == stack.name
    assert _blocks(pg, "parameter") == [{"name": "client_encoding", "value": "UTF8"}]


def test_standalone_db_instance_and_parameter_group():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    pid = "demo-test-api-db"
    stack.resource("Db").physical_id = pid
    live = {
        "EngineVersion": "15.8",
        "AllocatedStorage": 20,
        "MasterUsername": "postgres",
        "StorageEncrypted": False,
        "DeletionProtection": True,
    }
    inv.live[pid] = live
    spec = _spec(inv, stack, "Db")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_db_instance", pid, True)
    assert a["engine_version"] == "15.8" and a["username"] == "postgres"
    assert "password" not in a and "resolve:secretsmanager" not in _hcl(spec)
    assert a["deletion_protection"] is True and a["skip_final_snapshot"] is False
    assert a["parameter_group_name"] == _pid(stack, "DbParams")
    pg = _spec(inv, stack, "DbParams")
    assert pg.tf_type == "aws_db_parameter_group"
    assert _blocks(pg, "parameter") == [
        {"name": "log_min_duration_statement", "value": "500"},
        {"name": "rds.force_ssl", "value": "1"},
    ]


# -- Secrets ----------------------------------------------------------------------------------


def test_aurora_secret_is_secret_resource_only():
    inv, stack = _aurora()
    spec = _spec(inv, stack, "dbAuroraSecret")
    arn = _pid(stack, "dbAuroraSecret")
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_secretsmanager_secret", arn, True)
    a = _args(spec)
    assert a["name"] == "dbAuroraSecret"  # derived from the ARN's "<name>-XXXXXX" suffix
    assert a["description"] == f"Aurora main user secret for {stack.name}"
    text = _hcl(spec)
    assert "secret_string" not in text and "SecretStringTemplate" not in text
    assert any("GenerateSecretString" in n for n in spec.notes)


def test_secret_string_literal_is_never_emitted():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    spec = _spec(inv, stack, "ApiSecret")
    text = _hcl(spec) + "\n".join(spec.notes)
    assert "super-secret-literal" not in text and "secret_string" not in text
    assert _args(spec)["name"] == "demo/test/api-key"
    assert _args(spec)["kms_key_id"] == _pid(stack, "Key")


def test_secret_target_attachment_is_manual_cleanup():
    inv, stack = _aurora()
    out = _map(inv, stack, "dbSecretAuroraClusterAttachment")
    assert isinstance(out, NotImported) and out.fate == MANUAL_CLEANUP


def test_rotation_schedule():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    arn = _pid(stack, "ApiSecret")
    spec = _spec(inv, stack, "ApiSecretRotation")
    assert (spec.tf_type, spec.import_id, spec.stateful) == (
        "aws_secretsmanager_secret_rotation", arn, False,
    )  # fmt: skip
    a = _args(spec)
    assert a["secret_id"] == arn
    assert a["rotation_lambda_arn"] == f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:rotate"
    assert _blocks(spec, "rotation_rules") == [{"automatically_after_days": 30}]

    hosted = _map(inv, stack, "HostedRotation")
    assert isinstance(hosted, NotImported) and "RotationLambdaARN" in hosted.reason
    inv.live[_pid(stack, "HostedRotation")] = {"RotationLambdaARN": "arn:aws:lambda:x:y:function:z"}
    hosted = _spec(inv, stack, "HostedRotation")
    assert _blocks(hosted, "rotation_rules") == [{"schedule_expression": "rate(7 days)"}]


# -- SSM / KMS --------------------------------------------------------------------------------


def test_ssm_string_parameter_and_securestring_refused():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    pid = "/demo/test/api/feature-flag"
    stack.resource("Param").physical_id = pid
    spec = _spec(inv, stack, "Param")
    assert (spec.tf_type, spec.import_id) == ("aws_ssm_parameter", pid)
    assert _args(spec)["type"] == "String" and _args(spec)["value"] == "on"
    assert _args(spec)["tags"] == {"copilot-application": "demo"}
    out = _map(inv, stack, "SecureParam")
    assert isinstance(out, NotImported) and out.fate == BLOCKED
    assert "SecureString" in out.reason


def test_kms_key_policy_as_deployed_and_alias():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    key = _pid(stack, "Key")
    spec = _spec(inv, stack, "Key")
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_kms_key", key, True)
    assert json.loads(_args(spec)["policy"])["Statement"][0]["Principal"]["AWS"] == (
        f"arn:aws:iam::{ACCOUNT}:root"
    )
    assert any("template" in n for n in spec.notes)

    deployed = '{"Version":"2012-10-17","Statement":[]}'
    inv.live[key] = {"Policy": deployed}  # sources/live.py records GetKeyPolicy as "Policy"
    assert _args(_spec(inv, stack, "Key"))["policy"] == deployed

    alias = _spec(inv, stack, "KeyAlias")
    assert (alias.tf_type, alias.import_id) == ("aws_kms_alias", "alias/demo-data")
    assert _args(alias)["target_key_id"] == key


def test_worker_events_kms_key():
    inv, stack = inventory_from_template(RENDERED / "workloads" / "worker-test.stack.yml")
    spec = _spec(inv, stack, "EventsKMSKey")
    assert spec.tf_type == "aws_kms_key" and spec.stateful


def test_app_infra_key_bucket_and_ecr():
    inv, stack = inventory_from_template(SYN / "app-infra.yml", kind="stackset-instance")
    key = _spec(inv, stack, "KMSKey")
    assert _args(key)["enable_key_rotation"] is True
    bucket = _spec(inv, stack, "PipelineBuiltArtifactBucket")
    assert bucket.fidelity == "partial" and bucket.stateful
    policy = _spec(inv, stack, "PipelineBuiltArtifactBucketPolicy")
    b = _pid(stack, "PipelineBuiltArtifactBucket")
    assert (policy.tf_type, policy.import_id) == ("aws_s3_bucket_policy", b)
    assert f"arn:aws:s3:::{b}/*" in _args(policy)["policy"]
    repo = _spec(inv, stack, "ECRRepoapi")
    pid = _pid(stack, "ECRRepoapi")
    assert (repo.tf_type, repo.import_id, repo.stateful) == ("aws_ecr_repository", pid, True)
    assert _args(repo)["tags"] == {"copilot-service": "api"}
    assert repo.fidelity == "partial"
    assert any(f'aws_ecr_repository_policy (import id "{pid}")' in n for n in repo.notes)


# -- S3 / DynamoDB ----------------------------------------------------------------------------


def test_s3_addon_bucket_lists_sub_resources():
    inv, stack = inventory_from_template(SYN / "s3-ddb-addons.yml", kind="addons", params=ADDON)
    b = _pid(stack, "assetsBucket")
    spec = _spec(inv, stack, "assetsBucket")
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_s3_bucket", b, True)
    assert _args(spec) == {"bucket": b}
    assert spec.fidelity == "partial"
    notes = " ".join(spec.notes)
    for tf_type in (
        "aws_s3_bucket_versioning",
        "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_ownership_controls",
        "aws_s3_bucket_lifecycle_configuration",
    ):
        assert f'{tf_type} (import id "{b}")' in notes
    assert "aws_s3_bucket_acl (" not in notes  # Private + BucketOwnerEnforced: none needed
    policy = _spec(inv, stack, "assetsBucketPolicy")
    assert policy.import_id == b and not policy.stateful
    doc = json.loads(_args(policy)["policy"])
    assert doc["Statement"][0]["Resource"] == [f"arn:aws:s3:::{b}/*", f"arn:aws:s3:::{b}"]


def test_rendered_buckets():
    inv, stack = inventory_from_template(RENDERED / "workloads" / "static-site-test.stack.yml")
    b = _pid(stack, "Bucket")
    assert _spec(inv, stack, "Bucket").import_id == b
    policy = _spec(inv, stack, "BucketPolicyForCloudFront")
    assert policy.import_id == b
    env_inv, env = inventory_from_template(
        RENDERED / "environments" / "template-with-default-access-log-config.yml",
        stack_name="demo-test", kind="env", workload=None, workload_type=None,
    )  # fmt: skip
    assert _spec(env_inv, env, "ELBAccessLogsBucket").stateful


def test_ddb_addon_table():
    inv, stack = inventory_from_template(SYN / "s3-ddb-addons.yml", kind="addons", params=ADDON)
    pid = _pid(stack, "orders")
    inv.live[pid] = {"DeletionProtectionEnabled": False}
    spec = _spec(inv, stack, "orders")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_dynamodb_table", pid, True)
    assert a["billing_mode"] == "PAY_PER_REQUEST"
    assert (a["hash_key"], a["range_key"]) == ("pk", "sk")
    assert "read_capacity" not in a and "deletion_protection_enabled" not in a
    assert [b["name"] for b in _blocks(spec, "attribute")] == ["created", "pk", "sk"]
    assert _blocks(spec, "local_secondary_index") == [
        {"name": "byCreated", "range_key": "created", "projection_type": "ALL"}
    ]
    inv.live[pid] = {"DeletionProtectionEnabled": True}
    assert _args(_spec(inv, stack, "orders"))["deletion_protection_enabled"] is True
    inv.live[pid] = {}
    assert isinstance(_map(inv, stack, "orders"), NotImported)


def test_provisioned_table_capacity_comes_from_live():
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    pid = _pid(stack, "Provisioned")
    # DescribeTable's shape, as sources/live.py records it.
    inv.live[pid] = {
        "BillingModeSummary": {"BillingMode": "PROVISIONED"},
        "ProvisionedThroughput": {"ReadCapacityUnits": 12, "WriteCapacityUnits": 7},
        "DeletionProtectionEnabled": True,
    }
    out = _map(inv, stack, "Provisioned")
    assert isinstance(out, NotImported) and "byEmail" in out.reason
    inv.live[pid]["GlobalSecondaryIndexes"] = [
        {"IndexName": "byEmail",
         "ProvisionedThroughput": {"ReadCapacityUnits": 3, "WriteCapacityUnits": 2}}
    ]  # fmt: skip
    spec = _spec(inv, stack, "Provisioned")
    a = _args(spec)
    assert (a["read_capacity"], a["write_capacity"]) == (12, 7)  # autoscaled, not the template 5
    gsi = _blocks(spec, "global_secondary_index")[0]
    assert (gsi["name"], gsi["read_capacity"], gsi["write_capacity"]) == ("byEmail", 3, 2)
    assert gsi["projection_type"] == "KEYS_ONLY"
    assert _blocks(spec, "point_in_time_recovery") == [{"enabled": True}]
    assert _blocks(spec, "ttl") == [{"attribute_name": "expires", "enabled": True}]
    assert a["deletion_protection_enabled"] is True


def test_table_reads_describe_table_shape():
    # Regression: the mapper read flat BillingMode/ReadCapacityUnits/TableClass/KMSMasterKeyArn
    # keys, which DescribeTable (and so sources/live.py) never returns; they are nested.
    inv, stack = inventory_from_template(SYN / "data-iam-misc.yml")
    pid = _pid(stack, "Provisioned")
    table = {
        "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},  # switched since deploy
        "TableClassSummary": {"TableClass": "STANDARD_INFREQUENT_ACCESS"},
        "ProvisionedThroughput": {"ReadCapacityUnits": 0, "WriteCapacityUnits": 0},
        "DeletionProtectionEnabled": True,
    }
    inv.live[pid] = table
    spec = _spec(inv, stack, "Provisioned")
    a = _args(spec)
    assert a["billing_mode"] == "PAY_PER_REQUEST" and "read_capacity" not in a
    assert a["table_class"] == "STANDARD_INFREQUENT_ACCESS"
    assert any("BillingMode" in n and "live" in n for n in spec.notes)
    # Flat keys are not DescribeTable fields and are not read.
    inv.live[pid] = {"BillingMode": "PAY_PER_REQUEST", "DeletionProtectionEnabled": True}
    out = _map(inv, stack, "Provisioned")
    assert isinstance(out, NotImported) and "ReadCapacityUnits" in out.reason


def test_table_kms_key_arn_from_sse_description():
    inv, stack = inventory_from_template(SYN / "s3-ddb-addons.yml", kind="addons", params=ADDON)
    pid = _pid(stack, "orders")
    tpl = cfn.load(stack.template_body)
    body = tpl["Resources"]["orders"]
    body["Properties"]["SSESpecification"] = {"SSEEnabled": True, "KMSMasterKeyId": "alias/k"}
    res = stack.resource("orders")
    key_arn = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/1234"
    inv.live[pid] = {"DeletionProtectionEnabled": False}
    out = map_resource(inv, stack, Resolver(inv, stack, tpl), res, body)
    assert isinstance(out, NotImported) and "SSEDescription.KMSMasterKeyArn" in out.reason
    inv.live[pid]["SSEDescription"] = {"Status": "ENABLED", "KMSMasterKeyArn": key_arn}
    out = map_resource(inv, stack, Resolver(inv, stack, tpl), res, body)
    assert isinstance(out, TfSpec)
    assert _blocks(out, "server_side_encryption") == [{"enabled": True, "kms_key_arn": key_arn}]


# -- EFS --------------------------------------------------------------------------------------


def test_env_efs_file_system_and_mount_targets():
    inv, stack = inventory_from_template(
        RENDERED / "environments" / "template-with-default-access-log-config.yml",
        stack_name="demo-test", kind="env", workload=None, workload_type=None,
    )  # fmt: skip
    fs = _pid(stack, "FileSystem")
    spec = _spec(inv, stack, "FileSystem")
    a = _args(spec)
    assert (spec.tf_type, spec.import_id, spec.stateful) == ("aws_efs_file_system", fs, True)
    assert a["encrypted"] is True
    assert a["performance_mode"] == "generalPurpose" and a["throughput_mode"] == "bursting"
    assert _blocks(spec, "lifecycle_policy") == [{"transition_to_ia": "AFTER_30_DAYS"}]
    assert spec.fidelity == "partial"
    notes = " ".join(spec.notes)
    assert f'aws_efs_backup_policy (import id "{fs}"' in notes
    assert f'aws_efs_file_system_policy (import id "{fs}")' in notes
    stack.resource("MountTarget1").physical_id = "fsmt-0123"
    mt = _spec(inv, stack, "MountTarget1")
    assert (mt.tf_type, mt.import_id, mt.stateful) == ("aws_efs_mount_target", "fsmt-0123", False)
    assert _args(mt)["file_system_id"] == fs
    assert _args(mt)["subnet_id"] == _pid(stack, "PrivateSubnet1")


def test_job_efs_access_point_uses_custom_resource_output():
    inv, stack = inventory_from_template(RENDERED / "workloads" / "job-test.stack.yml")
    stack.resource("AccessPoint").physical_id = "fsap-0123"
    out = _map(inv, stack, "AccessPoint")
    assert isinstance(out, NotImported)  # EnvControllerAction output unknown
    inv.live[_pid(stack, "EnvControllerAction")] = {"ManagedFileSystemID": "fs-0abc"}
    spec = _spec(inv, stack, "AccessPoint")
    assert (spec.tf_type, spec.import_id) == ("aws_efs_access_point", "fsap-0123")
    assert _args(spec)["file_system_id"] == "fs-0abc"
    assert _blocks(spec, "posix_user") == [{"gid": 4225294584, "uid": 4225294584}]
    root = _blocks(spec, "root_directory")[0]
    assert root["path"] == "/job"
    assert dict(root["creation_info"].body)["permissions"] == "0755"


# -- sweeps -----------------------------------------------------------------------------------

_SWEEP = [
    (RENDERED / "environments" / "template-with-basic-manifest.yml", "env"),
    (RENDERED / "environments" / "template-with-importedvpc-flowlogs.yml", "env"),
    (RENDERED / "environments" / "template-with-default-access-log-config.yml", "env"),
    (RENDERED / "workloads" / "static-site-test.stack.yml", "workload"),
    (RENDERED / "workloads" / "job-test.stack.yml", "workload"),
    (RENDERED / "workloads" / "worker-test.stack.yml", "workload"),
    (SYN / "aurora-serverlessv2.yml", "addons"),
    (SYN / "aurora-serverless-v1.yml", "addons"),
    (SYN / "s3-ddb-addons.yml", "addons"),
    (SYN / "app-infra.yml", "stackset-instance"),
    (SYN / "data-iam-misc.yml", "addons"),
]


@pytest.mark.parametrize(("path", "kind"), _SWEEP, ids=lambda p: getattr(p, "name", p))
def test_every_data_resource_maps_and_honours_the_secrets_contract(path, kind):
    inv, stack = inventory_from_template(
        path, kind=kind, params=ADDON if kind == "addons" else None
    )
    stack.exports["demo-test-PrivateSubnets"] = "subnet-0aaa"
    stack.exports["demo-test-VpcId"] = "vpc-0123"
    seen = 0
    for res in stack.resources:
        if res.type not in DATA_TYPES:
            continue
        seen += 1
        out = _map(inv, stack, res.logical_id)
        if isinstance(out, NotImported):
            # Blocked only for missing live values / unresolvable intrinsics, never for a
            # property the mapper does not know.
            assert "unhandled properties" not in out.reason, (res.logical_id, out.reason)
            continue
        text = _hcl(out) + "\n".join(out.notes)
        assert "secret_string" not in text and "aws_secretsmanager_secret_version" not in {
            out.tf_type
        }
        assert "super-secret-literal" not in text and "never-emitted" not in text
        assert "master_password" not in dict(out.body) and "password" not in dict(out.body)
    assert seen


def test_all_rendered_data_types_are_covered():
    used: set[str] = set()
    for p in list(RENDERED.rglob("*.yml")) + list(SYN.glob("*.yml")):
        if p.name.endswith("manifest.yml"):
            continue
        try:
            tpl = cfn.load(p.read_text())
        except cfn.TemplateError:
            continue
        used |= {b["Type"] for b in tpl["Resources"].values()} & DATA_TYPES
    assert used == DATA_TYPES
