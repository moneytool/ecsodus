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
    assert len(r.errors) == 2


def test_missing_and_unexpected_imports() -> None:
    p = plan(change("aws_sns_topic.x", ["no-op"], True))
    r = check_plan(p, ["aws_sns_topic.a"], IMPORT)
    assert any("missing" in e for e in r.errors)
    assert any("did not generate" in e for e in r.errors)


def test_steady_requires_zero_changes() -> None:
    assert check_plan(plan(change("a.b", ["no-op"])), [], STEADY).ok
    assert not check_plan(plan(change("a.b", ["update"])), [], STEADY).ok
    assert not check_plan(plan(change("a.b", ["no-op"], True)), [], STEADY).ok


def test_data_sources_read_is_allowed() -> None:
    p = plan(change("data.aws_caller_identity.c", ["read"], mode="data"))
    assert check_plan(p, [], STEADY).ok


def test_rejects_non_plan_documents() -> None:
    with pytest.raises(ValueError):
        check_plan({"foo": 1}, [], IMPORT)


def test_state_check() -> None:
    assert check_state(["a.b", "c.d"], ["a.b"]).ok
    r = check_state(["a.b"], ["a.b", "c.d"])
    assert not r.ok and "c.d" in r.errors[0]
