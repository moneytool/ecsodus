# Round 2 vote: Claude Fable 5.1

(Verbatim; read-only; 2026-09-29.)

## Vote

**APPROVE WITH CONDITIONS.** r2 fixes every P0 from round 1 (retain patch, custom-resource Delete handlers, env-controller, nested addons, app stack/StackSet, adopt-in-place default) and the timing/pin facts check out (aws/copilot-cli: 3,733 stars, 446 forks, archived; express-service `versions.tf`: Terraform ≥ 1.5.7, aws ≥ 6.41; `ecsodus` free on PyPI); one P1 remains: the retain patch is a whitelist and leaves load-bearing non-imported resources (IAM roles, NAT/EIP/routes/IGW, autoscaling) to be deleted with the stacks.

## Round-1 findings status

| Finding | Status | Note |
|---|---|---|
| Fable 1 / Astra 1 / Opus 1 (P0) `--retain-resources` | addressed | §2 retain patches + runbook step 3 (`update-stack`, verify with `get-template`). |
| Fable 2 / Astra 2 / Opus 3 (P0) custom-resource Delete handlers (ACM, R53, bucket-cleaner, dns-delegation) | addressed | ACM/R53 discovery via APIs, `Retain` on every `Custom::*`, knowledge-base Delete column, `blocked` for unknowns, leftover-Lambda list in step 5. Whether `Retain` suppresses the Delete invocation stays unverified (AWS docs only say Retain applies to "any resource type"; the custom-resource protocol page says Delete is sent on stack delete, with no Retain carve-out) — see condition 2. |
| Fable 3 / Opus 2 (P0) env-controller deletes ALB/NAT/EFS | partial | `EnvControllerAction` gets `Retain` and the report lists per-stack side effects. But env ALB/NAT/EIP/EFS are only retained if fated `import`, and NAT/EIP are not in the §2 import list — condition 1. |
| Astra 3 (P0) service-first unsafe for partial migrations | partial | `blocked` and `retain-under-existing-owner` fates exist; addons recursed at both levels. Runbook step 4 does not say "do not delete env/app stacks while any blocked or unmigrated workload stack remains" — condition 3. |
| Opus 4 (P0) nested addons stack | partial | Nested templates are patched and orphaned addon stacks are deleted after the workload. Mechanics unstated: the `AddonsStack` (`AWS::CloudFormation::Stack`) resource must itself get `Retain`, and the nested template is patched via the parent's `TemplateURL` (S3 upload), not by updating the nested stack directly — condition 4. |
| Fable 7 / Opus 5 (P0) app stack + StackSet | addressed | §1, §2 inventory, runbook step 4 (`--retain-stacks`), step 6 (never `copilot app/env delete`), ECR + hosted zone import. |
| Fable 4 / Astra 6 / Opus 6 (P1) Express fit predicate / matrix | partial (deferred) | Express is opt-in rebuild, v0.3 for Copilot; report says "why the others can't", but the predicate itself is not written down anywhere in PLAN.md — condition 5. |
| Fable 5 (P1) ADOT vs Express | addressed | ADOT and sidecars out of v0.1 (blocked / v0.3). |
| Fable 6 (P1) Express custom domains outside TF | addressed (deferred) | Falls with Express rebuild to v0.3. |
| Fable 8 (P1) addon deletion defaults | addressed | Retain patch on nested stacks, `prevent_destroy` + `deletion_protection`, knowledge-base table of addon defaults. Final-snapshot handling not mentioned (note). |
| Fable 9 / Astra 4 / Opus 11 (P1) flat root resources, no `-generate-config-out`, verified state + no-change plan | addressed | §2 generate, runbook step 2, `check`. |
| Fable 10 / Astra 16 / Opus 12-adjacent (P1) scope vs hours; npm/Backend inconsistency | addressed | v0.1 = LBWS + Backend adopt-in-place; `verify`, cost model, Dockerfile gen, ADOT, Proton, npm dropped; M4 optional. |
| Astra 5 (P1) template is not operational truth | addressed | Live reads, pagination, provenance/timestamps, manifest-vs-template override detection, `blocked` over guessing. |
| Astra 7 (P1) API vs Terraform gates | addressed | Pins tested together, support matrix per release. |
| Astra 8 (P1) concurrency → request-count | addressed | v0.2: operator-selected scaling. |
| Astra 9 (P1) App Runner ingress/WAF/KMS discovery | addressed (deferred) | v0.2 scope lists ingress connections, WAF, KMS, roles; IP address type/endpoint SGs not named (note for v0.2). |
| Astra 10 (P1) source-service containerization | addressed | v0.3, requires repo + `apprunner.yaml`; Dockerfile generation dropped. |
| Astra 11 / Opus 8 (P1) DNS cutover preconditions, record type/apex | addressed (deferred) | Rebuild mode: ACM ahead, atomic change batches, TTL + 24h. Explicit record-type/apex pre-flight not named; only matters from v0.2 (note). |
| Astra 12 / Opus 9 (P1) parallel double-work | addressed | Per-service double-work question; adopt-in-place moves no traffic. |
| Astra 13 (P1) secrets ownership/disclosure | addressed | Never reads secret values, redacts env, secrets by reference; roles imported in adopt-in-place. |
| Astra 14 (P1) CI fights Terraform | addressed | `ignore_changes` on image when CI deploys; no deploy CLI. |
| Astra 15 (P1) validation too late/shallow | addressed | Real e2e in M1 with sentinel data, interrupted handoff, rollback; LocalStack gone. (Deploying the sample with the archived CLI still works: its `nodejs20.x` custom-resource runtime is deprecated but function-create is not blocked until 2027-07-29.) |
| Opus 7 (P1) rebuild is the riskier default | addressed | Adopt in place is the default. |
| Opus 10 (P1) SG/secret/KMS wiring for new tasks | partial | Irrelevant in adopt-in-place (imported). §2 lists rebuild mode as an opt-in without saying which release ships it; if rebuild is in v0.1 the SG/role carry-over must be specified — condition 6. |
| Opus 12 (P1) dual ownership | addressed | Runbook step 1 freeze, import-only apply, zero-change plan. |

## Conditions

1. **(P1, must land before M2) §2 "generate" → Retain-patch templates, and §2 "Adopt in place".** Invert the rule: the retain patch sets `DeletionPolicy: Retain` / `UpdateReplacePolicy: Retain` on **every** resource in every stack except those explicitly fated `drop-after-cutover`, and the report lists what will *not* be retained. As written ("every imported resource and every `Custom::*`"), deleting the env stack deletes the IGW attachment, route tables/routes, NAT gateways and EIPs (subnets fall back to the main route table — egress outage), the env security group and the access-logs bucket; deleting a workload stack deletes the task/execution IAM roles (new task launches fail on the next scale-out or deploy), autoscaling target/policies and alarms. Also extend the adopt-in-place import list with: IAM task/execution roles, the current task definition revision, autoscaling target and policies, NAT gateways, EIPs, route tables, IGW, VPC endpoints if present, and the env-level EFS when it exists.
2. **§6 Validation, "unverified questions".** State the fallback now, so a negative e2e result does not reopen the design: if `Retain` on a `Custom::*` does not suppress the Delete invocation, the runbook adds a step before each `delete-stack` that neutralizes the handler (update the custom-resource Lambda's code to a responder that returns `SUCCESS` on every request, or repoint `ServiceToken` to such a function in the retain patch). ecsodus stays read-only; it emits the function and the commands.
3. **§2 Runbook step 4.** Add: "Do not delete the env stack or the app stack while any workload stack remains in the environment or application (blocked, unmigrated, or owned by another team). Those stacks keep fate `retain-under-existing-owner`, and `ecsodus report` prints the list." This is Astra 3.
4. **§2 "generate" or §5 `emit/retain_patch`.** Specify the nested-stack mechanics: the parent's `AddonsStack` resource gets `Retain`; the patched addons template is uploaded to S3 (the Copilot artifact bucket or a user-supplied bucket) and the parent is updated with the new `TemplateURL`; the same for env-level addons under the env stack. Say that the runbook's `update-stack` calls pass `UsePreviousValue=true` for every parameter and the capabilities the stack already has (`CAPABILITY_NAMED_IAM`, `CAPABILITY_AUTO_EXPAND` where a `Transform` is present).
5. **§3 or §4.** Write the Express fit predicate the report will apply, in one list: single container; no sidecars/volumes/EFS; cpu 256–4096 and memory 512–8192; HTTP behind an ALB (no NLB, no gRPC-only, no Service Connect consumers); subnet scheme matches desired exposure (private subnets ⇒ internal ALB); custom domain accepted as a manual listener-rule step. Everything else ⇒ `service` submodule.
6. **§2 "Two modes" / §3.** State which release ships rebuild-in-parallel mode. Recommended: v0.1 is adopt-in-place only; rebuild arrives in v0.2 with App Runner. If it stays in v0.1, add the SG-membership and execution-role secret/KMS carry-over (Opus 10) to the mapper scope.

## New issues in r2

- **P1** — Retain whitelist leaves load-bearing non-imported resources unprotected (condition 1).
- **P2** — Runbook ordering: apply the retain patches (step 3) immediately after the freeze (step 1), before the Terraform import (step 2). The patch is harmless to Terraform and protects against any accidental delete during the import work; nothing depends on import happening first.
- **P2** — `check` only fails on destroy/replace of imported addresses. During the import-only phase it should also fail on any `update` to an imported address, since runbook step 2 requires a zero-change plan anyway; make `check --strict` the mode used in step 2.
- **P3** — Step 5 tag note: the AWS provider ignores `aws:`-prefixed tags by default, so retained `aws:cloudformation:*` tags will not show as drift; say so, and say the operator may leave them.
- **P3** — Copilot's custom-resource Lambdas run `nodejs20.x` (deprecated 2026-04-30; create blocked 2027-07-29, update blocked 2027-08-31). Not a problem for the retain patch (no Lambda change) or for today's e2e deploy, but the §6 e2e must happen before 2027-07-29, and the "keep CloudFormation" baseline in the report should carry a note that the stacks' custom resources become un-recreatable after that date.
