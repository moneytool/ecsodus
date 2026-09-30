"""Inventory against moto (mocked AWS): discovery, tags, SSM metadata, read-only access."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from ecsodus.sources import copilot
from ecsodus.sources.aws import Clients

REGION = "us-west-2"

ENV = """
Resources:
  EnvLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /copilot/shop-test
Outputs:
  EnvLogGroupName:
    Value: !Ref EnvLogGroup
    Export:
      Name: shop-test-EnvLogGroupName
"""

SVC = """
Resources:
  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /copilot/shop-test-web
  Topic:
    Type: AWS::SNS::Topic
"""


@pytest.fixture
def aws():
    with mock_aws():
        session = boto3.Session(
            region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        cfn = session.client("cloudformation")
        tags = [{"Key": "copilot-application", "Value": "shop"}]
        cfn.create_stack(
            StackName="shop-test",
            TemplateBody=ENV,
            Tags=tags + [{"Key": "copilot-environment", "Value": "test"}],
        )
        cfn.create_stack(
            StackName="shop-test-web",
            TemplateBody=SVC,
            Tags=tags
            + [
                {"Key": "copilot-environment", "Value": "test"},
                {"Key": "copilot-service", "Value": "web"},
            ],
        )
        cfn.create_stack(StackName="unrelated", TemplateBody=SVC.replace("shop", "other"))
        ssm = session.client("ssm")
        ssm.put_parameter(
            Name="/copilot/applications/shop", Type="String", Value=json.dumps({"name": "shop"})
        )
        ssm.put_parameter(
            Name="/copilot/applications/shop/components/web",
            Type="String",
            Value=json.dumps({"name": "web", "type": "Load Balanced Web Service"}),
        )
        ssm.put_parameter(
            Name="/copilot/applications/shop/environments/test",
            Type="String",
            Value=json.dumps({"name": "test"}),
        )
        ssm.put_parameter(
            Name="/copilot/shop/test/secrets/DB_PASSWORD",
            Type="SecureString",
            Value="hunter2",
            Tags=[{"Key": "copilot-application", "Value": "shop"}],
        )
        yield session


def test_inventory_discovers_copilot_stacks(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop")
    assert set(inv.stacks) == {"shop-test", "shop-test-web"}
    web = inv.stacks["shop-test-web"]
    assert web.kind == "workload" and web.workload == "web" and web.env == "test"
    assert web.workload_type == "Load Balanced Web Service"
    assert {r.logical_id for r in web.resources} == {"LogGroup", "Topic"}
    assert inv.stacks["shop-test"].kind == "env"
    assert inv.stacks["shop-test"].exports == {"shop-test-EnvLogGroupName": "/copilot/shop-test"}
    assert inv.envs == ["test"]
    assert [(w.name, w.migrate) for w in inv.workloads] == [("web", True)]
    assert "Resources" in web.template_body


def test_secure_string_names_only(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop")
    assert {"name": "/copilot/shop/test/secrets/DB_PASSWORD", "type": "SecureString"} in (
        inv.ssm_parameters
    )
    assert "hunter2" not in inv.to_json()


def test_keep_on_copilot(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop", keep_on_copilot=["test/web"])
    assert [(w.name, w.migrate) for w in inv.workloads] == [("web", False)]


def test_env_filter(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop", envs=["prod"])
    assert inv.stacks == {}


def test_live_log_groups(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop")
    assert inv.live["/copilot/shop-test-web"]["logGroupName"] == "/copilot/shop-test-web"
