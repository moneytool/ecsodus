# Verification review of the fixes: gpt-6-astra (Codex CLI, read-only)

(Verbatim, 2026-09-29/30, against 936da69. Every P1 in "New defects" and the listed partials were fixed in the following commit.)

## Verdict

**Fix first.** Reviewed the source diff and current code; 182 focused tests passed, but adversarial reproducers still produced unsafe gate passes and incomplete ownership plans. HEAD advanced during review to `936da69`; its runbook fail-fast fix is included below. No files were modified by this review. The sandbox blocked `uv run` cache/temp writes, so reproducers used `.venv/bin/python -B -c` with mocked AWS calls.

## Findings status

A = Astra finding; O = Opus finding. Grouped rows cover every P0/P1 finding.

| Finding | Fixed / partial / not fixed | Note (with reproducer result) |
|---|---|---|
| A1: Unauthorized template changes | fixed | `DisplayName: 1 → true` rejected by semantic and text checks; retain-patch tests pass. |
| A2 / O3: Nested change sets and hashes | partial | Missing referenced child and wrong URL rejected. Child with wrong `ParentChangeSetId`/`StackId` **passes**. Dynamic change attributed to a manifest child **passes without any child document**. URL equality does not verify uploaded bytes before execution. |
| A3: Unfinished change sets | partial | `CREATE_IN_PROGRESS` rejected. Nonempty document omitting `ExecutionStatus` **passes** because it defaults to `AVAILABLE`. |
| A4: Import identity | partial | Wrong import ID rejected. Correct ID with wrong provider/type **passes**; CLI discards those manifest identity fields. |
| A5 / O5: Steady resource survival | partial | Empty/incomplete plans rejected. Expected address containing `bucket-B` instead of manifest `bucket-A` **passes**. New `--forgotten` bypass described below. |
| A6: Secret-reading data sources | fixed | `aws_secretsmanager_secret_version` with `read` rejected; all data sources are forbidden. |
| A7: Freshness/live identity | partial | Stale manifest rejected, and runbook invokes `verify-fresh`. Mocked `UPDATE_IN_PROGRESS` stack with unchanged recorded timestamp **passes** freshness. Offline import check itself does not require proof of live verification. |
| A8: Vacuous retain verification | fixed | Zero discovered stacks returns `1`; deployed hash mismatch with manifest returns `1`. Full coverage is enforced when using the manifest without `--stack`. |
| A9 / O2: Hidden environments/consumers | partial | Other environments are discovered; unavailable-environment regression passes. An unselected environment **with no workloads** remains `handoff=True`, allowing its environment and app teardown. Selection only affects workloads. |
| A10: Teardown cutoff/dual ownership | fixed | Independent later environment remains in teardown; regression verifies imported resources belong to handed-off stacks. |
| A11: Kept-resource dependency closure | fixed | Kept workload referencing migrating cleanup Lambda now produces a closure error; regression passes. |
| A12: Out-of-band ownership | partial | Ordinary certificate import/keep tests pass. Blocked certificate does not block its owner; DNS ownership collisions silently omit records. See below. |
| A13: Paginator secret guard | fixed | Decrypting SSM paginator/history calls rejected; focused guard tests pass. |
| A14: Sensitive artifacts | partial | Mocked writes request/chmod `0600`; runbooks use `umask 077`; patch/plan files are ignored. Secret-bearing `*.tf` files remain committable, with only a warning. |
| A15 / O1: Regeneration scope/options | partial | Rendered commands preserve env, keep-set, bucket and teardown flag. Supplying `selection.profile="production"` still emits **no profile**; metadata-fallback generation is also not replayed. |
| A16 / O4: Failed checks continue | fixed | At current `936da69`, generated check is a standalone command. Mocked failure exits block `1` before any AWS mutation. |
| A17: Invalid change-set option | fixed | Rendered creates omit the option; describes include it. Installed botocore models confirm correct placement. |
| A18 / O8: StackSet order/waits | partial | Ordering, account/region scope and polling corrected. Failed per-instance results API **passes** the new completion check; see below. |
| A19: Cleanup without teardown | fixed | Rendering without teardown omits “now unowned” cleanup authorization and explicitly requires completed step 5. |
| O6: User Lambdas marked cleanup | fixed | Unreferenced user Lambda keeps its stack; custom-resource handler regression still passes. |
| O7: Transformed templates | fixed | Transform regression keeps the stack; code also detects resource-level intrinsics and nested `Fn::Transform`, preventing handoff. |

## New defects

1. **[P1] `--forgotten` can bypass survival checks for any resource** — `src/ecsodus/check/plan.py:104` — `check_plan({"resource_changes":[]}, {"aws_s3_bucket.prod":"bucket-A"}, "steady", ["aws_s3_bucket.prod"])` returns `ok=True`. The new exception intended for task-definition handoff can suppress coverage for production storage without even a `forget` action. **Fix:** derive eligible task-definition handoffs from complete manifest records; reject arbitrary exemptions and require evidence of the handoff.

2. **[P1] Blocked out-of-band certificates do not block teardown** — `src/ecsodus/mappers/fates.py:454` — Adding a discovered certificate with missing `DomainName` produces fate `blocked`, yet its owner remains `handoff=True` with `closure_errors=[]`. Generation can approve teardown while omitting the certificate from imports. **Fix:** propagate every out-of-band blocker into its owning stack before final fate demotion and teardown planning; fail closed for unknown ownership.

3. **[P1] DNS ownership ignores hosted-zone identity** — `src/ecsodus/mappers/fates.py:473` — Ownership is keyed only by `(name, type)`. Reproducer: a public-zone `api.example.com A` record is omitted when that tuple belongs to a CloudFormation record in another zone; `plan_zone_records(...)` returns `[]`. Split-horizon DNS can therefore leave records unmanaged while approving handoff. **Fix:** include hosted-zone ID and routing/set identity in ownership keys.

4. **[P1] StackSet result verification swallows API failures** — `src/ecsodus/emit/runbook.py:77` — Mocking operation status as `SUCCEEDED` and `list-stack-set-operation-results` as exit `9` with empty stdout makes the generated shell exit `0` and execute a continuation sentinel. `test -z "$(aws ...)"` tests empty output, masking the failed AWS command. **Fix:** capture results in a standalone checked assignment, then validate nonempty instance coverage and every instance’s success before proceeding.