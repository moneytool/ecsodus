"""The change-set acceptance rule (PLAN §2.4, §13.2-3)."""

from __future__ import annotations

import json

from ecsodus.check.changeset import EMPTY, FAIL, PASS, check_change_sets

URL = "https://b.s3.us-west-2.amazonaws.com/ecsodus/child.yml"


def rc(lid, details, action="Modify", replacement="False", rtype="AWS::SNS::Topic", scope=None):
    return {
        "Type": "Resource",
        "ResourceChange": {
            "Action": action,
            "LogicalResourceId": lid,
            "ResourceType": rtype,
            "Replacement": replacement,
            "Scope": scope or [],
            "Details": details,
        },
    }


def policy(attr="DeletionPolicy"):
    return {
        "Target": {"Attribute": attr, "RequiresRecreation": "Never"},
        "Evaluation": "Static",
        "ChangeSource": "DirectModification",
    }


def cs(*changes, name="demo-test-api", cid="root", parent=None):
    doc = {
        "StackName": name,
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "ChangeSetId": cid,
        "Changes": list(changes),
    }
    if parent:
        doc["ParentChangeSetId"] = parent
    return doc


def nested_change(url=URL, child="child"):
    d = {
        "Target": {
            "Attribute": "Properties",
            "Name": "TemplateURL",
            "RequiresRecreation": "Never",
            "AfterValue": url,
        }
    }
    change = rc("AddonsStack", [d, policy()], rtype="AWS::CloudFormation::Stack")
    if child:
        change["ResourceChange"]["ChangeSetId"] = child
    return change


def child_cs(*changes):
    return cs(*changes, name="child", cid="child", parent="root")


def test_policy_only_passes() -> None:
    r = check_change_sets([cs(rc("A", [policy(), policy("UpdateReplacePolicy")]))])
    assert r.verdict == PASS and r.accepted == 1


def test_policy_scope_without_details_passes() -> None:
    assert check_change_sets([cs(rc("A", [], scope=["DeletionPolicy"]))]).verdict == PASS


def test_property_change_fails() -> None:
    d = {"Target": {"Attribute": "Properties", "Name": "TopicName", "RequiresRecreation": "Always"}}
    r = check_change_sets([cs(rc("A", [d], replacement="True"))])
    assert r.verdict == FAIL and any("Replacement" in e for e in r.errors)


def test_add_remove_import_dynamic_actions_fail() -> None:
    for action in ("Add", "Remove", "Import", "Dynamic", "SyncWithActual"):
        assert check_change_sets([cs(rc("A", [policy()], action=action))]).verdict == FAIL


def test_conditional_replacement_fails() -> None:
    assert check_change_sets([cs(rc("A", [policy()], replacement="Conditional"))]).verdict == FAIL


def test_nested_template_url_must_be_the_patched_child() -> None:
    child = child_cs(rc("Table", [policy()]))
    nested = {"AddonsStack": URL}
    assert check_change_sets([cs(nested_change()), child], patched_nested=nested).verdict == PASS
    assert check_change_sets([cs(nested_change()), child], patched_nested={}).verdict == FAIL
    evil = cs(nested_change("https://evil.example/x.yml"))
    assert check_change_sets([evil, child], patched_nested=nested).verdict == FAIL
    # IDs without URLs cannot verify the new value: fail closed.
    assert (
        check_change_sets([cs(nested_change()), child], patched_nested=["AddonsStack"]).verdict
        == FAIL
    )
    # TemplateURL on a non-stack resource is never allowed.
    d = {
        "Target": {
            "Attribute": "Properties",
            "Name": "TemplateURL",
            "RequiresRecreation": "Never",
            "AfterValue": URL,
        }
    }
    assert check_change_sets([cs(rc("Topic", [d]))], patched_nested={"Topic": URL}).verdict == FAIL


def test_missing_nested_change_set_fails() -> None:
    r = check_change_sets([cs(nested_change())], patched_nested={"AddonsStack": URL})
    assert r.verdict == FAIL and any("not supplied" in e for e in r.errors)


def test_unreferenced_or_extra_root_fails() -> None:
    stray = cs(rc("X", [policy()]), name="other", cid="other", parent="root")
    assert check_change_sets([cs(rc("A", [policy()])), stray]).verdict == FAIL
    assert (
        check_change_sets([cs(rc("A", [policy()])), cs(rc("B", [policy()]), cid="root2")]).verdict
        == FAIL
    )


def test_in_progress_or_unexecutable_fails() -> None:
    assert (
        check_change_sets(
            [{"StackName": "s", "Status": "CREATE_IN_PROGRESS", "ChangeSetId": "root"}]
        ).verdict
        == FAIL
    )
    doc = cs(rc("A", [policy()]))
    doc["ExecutionStatus"] = "UNAVAILABLE"
    assert check_change_sets([doc]).verdict == FAIL


def test_metadata_only_with_flag_and_values() -> None:
    d = {
        "Target": {
            "Attribute": "Metadata",
            "RequiresRecreation": "Never",
            "BeforeValue": json.dumps({"aws:copilot:description": "x"}),
            "AfterValue": json.dumps({"aws:copilot:description": "x", "ecsodus:retain": "true"}),
        }
    }
    assert check_change_sets([cs(rc("A", [d, policy()]))]).verdict == FAIL
    assert check_change_sets([cs(rc("A", [d, policy()]))], allow_metadata_key=True).verdict == PASS
    tampered = json.loads(d["Target"]["AfterValue"]) | {"other": "1"}
    d2 = {"Target": dict(d["Target"], AfterValue=json.dumps(tampered))}
    assert check_change_sets([cs(rc("A", [d2]))], allow_metadata_key=True).verdict == FAIL


def test_dynamic_from_nested_needs_flag_and_the_child_change_set() -> None:
    d = {
        "Target": {"Attribute": "Properties", "Name": "ContainerDefinitions"},
        "Evaluation": "Dynamic",
        "ChangeSource": "ResourceAttribute",
        "CausingEntity": "AddonsStack.Outputs.TableName",
    }
    nested = {"AddonsStack": URL}
    root = cs(rc("TaskDefinition", [d]), nested_change())
    child = child_cs(rc("Table", [policy()]))
    assert check_change_sets([root, child], patched_nested=nested).verdict == FAIL
    ok = check_change_sets([root, child], patched_nested=nested, allow_nested_dynamic=True)
    assert ok.verdict == PASS
    # Without the child's change set the dynamic entry cannot be trusted.
    lone = cs(rc("TaskDefinition", [d]))
    bad = check_change_sets([lone], patched_nested=nested, allow_nested_dynamic=True)
    assert bad.verdict == FAIL


def test_empty_change_set_is_not_a_pass() -> None:
    empty = {
        "StackName": "s",
        "Status": "FAILED",
        "Changes": [],
        "ChangeSetId": "root",
        "StatusReason": "The submitted information didn't contain changes.",
    }
    assert check_change_sets([empty]).verdict == EMPTY


def test_failed_change_set_for_other_reason_fails() -> None:
    bad = {
        "StackName": "s",
        "Status": "FAILED",
        "Changes": [],
        "ChangeSetId": "root",
        "StatusReason": "Template format error",
    }
    assert check_change_sets([bad]).verdict == FAIL


def test_nested_change_sets_checked_too() -> None:
    child = child_cs(rc("Table", [{"Target": {"Attribute": "Properties", "Name": "BillingMode"}}]))
    assert (
        check_change_sets([cs(nested_change()), child], patched_nested={"AddonsStack": URL}).verdict
        == FAIL
    )


def test_missing_execution_status_or_foreign_parent_fails() -> None:
    doc = cs(rc("A", [policy()]))
    del doc["ExecutionStatus"]
    assert check_change_sets([doc]).verdict == FAIL
    child = child_cs(rc("Table", [policy()]))
    child["ParentChangeSetId"] = "someone-else"
    assert (
        check_change_sets([cs(nested_change()), child], patched_nested={"AddonsStack": URL}).verdict
        == FAIL
    )


def test_nested_change_sets_are_unavailable_from_the_root_only() -> None:
    from ecsodus.check.changeset import NESTED_UNAVAILABLE_REASON

    child = child_cs(rc("Table", [policy()]))
    child["ExecutionStatus"] = "UNAVAILABLE"
    child["StatusReason"] = NESTED_UNAVAILABLE_REASON
    nested = {"AddonsStack": URL}
    assert check_change_sets([cs(nested_change()), child], patched_nested=nested).verdict == PASS
    child["StatusReason"] = "something else"
    assert check_change_sets([cs(nested_change()), child], patched_nested=nested).verdict == FAIL
    root = cs(nested_change())
    root["ExecutionStatus"] = "UNAVAILABLE"
    root["StatusReason"] = NESTED_UNAVAILABLE_REASON
    child["StatusReason"] = NESTED_UNAVAILABLE_REASON
    assert check_change_sets([root, child], patched_nested=nested).verdict == FAIL
