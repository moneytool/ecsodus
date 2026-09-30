# Round 3 vote: Claude Opus 5.5

(Read-only; 2026-09-29.)

## Vote
**APPROVE WITH NOTES.** r3 addresses every round-2 condition and every round-2 P1 from all three votes, and I found no remaining P0 or P1. The new mechanics r3 adds contain two internal contradictions: the change-set abort rule versus nested `TemplateURL` updates, and the freshness check versus step 3. Both stop the runbook instead of letting it destroy anything, so they are P2 fixes to fold in during M2.

## Round-2 conditions status
| Condition | Status | Note |
|---|---|---|
| Astra C1 / Opus C3 / Fable C3: blockers propagate, no teardown with consumers, mixed test | addressed | §2.2 "Blockers propagate" (other envs, other teams, imported VPC); §2.5 step 5 is gated per stack and truncated; §6 has the mixed-app and two-env tests. |
| Astra C2 / Opus C5 / Fable C4: nested mechanics | addressed | §2.4 covers S3 upload, root-driven `TemplateURL`, Retain on `AddonsStack`, env addons, >51,200 B, `UsePreviousValue`, capabilities incl. `AUTO_EXPAND`, `*_COMPLETE`, change set only; §2.5 step 3 runs `get-template` on nested stacks. The abort rule conflicts with this (note 1). |
| Astra C3 / Opus C5 (StackSet part): app stack vs StackSet instances; §1 attribution | addressed | §1 is corrected (hosted zone in the app stack; ECR/KMS/bucket in the StackSet). §2.5 step 5.4: `--retain-stacks`, then patch the standalone stack, delete it, then `delete-stack-set`; never `update-stack` a managed instance. |
| Astra C4 / Opus C1: secrets, SSM, roles, policies, rotation, KMS; env-value contract | addressed (rotation partial) | §2.2 closure list imports roles, policies, addon secrets, SSM SecureStrings by name, and the KMS keys they use. The env contract is plaintext in a 0600 `inventory.json`, redacted only in `REPORT.md`. Rotation resources are only flagged (note 6). |
| Astra C5 / Opus C4 / Fable new-P2: import-only guard, state check, deletion protection | addressed | §2.6 `--phase import` fails on update, create, delete, replace and on missing imports; `--state` added; `deletion_protection` is turned on out of band, then re-inventoried (§2.4, §2.5 step 2). |
| Astra C6 / Fable C6: rebuild not in v0.1 | addressed | §2.5 heading, §3 "Adopt in place only"; v0.2 carries the SG, KMS, DNS and double-work items. |
| Fable C1 / Opus C1: retain-all, closure, extended import list | addressed | §2.4 puts Retain on every resource not fated drop; §2.2 closure rule makes `generate` refuse output when it fails, and the list includes NAT, EIP, routes, IGW, VPC endpoints, autoscaling, current task-def revision, EFS. The pipeline-bucket drop fate needs care (note 3). |
| Fable C2 / Opus C2: Retain-suppresses-Delete fallback; out-of-band objects imported | addressed | §2.4 neutralizer; §6 hard gate via the UNVERIFIED banner and `--i-understand-teardown-is-unverified` flag; ACM certs, validation CNAMEs and alias records are in the import list. |
| Fable C5 / Opus C6: Express predicate | addressed | §2.3, informational in v0.1. |
| Astra new P1 / Opus new P1: `deletion_protection` vs import-only | addressed | §2.4 emits it only where it is already on live; §2.5 step 2 turns it on first. |
| Fable new P1 / Opus new P1: whitelist leaves IAM, network, autoscaling unprotected | addressed | Retain-all plus closure (§2.2, §2.4). |
| Opus P2s: `ignore_changes` target, deploy owner, remote state, checkpoint, freshness | addressed | §2.4, §2.5 step 4, §2.1. |
| Astra P2s: bounded pins, disputed/unavailable values | addressed | §5 uses `~>` plus exact tested versions; §2.1. |
| Fable P2/P3s: retain before import, `aws:` tags, `nodejs20.x` dates, final snapshot | addressed | §2.5 order and step 6, §1, §2.3, §4, §6. I verified the `nodejs20.x` dates against the AWS Lambda runtimes page: deprecated 2026-04-30, create blocked 2027-07-29, update blocked 2027-08-31. The `aws:`-tag claim is correct. |

## Blocking issues (only if REJECT)
None.

## Notes (non-blocking)
1. **P2: §2.4 abort rule vs nested stacks.** "Abort if the change set shows any resource `Modify`" will fire on every parent that has addons. A changed `TemplateURL` is a property change on `AWS::CloudFormation::Stack`, so the parent change set shows `Modify` on `AddonsStack`. Fix:
   - create change sets with `--include-nested-stacks`;
   - allow `Modify` only on `AWS::CloudFormation::Stack` resources whose sole changed property is `TemplateURL`;
   - check each child change set recursively under the same rule.

   Also decide how a DeletionPolicy-only change shows up, which §6 already asks. Key the check on `ResourceChange.Details`/`Scope` (no `Properties` or `Tags` changes) rather than on `Action` alone, in case AWS reports policy-only edits as `Modify`. As written the rule fails closed, but it would block every addon-bearing workload.
2. **P2: §2.1 freshness vs §2.5 steps 3 and 4.** Step 3 updates every stack, so each `LastUpdatedTime` changes. The step-4 `check` then refuses the inventory taken in step 2 because "stacks changed since". Fix: end step 3 with `ecsodus inventory` again, or let freshness accept changes whose template diff is exactly ecsodus's own retain patch (verified with `get-template`).
3. **P2: §2.2 `drop-after-cutover` includes "the pipeline bucket".** In Copilot, the StackSet's artifact bucket also holds addon templates and `env_file` uploads, which task definitions reference by S3 ARN (`environmentFiles`). §2.4 also proposes it as the default `--patch-bucket`. Fix:
   - fate it `import` or retain by default;
   - make the closure rule scan ARN-string references (`environmentFiles`, `TemplateURL`, IAM policy resources), not only `Ref`/`GetAtt`.

   Otherwise the StackSet teardown (step 5.4) can break task launches. A non-empty bucket makes CloudFormation's delete fail rather than succeed, which limits the damage.
4. **P2: §2.5, coexistence after a partial migration.** Retained env and app stacks keep resources that Terraform now also owns. `copilot env deploy` or `copilot app upgrade` against a retained env re-renders the template without the Retain policies and can modify imported resources. Add rules:
   - after a partial migration, only `copilot svc deploy` of unmigrated workloads is allowed;
   - never `env deploy` or `app upgrade` a retained stack;
   - re-run the retain verification (`get-template`) after any Copilot operation.
5. **P3: §6 gating scope.** `--i-understand-teardown-is-unverified` gates steps 5–7, which also hides step 6 (Verify) and step 7 ("never run `copilot app/env delete`"). Gate only step 5, and always emit steps 6 and 7.
6. **P3: §2.2 rotation resources** are only flagged. With retain-all they survive but end up with no owner. Give them an explicit fate (import, or documented manual ownership) in the report.
7. **P3: §2.4 S3 native lockfile** (`use_lockfile`) needs Terraform ≥ 1.10. Make that the floor in the §5 support matrix.
8. **P3: §2.4 imported `aws_ecs_task_definition`.** Once the named deploy owner registers new revisions and deregisters old ones, Terraform will plan to recreate the imported revision. Consider `removed`/`state rm` of the task definition after cutover, or leaving it out of the import set and relying on `ignore_changes` on the service.

Sources: [AWS Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), [CloudFormation DeletionPolicy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html), [Viewing a change set](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-updating-stacks-changesets-view.html)
