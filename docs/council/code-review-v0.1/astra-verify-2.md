# Final verification: gpt-6-astra (Codex CLI, read-only)

(Verbatim, 2026-09-30, against d79b263. The new P1 and the partials marked below were fixed in the next commit; residual items are listed in README.md.)

## Verdict

**fix first**

Verified HEAD `d79b263` with `.venv/bin/python -B -c ...`: 102 focused tests passed, plus adversarial in-memory and shell reproducers. Repository unchanged. File-based tests were blocked by sandbox temporary-write restrictions.

## Status

| Item | fixed / partial / not fixed | Reproducer result |
|---|---|---|
| A1: Unauthorized template changes | fixed | `DisplayName: 1 → true` rejected by semantic and text checks. |
| A2 / O3: Nested change sets and hashes | partial | Missing child and foreign parent rejected. Child declaring itself its parent and supplying a wrong `StackId` still **passes**. Uploaded bytes remain unverified. |
| A3: Unfinished change sets | fixed | Missing `ExecutionStatus` and in-progress status rejected. |
| A4: Import identity | partial | Wrong ID rejected; correct ID with wrong resource type **passes**. Provider `evil.example/hashicorp/aws` also **passes** the suffix check. |
| A5 / O5: Steady resource survival | partial | Missing resources rejected; no-op for `bucket-B` when manifest expects `bucket-A` still **passes**. |
| A6: Secret-reading data sources | fixed | Data-source rejection regressions pass. |
| A7: Freshness/live identity | partial | `UPDATE_IN_PROGRESS` now returns `1`; `DELETE_COMPLETE` with matching timestamp returns `0`. Offline import gate still requires no live-verification proof. |
| A8: Vacuous retain verification | fixed | Empty discovery and deployed-template hash mismatch each return `1`. |
| A9 / O2: Hidden environments | fixed | Unselected environment without workloads remains kept; app layer also remains kept. |
| A10: Teardown cutoff | fixed | Independent-environment teardown and ownership regressions pass. |
| A11: Dependency closure | fixed | Kept workload referencing migrating cleanup resource produces closure error. |
| A12: Out-of-band ownership | partial | Known-owner blocked certificate keeps its stack. Unknown-owner certificate produces no closure error; DNS gaps remain below. |
| A13: Paginator secret guard | fixed | Decryption and secret-value paginator regressions pass. |
| A14: Sensitive artifacts | partial | Captured generated `.gitignore` still permits secret-bearing `*.tf` files. |
| A15 / O1: Regeneration options | fixed | Rendered commands preserve `--profile production`, environment, patch bucket, teardown flag and `--metadata-fallback`. |
| A16 / O4: Failed checks continue | fixed | Generated execution block exits `1` on failed check; execution sentinel is not reached. |
| A17: Invalid change-set option | fixed | Correct placement confirmed against installed botocore models. |
| A18 / O8: StackSet verification | partial | Results API exit `9` now stops shell. Zero result coverage still continues successfully; see new defect. |
| A19: Cleanup without teardown | fixed | Disabled-teardown rendering omits “now unowned” authorization and retains completion prerequisite. |
| O6: User Lambda cleanup | fixed | User Lambda keeps stack; handler regression passes. |
| O7: Transformed templates | fixed | Transform regression prevents handoff. |
| Review P1-1: Arbitrary `--forgotten` | partial | Bucket exemption rejected; task-definition exemption requires `forget`. Eligibility still comes from address prefix, not complete manifest handoff records. |
| Review P1-2: Blocked certificates | partial | Missing domain with known owner prevents teardown. Unknown owner still becomes `retain-under-existing-owner`, with `closure_errors=[]`. |
| Review P1-3: DNS ownership | partial | Distinct explicit zone IDs are distinguished. Same-zone different `SetIdentifier` is silently omitted; zone-name fallback also conflates same-name zones. |
| Review P1-4: Swallowed StackSet API failure | fixed | Mocked results API failure exits `9`, without continuation. New coverage-check defect remains. |

## New defects

1. **[P1] Empty StackSet result coverage fails open** — `src/ecsodus/emit/runbook.py:85`.

   **Scenario:** Operation status is `SUCCEEDED`, but result queries return `total=0`, `bad=0`. Running the generated helper under `set -euo pipefail`, followed by a continuation sentinel, prints `CONTINUED` and exits `0`.

   The new line `test "$total" -ge 1 && test "$bad" -eq 0` places the coverage check on the left of `&&`, where failure does not trigger `errexit`. Teardown can therefore continue without verified instance results.

   **Fix:** Emit both tests as separate checked commands, or explicitly exit when either fails. Validate expected account/region coverage before subsequent mutations.