"""Scheduled Job mappers (ADR-0015) against the real Copilot job render (no AWS calls)."""

from __future__ import annotations

import json

import pytest

import ecsodus.mappers.tf_data  # noqa: F401  (registers the EFS mappers)
from ecsodus.model import Inventory, Stack
from tests.helpers import ACCOUNT, REGION
from tests.unit.test_tf_compute import args, blocked, load, run, set_pid, spec_of

ARN = f"{REGION}:{ACCOUNT}"
STACK = "my-app-test-job"
SM = f"arn:aws:states:{ARN}:stateMachine:{STACK}"
RULE = f"{STACK}-Rule-ABC"
TD = f"arn:aws:ecs:{ARN}:task-definition/{STACK}:2"


@pytest.fixture
def job() -> tuple[Inventory, Stack]:
    inv, stack = load(
        "workloads/job-test.stack.yml",
        stack_name=STACK,
        workload="job",
        workload_type="Scheduled Job",
    )
    set_pid(stack, "StateMachine", SM)
    set_pid(stack, "Rule", RULE)
    set_pid(stack, "TaskDefinition", TD)
    set_pid(stack, "LogGroup", f"/copilot/{STACK}")
    return inv, stack


def test_state_machine_definition_is_substituted(job):
    inv, stack = job
    spec = spec_of(run(inv, stack, "StateMachine"))
    assert spec.tf_type == "aws_sfn_state_machine" and spec.import_id == SM
    a = args(spec)
    assert a["name"] == STACK
    definition = a["definition"]
    assert isinstance(definition, str)  # written as deployed text: the provider compares text
    assert "${" not in definition
    assert TD in definition and "my-app-test-Cluster-abc" in definition
    assert '["subnet-0aaa","subnet-0bbb"]' in definition  # the joined list, split back
    assert json.loads(definition)["StartAt"] == "Run Fargate Task"
    logging = dict(a["logging_configuration"].body)
    assert logging["level"] == "ALL" and logging["include_execution_data"] is True
    assert logging["log_destination"] == f"arn:aws:logs:{ARN}:log-group:/copilot/{STACK}:*"


def test_state_machine_live_definition_must_match(job):
    inv, stack = job
    inv.live[SM] = {"definition": json.dumps({"StartAt": "Other", "States": {}})}
    blocked(run(inv, stack, "StateMachine"), "live definition differs")


def test_state_machine_live_role_and_type_must_match(job):
    inv, stack = job
    inv.live[SM] = {"roleArn": "arn:aws:iam::123456789012:role/other"}
    blocked(run(inv, stack, "StateMachine"), "live roleArn")
    inv.live[SM] = {"type": "EXPRESS"}
    blocked(run(inv, stack, "StateMachine"), "live type")


def test_state_machine_name_must_match_arn(job):
    inv, stack = job
    set_pid(stack, "StateMachine", f"arn:aws:states:{ARN}:stateMachine:renamed")
    blocked(run(inv, stack, "StateMachine"), "StateMachineName")


def test_rule_target_assumes_a_role(job):
    inv, stack = job
    spec = spec_of(run(inv, stack, "Rule"))
    assert args(spec)["schedule_expression"] == "cron(0 12 ? * MON *)"
    [(suffix, target)] = spec.companions
    assert suffix == "target_statemachine"
    t = args(target)
    assert t["arn"] == SM and t["role_arn"].startswith(f"arn:aws:iam::{ACCOUNT}:role/")


def test_rule_target_role_drift_is_blocked(job):
    inv, stack = job
    inv.live[RULE] = {"Targets": [{"Id": "statemachine", "Arn": SM}]}  # role removed by hand
    blocked(run(inv, stack, "Rule"), "live targets")


def test_state_machine_publish_is_ignored_for_import_then_hardened(job):
    from ecsodus.emit.terraform import IMPORT_UNREAD

    inv, stack = job
    spec = spec_of(run(inv, stack, "StateMachine"))
    assert args(spec)["publish"] is False
    assert IMPORT_UNREAD["aws_sfn_state_machine"] == ("publish",)


def test_env_controller_output_comes_from_the_env_stack(job):
    """GetAtt EnvControllerAction.ManagedFileSystemID resolves to the env stack's output, which
    is what Copilot's env-controller returns (found on the 2026-10-07 AWS run)."""
    from ecsodus.mappers.resolve import Resolver, Unresolvable

    inv, stack = job
    r = Resolver(inv, stack)
    att = {"Fn::GetAtt": ["EnvControllerAction", "ManagedFileSystemID"]}
    with pytest.raises(Unresolvable, match="no such output"):
        r.resolve(att)
    inv.stacks["my-app-test"].outputs["ManagedFileSystemID"] = "fs-0abc"
    assert r.resolve(att) == "fs-0abc"
    spec = spec_of(run(inv, stack, "AccessPoint"))
    assert args(spec)["file_system_id"] == "fs-0abc"
    inv.stacks["my-app-test"].outputs["EnabledFeatures"] = "efs"
    with pytest.raises(Unresolvable, match="not an env-controller output"):
        r.resolve({"Fn::GetAtt": ["EnvControllerAction", "EnabledFeatures"]})


def test_state_machine_definition_is_written_as_live_text(job):
    """The provider compares definitions as text, so the live text is written verbatim when
    it is JSON-equal to the template's (2026-10-07 AWS run)."""
    inv, stack = job
    template_text = args(spec_of(run(inv, stack, "StateMachine")))["definition"]
    live_text = json.dumps(json.loads(template_text), indent=4)
    inv.live[SM] = {"definition": live_text}
    assert args(spec_of(run(inv, stack, "StateMachine")))["definition"] == live_text
