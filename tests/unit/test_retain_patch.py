"""Retain patcher invariants over every real Copilot-rendered fixture (PLAN §6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecsodus import cfn
from ecsodus.emit.retain_patch import (
    METADATA_KEY,
    missing_retain,
    patch_template,
    verify_patch,
)

FIX = Path(__file__).parent.parent / "fixtures" / "copilot" / "rendered"
TEMPLATES = sorted(
    p for p in FIX.rglob("*.yml") if "manifest" not in p.name and "params" not in p.name
)


def nested(tpl: dict) -> dict[str, str]:
    return {
        lid: f"https://b.s3.us-west-2.amazonaws.com/ecsodus/{lid}.yml"
        for lid, body in tpl["Resources"].items()
        if body.get("Type") == "AWS::CloudFormation::Stack"
    }


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_every_resource_retained_nothing_else_changed(path: Path) -> None:
    text = path.read_text()
    tpl = cfn.load(text)
    overrides = nested(tpl)
    result = patch_template(text, overrides)
    assert missing_retain(result.text) == []
    assert verify_patch(text, result.text, overrides) == []
    # Byte stability: removing the inserted/replaced lines gives back the original lines.
    added = [ln for ln in result.text.splitlines() if ln not in text.splitlines()]
    assert all(
        ln.strip().startswith(
            ("DeletionPolicy: Retain", "UpdateReplacePolicy: Retain", "TemplateURL: ")
        )
        for ln in added
    ), added[:5]
    kept = [ln for ln in text.splitlines() if ln in result.text.splitlines()]
    assert len(kept) >= len(text.splitlines()) - 2 * len(overrides) - sum(
        1
        for b in tpl["Resources"].values()
        for a in ("DeletionPolicy", "UpdateReplacePolicy")
        if a in b
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_metadata_fallback(path: Path) -> None:
    text = path.read_text()
    overrides = nested(cfn.load(text))
    result = patch_template(text, overrides, metadata_fallback=True)
    after = cfn.load(result.text)
    assert all(
        (b.get("Metadata") or {}).get(METADATA_KEY) == "true" for b in after["Resources"].values()
    )
    assert verify_patch(text, result.text, overrides, metadata_fallback=True) == []


def test_patch_is_idempotent() -> None:
    text = TEMPLATES[0].read_text()
    once = patch_template(text).text
    twice = patch_template(once)
    assert twice.text == once
    assert twice.changed_resources == []


def test_existing_policies_are_replaced() -> None:
    text = (
        "Resources:\n"
        "  Db:\n"
        "    Type: AWS::RDS::DBCluster\n"
        "    DeletionPolicy: Snapshot\n"
        "    UpdateReplacePolicy: Delete\n"
        "    Properties:\n"
        "      Engine: aurora-postgresql\n"
    )
    out = patch_template(text).text
    body = cfn.load(out)["Resources"]["Db"]
    assert body["DeletionPolicy"] == "Retain" and body["UpdateReplacePolicy"] == "Retain"
    assert out.count("DeletionPolicy") == 1


def test_json_templates() -> None:
    text = json.dumps({"Resources": {"T": {"Type": "AWS::SNS::Topic", "Properties": {}}}}, indent=2)
    out = patch_template(text).text
    assert cfn.load(out)["Resources"]["T"]["DeletionPolicy"] == "Retain"


def test_verify_rejects_extra_changes() -> None:
    text = TEMPLATES[0].read_text()
    patched = patch_template(text).text.replace(
        "Type: AWS::Logs::LogGroup", "Type: AWS::Logs::LogGroup\n    Condition: X", 1
    )
    assert verify_patch(text, patched)


def test_flow_style_resource_is_refused() -> None:
    text = "Resources:\n  T: {Type: AWS::SNS::Topic}\n"
    with pytest.raises(cfn.TemplateError):
        patch_template(text)


def test_override_on_non_stack_is_refused() -> None:
    text = "Resources:\n  T:\n    Type: AWS::SNS::Topic\n"
    with pytest.raises(cfn.TemplateError):
        patch_template(text, {"T": "https://x"})


def test_tagged_mapping_patches_after_semantic_load() -> None:
    # Regression: the semantic loader's `!` constructor leaked into the round-trip loader, so
    # once any template had been loaded, a tagged mapping (Copilot's Aurora addon writes
    # `!GetAZs {Ref: AWS::Region}`) made patch_template fail to parse.
    text = (
        "Resources:\n"
        "  I:\n"
        "    Type: AWS::RDS::DBInstance\n"
        "    Properties:\n"
        "      AvailabilityZone: !Select\n"
        "        - 0\n"
        "        - !GetAZs\n"
        "          Ref: AWS::Region\n"
        "      Other: !GetAZs {Ref: AWS::Region}\n"
    )
    props = cfn.load(text)["Resources"]["I"]["Properties"]
    assert props["Other"] == {"Fn::GetAZs": {"Ref": "AWS::Region"}}
    out = patch_template(text).text
    assert not verify_patch(text, out)
    assert cfn.load(out)["Resources"]["I"]["DeletionPolicy"] == "Retain"


def test_trailing_blank_lines_from_cli_output_are_not_a_change() -> None:
    text = TEMPLATES[0].read_text()
    patched = patch_template(text).text
    assert verify_patch(text + "\n  \n", patched) == []
    assert verify_patch(text, patched + "\n") == []
