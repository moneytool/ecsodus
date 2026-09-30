# Round 2 vote: Claude Opus 5.5

(Verbatim; read-only; 2026-09-29.)

## Vote
**APPROVE WITH CONDITIONS.** r2 fixes all four round-1 P0s at the design level (retain patch, custom-resource Retain, nested addons, app stack and StackSet). What remains are six specific edits to PLAN.md. They close gaps where following the runbook as written could still delete a live dependency or contradict itself. None of them needs a redesign.

## Round-1 findings status
| Finding | Status | Note |
|---|---|---|
| Opus 1, Fable 1, Astra 1 (P0): `--retain-resources` needs `DELETE_FAILED` | addressed | Retain patch, then `update-stack`, then `get-template` verify, then delete (§2, runbook 3–4). |
| Opus 2, Fable 3 (P0): env-controller removes ALB/NAT/EFS | addressed | Patch order is app, env, then workloads, with Retain on `EnvControllerAction`. Env resources are retained even if the Delete still fires, because Retain also covers removal during an update (AWS DeletionPolicy docs). |
| Opus 3, Fable 2, Astra 2 (P0): destructive custom-resource Delete handlers | partial | Retain on every `Custom::*` and inventory through the ACM/Route 53 APIs. But whether Retain actually suppresses the Delete call is still unverified; the AWS DeletionPolicy page only says "any resource type". There is no fallback if it doesn't, and no fate is stated for out-of-band certificates and records (C2). |
| Opus 4 (P0), Fable 8 (P1): addons are nested stacks with no `DeletionPolicy` | partial | Walked recursively and patched. The way to patch a nested stack (re-upload the child, update the parent's `TemplateURL`) is not specified (C5). |
| Opus 5 (P0), Fable 7 (P1): app stack and StackSet | addressed | ECR repos and hosted zone imported, `--retain-stacks`, "never run `copilot app/env delete`". |
| Astra 3 (P0): partial migrations, env teardown with remaining consumers | partial | `blocked` and `retain-under-existing-owner` fates exist. But runbook step 4 still deletes the env and app stacks unconditionally, even with blocked workloads in the env or other envs still on Copilot (C3). |
| Opus 6, Fable 4, Astra 6 (P1): Express fit matrix | partial | Express moved to opt-in rebuild mode (v0.3). The report promises "why the others can't" but §2 never defines the fit predicate (C6). |
| Opus 7 (P1): adopt in place by default | addressed | |
| Opus 8, Astra 11 (P1): DNS preconditions | partial | ACM ahead of time, atomic batches and TTL + 24h are in. The record-type/apex pre-flight (App Runner custom domains are CNAMEs) is missing. It only matters for rebuild mode and v0.2. Note, not blocking. |
| Opus 9, Astra 12 (P1), Fable 16 (P2): double work in parallel runs | partial | The report asks the question, but the rebuild runbook has no "keep new consumers disabled until cutover" step. Rebuild is opt-in, so note only. |
| Opus 10, Astra 13 (P1): SGs, IAM, secrets, KMS | partial | SGs imported and secret values never read. Task and execution roles, autoscaling and NAT/route tables are missing from the adopt list, and CMKs are not flagged (C1). |
| Opus 11, Fable 9, Astra 4 (P1): flat root imports, no config generation | addressed | Verified state membership before teardown is not explicit (folded into C4). |
| Opus 12, Astra 4 (P1): dual ownership, freeze | addressed | Runbook steps 1–2. |
| Astra 5 (P1): template is not live truth; pagination | addressed | Live reads, pagination, provenance, override detection. |
| Astra 7 (P1): pin and test versions together | addressed | Pins plus a support matrix for each release. |
| Astra 8 (P1): concurrency is not request count | addressed | Scaling is operator-selected. |
| Astra 9, Fable 15 (P2): App Runner security features | addressed (v0.2) | Dual-stack/IP address type still missing. Note. |
| Astra 10 (P1): source-based services | addressed | Deferred to v0.3, needs the repo and `apprunner.yaml`. |
| Astra 14 (P1): CI fights Terraform, one deploy owner | partial | `ignore_changes` targets the wrong attribute for adopt mode, and no post-migration deploy owner is named (C4, New). |
| Astra 15 (P1): validation too late and shallow | partial | Early M1 e2e with sentinel data, interrupted handoff and rollback. Missing: a partial-migration case, and a gate on unexpected *updates* (C4). |
| Astra 16, Fable 10 (P1): scope | addressed | Narrowed, report ships after M1, verify/cost/ADOT/Dockerfile/Proton/npm cut. |
| Fable 5 (P1): ADOT vs Express | addressed | Deferred to v0.3. |
| Fable 6 (P1): Express custom domains outside Terraform | addressed | Deferred with Express rebuild (v0.3). Revisit then. |

## Conditions
1. **§2 "Two modes" / report fates: dependency closure.** Add this rule: in adopt-in-place, any resource referenced by a surviving resource must be fated `import` or `retain-under-existing-owner`. That covers task and execution roles and their policies (including addon managed policies), autoscaling targets, policies and alarms, Cloud Map services, NAT gateways, EIPs, route tables, IGW and VPC endpoints. `drop-after-cutover` is allowed only for Copilot-internal resources: custom-resource Lambdas and their roles, and the pipeline bucket. `generate` must refuse output if the closure check fails. Why: the retain patch covers only imported and `Custom::*` resources, so a role fated `recreate` or `drop` gets deleted at teardown and running tasks lose credentials. Also flag CMKs in the report.
2. **§2 runbook step 3 and §6: custom-resource Delete.** Make "does Retain suppress the Delete call on `Custom::` resources" a hard gate. No teardown guidance ships until the M1 e2e confirms it, and the plan names a fallback. Also state fates for out-of-band objects: the ACM certificate, the validation CNAMEs and the alias A records are `import`.
3. **§2 runbook step 4: partial migrations.** Stop before deleting the env stack if any workload or addon in that env is `blocked` or not migrated. Delete the app stack and StackSet only after every env of the app has been migrated. `generate` should emit the runbook truncated at that point.
4. **§2 `check`: import-only gate and state check.** Add an import-only mode for runbook step 2. It fails on any action other than import/no-op, including updates, and it fails if any `import`-fated resource from `inventory.json` is missing from the plan's imports. Before step 3, compare `terraform state list` against the inventory. Add a `check` test and an e2e case for a partial migration.
5. **§2 runbook step 3: retain-patch mechanics.**
   - Patch nested addon stacks by uploading the patched child template to S3 and updating the parent with a new `TemplateURL`. Put Retain on `AddonsStack` too, so that "orphaned addon stacks" in step 4 is consistent.
   - Use S3 `TemplateURL` for templates over 51,200 bytes. Pass `UsePreviousValue` for every parameter and `CAPABILITY_IAM`/`CAPABILITY_NAMED_IAM`.
   - Go through a change set first, and abort if it shows any resource Modify or Replace.
   - Pre-check that each stack is in a `*_COMPLETE` state.
   - For StackSet instances: `delete-stack-instances --retain-stacks`, then retain-patch the now-standalone stack, delete it, then `delete-stack-set`. Do not run `update-stack` on a StackSet-managed instance.
6. **§2 report: Express fit predicate.** Write the predicate out: single container, no volumes or EFS, cpu ≤ 4096 and memory ≤ 8192, HTTP on an ALB, no NLB, no Service Connect/Cloud Map consumers, a subnet scheme that matches the wanted exposure, and a custom domain only through the documented manual listener-rule step.

## New issues in r2
- **P1: `deletion_protection` contradicts runbook step 2.** §2 `generate` emits `deletion_protection` on stateful resources, but step 2 requires an import-only apply with no attribute changes and then a zero-change plan. If the live Aurora cluster or DynamoDB table doesn't have protection on, the first plan shows an update. Fix: in runbook step 1, turn on RDS and DynamoDB deletion protection out of band, and emit HCL that matches. This also gives defence in depth: if a retain patch is missing, the CloudFormation delete fails into `DELETE_FAILED` instead of destroying data.
- **P1: IAM roles and network plumbing missing from the adopt-in-place list (§2).** See C1.
- **P2: `ignore_changes` on "the image" is the wrong attribute for adopt mode.** It should be `aws_ecs_service.task_definition` (plus `desired_count`). `aws_ecs_task_definition` is immutable, so any drift means a replace, which `check` will catch but which will be noisy. Name the post-Copilot deploy owner in RUNBOOK.md (for example ecspresso, or CI registering revisions).
- **P2: Terraform state is not addressed** (Astra's "missing" list): remote encrypted state with locking, and a checkpoint before teardown. Add one line to the runbook.
- **P2: inventory freshness.** A timestamp is recorded but never used. `check` and the runbook should refuse an inventory older than N hours, or one whose stack `LastUpdatedTime` has changed since, and should refuse if the account or region differs from the plan's provider.
- **P3: pins say "≥" but also "tested together".** Publish the exact tested versions in the support matrix (already implied in §9).
