"""REPORT.md: the migration readiness report (PLAN §2.3). Useful on its own.

The report never contains environment values or secret values.
"""

from __future__ import annotations

from ecsodus import __version__
from ecsodus.mappers.fates import (
    BLOCKED,
    EXTERNAL_REFERENCE,
    IMPORT,
    MANUAL_CLEANUP,
    RETAIN_UNDER_EXISTING_OWNER,
    MigrationPlan,
)
from ecsodus.mappers.tfmap import is_custom_resource

KEEP_CFN = (
    "**Zero-risk baseline: keep the CloudFormation.** Copilot's stacks keep running without the "
    "CLI. You can deploy them with `aws cloudformation deploy` plus a deploy tool such as "
    "ecspresso. Caveats: the custom-resource Lambdas run `nodejs20.x`, so creating them is "
    "blocked from 2027-07-29, and a stack update that changes their code fails from 2027-08-31. "
    "Choose ecsodus if you want Terraform ownership."
)


def render(plan: MigrationPlan) -> str:
    inv = plan.inventory
    out: list[str] = []
    w = out.append
    counts = plan.fate_counts()
    ready = not plan.closure_errors and any(s.handoff for s in plan.stacks.values())

    w(f"# Migration readiness: Copilot app `{inv.app}`\n")
    w(
        f"ecsodus {__version__} · account `{inv.account}` · region `{inv.region}` · inventory "
        f"captured {inv.captured_at}\n"
    )
    w("## Summary\n")
    w(
        f"- **Verdict:** {'ready for adopt-in-place hand-off' if ready else 'not ready'}"
        + ("" if not plan.closure_errors else " (closure check failed)")
    )
    w(
        f"- Stacks: {len(plan.stacks)} "
        f"({sum(s.handoff for s in plan.stacks.values())} hand off, "
        f"{sum(not s.handoff for s in plan.stacks.values())} kept on Copilot)"
    )
    w("- Resources by fate: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if plan.teardown_stops_at:
        w(
            f"- Teardown stops before `{plan.teardown_stops_at}` (a shared stack still has "
            "consumers)."
        )
    w("")
    w(KEEP_CFN + "\n")

    w("## Workloads\n")
    w("| Workload | Status | Express Mode fit (informational; rebuild mode is v0.2) |")
    w("|---|---|---|")
    for wl in sorted(inv.workloads, key=lambda x: (x.env, x.name)):
        key = f"{wl.env}/{wl.name}"
        fit = plan.express.get(key)
        fit_s = (
            "eligible"
            if fit and fit.eligible
            else ("no: " + "; ".join(fit.reasons) if fit else "n/a")
        )
        w(f"| `{key}` ({wl.type}) | {plan.workload_status.get(key, '?')} | {fit_s} |")
    w("")
    w(
        "Before any rebuild-in-parallel (v0.2), answer for each service: *does this container run "
        "background work, consumers or migrations on boot?* Parallel runs would duplicate it.\n"
    )

    if plan.closure_errors:
        w("## Closure errors (generation refused)\n")
        for e in plan.closure_errors:
            w(f"- {e}")
        w("")

    w("## Stacks\n")
    for name, sp in sorted(plan.stacks.items(), key=lambda kv: (kv[1].kind, kv[0])):
        w(f"### `{name}` ({sp.kind}): {'hand off' if sp.handoff else 'kept'}\n")
        if not sp.handoff:
            w("Kept because: " + "; ".join(sp.kept_because) + "\n")
        if sp.unpatched_side_effects:
            w(
                "<details><summary>Deleting this stack <b>without</b> the retain patch would "
                f"destroy {len(sp.unpatched_side_effects)} thing(s)</summary>\n"
            )
            for e in sp.unpatched_side_effects:
                w(f"- {e}")
            w("\n</details>\n")
            w("With the retain patch: **nothing**. Every resource is retained.\n")
        rows = plan.by_stack(name)
        if rows:
            w("| Logical ID | Type | Fate | Terraform | Note |")
            w("|---|---|---|---|---|")
            for r in rows:
                w(
                    f"| {r.logical_id} | {r.type} | {r.fate} | {r.tf_address or ''} | "
                    f"{(r.reason or '').replace('|', '/')} |"
                )
            w("")

    blocked = [
        r
        for r in plan.resources
        if r.fate == BLOCKED
        or (r.fate == RETAIN_UNDER_EXISTING_OWNER and "would be: blocked" in r.reason)
    ]
    if blocked:
        w("## Blocked resources\n")
        w("Each one keeps its stack (and everything that stack depends on) on Copilot.\n")
        for r in blocked:
            w(f"- `{r.stack}/{r.logical_id}` ({r.type}): {r.reason}")
        w("")

    cleanup = [r for r in plan.resources if r.fate == MANUAL_CLEANUP]
    if cleanup:
        w("## Manual cleanup after teardown\n")
        w(
            "Retained by the patch, so no stack delete invokes a handler. Delete by hand after "
            "step 6.\n"
        )
        handles = [r for r in cleanup if is_custom_resource(r.type)]
        for r in cleanup:
            if r not in handles:
                w(f"- `{r.stack}/{r.logical_id}` ({r.type}) {r.physical_id or ''}")
        if handles:
            w(
                "\nCustom-resource handles are not AWS resources: they disappear with their "
                "stack, so there is nothing to delete. Never delete anything by a handle's "
                "physical ID: `HTTPSCert`'s is the imported certificate's ARN, and "
                "`DelegateDNSAction`'s names the env zone's NS delegation.\n"
            )
            for r in handles:
                w(f"- `{r.stack}/{r.logical_id}` ({r.type})")
        w("")

    ext = [p for p in inv.ssm_parameters if p.get("type") == "SecureString"]
    external = [r for r in plan.resources if r.fate == EXTERNAL_REFERENCE]
    if ext or external:
        w("## External references (never imported)\n")
        for p in ext:
            w(
                f"- SSM SecureString `{p['name']}`: referenced by ARN in task definitions; "
                "Terraform never reads its value"
            )
        for r in external:
            w(f"- `{r.stack}/{r.logical_id}` ({r.type}): {r.reason}")
        w("")

    partial = [
        r for r in plan.resources if r.fate == IMPORT and r.spec and r.spec.fidelity != "full"
    ]
    if partial:
        w("## Partial argument coverage\n")
        w(
            "These imports are generated, but `check --phase import` will flag any argument "
            "ecsodus could not reproduce. Resolve them before applying.\n"
        )
        for r in partial:
            w(f"- `{r.tf_address}`: " + "; ".join(r.spec.notes if r.spec else []))
        w("")

    if inv.disputed or inv.unavailable:
        w("## Disputed and unavailable values\n")
        for d in inv.disputed:
            w(f"- disputed: {d}")
        for u in inv.unavailable:
            w(f"- unavailable: {u}")
        w("")
    return "\n".join(out) + "\n"
