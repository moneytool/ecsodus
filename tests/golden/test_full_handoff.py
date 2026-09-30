"""Golden integration test: a realistic Copilot app hands off completely.

The app is built from verbatim Copilot renders (env stack, a Load Balanced Web Service and its
addons nested stack) with live reads synthesised in the exact shape ``ecsodus inventory`` records
them (see ``live_synth``). With complete, consistent live data nothing may be blocked: every stack
hands off, the closure holds, ``ecsodus generate`` succeeds, the retain patches verify, and the
generated Terraform passes ``terraform validate`` against the real AWS provider schema.

Two addons variants run: S3 + DynamoDB (snapshot ``full-handoff-imports.txt``) and Aurora
Serverless v2 (snapshot ``full-handoff-aurora-imports.txt``). Snapshots list every
``(tf_address, import_id)`` pair; regenerate with ``ECSODUS_UPDATE_GOLDEN=1 uv run pytest``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ecsodus import cfn
from ecsodus.cli import main
from ecsodus.emit.patches import build_patches
from ecsodus.emit.retain_patch import verify_patch
from ecsodus.mappers.fates import (
    BLOCKED,
    IMPORT,
    MANUAL_CLEANUP,
    NESTED_WRAPPER,
    RETAIN_UNDER_EXISTING_OWNER,
    MigrationPlan,
    build_plan,
)
from ecsodus.model import Inventory
from tests.golden import live_synth as app

GOLDEN = Path(__file__).parent / "snapshots"
VARIANTS = ("s3-ddb", "aurora")
SNAPSHOTS = {
    "s3-ddb": GOLDEN / "full-handoff-imports.txt",
    "aurora": GOLDEN / "full-handoff-aurora-imports.txt",
}
STACKS = {app.ENV_STACK, app.SVC_STACK, app.ADDONS_STACK}

# Every resource's fate, per variant. Nothing is blocked or kept; the only non-imports are the
# Copilot custom-resource handles and their Lambdas (manual-cleanup, retained by the patch),
# the Aurora SecretTargetAttachment (manual-cleanup: no Terraform resource, PLAN §13.8) and the
# addons wrapper (nested-wrapper: its child stack is handed off itself).
EXPECTED_FATES = {
    "s3-ddb": {IMPORT: 63, MANUAL_CLEANUP: 11, NESTED_WRAPPER: 1},
    "aurora": {IMPORT: 66, MANUAL_CLEANUP: 12, NESTED_WRAPPER: 1},
}
# Imports whose Terraform arguments cannot cover everything the template sets, by design: the
# covering resources are separate in provider 6.x and listed in the resource's notes.
EXPECTED_PARTIAL = {
    "s3-ddb": {
        # capacity providers -> aws_ecs_cluster_capacity_providers
        f"{app.ENV_STACK}/Cluster",
        # managed policy attachments -> aws_iam_role_policy_attachment
        f"{app.SVC_STACK}/ExecutionRole",
        f"{app.SVC_STACK}/EnvControllerRole",
        f"{app.SVC_STACK}/RulePriorityFunctionRole",
        # bucket sub-configurations -> aws_s3_bucket_* resources
        f"{app.ADDONS_STACK}/assetsBucket",
    },
}
EXPECTED_PARTIAL["aurora"] = EXPECTED_PARTIAL["s3-ddb"] - {f"{app.ADDONS_STACK}/assetsBucket"}


@pytest.fixture(scope="module", params=VARIANTS)
def variant(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module")
def built(variant: str) -> tuple[Inventory, MigrationPlan]:
    inv = app.build_app(variant)
    return inv, build_plan(inv)


@pytest.fixture(scope="module")
def generated(
    variant: str, built: tuple[Inventory, MigrationPlan], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    inv, _ = built
    tmp = tmp_path_factory.mktemp(f"full-handoff-{variant}")
    inv.save(tmp / "inventory.json")
    out = tmp / "infra"
    rc = main(["generate", str(tmp / "inventory.json"), "--out", str(out), "--patch-bucket", "b"])
    assert rc == 0
    return out


def test_every_stack_hands_off(variant: str, built: tuple[Inventory, MigrationPlan]) -> None:
    inv, plan = built
    assert set(plan.stacks) == STACKS
    for name, sp in plan.stacks.items():
        assert sp.handoff, (name, sp.kept_because)
        assert not sp.kept_because, name
    blocked = [(r.stack, r.logical_id, r.reason) for r in plan.resources if r.fate == BLOCKED]
    assert blocked == []
    assert not [r for r in plan.resources if r.fate == RETAIN_UNDER_EXISTING_OWNER]
    assert plan.closure_errors == []
    assert plan.fate_counts() == EXPECTED_FATES[variant]
    # All three stacks are torn down, children before parents, env last.
    assert plan.teardown == [app.SVC_STACK, app.ADDONS_STACK, app.ENV_STACK]
    assert plan.teardown_stops_at is None
    assert plan.workload_status == {f"{app.ENV}/{app.SVC}": "migrating"}


def test_every_created_resource_has_a_fate(built: tuple[Inventory, MigrationPlan]) -> None:
    inv, plan = built
    planned = {(r.stack, r.logical_id) for r in plan.resources}
    for stack in inv.stacks.values():
        for res in stack.resources:
            assert (stack.name, res.logical_id) in planned
    # The out-of-band objects Copilot's HTTPSCert created are imported with the env stack.
    oob = {r.type: r for r in plan.resources if r.type.startswith("OutOfBand::")}
    assert set(oob) == {"OutOfBand::ACM::Certificate", "OutOfBand::Route53::Record"}
    assert all(r.fate == IMPORT and r.stack == app.ENV_STACK for r in oob.values())


def test_fidelity_is_full_except_documented_gaps(
    variant: str, built: tuple[Inventory, MigrationPlan]
) -> None:
    _, plan = built
    partial = {
        f"{r.stack}/{r.logical_id}"
        for r in plan.imports()
        if r.spec is not None and r.spec.fidelity != "full" and not r.type.startswith("OutOfBand")
    }
    assert partial == EXPECTED_PARTIAL[variant]


def test_live_values_reach_the_terraform(built: tuple[Inventory, MigrationPlan]) -> None:
    """Spot checks that values only live reads know made it into the arguments."""
    _, plan = built
    by = {(r.stack, r.logical_id): dict(r.spec.body) for r in plan.imports() if r.spec}
    env, svc = app.ENV_STACK, app.SVC_STACK
    assert by[(env, "PublicSubnet2")]["availability_zone"] == "us-west-2b"
    assert by[(env, "NatGateway1")]["allocation_id"] == app.EIPS["NatGateway1Attachment"][1]
    assert by[(env, "PublicLoadBalancer")]["name"] == app.LB_NAME
    assert by[(env, "HTTPSListener")]["certificate_arn"] == app.CERT_ARN
    assert by[(env, "HTTPSListener")]["ssl_policy"] == "ELBSecurityPolicy-2016-08"
    assert by[(svc, "Service")]["desired_count"] == 5
    assert by[(svc, "Service")]["task_definition"] == app.TD_ARN
    assert by[(svc, "HTTPSListenerRule1")]["listener_arn"] == app.HTTPS_LISTENER
    assert by[(svc, "HTTPSListenerRule1")]["priority"] == 2
    assert "tags" not in by[(svc, "HTTPSListenerRule1")]  # CFN never tags listener rules
    assert by[(svc, "TargetGroup")]["name"] == app.FE_TG[0]
    # Live tags win, and CloudFormation's aws: system tags are dropped.
    assert by[(env, "VPC")]["tags"] == {
        "copilot-application": app.APP,
        "copilot-environment": app.ENV,
        "Name": f"copilot-{app.APP}-{app.ENV}",
    }
    # Inline policies are emitted because the live role has exactly the template's set.
    assert [b.body[0][1] for k, b in plan_body(plan, svc, "TaskRole") if k == "inline_policy"] == [
        "DenyIAM",
        "Publish2SNS",
    ]


def plan_body(plan: MigrationPlan, stack: str, lid: str) -> list:
    rp = next(r for r in plan.resources if (r.stack, r.logical_id) == (stack, lid))
    assert rp.spec is not None
    return rp.spec.body


def test_generate_manifest_matches_plan(
    built: tuple[Inventory, MigrationPlan], generated: Path
) -> None:
    _, plan = built
    manifest = json.loads((generated / "ecsodus-manifest.json").read_text())
    imports = plan.imports()
    assert len(manifest["imports"]) == len(imports)
    assert {(i["address"], i["id"]) for i in manifest["imports"]} == {
        (r.tf_address, r.spec.import_id) for r in imports if r.spec
    }
    assert set(manifest["handoff_stacks"]) == STACKS and manifest["kept_stacks"] == {}
    assert manifest["teardown"] == plan.teardown
    tf = [p for p in generated.glob("*.tf") if p.name not in ("versions.tf", "provider.tf")]
    assert {p.stem for p in tf} == STACKS
    assert sum(p.read_text().count("\nimport {") for p in tf) == len(imports)
    child = manifest["retain_patches"][app.SVC_STACK]["nested"]["AddonsStack"]
    assert child["stack"] == app.ADDONS_STACK


def test_retain_patches_verify(built: tuple[Inventory, MigrationPlan], generated: Path) -> None:
    inv, _ = built
    ps = build_patches(inv, "b")
    assert set(ps.stacks) == STACKS
    for name, p in ps.stacks.items():
        overrides = {lid: ps.stacks[child].url for lid, child in p.children.items()}
        original = inv.stacks[name].template_body
        assert verify_patch(original, p.result.text, overrides) == [], name
        patched = cfn.load(p.result.text)["Resources"]
        for lid, body in patched.items():
            assert body.get("DeletionPolicy") == "Retain", (name, lid)
            assert body.get("UpdateReplacePolicy") == "Retain", (name, lid)
        assert (generated / "retain-patches" / f"{name}.yml").read_text() == p.result.text
    wrapper = cfn.load(ps.stacks[app.SVC_STACK].result.text)["Resources"]["AddonsStack"]
    assert wrapper["Properties"]["TemplateURL"] == ps.stacks[app.ADDONS_STACK].url


def test_import_snapshot(variant: str, built: tuple[Inventory, MigrationPlan]) -> None:
    _, plan = built
    lines = sorted(f"{r.tf_address}\t{r.spec.import_id}" for r in plan.imports() if r.spec)
    text = "\n".join(lines) + "\n"
    snap = SNAPSHOTS[variant]
    if os.environ.get("ECSODUS_UPDATE_GOLDEN") or not snap.exists():
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(text)
    assert text == snap.read_text()


@pytest.mark.terraform
@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_validate(generated: Path) -> None:
    env = dict(os.environ)
    cache = Path.home() / ".cache" / "ecsodus-tf-plugins"
    cache.mkdir(parents=True, exist_ok=True)
    env["TF_PLUGIN_CACHE_DIR"] = str(cache)
    init = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=generated,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert init.returncode == 0, init.stdout + init.stderr
    res = subprocess.run(
        ["terraform", "validate", "-json", "-no-color"],
        cwd=generated,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    report = json.loads(res.stdout)
    errors = [d for d in report["diagnostics"] if d["severity"] == "error"]
    assert res.returncode == 0 and report["valid"] and not errors, res.stdout + res.stderr
    # The only warnings are the provider's deprecation of aws_iam_role.inline_policy, which
    # ecsodus uses deliberately (exact, and only where live has exactly those policies).
    warnings = {d["summary"] for d in report["diagnostics"] if d["severity"] == "warning"}
    assert warnings <= {"Argument is deprecated"}, warnings
