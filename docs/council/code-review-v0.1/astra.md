# Code review: gpt-6-astra (Codex CLI, read-only)

(Verbatim, 2026-09-29, against commit 66f3245.)

## Verdict

**Fix first.** Offline reproductions confirmed unsafe gate passes, incomplete ownership closure, secret-protection gaps, and dangerous runbook behavior. The 65 existing retain-patch, change-set, plan, and fate tests pass but miss these cases. No files were modified; no live AWS mutations were performed.

## Findings

1. **[P0] Template verification accepts unauthorized changes** — `src/ecsodus/emit/retain_patch.py:208` — Changing `Properties.DisplayName: 1` to `true` passes because Python considers `1 == True`. `_strip()` also removes `ecsodus:retain` metadata unconditionally, permitting its alteration without fallback enabled. Both reproductions return no problems. **Fix:** compare scalar types explicitly, condition metadata exemptions on the flag, and enforce byte stability outside approved edit spans.

2. **[P0] Nested change sets and template hashes are not verified** — `src/ecsodus/check/changeset.py:162` — A known `AddonsStack` with `TemplateURL` changed to an arbitrary URL passes with its referenced child change set entirely absent. The checker receives logical IDs, not hashes; `--allow-nested-dynamic` likewise trusts membership without verifying the child. **Fix:** bind stack/change-set identities, require every descendant recursively, and verify new child template bytes against manifest hashes.

3. **[P0] Unfinished change sets pass with zero inspected changes** — `src/ecsodus/check/changeset.py:99` — `{"Status":"CREATE_IN_PROGRESS"}` returns `PASS`, accepted changes `0`. The generated waiter explicitly ignores failure, allowing this input to reach the gate. **Fix:** require completed, executable change sets and reject incomplete documents; handle verified no-ops separately.

4. **[P0] Import gate checks addresses but ignores physical IDs** — `src/ecsodus/cli.py:149` — A manifest expecting production bucket A accepts `change.importing.id = B` at the same Terraform address. The wrong infrastructure is adopted while A is later detached from CloudFormation. **Fix:** pass complete manifest import records and validate physical ID, resource type, and provider identity.

5. **[P0] Steady gate does not establish resource survival** — `src/ecsodus/check/plan.py:71` — An empty steady plan passes even when the manifest expects production resources. A targeted plan or wrong empty configuration therefore satisfies the runbook’s survival check. **Fix:** require complete expected-resource coverage and live identity verification against the handoff record.

6. **[P0] Deferred secret-reading data sources pass** — `src/ecsodus/check/plan.py:53` — Adding an `aws_secretsmanager_secret_version` data source with `actions: ["read"]` passes either phase; applying the accepted plan can fetch plaintext secret material into state. **Fix:** explicitly restrict permitted data-source types and reads; reject secret-value reads.

7. **[P0] Freshness and live identity requirements are unenforced** — `src/ecsodus/cli.py:148` — Checks consume a manifest without validating its age, recorded stack update times, or caller identity. Generation only checks inventory age. A stack changed since inventory can still receive approval based on obsolete ownership information. **Fix:** recheck identity and stack freshness before import; use handoff identities after teardown.

8. **[P0] `verify-retain` succeeds without checking any stack** — `src/ecsodus/cli.py:237` — A wrong app name or region yielding no matching stacks returns exit code `0`. It also never validates recorded child hashes. **Fix:** require an expected stack set, reject missing/empty coverage, and compare deployed child hashes.

9. **[P1] Environment filtering hides surviving app consumers** — `src/ecsodus/sources/copilot.py:85` — With environments `prod` and `staging`, inventorying `--env prod` discards staging before fate propagation. App resources and StackSet instances can reach teardown while staging still consumes them. **Fix:** discover all consumers; use environment selection only to determine migration eligibility.

10. **[P1] Teardown cutoff creates dual ownership** — `src/ecsodus/mappers/fates.py:342` — A kept alphabetically earlier environment truncates later environments from teardown, but those later stacks retain `handoff=True` and their resources remain imports. Reproduced: resources are imported while their owning stack remains. **Fix:** reconcile final teardown eligibility with fates before emitting imports.

11. **[P1] Closure ignores dependencies of surviving kept resources** — `src/ecsodus/mappers/fates.py:306` — A kept workload’s IAM policy referencing a Lambda in a migrating workload produces no closure error; that Lambda’s stack reaches teardown and the Lambda reaches manual cleanup. **Fix:** build dependency closure across all surviving resources, including kept consumers and literal ARN/name references.

12. **[P1] Out-of-band certificates and DNS disappear from ownership planning** — `src/ecsodus/mappers/fates.py:115` — `inventory.out_of_band` is never consumed by the planner. A discovered custom-domain certificate receives no fate/import, and `_out_of_band()` emits no DNS records. Migration can be reported complete with these dependencies unmanaged. **Fix:** include these objects and their consumers in fate assignment, imports, and closure.

13. **[P0] Paginators bypass the secret-read guard** — `src/ecsodus/sources/aws.py:59` — `ReadOnlyClient(..., "ssm").get_paginator("get_parameters_by_path").paginate(WithDecryption=True, ...)` reaches the underlying client and returns plaintext. Confirmed with a stubbed response; the direct-call guard is bypassed. **Fix:** guard paginator operations and arguments using the same restrictions as direct calls.

14. **[P0] Sensitive generated artifacts lack required protection** — `src/ecsodus/cli.py:97`; `src/ecsodus/emit/terraform.py:246` — Templates containing plaintext credentials/environment values are written as ordinary retain-patch files. Generated `.gitignore` omits these patches, secret-bearing `.tf` files, and saved `.plan` files. Runbook plan JSON redirections also inherit the operator’s umask. **Fix:** write sensitive artifacts with `0600`, establish `umask 077`, and ignore every sensitive generated artifact.

15. **[P1] Regeneration silently changes partial-migration scope** — `src/ecsodus/emit/runbook.py:147` — Starting with `--keep-on-copilot worker`, the emitted re-inventory command omits that selection. Regeneration marks the worker and potentially its shared dependencies for migration. **Fix:** persist and replay migration selections, AWS context, and generation options.

16. **[P0] Failed checks do not stop pasted runbook commands** — `src/ecsodus/emit/runbook.py:280` — Pasting the import block executes `terraform apply tf-import.plan` after a failed `ecsodus check`. The same unconditional sequencing exists before change-set execution and stack deletion. **Fix:** explicitly chain each mutation to successful checks or emit fail-fast scripts.

17. **[P1] Change-set commands use an invalid option** — `src/ecsodus/emit/runbook.py:224` — `--include-property-values` is emitted on `create-change-set`, where it is unsupported, and omitted from `describe-change-set`, where metadata verification needs it. Confirmed against the installed botocore operation models. **Fix:** move the option to every root and descendant describe command.

18. **[P1] StackSet teardown ordering and waits are incorrect** — `src/ecsodus/emit/runbook.py:336` — The first deletion loop deletes the app stack before the later StackSet teardown block. That block requests asynchronous detachment and immediately attempts standalone deletion without waiting for successful operation and instance results. **Fix:** execute workload → addons → environment → detached instances → StackSet → app, with machine-enforced completion checks.

19. **[P1] Cleanup is instructed even when teardown is disabled** — `src/ecsodus/emit/runbook.py:378` — Default generation omits step 5 but still tells the operator to delete resources described as “now unowned,” selected from the planned teardown list. Those Lambdas may still serve live CloudFormation stacks. **Fix:** condition cleanup authorization on verified completed teardown, while retaining read-only verification instructions.