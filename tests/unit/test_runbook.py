from __future__ import annotations

import shlex

import pytest

from ecsodus.emit.patches import build_patches
from ecsodus.emit.runbook import render
from ecsodus.mappers.fates import build_plan
from ecsodus.model import APP, STACKSET_INSTANCE, StackSet
from tests.synthetic import app


@pytest.mark.parametrize("kind", [APP, STACKSET_INSTANCE])
@pytest.mark.parametrize("parameters", [{}, {"Zulu": "z", "Alpha": "a"}])
@pytest.mark.parametrize("capabilities", [[], ["CAPABILITY_IAM"]])
def test_retain_commands_preserve_parameters_only_when_present(
    kind: str, parameters: dict[str, str], capabilities: list[str]
) -> None:
    inv = app()
    stack = inv.stacks["demo-infrastructure-roles"]
    stack.kind = kind
    stack.parameters = parameters
    stack.capabilities = capabilities
    if kind == STACKSET_INSTANCE:
        inv.stacksets["demo-infrastructure"] = StackSet(
            name="demo-infrastructure",
            template_body=stack.template_body,
            parameters=parameters,
            capabilities=capabilities,
            administration_role_arn="arn:aws:iam::123456789012:role/admin",
            execution_role_name="execution",
        )
    plan = build_plan(inv)
    assert plan.stacks[stack.name].handoff
    rb = render(plan, build_patches(inv, "patch-bucket"), include_teardown=False)
    marker = (
        "create-change-set --stack-name demo-infrastructure-roles "
        if kind == APP
        else "update-stack-set --stack-set-name demo-infrastructure "
    )
    command = next(line for line in rb.splitlines() if marker in line)
    args = shlex.split(command)
    if parameters:
        pos = args.index("--parameters")
        assert args[pos + 1 : pos + 3] == [
            "ParameterKey=Alpha,UsePreviousValue=true",
            "ParameterKey=Zulu,UsePreviousValue=true",
        ]
    else:
        assert "--parameters" not in args
    if capabilities:
        assert args[args.index("--capabilities") + 1] == "CAPABILITY_IAM"
    else:
        assert "--capabilities" not in args
    if kind == STACKSET_INSTANCE:
        assert args[args.index("--execution-role-name") + 1] == "execution"


def test_leftover_list_never_names_a_custom_resource_handle() -> None:
    """A handle's physical ID can be a live, imported resource: Copilot's HTTPSCert reports the
    certificate ARN. The post-teardown deletion list must not tell anyone to delete it."""
    inv = app()
    cert = "arn:aws:acm:us-west-2:123456789012:certificate/abc"
    env = inv.stacks["demo-test"]
    env.resource("CustomDomainAction").physical_id = cert  # stands in for HTTPSCert
    plan = build_plan(inv)
    rb = render(plan, build_patches(inv, "patch-bucket"), include_teardown=True)
    leftovers = rb.split("delete the Copilot-internal leftovers", 1)[1].split("## 7.", 1)[0]
    assert "`AWS::Lambda::Function` `demo-test-CustomDomainFunction-X1`" in leftovers
    assert cert not in leftovers
    assert "Custom::CustomDomainFunction" not in leftovers.split("Custom-resource handles", 1)[0]
