"""End-to-end offline pipeline: inventory.json -> generate -> check (and terraform validate)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from ecsodus.cli import main
from tests.synthetic import app


@pytest.fixture
def generated(tmp_path: Path) -> Path:
    inv = app()
    inv_path = tmp_path / "inventory.json"
    inv.save(inv_path)
    out = tmp_path / "infra"
    rc = main(["generate", str(inv_path), "--out", str(out), "--patch-bucket", "my-bucket"])
    assert rc == 0
    return out


def test_generate_outputs(generated: Path) -> None:
    names = {p.name for p in generated.iterdir()}
    assert {
        "versions.tf",
        "provider.tf",
        "backend.hcl.example",
        "ecsodus-manifest.json",
        "REPORT.md",
        "RUNBOOK.md",
        "retain-patches",
        ".gitignore",
    } <= names
    assert "demo-test-api.tf" in names and "demo-test.tf" in names
    # Secret-bearing files are 0600.
    mode = stat.S_IMODE(os.stat(generated / "demo-test-api.tf").st_mode)
    assert mode == 0o600
    manifest = json.loads((generated / "ecsodus-manifest.json").read_text())
    addresses = {i["address"] for i in manifest["imports"]}
    assert "aws_cloudwatch_log_group.api_log_group" in addresses
    assert manifest["retain_patches"]["demo-test-api"]["nested"]["AddonsStack"]["stack"] == (
        "demo-test-api-AddonsStack-1"
    )
    tf = (generated / "demo-test-api.tf").read_text()
    assert "import {" in tf and "to = aws_cloudwatch_log_group.api_log_group" in tf


def test_retain_patch_points_parent_at_patched_child(generated: Path) -> None:
    manifest = json.loads((generated / "ecsodus-manifest.json").read_text())
    child_url = manifest["retain_patches"]["demo-test-api-AddonsStack-1"]["url"]
    parent = (generated / "retain-patches" / "demo-test-api.yml").read_text()
    assert f"TemplateURL: {json.dumps(child_url)}" in parent
    assert parent.count("DeletionPolicy: Retain") == 4


def test_runbook_gates_teardown(generated: Path, tmp_path: Path) -> None:
    rb = (generated / "RUNBOOK.md").read_text()
    assert "UNVERIFIED TEARDOWN" in rb
    assert "Not emitted" in rb and "aws cloudformation delete-stack " not in rb
    assert "ecsodus check --changeset" in rb and "--include-nested-stacks" in rb
    assert "## 6. Verify" in rb and "## 7. Never" in rb
    inv_path = tmp_path / "inventory.json"
    out2 = tmp_path / "infra2"
    assert (
        main(
            [
                "generate",
                str(inv_path),
                "--out",
                str(out2),
                "--patch-bucket",
                "b",
                "--i-understand-teardown-is-unverified",
            ]
        )
        == 0
    )
    rb2 = (out2 / "RUNBOOK.md").read_text()
    assert "aws cloudformation delete-stack --stack-name demo-test-api" in rb2
    assert rb2.index("demo-test-api\n") < rb2.index("delete-stack --stack-name demo-test\n")


def test_check_commands(generated: Path, tmp_path: Path, capsys) -> None:
    manifest = generated / "ecsodus-manifest.json"
    records = json.loads(manifest.read_text())["imports"]
    imports = [i["address"] for i in records]
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": i["address"],
                "mode": "managed",
                "change": {"actions": ["no-op"], "importing": {"id": i["id"]}},
            }
            for i in records
        ],
    }
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    assert main(["check", str(p), "--manifest", str(manifest), "--phase", "import"]) == 0
    plan["resource_changes"][0]["change"]["actions"] = ["update"]
    p.write_text(json.dumps(plan))
    assert main(["check", str(p), "--manifest", str(manifest), "--phase", "import"]) == 1
    state = tmp_path / "state.txt"
    state.write_text("\n".join(imports))
    assert main(["check", "--state", str(state), "--manifest", str(manifest)]) == 0
    empty = tmp_path / "cs.json"
    empty.write_text(
        json.dumps(
            {
                "StackName": "s",
                "Status": "FAILED",
                "Changes": [],
                "StatusReason": "didn't contain changes",
            }
        )
    )
    assert (
        main(
            [
                "check",
                "--changeset",
                str(empty),
                "--manifest",
                str(manifest),
                "--stack",
                "demo-test-api",
            ]
        )
        == 3
    )


def test_template_diff(generated: Path, tmp_path: Path) -> None:
    inv = app()
    cur = tmp_path / "cur.yml"
    cur.write_text(inv.stacks["demo-test"].template_body)
    patched = generated / "retain-patches" / "demo-test.yml"
    assert main(["check", "--template-diff", str(cur), str(patched)]) == 0
    tampered = tmp_path / "t.yml"
    tampered.write_text(patched.read_text().replace("10.0.0.0/16", "10.1.0.0/16"))
    assert main(["check", "--template-diff", str(cur), str(tampered)]) == 1


def test_stale_inventory_refused(tmp_path: Path) -> None:
    inv = app()
    inv.captured_at = "2026-01-01T00:00:00+00:00"
    path = tmp_path / "inventory.json"
    inv.save(path)
    with pytest.raises(SystemExit):
        main(["generate", str(path), "--out", str(tmp_path / "o"), "--patch-bucket", "b"])


def test_report_command(tmp_path: Path) -> None:
    inv = app(worker_type="Worker Service")
    path = tmp_path / "inventory.json"
    inv.save(path)
    out = tmp_path / "REPORT.md"
    assert main(["report", str(path), "-o", str(out)]) == 0
    text = out.read_text()
    assert "keep the CloudFormation" in text
    assert "Worker Service" in text and "kept" in text
    assert "Deleting this stack <b>without</b> the retain patch" in text


@pytest.mark.terraform
@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_validate(generated: Path) -> None:
    env = dict(os.environ)
    cache = Path.home() / ".cache" / "ecsodus-tf-plugins"
    cache.mkdir(parents=True, exist_ok=True)
    env["TF_PLUGIN_CACHE_DIR"] = str(cache)
    subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=generated,
        env=env,
        check=True,
        capture_output=True,
        timeout=600,
    )
    res = subprocess.run(
        ["terraform", "validate", "-no-color"],
        cwd=generated,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_runbook_blocks_stop_at_a_failing_check(generated: Path, tmp_path: Path) -> None:
    """Run a real generated block with a failing `ecsodus` and a recording `aws` stub."""
    import re

    rb = (generated / "RUNBOOK.md").read_text()
    block = next(b for b in re.findall(r"```bash\n(.*?)```", rb, re.S) if "execute-change-set" in b)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "ecsodus").write_text('#!/bin/sh\necho "ecsodus $*" >> ' + str(log) + "\nexit 1\n")
    (bin_dir / "aws").write_text('#!/bin/sh\necho "aws $*" >> ' + str(log) + "\n")
    (bin_dir / "jq").write_text("#!/bin/sh\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    res = subprocess.run(["bash", "-c", block], cwd=generated, env=env, capture_output=True)
    calls = log.read_text()
    assert res.returncode != 0
    assert "ecsodus check --changeset" in calls
    assert "execute-change-set" not in calls


@pytest.mark.parametrize("total,bad,ok", [("1", "0", True), ("0", "0", False), ("2", "1", False)])
def test_stackset_wait_requires_results(tmp_path: Path, total: str, bad: str, ok: bool) -> None:
    from ecsodus.emit.runbook import _wait_stackset_op

    stub = tmp_path / "aws"
    stub.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        "  *describe-stack-set-operation*) echo SUCCEEDED;;\n"
        f'  *"length(Summaries)"*) echo {total};;\n'
        f"  *) echo {bad};;\nesac\n"
    )
    stub.chmod(0o755)
    script = (
        "set -euo pipefail\nop=abc\n" + "\n".join(_wait_stackset_op("ss")) + "\necho CONTINUED\n"
    )
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    res = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert ("CONTINUED" in res.stdout) is ok
