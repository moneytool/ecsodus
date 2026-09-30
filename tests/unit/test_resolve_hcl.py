"""Intrinsic resolution and HCL rendering."""

from __future__ import annotations

import pytest

from ecsodus.emit import hcl
from ecsodus.emit.hcl import Block, Raw
from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.model import Inventory, Resource, Stack

TEMPLATE = """
Parameters:
  AppName: {Type: String}
  Subnets: {Type: CommaDelimitedList}
  Flag: {Type: String}
Conditions:
  On: !Equals [!Ref Flag, 'yes']
  Off: !Not [!Condition On]
Resources:
  Topic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: !Sub '${AppName}-${AWS::Region}-topic'
  Role:
    Type: AWS::IAM::Role
    Condition: Off
"""


def make() -> Resolver:
    stack = Stack(
        name="demo-test",
        kind="env",
        template_body=TEMPLATE,
        parameters={"AppName": "demo", "Subnets": "a, b", "Flag": "yes"},
        resources=[
            Resource("Topic", "AWS::SNS::Topic", "arn:aws:sns:us-west-2:1:demo-topic"),
            Resource("Role", "AWS::IAM::Role", "demo-role"),
        ],
    )
    inv = Inventory(
        app="demo", account="1", region="us-west-2", captured_at="x", stacks={"demo-test": stack}
    )
    return Resolver(inv, stack)


def test_ref_sub_join_select_if() -> None:
    r = make()
    assert r.resolve({"Fn::Sub": "${AppName}-${AWS::Region}"}) == "demo-us-west-2"
    assert r.resolve({"Ref": "Subnets"}) == ["a", "b"]
    assert r.resolve({"Fn::Join": ["-", [{"Ref": "AppName"}, "x"]]}) == "demo-x"
    assert r.resolve({"Fn::Select": [1, {"Ref": "Subnets"}]}) == "b"
    assert r.resolve({"Fn::If": ["On", "y", "n"]}) == "y"
    assert r.resolve({"Fn::GetAtt": ["Role", "Arn"]}) == "arn:aws:iam::1:role/demo-role"
    assert r.resolve(["a", {"Ref": "AWS::NoValue"}]) == ["a"]


def test_conditions() -> None:
    r = make()
    assert r.condition("On") is True
    assert r.resource_exists("Role") is False
    assert r.resource_exists("Topic") is True


def test_unresolvable() -> None:
    r = make()
    with pytest.raises(Unresolvable):
        r.resolve({"Fn::GetAZs": ""})
    with pytest.raises(Unresolvable):
        r.resolve({"Fn::ImportValue": "nope"})


def test_hcl_rendering_escapes_interpolation() -> None:
    text = hcl.block(
        "resource",
        ("aws_x", "y"),
        [
            ("name", "a${b}"),
            ("n", 3),
            ("on", True),
            ("list", ["a", "b"]),
            ("tags", {"k": "v", "a:b": "c"}),
            ("expr", Raw("jsonencode([])")),
            ("lifecycle", Block([("prevent_destroy", True)])),
        ],
    )
    assert '"a$${b}"' in text
    assert '"a:b" = "c"' in text
    assert "expr" in text and "jsonencode([])" in text
    assert "lifecycle {" in text


def test_load_balancer_attribute_aliases_and_full_names() -> None:
    lb = "arn:aws:elasticloadbalancing:us-west-2:1:loadbalancer/app/demo-lb/0123456789abcdef"
    tg = "arn:aws:elasticloadbalancing:us-west-2:1:targetgroup/demo-tg/0123456789abcdef"
    tpl = (
        "Resources:\n  LB:\n    Type: AWS::ElasticLoadBalancingV2::LoadBalancer\n"
        "  TG:\n    Type: AWS::ElasticLoadBalancingV2::TargetGroup\n"
    )
    stack = Stack(
        name="s",
        kind="env",
        template_body=tpl,
        resources=[
            Resource("LB", "AWS::ElasticLoadBalancingV2::LoadBalancer", lb),
            Resource("TG", "AWS::ElasticLoadBalancingV2::TargetGroup", tg),
        ],
    )
    inv = Inventory(
        app="a",
        account="1",
        region="us-west-2",
        captured_at="x",
        stacks={"s": stack},
        live={lb: {"CanonicalHostedZoneId": "Z1H1FL5HABSF5"}},
    )
    r = Resolver(inv, stack)
    assert r.resolve({"Fn::GetAtt": ["LB", "CanonicalHostedZoneID"]}) == "Z1H1FL5HABSF5"
    assert r.resolve({"Fn::GetAtt": ["LB", "LoadBalancerFullName"]}) == (
        "app/demo-lb/0123456789abcdef"
    )
    assert r.resolve({"Fn::GetAtt": ["TG", "TargetGroupFullName"]}) == (
        "targetgroup/demo-tg/0123456789abcdef"
    )
