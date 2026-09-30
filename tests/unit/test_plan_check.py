"""Terraform plan and state gates (PLAN §2.6, §13.6)."""

from __future__ import annotations

import pytest

from ecsodus.check.plan import IMPORT, STEADY, check_plan, check_state


def change(address: str, actions: list[str], importing: bool = False, mode: str = "managed"):
    c = {"actions": actions}
    if importing:
        c["importing"] = {"id": "x"}
    return {"address": address, "mode": mode, "change": c}


def plan(*rcs):
    return {"format_version": "1.2", "resource_changes": list(rcs)}


def test_import_id_must_match_manifest() -> None:
    p = plan(change("aws_s3_bucket.a", ["no-op"], True))
    assert check_plan(p, {"aws_s3_bucket.a": "x"}, IMPORT).ok
    r = check_plan(p, {"aws_s3_bucket.a": "prod-bucket"}, IMPORT)
    assert not r.ok and "manifest expects" in r.errors[0]


def test_steady_requires_full_coverage() -> None:
    assert not check_plan(plan(), ["aws_s3_bucket.a"], STEADY).ok  # empty/targeted plan
    assert check_plan(plan(change("aws_s3_bucket.a", ["no-op"])), ["aws_s3_bucket.a"], STEADY).ok


def test_errored_plan_fails() -> None:
    assert not check_plan({"format_version": "1.2", "errored": True}, [], STEADY).ok


def test_pure_imports_pass() -> None:
    p = plan(change("aws_sns_topic.a", ["no-op"], True), change("aws_sns_topic.b", ["no-op"], True))
    assert check_plan(p, ["aws_sns_topic.a", "aws_sns_topic.b"], IMPORT).ok


def test_import_with_update_fails() -> None:
    p = plan(change("aws_sns_topic.a", ["update"], True))
    r = check_plan(p, ["aws_sns_topic.a"], IMPORT)
    assert not r.ok and "update" in r.errors[0]


def test_replace_and_create_fail() -> None:
    p = plan(change("aws_lb.a", ["delete", "create"], True), change("aws_lb.b", ["create"]))
    r = check_plan(p, ["aws_lb.a"], IMPORT)
    assert any("delete/create" in e for e in r.errors)
    assert any("aws_lb.b: create" in e for e in r.errors)


def test_missing_and_unexpected_imports() -> None:
    p = plan(change("aws_sns_topic.x", ["no-op"], True))
    r = check_plan(p, ["aws_sns_topic.a"], IMPORT)
    assert any("missing" in e for e in r.errors)
    assert any("did not generate" in e for e in r.errors)


def test_steady_requires_zero_changes() -> None:
    assert check_plan(plan(change("a.b", ["no-op"])), ["a.b"], STEADY).ok
    assert not check_plan(plan(change("a.b", ["update"])), [], STEADY).ok
    assert not check_plan(plan(change("a.b", ["no-op"], True)), [], STEADY).ok


def test_data_sources_are_rejected() -> None:
    p = plan(change("data.aws_secretsmanager_secret_version.s", ["read"], mode="data"))
    assert not check_plan(p, [], STEADY).ok
    assert not check_plan(p, [], IMPORT).ok


def test_rejects_non_plan_documents() -> None:
    with pytest.raises(ValueError):
        check_plan({"foo": 1}, [], IMPORT)


def test_state_check() -> None:
    assert check_state(["a.b", "c.d"], ["a.b"]).ok
    r = check_state(["a.b"], ["a.b", "c.d"])
    assert not r.ok and "c.d" in r.errors[0]


def test_forgotten_task_definition_in_steady_phase() -> None:
    p = plan(change("aws_ecs_task_definition.td", ["forget"]), change("aws_sns_topic.a", ["no-op"]))
    expected = ["aws_ecs_task_definition.td", "aws_sns_topic.a"]
    assert not check_plan(p, expected, STEADY).ok
    assert check_plan(p, expected, STEADY, forgotten=["aws_ecs_task_definition.td"]).ok


def test_forgotten_is_limited_to_task_definitions_with_a_forget_action() -> None:
    assert not check_plan(
        plan(), {"aws_s3_bucket.prod": "b"}, STEADY, forgotten=["aws_s3_bucket.prod"]
    ).ok
    assert not check_plan(
        plan(),
        {"aws_ecs_task_definition.td": "arn"},
        STEADY,
        forgotten=["aws_ecs_task_definition.td"],
    ).ok


def test_non_aws_provider_rejected() -> None:
    rc = change("aws_s3_bucket.a", ["no-op"], True)
    rc["provider_name"] = "registry.terraform.io/evil/aws"
    assert not check_plan(plan(rc), ["aws_s3_bucket.a"], IMPORT).ok


def test_steady_identity_must_match_manifest() -> None:
    def rc(before):
        r = change("aws_s3_bucket.a", ["no-op"])
        r["change"]["before"] = before
        return r

    assert check_plan(plan(rc({"id": "bucket-a"})), {"aws_s3_bucket.a": "bucket-a"}, STEADY).ok
    assert not check_plan(plan(rc({"id": "bucket-b"})), {"aws_s3_bucket.a": "bucket-a"}, STEADY).ok
    assert not check_plan(plan(rc(None)), {"aws_s3_bucket.a": "bucket-a"}, STEADY).ok
    svc = {
        "id": "arn:aws:ecs:us-west-2:1:service/my-cluster/my-svc",
        "cluster": "arn:...:cluster/my-cluster",
    }
    r = change("aws_ecs_service.s", ["no-op"])
    r["change"]["before"] = svc
    assert check_plan(plan(r), {"aws_ecs_service.s": "my-cluster/my-svc"}, STEADY).ok


def test_exact_provider_and_matching_type() -> None:
    r = change("aws_s3_bucket.a", ["no-op"], True)
    r["provider_name"] = "evil.example/hashicorp/aws"
    assert not check_plan(plan(r), ["aws_s3_bucket.a"], IMPORT).ok
    r2 = change("aws_s3_bucket.a", ["no-op"], True)
    r2["type"] = "aws_iam_role"
    assert not check_plan(plan(r2), ["aws_s3_bucket.a"], IMPORT).ok
