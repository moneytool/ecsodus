"""The change-set acceptance rule (PLAN §2.4, §13.2-3)."""

from __future__ import annotations

import json

from ecsodus.check.changeset import EMPTY, FAIL, PASS, check_change_sets


def rc(lid: str, details: list, action: str = "Modify", replacement: str = "False",
       rtype: str = "AWS::SNS::Topic", scope: list | None = None) -> dict:
    return {"Type": "Resource", "ResourceChange": {
        "Action": action, "LogicalResourceId": lid, "ResourceType": rtype,
        "Replacement": replacement, "Scope": scope or [], "Details": details}}


def policy(attr: str = "DeletionPolicy") -> dict:
    return {"Target": {"Attribute": attr, "RequiresRecreation": "Never"}, "Evaluation": "Static",
            "ChangeSource": "DirectModification"}


def cs(*changes: dict, name: str = "demo-test-api") -> dict:
    return {"StackName": name, "Status": "CREATE_COMPLETE", "Changes": list(changes)}


def test_policy_only_passes() -> None:
    r = check_change_sets([cs(rc("A", [policy(), policy("UpdateReplacePolicy")]))])
    assert r.verdict == PASS and r.accepted == 1


def test_policy_scope_without_details_passes() -> None:
    r = check_change_sets([cs(rc("A", [], scope=["DeletionPolicy"]))])
    assert r.verdict == PASS


def test_property_change_fails() -> None:
    d = {"Target": {"Attribute": "Properties", "Name": "TopicName",
                    "RequiresRecreation": "Always"}}
    r = check_change_sets([cs(rc("A", [d], replacement="True"))])
    assert r.verdict == FAIL
    assert any("Replacement" in e for e in r.errors)


def test_add_remove_import_dynamic_actions_fail() -> None:
    for action in ("Add", "Remove", "Import", "Dynamic", "SyncWithActual"):
        r = check_change_sets([cs(rc("A", [policy()], action=action))])
        assert r.verdict == FAIL, action


def test_conditional_replacement_fails() -> None:
    r = check_change_sets([cs(rc("A", [policy()], replacement="Conditional"))])
    assert r.verdict == FAIL


def test_nested_template_url_allowed_only_for_patched_wrapper() -> None:
    d = {"Target": {"Attribute": "Properties", "Name": "TemplateURL",
                    "RequiresRecreation": "Never"}}
    stack = "AWS::CloudFormation::Stack"
    ok = check_change_sets([cs(rc("AddonsStack", [d, policy()], rtype=stack))],
                           patched_nested=["AddonsStack"])
    assert ok.verdict == PASS
    bad = check_change_sets([cs(rc("AddonsStack", [d], rtype=stack))], patched_nested=[])
    assert bad.verdict == FAIL
    other = check_change_sets([cs(rc("Topic", [d]))], patched_nested=["Topic"])
    assert other.verdict == FAIL


def test_metadata_only_with_flag_and_values() -> None:
    d = {"Target": {"Attribute": "Metadata", "RequiresRecreation": "Never",
                    "BeforeValue": json.dumps({"aws:copilot:description": "x"}),
                    "AfterValue": json.dumps({"aws:copilot:description": "x",
                                              "ecsodus:retain": "true"})}}
    assert check_change_sets([cs(rc("A", [d, policy()]))]).verdict == FAIL
    assert check_change_sets([cs(rc("A", [d, policy()]))],
                             allow_metadata_key=True).verdict == PASS
    tampered = json.loads(d["Target"]["AfterValue"]) | {"other": "1"}
    d2 = {"Target": dict(d["Target"], AfterValue=json.dumps(tampered))}
    assert check_change_sets([cs(rc("A", [d2]))], allow_metadata_key=True).verdict == FAIL


def test_dynamic_from_nested_needs_flag() -> None:
    d = {"Target": {"Attribute": "Properties", "Name": "ContainerDefinitions"},
         "Evaluation": "Dynamic", "ChangeSource": "ResourceAttribute",
         "CausingEntity": "AddonsStack.Outputs.TableName"}
    change = rc("TaskDefinition", [d], replacement="False")
    assert check_change_sets([cs(change)], patched_nested=["AddonsStack"]).verdict == FAIL
    assert check_change_sets([cs(change)], patched_nested=["AddonsStack"],
                             allow_nested_dynamic=True).verdict == PASS


def test_empty_change_set_is_not_a_pass() -> None:
    empty = {"StackName": "s", "Status": "FAILED", "Changes": [],
             "StatusReason": "The submitted information didn't contain changes."}
    assert check_change_sets([empty]).verdict == EMPTY


def test_failed_change_set_for_other_reason_fails() -> None:
    bad = {"StackName": "s", "Status": "FAILED", "Changes": [policy()],
           "StatusReason": "Template format error"}
    assert check_change_sets([bad]).verdict == FAIL


def test_nested_change_sets_checked_too() -> None:
    root = cs(rc("A", [policy()]))
    child = cs(rc("Table", [{"Target": {"Attribute": "Properties", "Name": "BillingMode"}}]),
               name="child")
    assert check_change_sets([root, child]).verdict == FAIL
