"""RUNBOOK.md: the operator's exact commands (PLAN §2.5, §13).

ecsodus never runs these. Every shell block runs in a fail-fast subshell
(``( set -euo pipefail; umask 077; ... )``), so a failed check stops the block even when it is
pasted into an interactive terminal. Each check is its own line directly before the mutation it
gates (a failing command on the left of ``&&`` would not stop a ``set -e`` shell).

All steps are always emitted. The teardown gate was removed after the AWS end-to-end run of
2026-09-30 passed (ADR-0012); the banner states what that run did and did not cover.
"""

from __future__ import annotations

import shlex

from ecsodus import __version__
from ecsodus.emit.patches import PatchSet
from ecsodus.mappers.fates import MANUAL_CLEANUP, MigrationPlan
from ecsodus.mappers.tfmap import is_custom_resource
from ecsodus.model import ADDONS, APP, ENV, ENV_ADDONS, STACKSET_INSTANCE, WORKLOAD

VERIFIED_SCOPE = (
    "> **Verified on real AWS (2026-09-30).** The full runbook ran end to end against a Copilot\n"
    "> v1.34.1 app (env + Load Balanced Web Service + DynamoDB/S3 addons): `DeletionPolicy:\n"
    "> Retain` stopped every custom-resource Delete handler, and no data or traffic was lost\n"
    "> (docs/e2e/2026-09-30-aws-e2e.md). **Not yet exercised on real AWS:** custom domains and\n"
    "> ACM certificates, Aurora addons, private placement with NAT, and partial migrations. If\n"
    "> your app uses one of these, run the steps on a non-production copy first.\n"
)
MANIFEST = "ecsodus-manifest.json"


def q(s: str) -> str:
    return shlex.quote(s)


def _params(names: list[str]) -> str:
    return " ".join(f"ParameterKey={q(n)},UsePreviousValue=true" for n in names)


class _Doc:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def w(self, text: str = "") -> None:
        self.lines.append(text)

    def sh(self, *commands: str) -> None:
        """A fail-fast shell block: stops at the first failing command, even when pasted."""
        self.w("```bash")
        self.w("(")
        self.w("set -euo pipefail")
        self.w("umask 077")
        # Checks and the mutations they gate are written as separate lines: under `set -e` a
        # failing command on the left of `&&` does NOT stop the shell, a failing line does.
        cmds = list(commands)
        i = 0
        while i < len(cmds):
            c = cmds[i]
            if c.endswith(" \\") and i + 1 < len(cmds) and cmds[i + 1].startswith("  && "):
                self.w(c[:-2])
                self.w(cmds[i + 1][5:])
                i += 2
                continue
            self.w(c)
            i += 1
        self.w(")")
        self.w("```\n")


def _wait_stackset_op(ss_name: str) -> list[str]:
    """Poll a StackSet operation to SUCCEEDED, then require at least one instance result and
    every instance result SUCCEEDED. Each AWS call is its own checked assignment, so a failing
    call stops the block instead of producing empty output that looks like success."""
    return [
        "while :; do st=$(aws cloudformation describe-stack-set-operation "
        f'--stack-set-name {q(ss_name)} --operation-id "$op" '
        "--query StackSetOperation.Status --output text)",
        '  case "$st" in SUCCEEDED) break;; FAILED|STOPPED) echo "StackSet operation $st"; '
        "exit 1;; esac; sleep 10; done",
        "total=$(aws cloudformation list-stack-set-operation-results "
        f'--stack-set-name {q(ss_name)} --operation-id "$op" '
        "--query 'length(Summaries)' --output text)",
        "bad=$(aws cloudformation list-stack-set-operation-results "
        f'--stack-set-name {q(ss_name)} --operation-id "$op" '
        "--query \"length(Summaries[?Status!='SUCCEEDED'])\" --output text)",
        'test "$total" -ge 1',
        'test "$bad" -eq 0',
    ]


def _delete(app: str, name: str) -> list[str]:
    return [
        f"ecsodus verify-retain --app {q(app)} --stack {q(name)} \\",
        f"  && aws cloudformation delete-stack --stack-name {q(name)}",
        f"aws cloudformation wait stack-delete-complete --stack-name {q(name)}",
    ]


def render(
    plan: MigrationPlan,
    patches: PatchSet,
    *,
    include_teardown: bool = True,
    out_dir: str = ".",
    inventory_path: str = "inventory.json",
) -> str:
    inv = plan.inventory
    d = _Doc()
    w = d.w
    handoff = {n for n, sp in plan.stacks.items() if sp.handoff}
    roots = [s for s in inv.stacks.values() if s.name in handoff and s.kind in (APP, ENV, WORKLOAD)]
    order = {APP: 0, ENV: 1, WORKLOAD: 2}
    roots.sort(key=lambda s: (order[s.kind], s.name))
    sel = inv.selection or {}
    select_args = " ".join(
        ([f"--profile {q(sel['profile'])}"] if sel.get("profile") else [])
        + [f"--env {q(e)}" for e in sel.get("envs", [])]
        + [f"--keep-on-copilot {q(k)}" for k in sel.get("keep_on_copilot", [])]
    )
    reinventory = " ".join(
        x
        for x in (
            f"ecsodus inventory --app {q(inv.app)} --region {q(inv.region)}",
            select_args,
            f"-o {q(inventory_path)}",
        )
        if x
    )
    regenerate = f"ecsodus generate {q(inventory_path)} --patch-bucket {q(patches.bucket)}" + (
        " --metadata-fallback" if patches.metadata_fallback else ""
    )

    w(f"# Runbook: migrate Copilot app `{inv.app}` to Terraform (adopt in place)\n")
    w(
        f"Generated by ecsodus {__version__} for account `{inv.account}`, region "
        f"`{inv.region}`, from an inventory captured at {inv.captured_at}.\n"
    )
    w(VERIFIED_SCOPE)
    w(
        f"Run every block from the directory that holds the generated Terraform (`{out_dir}`). "
        "Each block runs in a fail-fast subshell and stops at the first failing check. Nothing "
        "here is run by ecsodus. The generated `*.tf` files contain plaintext task-definition "
        "environment values copied from your stacks: review them before committing.\n"
    )
    kept = {n: sp for n, sp in plan.stacks.items() if not sp.handoff}
    if kept:
        w("## Stacks that stay on Copilot\n")
        w(
            "These stacks are **kept**. Nothing in this runbook touches them, and no shared "
            "stack they depend on is deleted.\n"
        )
        for n, sp in sorted(kept.items()):
            w(f"- `{n}`: {'; '.join(sp.kept_because)}")
        w()
    if plan.closure_errors:
        w("## STOP: closure check failed\n")
        w("`ecsodus generate` refused to produce a complete hand-off. Fix these first:\n")
        for e in plan.closure_errors:
            w(f"- {e}")
        return "\n".join(d.lines) + "\n"

    # 1 ------------------------------------------------------------------------------------
    w("## 1. Freeze\n")
    w(
        "- Stop all `copilot deploy`, `copilot env deploy`, `copilot app upgrade` and pipeline "
        "runs for this app until the runbook is finished.\n- Record each stack's last update "
        "time:\n"
    )
    d.sh(
        *[
            f"aws cloudformation describe-stacks --stack-name {q(s.name)} "
            "--query 'Stacks[0].LastUpdatedTime' --output text"
            for s in roots
        ]
    )

    # 2 ------------------------------------------------------------------------------------
    w("## 2. Protect\n")
    w(
        "Take backups, test a restore, and turn on deletion protection where it is off. This "
        "creates CloudFormation drift on purpose. The retain patch in step 3 does not revert it, "
        "because the template property is unchanged.\n"
    )
    protect: list[str] = []
    for rp in plan.imports():
        pid = rp.physical_id or ""
        live = inv.live.get(pid, {})
        snap = q(pid + "-ecsodus")
        if rp.type == "AWS::RDS::DBCluster":
            protect += [
                f"aws rds create-db-cluster-snapshot --db-cluster-identifier {q(pid)} "
                f"--db-cluster-snapshot-identifier {snap}",
                f"aws rds wait db-cluster-snapshot-available --db-cluster-snapshot-identifier {snap}",
            ]
            if not live.get("DeletionProtection"):
                protect.append(
                    f"aws rds modify-db-cluster --db-cluster-identifier {q(pid)} "
                    "--deletion-protection --apply-immediately"
                )
        elif rp.type == "AWS::RDS::DBInstance" and not live.get("DBClusterIdentifier"):
            # Aurora members are protected (and snapshotted) through their cluster.
            protect += [
                f"aws rds create-db-snapshot --db-instance-identifier {q(pid)} "
                f"--db-snapshot-identifier {snap}",
                f"aws rds wait db-snapshot-available --db-snapshot-identifier {snap}",
            ]
            if not live.get("DeletionProtection"):
                protect.append(
                    f"aws rds modify-db-instance --db-instance-identifier {q(pid)} "
                    "--deletion-protection --apply-immediately"
                )
        elif rp.type == "AWS::DynamoDB::Table":
            protect.append(f"aws dynamodb create-backup --table-name {q(pid)} --backup-name {snap}")
            if not live.get("DeletionProtectionEnabled"):
                protect.append(
                    f"aws dynamodb update-table --table-name {q(pid)} --deletion-protection-enabled"
                )
        elif rp.type == "AWS::S3::Bucket":
            if ((live.get("Versioning") or {}).get("Status")) != "Enabled":
                protect.append(
                    f"aws s3api put-bucket-versioning --bucket {q(pid)} "
                    "--versioning-configuration Status=Enabled"
                )
        elif rp.type == "AWS::EFS::FileSystem":
            protect.append(f"# EFS {pid}: confirm an AWS Backup recovery point exists and restores")
    d.sh(*(protect or ["# no stateful resources need protection changes"]))
    w("Then refresh the inventory (same selection) and regenerate, so the Terraform matches:\n")
    d.sh(reinventory, f"{regenerate} --out .")

    # 3 ------------------------------------------------------------------------------------
    w("## 3. Retain patches\n")
    w(
        "Every resource in every handed-off stack gets `DeletionPolicy: Retain` and "
        "`UpdateReplacePolicy: Retain`, with no exceptions. The patched templates are in "
        "`retain-patches/`. Nested stacks are patched through their parent's `TemplateURL`. "
        "After this step, no stack delete can remove or empty anything.\n"
    )
    uploads = [
        f"aws s3 cp retain-patches/{q(name)}.yml s3://{patches.bucket}/{p.key}"
        for name, p in sorted(patches.stacks.items())
        if name in handoff and not p.already_retained
    ]
    if uploads:
        w("Upload the patched templates:\n")
        d.sh(*uploads)
    instances = sorted(n for n in handoff if inv.stacks[n].kind == STACKSET_INSTANCE)
    for ss_name, ss in sorted(inv.stacksets.items()):
        if not instances or ss_name not in patches.stackset:
            continue
        caps = " ".join(ss.capabilities)
        w(f"### 3a. StackSet `{ss_name}`\n")
        w(
            "StackSets have no change sets. Diff offline, update with zero failure tolerance, "
            "wait for every instance, then verify each instance stack.\n"
        )
        d.sh(
            f"aws cloudformation describe-stack-set --stack-set-name {q(ss_name)} "
            "--query StackSet.TemplateBody --output text > stackset-current.yml",
            f"ecsodus check --template-diff stackset-current.yml "
            f"retain-patches/stackset-{ss_name}.yml",
            f"op=$(aws cloudformation update-stack-set --stack-set-name {q(ss_name)} "
            f"--template-body file://retain-patches/stackset-{ss_name}.yml "
            + (f"--parameters {_params(sorted(ss.parameters))} " if ss.parameters else "")
            + (f"--capabilities {caps} " if caps else "")
            + f"--administration-role-arn {q(ss.administration_role_arn)} "
            f"--execution-role-name {q(ss.execution_role_name)} "
            "--operation-preferences FailureToleranceCount=0,MaxConcurrentCount=1 "
            "--query OperationId --output text)",
            *_wait_stackset_op(ss_name),
            *[
                f"ecsodus verify-retain --app {q(inv.app)} --stack {q(n)} --manifest {MANIFEST}"
                for n in instances
            ],
        )
    w("### 3b. Stacks\n")
    w(
        "For each stack below, in order. A stack marked *already retained* is skipped once "
        "`verify-retain` confirms it.\n"
    )
    for s in roots:
        p = patches.stacks[s.name]
        w(f"#### `{s.name}` ({s.kind})\n")
        if p.already_retained:
            w("Already retained. Confirm, then skip:\n")
            d.sh(f"ecsodus verify-retain --app {q(inv.app)} --stack {q(s.name)}")
            continue
        caps = " ".join(s.capabilities)
        cs = f"ecsodus-retain-{p.result.sha256[:12]}"
        root_file = f"cs-{s.name}.json"
        cmds = [
            f"rm -f cs-{s.name}.json cs-{s.name}.nested-*.json",
            # A fresh name per run: deleting a change set is asynchronous, so reusing a name on
            # rerun races the deletion (observed in the AWS end-to-end run).
            f'cs="{cs}-$(date +%s)"',
            f"aws cloudformation create-change-set --stack-name {q(s.name)} "
            f'--change-set-name "$cs" --template-url {q(p.url)} --include-nested-stacks'
            + (f" --parameters {_params(sorted(s.parameters))}" if s.parameters else "")
            + (f" --capabilities {caps}" if caps else ""),
            f"aws cloudformation wait change-set-create-complete --stack-name {q(s.name)} "
            f'--change-set-name "$cs" || true   # an empty change set ends FAILED; check decides',
            f"aws cloudformation describe-change-set --stack-name {q(s.name)} "
            f'--change-set-name "$cs" --include-property-values > {root_file}',
        ]
        files = root_file
        if p.children:
            cmds += [
                f"for id in $(jq -r '.Changes[].ResourceChange | select(.ResourceType==\"AWS::"
                f"CloudFormation::Stack\") | .ChangeSetId // empty' {root_file}); do",
                '  aws cloudformation describe-change-set --change-set-name "$id" '
                f'--include-property-values > "cs-{s.name}.nested-${{id##*/}}.json"',
                "done",
            ]
            files = f"cs-{s.name}.json cs-{s.name}.nested-*.json"
        cmds += [
            f"ecsodus check --changeset {files} --manifest {MANIFEST} --stack {q(s.name)} \\",
            f"  && aws cloudformation execute-change-set --stack-name {q(s.name)} "
            f'--change-set-name "$cs"',
            f"aws cloudformation wait stack-update-complete --stack-name {q(s.name)}",
            f"ecsodus verify-retain --app {q(inv.app)} --stack {q(s.name)} --manifest {MANIFEST}",
        ]
        d.sh(*cmds)
        w(
            "If `check --changeset` exits with **3 (empty)**: the stack may already be retained "
            "(`verify-retain` passes: skip it), or CloudFormation treated the policy-only change "
            "as a no-op. In that case regenerate with `--metadata-fallback` and add "
            "`--allow-metadata-key` to the check. The check also fails if any nested change set "
            "is missing, so a failed `describe-change-set` in the loop can never pass silently.\n"
        )
    w(
        "Finally, re-inventory (same selection) and regenerate. The patch changed every stack's "
        "`LastUpdatedTime`, and regeneration must produce the same Terraform (PLAN §13.9):\n"
    )
    d.sh(
        reinventory,
        "regen=$(mktemp -d ./regen.XXXXXX)",
        f'{regenerate} --out "$regen"',
        # Compare only what ecsodus generates; operator files (backend.hcl, *_override.tf,
        # plans, state) are not regenerated and must not fail the check.
        'for f in "$regen"/*.tf; do diff -u "$(basename "$f")" "$f"; done',
        'for f in $(grep -l "^# Generated by ecsodus" ./*.tf); do test -f "$regen/$f"; done',
        f'cp "$regen"/{MANIFEST} {MANIFEST}',
    )

    # 4 ------------------------------------------------------------------------------------
    w("## 4. Import into Terraform\n")
    w("Edit the bucket name in `backend.hcl` first (`cp backend.hcl.example backend.hcl`).\n")
    d.sh(
        f"ecsodus verify-fresh --manifest {MANIFEST}",
        "terraform init -backend-config=backend.hcl",
        "terraform plan -out tf-import.plan",
        "terraform show -json tf-import.plan > plan-import.json",
        f"ecsodus check plan-import.json --manifest {MANIFEST} --phase import \\",
        "  && terraform apply tf-import.plan",
        "terraform state list > state.txt",
        f"ecsodus check --state state.txt --manifest {MANIFEST}",
        "terraform plan -out tf-steady.plan",
        "terraform show -json tf-steady.plan > plan-steady.json",
        f"ecsodus check plan-steady.json --manifest {MANIFEST} --phase steady",
        "terraform state pull > checkpoint.tfstate",
    )
    from ecsodus.emit.terraform import hardening_edits

    hardening = hardening_edits(plan)
    if hardening:
        w("### 4b. Harden import-unread arguments (after the steady check passes)\n")
        w(
            "The provider does not read these arguments back on import, so they are under "
            "`ignore_changes` for the import. Once the steady check passes, remove each from "
            "`ignore_changes`, run a plan, and confirm that it shows **only** in-place updates "
            "of exactly these arguments (state-only; no AWS change). Then apply:\n"
        )
        for address, attrs in hardening:
            w(f"- `{address}`: {', '.join(attrs)}")
        w()
    w(
        "**Rollback before step 5:** `terraform state rm` each imported address (listed in "
        f"`{MANIFEST}`). CloudFormation still owns everything, and the retain patches are "
        "harmless. **After step 5 there is no rollback to Copilot.**\n"
    )
    w(
        "**After the migration, image rollouts belong to your deploy tool** (ecspresso, or CI "
        "that registers task-definition revisions). Terraform ignores `task_definition` and "
        "`desired_count` on services. When a new revision replaces the imported one, delete the "
        "`aws_ecs_task_definition` resource block **and** its `import` block in the same change "
        "that adds the `removed` block below. Gate that change with "
        f"`ecsodus check plan.json --manifest {MANIFEST} --phase steady --forgotten <address>`:\n"
    )
    w("```hcl")
    for rp in plan.imports():
        if rp.type == "AWS::ECS::TaskDefinition" and rp.tf_address:
            w(
                f"removed {{\n  from = {rp.tf_address}\n  lifecycle {{\n    destroy = false\n  }}\n}}"
            )
    w("```\n")

    # 5 ------------------------------------------------------------------------------------
    w("## 5. Teardown of Copilot stacks\n")
    if not include_teardown:
        w("Not emitted (generated with teardown disabled by the caller).\n")
    else:
        w(
            "Delete only handed-off stacks, in this order: workloads, orphaned addons, "
            "environments, StackSet instances in this account and region, the StackSet (only "
            "if it has no other instances), then the app stack. Before each delete, "
            "`verify-retain` must pass.\n"
        )
        teardown_cmds: list[str] = []
        for name in plan.teardown:
            s = inv.stacks[name]
            if s.kind in (STACKSET_INSTANCE, APP):
                continue
            if s.kind in (ADDONS, ENV_ADDONS):
                teardown_cmds.append(
                    f"# {name} was orphaned when its parent was deleted (wrapper retained)"
                )
            teardown_cmds += _delete(inv.app, name)
        for ss_name, ss in sorted(inv.stacksets.items()):
            if not instances:
                break
            teardown_cmds.append(
                f"op=$(aws cloudformation delete-stack-instances --stack-set-name {q(ss_name)} "
                f"--accounts {q(inv.account)} --regions {q(inv.region)} --retain-stacks "
                "--operation-preferences FailureToleranceCount=0 --query OperationId "
                "--output text)"
            )
            teardown_cmds += _wait_stackset_op(ss_name)
            for n in instances:
                teardown_cmds += _delete(inv.app, n)
            others = [
                i for i in ss.instances if (i["account"], i["region"]) != (inv.account, inv.region)
            ]
            if others:
                teardown_cmds.append(
                    f"# StackSet {ss_name} keeps {len(others)} instance(s) elsewhere"
                )
            else:
                teardown_cmds.append(
                    f"aws cloudformation delete-stack-set --stack-set-name {q(ss_name)}"
                )
        for name in plan.teardown:
            if inv.stacks[name].kind == APP:
                teardown_cmds += _delete(inv.app, name)
        d.sh(*(teardown_cmds or ["# nothing to delete"]))
    if plan.teardown_stops_at:
        w(
            f"**Kept shared stack `{plan.teardown_stops_at}`**: "
            f"{'; '.join(plan.stacks[plan.teardown_stops_at].kept_because)}. It is not deleted, "
            "and neither is any stack it or its consumers still need.\n"
        )

    # 6 ------------------------------------------------------------------------------------
    w("## 6. Verify\n")
    d.sh(
        "terraform plan -out tf-final.plan",
        "terraform show -json tf-final.plan > plan-final.json",
        f"ecsodus check plan-final.json --manifest {MANIFEST} --phase steady",
    )
    w(
        "A zero-change plan after refresh, covering every imported address, proves that every "
        "imported resource still exists and matches. Then read your sentinel data back.\n"
    )
    if include_teardown:
        w(
            "After step 5 has completed, delete the Copilot-internal leftovers. The patch "
            "retained them, and they are now unowned:\n"
        )
        for rp in plan.resources:
            if (
                rp.fate == MANUAL_CLEANUP
                and rp.physical_id
                and rp.stack in plan.teardown
                and not is_custom_resource(rp.type)
            ):
                w(f"- `{rp.type}` `{rp.physical_id}` (from `{rp.stack}/{rp.logical_id}`)")
        w()
        w(
            "Custom-resource handles (`Custom::*`, `AWS::CloudFormation::CustomResource`) are not "
            "AWS resources and are not listed: "
            "they disappear with their stack. Never delete anything by a handle's physical ID. "
            "`HTTPSCert`'s is the ARN of the certificate Terraform now owns.\n"
        )
    else:
        w(
            "Copilot-internal leftovers (custom-resource Lambdas and roles) are listed in "
            "REPORT.md. Delete them **only after** a completed step 5; until then they still "
            "serve their stacks.\n"
        )
    w(
        "Retained resources keep their `aws:cloudformation:*` tags. The AWS provider ignores "
        "`aws:` tags, so they cause no drift, and you may leave them.\n"
    )

    # 7 ------------------------------------------------------------------------------------
    w("## 7. Never, after migrating\n")
    w(
        "- Never run `copilot app delete`, `copilot env delete`, `copilot env deploy` or "
        "`copilot app upgrade` against a retained or migrated stack. They re-render templates "
        "without the Retain policies and can modify imported resources."
    )
    w(
        "- After a partial migration, only `copilot svc deploy` of *unmigrated* workloads is "
        "allowed. Afterwards, re-run `ecsodus verify-retain`."
    )
    w()
    _ = (ENV, WORKLOAD)
    return "\n".join(d.lines) + "\n"
