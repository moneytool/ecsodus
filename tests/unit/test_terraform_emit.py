"""Lifecycle merging in the Terraform emitter."""

from __future__ import annotations

from ecsodus.emit import hcl
from ecsodus.emit.hcl import Block, Raw
from ecsodus.emit.terraform import _with_lifecycle


def render(tf_type, body, stateful):
    return hcl.block("resource", (tf_type, "x"), _with_lifecycle(tf_type, body, stateful))


def test_prevent_destroy_added_for_stateful() -> None:
    out = render("aws_dynamodb_table", [("name", "t")], True)
    assert "prevent_destroy = true" in out


def test_merges_existing_ignore_changes() -> None:
    body = [
        ("name", "s"),
        ("lifecycle", Block([("ignore_changes", Raw("[task_definition, desired_count]"))])),
    ]
    out = render("aws_ecs_service", body, True)
    assert out.count("lifecycle {") == 1
    assert "ignore_changes  = [task_definition, desired_count]" in out
    assert "prevent_destroy = true" in out


def test_import_unread_arguments_ignored() -> None:
    body = [
        ("cluster_identifier", "db"),
        ("skip_final_snapshot", False),
        ("final_snapshot_identifier", "db-final"),
    ]
    out = render("aws_rds_cluster", body, True)
    assert "ignore_changes  = [skip_final_snapshot, final_snapshot_identifier]" in out


def test_non_stateful_without_extras_untouched() -> None:
    body = [("name", "x")]
    assert _with_lifecycle("aws_sns_topic", body, False) == body
