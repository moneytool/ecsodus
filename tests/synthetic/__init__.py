"""A small synthetic Copilot-shaped app for pipeline tests (no AWS).

Layout: app stack, env stack ``demo-test`` (VPC, log group, cluster, custom-domain custom
resource), workload stacks ``demo-test-api`` (LBWS) and ``demo-test-worker`` (configurable
type), each with an ``EnvControllerAction`` custom resource; ``api`` has a nested addons stack
with a log group. Only resource types with simple mappers are used, so tests do not depend on
live data for most resources.
"""

from __future__ import annotations

from ecsodus.model import Inventory, Resource, Stack, Workload

ACCOUNT = "123456789012"
REGION = "us-west-2"

ENV_TEMPLATE = """\
AWSTemplateFormatVersion: 2010-09-09
Parameters:
  AppName:
    Type: String
  EnvironmentName:
    Type: String
Resources:
  VPC:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: 10.0.0.0/16
      EnableDnsHostnames: true
      EnableDnsSupport: true
      Tags:
        - Key: Name
          Value: !Sub 'copilot-${AppName}-${EnvironmentName}'
  EnvLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/copilot/${AppName}-${EnvironmentName}'
      RetentionInDays: 30
  Cluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterSettings:
        - Name: containerInsights
          Value: disabled
  CustomDomainFunction:
    Type: AWS::Lambda::Function
    Properties:
      Handler: index.handler
  CustomDomainAction:
    Type: Custom::CustomDomainFunction
    Properties:
      ServiceToken: !GetAtt CustomDomainFunction.Arn
Outputs:
  ClusterId:
    Value: !Ref Cluster
    Export:
      Name: !Sub '${AWS::StackName}-ClusterId'
"""

WORKLOAD_TEMPLATE = """\
AWSTemplateFormatVersion: 2010-09-09
Parameters:
  AppName:
    Type: String
  EnvName:
    Type: String
  WorkloadName:
    Type: String
  AddonsTemplateURL:
    Type: String
    Default: ''
Conditions:
  HasAddons: !Not [!Equals [!Ref AddonsTemplateURL, '']]
Resources:
  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/copilot/${AppName}-${EnvName}-${WorkloadName}'
      RetentionInDays: 30
  EnvControllerFunction:
    Type: AWS::Lambda::Function
    Properties:
      Handler: index.handler
  EnvControllerAction:
    Type: Custom::EnvControllerFunction
    Properties:
      ServiceToken: !GetAtt EnvControllerFunction.Arn
      Workload: !Ref WorkloadName
  AddonsStack:
    Type: AWS::CloudFormation::Stack
    Condition: HasAddons
    DependsOn: EnvControllerAction
    Properties:
      Parameters:
        App: !Ref AppName
      TemplateURL:
        !Ref AddonsTemplateURL
"""

ADDONS_TEMPLATE = """\
Parameters:
  App:
    Type: String
Resources:
  DataLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/copilot/${App}-data'
Outputs:
  DataLogGroupName:
    Value: !Ref DataLogGroup
"""

APP_TEMPLATE = """\
Resources:
  AppLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /copilot/demo-app
"""


def _stack(
    name: str, kind: str, template: str, params: dict[str, str], resources: list, **kw: object
) -> Stack:
    return Stack(
        name=name,
        kind=kind,
        stack_id=f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/uuid-{name}",
        status="UPDATE_COMPLETE",
        template_body=template,
        parameters=params,
        resources=[Resource(*r) for r in resources],
        last_updated="2026-09-29T00:00:00+00:00",
        capabilities=["CAPABILITY_IAM"],
        **kw,
    )


def app(
    worker_type: str = "Backend Service",
    worker_migrates: bool = True,
    extra_workload_resource: tuple[str, str] | None = None,
) -> Inventory:
    env = _stack(
        "demo-test",
        "env",
        ENV_TEMPLATE,
        {"AppName": "demo", "EnvironmentName": "test"},
        [
            ("VPC", "AWS::EC2::VPC", "vpc-0123456789abcdef0"),
            ("EnvLogGroup", "AWS::Logs::LogGroup", "/copilot/demo-test"),
            ("Cluster", "AWS::ECS::Cluster", "demo-test-Cluster-AbC"),
            ("CustomDomainFunction", "AWS::Lambda::Function", "demo-test-CustomDomainFunction-X1"),
            ("CustomDomainAction", "Custom::CustomDomainFunction", "demo-test-cda-1"),
        ],
        env="test",
    )
    env.exports = {"demo-test-ClusterId": "demo-test-Cluster-AbC"}
    stacks = {"demo-test": env}
    for name, wtype in (("api", "Load Balanced Web Service"), ("worker", worker_type)):
        sname = f"demo-test-{name}"
        resources = [
            ("LogGroup", "AWS::Logs::LogGroup", f"/copilot/demo-test-{name}"),
            ("EnvControllerFunction", "AWS::Lambda::Function", f"{sname}-EnvCtl-Z9"),
            ("EnvControllerAction", "Custom::EnvControllerFunction", f"{sname}-eca"),
        ]
        params = {
            "AppName": "demo",
            "EnvName": "test",
            "WorkloadName": name,
            "AddonsTemplateURL": "",
        }
        template = WORKLOAD_TEMPLATE
        if name == "api":
            params["AddonsTemplateURL"] = "https://bucket.s3.amazonaws.com/addons.yml"
            resources.append(
                (
                    "AddonsStack",
                    "AWS::CloudFormation::Stack",
                    f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/"
                    f"demo-test-api-AddonsStack-1/uuid-addons",
                )
            )
        if name == "worker" and extra_workload_resource:
            lid, rtype = extra_workload_resource
            template = template + f"  {lid}:\n    Type: {rtype}\n    Properties: {{}}\n"
            resources.append((lid, rtype, f"{sname}-{lid}"))
        stacks[sname] = _stack(
            sname,
            "workload",
            template,
            params,
            resources,
            env="test",
            workload=name,
            workload_type=wtype,
        )
    addons = _stack(
        "demo-test-api-AddonsStack-1",
        "addons",
        ADDONS_TEMPLATE,
        {"App": "demo"},
        [("DataLogGroup", "AWS::Logs::LogGroup", "/copilot/demo-data")],
        env="test",
        workload="api",
        parent="demo-test-api",
        parent_logical_id="AddonsStack",
    )
    addons.stack_id = (
        f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/demo-test-api-AddonsStack-1/uuid-addons"
    )
    addons.outputs = {"DataLogGroupName": "/copilot/demo-data"}
    stacks[addons.name] = addons
    stacks["demo-infrastructure-roles"] = _stack(
        "demo-infrastructure-roles",
        "app",
        APP_TEMPLATE,
        {},
        [("AppLogGroup", "AWS::Logs::LogGroup", "/copilot/demo-app")],
    )
    from ecsodus.model import now_iso

    return Inventory(
        app="demo",
        account=ACCOUNT,
        region=REGION,
        captured_at=now_iso(),
        envs=["test"],
        workloads=[
            Workload("api", "Load Balanced Web Service", "test"),
            Workload("worker", worker_type, "test", worker_migrates),
        ],
        stacks=stacks,
        live={
            "vpc-0123456789abcdef0": {
                "EnableDnsSupport": True,
                "EnableDnsHostnames": True,
                "CidrBlock": "10.0.0.0/16",
                "InstanceTenancy": "default",
            }
        },
    )
