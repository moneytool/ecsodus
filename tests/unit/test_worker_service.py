"""Worker Service mappers (ADR-0014) against the real Copilot worker render (no AWS calls)."""

from __future__ import annotations

import json
import re

import pytest

from ecsodus.mappers.resolve import Resolver, Unresolvable
from ecsodus.mappers.tfmap import MANUAL_CLEANUP, NotImported
from ecsodus.model import Inventory, Stack
from tests.golden.live_synth import _with_lambda_code
from tests.helpers import ACCOUNT, REGION
from tests.unit.test_tf_compute import args, blocked, load, render, run, set_pid, spec_of

ARN = f"{REGION}:{ACCOUNT}"
STACK = "my-app-test-dogworker"
FN = f"{STACK}-BacklogPerTaskCalculatorF-AbC"
RULE = f"{STACK}-BacklogPerTaskScheduledRule-XYZ"
SID = f"{STACK}-PermissionToInvokeBacklogPerTask-QWE"


@pytest.fixture
def worker() -> tuple[Inventory, Stack]:
    inv, stack = load(
        "workloads/worker-test.stack.yml",
        stack_name=STACK,
        workload="dogworker",
        workload_type="Worker Service",
    )
    stack.template_body = _with_lambda_code(stack.template_body)
    set_pid(stack, "BacklogPerTaskCalculatorFunction", FN)
    set_pid(stack, "BacklogPerTaskScheduledRule", RULE)
    set_pid(stack, "PermissionToInvokeBacklogPerTaskCalculatorLambda", SID)
    set_pid(stack, "Service", f"arn:aws:ecs:{ARN}:service/my-app-test-Cluster-abc/{STACK}-Svc")
    sqs = f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}"
    for res in stack.resources:
        if res.type == "AWS::SQS::Queue":
            res.physical_id = f"{sqs}/{STACK}-{res.logical_id}-1AB"
    return inv, stack


# -- Lambda ---------------------------------------------------------------------------------


def test_backlog_calculator_is_imported_with_code_ignored(worker):
    inv, stack = worker
    spec = spec_of(run(inv, stack, "BacklogPerTaskCalculatorFunction"))
    assert spec.tf_type == "aws_lambda_function" and spec.import_id == FN
    a = args(spec)
    assert a["function_name"] == FN and a["runtime"] == "nodejs20.x"
    assert a["s3_key"].startswith("manual/scripts/custom-resources/backlogpertaskcalculator")
    assert "ignore_changes = [s3_bucket, s3_key]" in render(spec)
    variables = dict(a["environment"].body)["variables"]
    assert variables["NAMESPACE"] == f"my-app-test-{'dogworker'}"
    assert variables["QUEUE_NAMES"].split(",")[0] == f"{STACK}-EventsQueue-1AB"
    assert any("nodejs20.x is deprecated" in n for n in spec.notes)


def test_custom_resource_handlers_stay_manual_cleanup(worker):
    inv, stack = worker
    for lid in ("DynamicDesiredCountFunction", "EnvControllerFunction"):
        result = run(inv, stack, lid)
        assert isinstance(result, NotImported) and result.fate == MANUAL_CLEANUP, lid


def test_backlog_calculator_outside_a_worker_is_not_a_runtime_function(worker):
    inv, stack = worker
    stack.workload_type = "Backend Service"
    result = run(inv, stack, "BacklogPerTaskCalculatorFunction")
    assert isinstance(result, NotImported) and result.fate == MANUAL_CLEANUP


def test_backlog_calculator_without_s3_code_is_blocked():
    inv, stack = load(
        "workloads/worker-test.stack.yml", stack_name=STACK, workload_type="Worker Service"
    )  # the render, before Copilot fills Code in
    blocked(run(inv, stack, "BacklogPerTaskCalculatorFunction"), "Code must be")


@pytest.mark.parametrize("pid", [SID, f"arn:aws:lambda:{ARN}:function:{FN}|{SID}"])
def test_permission_import_id_from_either_physical_id_form(worker, pid: str):
    inv, stack = worker
    set_pid(stack, "PermissionToInvokeBacklogPerTaskCalculatorLambda", pid)
    spec = spec_of(run(inv, stack, "PermissionToInvokeBacklogPerTaskCalculatorLambda"))
    assert spec.tf_type == "aws_lambda_permission"
    assert spec.import_id == f"{FN}/{SID}"
    a = args(spec)
    assert a["principal"] == "events.amazonaws.com"
    assert a["source_arn"] == f"arn:aws:events:{ARN}:rule/{RULE}"


def test_permission_missing_from_live_policy_is_blocked(worker):
    inv, stack = worker
    inv.live[FN] = {"PolicySids": ["something-else"]}
    blocked(run(inv, stack, "PermissionToInvokeBacklogPerTaskCalculatorLambda"), "live policy")


# -- EventBridge ----------------------------------------------------------------------------


def test_events_rule_with_its_target_as_a_companion(worker):
    inv, stack = worker
    spec = spec_of(run(inv, stack, "BacklogPerTaskScheduledRule"))
    assert spec.tf_type == "aws_cloudwatch_event_rule" and spec.import_id == RULE
    a = args(spec)
    assert a["schedule_expression"] == "rate(1 minute)" and a["state"] == "ENABLED"
    [(suffix, target)] = spec.companions
    assert suffix == "target_BacklogPerTaskCalculatorFunctionTrigger"
    assert target.tf_type == "aws_cloudwatch_event_target"
    assert target.import_id == f"{RULE}/BacklogPerTaskCalculatorFunctionTrigger"
    assert args(target)["arn"] == f"arn:aws:lambda:{ARN}:function:{FN}"


def test_events_rule_live_targets_must_match(worker):
    inv, stack = worker
    inv.live[RULE] = {"Targets": [{"Id": "Other", "Arn": "arn:aws:lambda:x"}]}
    blocked(run(inv, stack, "BacklogPerTaskScheduledRule"), "live targets")
    inv.live[RULE] = {
        "Targets": [
            {
                "Id": "BacklogPerTaskCalculatorFunctionTrigger",
                "Arn": f"arn:aws:lambda:{ARN}:function:{FN}",
                "Input": "{}",  # added outside CloudFormation
            }
        ]
    }
    blocked(run(inv, stack, "BacklogPerTaskScheduledRule"), "live targets")


def test_events_rule_on_a_custom_bus_is_blocked(worker):
    inv, stack = worker
    set_pid(stack, "BacklogPerTaskScheduledRule", f"my-bus|{RULE}")
    blocked(run(inv, stack, "BacklogPerTaskScheduledRule"), "default event bus")


# -- SNS subscriptions ----------------------------------------------------------------------


SUB = f"arn:aws:sns:{ARN}:my-app-test-dogsvc-givesdogs:0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def test_subscription_with_filter_policy(worker):
    inv, stack = worker
    set_pid(stack, "dogsvcgivesdogsSNSTopicSubscription", SUB)
    spec = spec_of(run(inv, stack, "dogsvcgivesdogsSNSTopicSubscription"))
    assert spec.tf_type == "aws_sns_topic_subscription" and spec.import_id == SUB
    a = args(spec)
    assert a["topic_arn"] == f"arn:aws:sns:{ARN}:my-app-test-dogsvc-givesdogs"
    assert a["protocol"] == "sqs"
    assert a["endpoint"] == f"arn:aws:sqs:{ARN}:{STACK}-EventsQueue-1AB"
    text = render(spec)
    assert re.search(r"filter_policy\s+= jsonencode\(", text)
    assert "anything-but" in text
    assert a["confirmation_timeout_in_minutes"] == 1 and a["endpoint_auto_confirms"] is False
    assert "raw_message_delivery" not in a  # the default, omitted


def test_subscription_live_drift_is_blocked(worker):
    inv, stack = worker
    set_pid(stack, "dogsvcgivesdogsSNSTopicSubscription", SUB)
    inv.live[SUB] = {"FilterPolicy": json.dumps({"store": ["other"]})}
    blocked(run(inv, stack, "dogsvcgivesdogsSNSTopicSubscription"), "FilterPolicy differs")
    inv.live[SUB] = {"RawMessageDelivery": "true"}
    blocked(run(inv, stack, "dogsvcgivesdogsSNSTopicSubscription"), "RawMessageDelivery")


def test_subscription_without_an_arn_is_blocked(worker):
    inv, stack = worker
    set_pid(stack, "mytopicmytopicfifoSNSTopicSubscription", "pending confirmation")
    blocked(run(inv, stack, "mytopicmytopicfifoSNSTopicSubscription"), "not an ARN")


# -- resolver -------------------------------------------------------------------------------


def test_queue_name_and_rule_arn_resolve_from_physical_ids(worker):
    inv, stack = worker
    r = Resolver(inv, stack)
    assert r.resolve({"Fn::GetAtt": ["mytopicmytopicfifoEventsQueue", "QueueName"]}) == (
        f"{STACK}-mytopicmytopicfifoEventsQueue-1AB"
    )
    assert r.resolve({"Fn::GetAtt": ["BacklogPerTaskScheduledRule", "Arn"]}) == (
        f"arn:aws:events:{ARN}:rule/{RULE}"
    )


def test_external_exports_resolve_import_value(worker):
    inv, stack = worker
    r = Resolver(inv, stack)
    with pytest.raises(Unresolvable, match="stack-fs-12345"):
        r.resolve({"Fn::ImportValue": "stack-fs-12345"})
    inv.external_exports["stack-fs-12345"] = {"value": "fs-0abc", "stack": "shared-efs"}
    assert r.resolve({"Fn::ImportValue": "stack-fs-12345"}) == "fs-0abc"
    # Survives the inventory round trip.
    assert Inventory.from_dict(json.loads(inv.to_json())).external_exports == inv.external_exports
