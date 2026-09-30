"""ecsodus must never be able to call a mutating or secret-reading AWS API."""

from __future__ import annotations

import ast
from pathlib import Path

import boto3
import pytest

from ecsodus.sources.aws import Clients, ReadOnlyClient, ReadOnlyViolation

SRC = Path(__file__).parent.parent.parent / "src" / "ecsodus"


def client(service: str) -> ReadOnlyClient:
    return Clients(boto3.Session(region_name="us-west-2", aws_access_key_id="x",
                                 aws_secret_access_key="x"))(service)


@pytest.mark.parametrize("service,op", [
    ("cloudformation", "delete_stack"), ("cloudformation", "update_stack"),
    ("cloudformation", "create_change_set"), ("cloudformation", "execute_change_set"),
    ("ecs", "update_service"), ("rds", "modify_db_cluster"), ("s3", "put_object"),
    ("iam", "attach_role_policy"), ("ssm", "put_parameter"),
    ("secretsmanager", "get_secret_value"),
])
def test_mutating_and_secret_calls_refused(service: str, op: str) -> None:
    with pytest.raises(ReadOnlyViolation):
        getattr(client(service), op)


def test_ssm_decryption_refused() -> None:
    with pytest.raises(ReadOnlyViolation):
        client("ssm").get_parameters_by_path(Path="/", WithDecryption=True)


def test_read_calls_allowed() -> None:
    c = client("cloudformation")
    assert callable(c.describe_stacks)
    assert c.get_paginator("list_stacks") is not None
    with pytest.raises(ReadOnlyViolation):
        c.get_paginator("delete_stack")


def test_sources_only_call_read_operations() -> None:
    """Static scan: every attribute call on a client in sources/ is a read operation."""
    reads = ("describe_", "list_", "get_", "lookup_")
    for path in (SRC / "sources").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                if "_" in name and name.split("_")[0] in {
                    "create", "delete", "update", "put", "modify", "execute", "attach",
                    "detach", "remove", "tag", "untag", "set", "start", "stop",
                }:
                    pytest.fail(f"{path.name}: calls {name}")
                assert not name.startswith(("delete_", "update_")) or name in reads
