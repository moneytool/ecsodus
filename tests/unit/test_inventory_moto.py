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
    # --env narrows the migration, never the discovery: other envs stay visible as consumers.
    with pytest.raises(ValueError, match="no environment stack"):
        copilot.inventory(Clients(aws), "shop", envs=["prod"])
    inv = copilot.inventory(Clients(aws), "shop", envs=["test"])
    assert set(inv.stacks) == {"shop-test", "shop-test-web"}
    assert inv.selection == {"envs": ["test"], "keep_on_copilot": []}


def test_unknown_keep_name_is_an_error(aws) -> None:
    with pytest.raises(ValueError, match="no workload"):
        copilot.inventory(Clients(aws), "shop", keep_on_copilot=["test/wbe"])


def test_live_log_groups(aws) -> None:
    inv = copilot.inventory(Clients(aws), "shop")
    assert inv.live["/copilot/shop-test-web"]["logGroupName"] == "/copilot/shop-test-web"


SHARED = """
Resources:
  Topic:
    Type: AWS::SNS::Topic
Outputs:
  FsId:
    Value: fs-0shared
    Export:
      Name: shared-fs-id
  Other:
    Value: not-referenced
    Export:
      Name: shared-other
  # Names that occur in the app's template but are not imported by it (review on PR #20):
  # a logical id, a word in a description, and both prefix directions of the real import.
  LogicalId:
    Value: rule-export
    Export:
      Name: Rule
  InDescription:
    Value: described
    Export:
      Name: described-export
  Prefix:
    Value: prefix
    Export:
      Name: shared-fs
  Extended:
    Value: extended
    Export:
      Name: shared-fs-id-backup
"""

WORKER = """
Description: Worker that also mentions described-export in prose
Resources:
  Role:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Effect: Allow
            Principal: {Service: lambda.amazonaws.com}
            Action: sts:AssumeRole
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      Handler: index.handler
      Runtime: nodejs20.x
      Role: !GetAtt Role.Arn
      Code: {ZipFile: "exports.handler = async () => {}"}
  Rule:
    Type: AWS::Events::Rule
    Properties:
      ScheduleExpression: rate(1 minute)
      Targets:
        - Id: Trigger
          Arn: !GetAtt Fn.Arn
  Permission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref Fn
      Action: lambda:InvokeFunction
      Principal: events.amazonaws.com
      SourceArn: !GetAtt Rule.Arn
Outputs:
  Fs:
    Value: !ImportValue shared-fs-id
"""


def test_worker_live_reads_and_external_exports(aws) -> None:
    """ADR-0014: rule targets, function tags and policy statement ids, subscription attributes
    (never GetFunction: it returns environment variables), and only the external exports the
    app's templates name."""
    cfn = aws.client("cloudformation")
    cfn.create_stack(StackName="shared-efs", TemplateBody=SHARED)
    cfn.create_stack(
        StackName="shop-test-worker",
        TemplateBody=WORKER,
        Tags=[
            {"Key": "copilot-application", "Value": "shop"},
            {"Key": "copilot-environment", "Value": "test"},
            {"Key": "copilot-service", "Value": "worker"},
        ],
    )
    inv = copilot.inventory(Clients(aws), "shop")
    assert inv.external_exports == {"shared-fs-id": {"value": "fs-0shared", "stack": "shared-efs"}}
    pid = {r.logical_id: r.physical_id for r in inv.stacks["shop-test-worker"].resources}
    rule = inv.live[pid["Rule"]]
    assert [t["Id"] for t in rule["Targets"]] == ["Trigger"]
    assert "Tags" in rule
    fn = inv.live[pid["Fn"]]
    assert set(fn) == {"Tags", "PolicySids"} and len(fn["PolicySids"]) == 1
    assert not [u for u in inv.unavailable if "live read failed" in u.get("reason", "")]


def test_subscription_attributes_read(aws) -> None:
    """Moto's CloudFormation has no AWS::SNS::Subscription, so the reader runs directly."""
    from ecsodus.model import Inventory
    from ecsodus.sources import live

    sns, sqs = aws.client("sns"), aws.client("sqs")
    topic = sns.create_topic(Name="t")["TopicArn"]
    url = sqs.create_queue(QueueName="q")["QueueUrl"]
    queue = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]
    sub = sns.subscribe(
        TopicArn=topic,
        Protocol="sqs",
        Endpoint=queue["QueueArn"],
        Attributes={"RawMessageDelivery": "true"},
        ReturnSubscriptionArn=True,
    )["SubscriptionArn"]
    inv = Inventory(app="shop", account="123456789012", region=REGION, captured_at="now")
    live.READERS["AWS::SNS::Subscription"](Clients(aws), inv, [sub, "pending confirmation"])
    assert inv.live[sub]["RawMessageDelivery"] == "true"
    assert "pending confirmation" not in inv.live
