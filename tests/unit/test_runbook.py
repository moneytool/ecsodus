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
