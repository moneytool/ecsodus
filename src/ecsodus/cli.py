"""ecsodus command line (PLAN §2).

    ecsodus inventory --app APP [--env ENV ...] [--keep-on-copilot NAME ...] -o inventory.json
    ecsodus report    inventory.json [-o REPORT.md]
    ecsodus generate  inventory.json --out DIR [--patch-bucket B] [--metadata-fallback]
                      [--i-understand-teardown-is-unverified]
    ecsodus check     PLAN.json --manifest M --phase import|steady
    ecsodus check     --state state.txt --manifest M
    ecsodus check     --changeset CS.json ... --manifest M --stack S [--allow-metadata-key]
    ecsodus check     --template-diff CURRENT PATCHED
    ecsodus verify-retain --app APP [--stack S ...]

Exit codes: 0 ok, 1 check failed, 2 usage/input error, 3 change set empty (see RUNBOOK step 3).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ecsodus import __version__
from ecsodus.model import Inventory, write_sensitive

MAX_INVENTORY_AGE_S = 24 * 3600


def _err(msg: str) -> int:
    print(f"ecsodus: {msg}", file=sys.stderr)
    return 2


def _load_inventory(path: str, allow_stale: bool = False) -> Inventory:
    inv = Inventory.load(path)
    if not allow_stale and inv.age_seconds() > MAX_INVENTORY_AGE_S:
        raise SystemExit(_err(
            f"inventory {path} is older than 24h (captured {inv.captured_at}); re-run "
            "`ecsodus inventory` (or pass --allow-stale for offline review only)"))
    return inv


# -- inventory -----------------------------------------------------------------------------
def cmd_inventory(a: argparse.Namespace) -> int:
    import boto3

    from ecsodus.sources import copilot
    from ecsodus.sources.aws import Clients

    session = boto3.Session(profile_name=a.profile, region_name=a.region)
    inv = copilot.inventory(Clients(session), a.app, a.env or None, a.keep_on_copilot or ())
    if not inv.stacks:
        return _err(f"no Copilot stacks found for app {a.app!r} in {inv.account}/{inv.region}")
    inv.save(a.output)
    print(f"wrote {a.output} (mode 0600): {len(inv.stacks)} stacks, "
          f"{sum(len(s.resources) for s in inv.stacks.values())} resources, "
          f"{len(inv.unavailable)} unavailable")
    return 0


# -- report --------------------------------------------------------------------------------
def cmd_report(a: argparse.Namespace) -> int:
    from ecsodus.emit import report
    from ecsodus.mappers.fates import build_plan

    inv = _load_inventory(a.inventory, allow_stale=True)
    text = report.render(build_plan(inv))
    if a.output == "-":
        sys.stdout.write(text)
    else:
        Path(a.output).write_text(text)
        print(f"wrote {a.output}")
    return 0


# -- generate ------------------------------------------------------------------------------
def cmd_generate(a: argparse.Namespace) -> int:
    from ecsodus.emit import report, runbook, terraform
    from ecsodus.emit.patches import build_patches, default_patch_bucket
    from ecsodus.mappers.fates import build_plan

    inv = _load_inventory(a.inventory, allow_stale=a.allow_stale)
    plan = build_plan(inv)
    out = Path(a.out)
    bucket = a.patch_bucket or default_patch_bucket(inv)
    if not bucket:
        return _err("no Copilot artifact bucket found; pass --patch-bucket")
    patches = build_patches(inv, bucket, metadata_fallback=a.metadata_fallback)
    (out / "retain-patches").mkdir(parents=True, exist_ok=True)
    for name, p in patches.stacks.items():
        (out / "retain-patches" / f"{name}.yml").write_text(p.result.text)
    for name, r in patches.stackset.items():
        (out / "retain-patches" / f"stackset-{name}.yml").write_text(r.text)
    (out / "REPORT.md").write_text(report.render(plan))
    (out / "RUNBOOK.md").write_text(runbook.render(
        plan, patches, include_teardown=a.i_understand_teardown_is_unverified,
        out_dir=str(out), inventory_path=a.inventory))
    if plan.closure_errors:
        print("closure check FAILED; Terraform not generated. See REPORT.md:", file=sys.stderr)
        for e in plan.closure_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    written = terraform.write_project(plan, patches, out)
    n_imports = len(plan.imports())
    print(f"wrote {len(written)} Terraform files ({n_imports} imports), "
          f"{len(patches.stacks)} retain patches, REPORT.md, RUNBOOK.md to {out}/")
    kept = [n for n, s in plan.stacks.items() if not s.handoff]
    if kept:
        print(f"{len(kept)} stack(s) kept on Copilot; see REPORT.md")
    return 0


# -- check ---------------------------------------------------------------------------------
def _manifest(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def cmd_check(a: argparse.Namespace) -> int:
    from ecsodus.check import changeset, plan as plan_check

    if a.template_diff:
        from ecsodus.emit.retain_patch import verify_patch

        current, patched = (Path(p).read_text() for p in a.template_diff)
        problems = verify_patch(current, patched, metadata_fallback=a.allow_metadata_key)
        for p in problems:
            print(f"FAIL {p}")
        print("template diff: " + ("only retain-patch edits" if not problems else "REJECTED"))
        return 1 if problems else 0

    if not a.manifest:
        return _err("--manifest is required")
    m = _manifest(a.manifest)
    expected = [i["address"] for i in m["imports"]]

    if a.changeset:
        docs = [json.loads(Path(p).read_text()) for p in a.changeset]
        nested: list[str] = []
        stacks = [a.stack] if a.stack else list(m["retain_patches"])
        for s in stacks:
            nested += list((m["retain_patches"].get(s) or {}).get("nested", {}))
        res = changeset.check_change_sets(
            docs, patched_nested=nested, allow_metadata_key=a.allow_metadata_key,
            allow_nested_dynamic=a.allow_nested_dynamic)
        for e in res.errors:
            print(f"FAIL {e}")
        if res.verdict == changeset.EMPTY:
            print("EMPTY change set: run `ecsodus verify-retain`; skip the stack if it passes, "
                  "otherwise regenerate with --metadata-fallback (RUNBOOK step 3)")
            return 3
        print(f"change sets: {res.change_sets}, accepted changes: {res.accepted}, "
              f"verdict: {res.verdict.upper()}")
        return 0 if res.ok else 1

    if a.state:
        res = plan_check.check_state(Path(a.state).read_text().splitlines(), expected)
    else:
        if not a.plan or not a.phase:
            return _err("give a plan JSON and --phase, or --state, or --changeset")
        doc = json.loads(Path(a.plan).read_text())
        res = plan_check.check_plan(doc, expected, a.phase)
    for e in res.errors:
        print(f"FAIL {e}")
    for w in res.warnings:
        print(f"warn {w}")
    print(f"{'PASS' if res.ok else 'FAIL'} {json.dumps(res.summary, sort_keys=True)}")
    return 0 if res.ok else 1


# -- verify-retain -------------------------------------------------------------------------
def cmd_verify_retain(a: argparse.Namespace) -> int:
    import boto3

    from ecsodus.emit.retain_patch import missing_retain
    from ecsodus.sources.aws import Clients, paginate

    clients = Clients(boto3.Session(profile_name=a.profile, region_name=a.region))
    cfn = clients("cloudformation")
    names = list(a.stack or [])
    if not names:
        for s in paginate(cfn, "list_stacks", "StackSummaries"):
            if s.get("StackStatus") == "DELETE_COMPLETE":
                continue
            d = cfn.describe_stacks(StackName=s["StackId"])["Stacks"][0]
            tags = {t["Key"]: t["Value"] for t in d.get("Tags") or []}
            if tags.get("copilot-application") == a.app and not d.get("ParentId"):
                names.append(d["StackName"])
    failed = False
    seen: set[str] = set()

    def check(stack_id: str, label: str) -> None:
        nonlocal failed
        if stack_id in seen:
            return
        seen.add(stack_id)
        body = cfn.get_template(StackName=stack_id, TemplateStage="Original")["TemplateBody"]
        if not isinstance(body, str):
            body = json.dumps(body)
        missing = missing_retain(body)
        if missing:
            failed = True
            print(f"FAIL {label}: {len(missing)} resource(s) without Retain: "
                  + ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
        else:
            print(f"ok   {label}")
        for r in paginate(cfn, "list_stack_resources", "StackResourceSummaries",
                          StackName=stack_id):
            if r["ResourceType"] == "AWS::CloudFormation::Stack" and r.get("PhysicalResourceId"):
                check(r["PhysicalResourceId"], f"{label}/{r['LogicalResourceId']}")

    for n in names:
        check(n, n)
    return 1 if failed else 0


# -- parser --------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ecsodus", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"ecsodus {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def aws_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--profile")
        sp.add_argument("--region")

    s = sub.add_parser("inventory", help="read a Copilot app from AWS (read-only)")
    s.add_argument("--app", required=True)
    s.add_argument("--env", action="append", help="limit to this environment (repeatable)")
    s.add_argument("--keep-on-copilot", action="append", metavar="[ENV/]WORKLOAD",
                   help="workload that stays on Copilot (partial migration)")
    s.add_argument("-o", "--output", default="inventory.json")
    aws_opts(s)
    s.set_defaults(fn=cmd_inventory)

    s = sub.add_parser("report", help="write the readiness report")
    s.add_argument("inventory")
    s.add_argument("-o", "--output", default="REPORT.md")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("generate", help="write Terraform, retain patches, report and runbook")
    s.add_argument("inventory")
    s.add_argument("--out", required=True)
    s.add_argument("--patch-bucket", help="S3 bucket for patched templates "
                   "(default: the Copilot artifact bucket)")
    s.add_argument("--metadata-fallback", action="store_true",
                   help="add an ecsodus:retain Metadata key per resource (RUNBOOK step 3)")
    s.add_argument("--i-understand-teardown-is-unverified", action="store_true",
                   help="emit runbook step 5 (teardown) before the AWS end-to-end run")
    s.add_argument("--allow-stale", action="store_true",
                   help="accept an inventory older than 24h (offline review only)")
    s.set_defaults(fn=cmd_generate)

    s = sub.add_parser("check", help="gate a Terraform plan, state, or change set")
    s.add_argument("plan", nargs="?", help="terraform show -json output")
    s.add_argument("--manifest", help="ecsodus-manifest.json from generate")
    s.add_argument("--phase", choices=["import", "steady"])
    s.add_argument("--state", help="terraform state list output")
    s.add_argument("--changeset", nargs="+", help="describe-change-set JSON files")
    s.add_argument("--stack", help="stack the change sets belong to")
    s.add_argument("--allow-metadata-key", action="store_true")
    s.add_argument("--allow-nested-dynamic", action="store_true",
                   help="accept Dynamic entries caused by patched nested stacks (PLAN §13.3)")
    s.add_argument("--template-diff", nargs=2, metavar=("CURRENT", "PATCHED"))
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("verify-retain", help="confirm every stack resource is Retain (read-only)")
    s.add_argument("--app", required=True)
    s.add_argument("--stack", action="append")
    aws_opts(s)
    s.set_defaults(fn=cmd_verify_retain)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except (ValueError, FileNotFoundError) as exc:
        return _err(str(exc))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

_ = write_sensitive
