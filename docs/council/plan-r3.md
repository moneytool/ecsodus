# ecsodus: plan (r3)

*Safe exit from AWS Copilot CLI to Terraform-managed ECS. 2026-09-29.*
*History: [r1](council/plan-r1.md), [r2](council/plan-r2.md). Council reviews and votes are in
[`council/`](council/README.md). r3 folds in every round-2 condition; §11 maps each one to the
section that addresses it.*

## 1. Problem and timing

| Tool | Status (2026-09-29) | Deadline | AWS path |
|---|---|---|---|
| Copilot CLI | End of support 2026-06-12; repo archived 2026-06-22 (3.7k stars, 446 forks) | None: stacks keep running, but the CLI goes stale. The custom-resource Lambdas run `nodejs20.x`: creating them is blocked from 2027-07-29, updating from 2027-08-31 | ECS Express Mode, CDK L3, or keep the CloudFormation |
| App Runner | Closed to new customers 2026-04-30; existing services keep running, no new features | None | ECS Express Mode + Route 53 weighted DNS |
| Proton | End of support **2026-10-07** | Yes, in 8 days | CloudFormation Git Sync, CodePipeline, GitHub Actions |

**The gap.** Leaving Copilot for Terraform means two things: import what Copilot built, then
delete Copilot's CloudFormation stacks without deleting the infrastructure. Doing that naively
destroys data and takes production down, for four reasons:

- **Custom resources.** Copilot's Lambda-backed custom resources, on stack delete, delete ACM
  certificates, DNS records and NS delegations, and empty buckets.
- **The env-controller.** Deleting the last service stack makes it remove the shared ALB, the
  NAT gateways and the EFS file system from the env stack.
- **Addons.** Addon databases live in nested stacks with no `DeletionPolicy`.
- **The app layer.** The app stack owns the hosted zone, and the app StackSet owns the ECR
  repositories, the KMS key and the pipeline bucket.

Generic tools cover none of this: extract-cf2tf, `-generate-config-out`, AWS's written guides.
**ecsodus knows where Copilot's landmines are.**

## 2. Product

`ecsodus` is a read-only Python CLI. It never applies Terraform, never modifies or deletes AWS
resources, never shifts traffic and never reads secret values. Every command that changes AWS is
written into the runbook for the operator to run.

```
ecsodus inventory --app myapp [--env prod] [--copilot-dir ./copilot]  -> inventory.json (0600, sensitive)
ecsodus report    inventory.json                                      -> REPORT.md (redacted)
ecsodus generate  inventory.json --out ./infra                        -> Terraform + retain patches + RUNBOOK.md
ecsodus check     plan.json --inventory inventory.json --phase import|steady
ecsodus check     --state state.txt --inventory inventory.json        -> every import-fated resource is in state
```

### 2.1 inventory
- **What it walks:** the app stack, the StackSet and its instance stacks, the env stack(s), and
  each workload stack with its nested addon stacks, recursively and fully paginated.
- **Live reads:** ECS service and task definition, autoscaling, and RDS/DynamoDB/EFS state.
  Copilot's SSM metadata (`/copilot/applications/...`).
- **Out-of-band objects** that custom resources created: ACM certificates, validation CNAMEs and
  alias records, found through the ACM and Route 53 APIs.
- **Provenance:** every field records its source, account, region and a timestamp.
- **Disagreements:** where the deployed template and live state disagree (drift, autoscaled
  counts, digests), both values are recorded and the field is marked `disputed`. ecsodus never
  picks one silently. Values that could not be read are `unavailable`, and that field is
  `blocked`.
- **Freshness:** stack `LastUpdatedTime` and the caller's account and region are recorded.
  `generate` and `check` refuse an inventory older than 24h, one whose stacks changed since
  (re-checked), or one whose account/region differs from the Terraform provider's.
- **Sensitivity:** `inventory.json` holds plaintext task-definition `environment` values, which
  are already readable by anyone who can describe the task definition. It is written with mode
  0600, and `generate` adds it to `.gitignore`. `secrets` stay as `valueFrom` ARNs; their values
  are never fetched. `REPORT.md` redacts every environment value and flags names that look like
  credentials.

### 2.2 Fates, and dependency closure
Every resource gets exactly one fate:

- `import`: it moves to Terraform.
- `retain-under-existing-owner`: it stays in its stack for now, because an unmigrated consumer
  still needs it.
- `drop-after-cutover`: it may be deleted. Only Copilot-internal resources qualify:
  custom-resource Lambdas and their roles and log groups, the pipeline bucket, and
  `EnvControllerAction`-style handles.
- `blocked`: unsupported. ecsodus refuses to generate anything for it.

**Closure rule.** Any resource referenced by a surviving resource must be `import` or
`retain-under-existing-owner`. `generate` refuses to produce output if the closure fails. In
adopt-in-place this covers:

- cluster, service, the current task-definition revision, task and execution IAM roles and their
  policies (including addon managed policies)
- autoscaling target, policies and alarms
- ALB, listeners, rules, target groups, security groups
- VPC, subnets, route tables and routes, IGW and attachment, NAT gateways, EIPs, VPC endpoints
- Cloud Map namespace and services, log groups
- addons (Aurora/RDS cluster and instances, DynamoDB, S3, addon secrets, addon client security
  groups), env-level EFS
- ECR repositories, the hosted zone, ACM certificates with their validation records, alias
  records
- SSM parameters, including `copilot secret init` SecureStrings, imported by name without
  reading their values
- KMS keys that any of the above use

**Blockers propagate.** If a workload is `blocked` or not being migrated, everything it depends
on is `retain-under-existing-owner`, including its env and the app. The runbook is cut short
before any stack that still has a consumer (§2.5). This covers:

- other environments of the same app
- workloads owned by other teams
- externally owned (imported) VPCs, which are referenced by data source and never imported

The report also:
- flags customer-managed KMS keys, with their key policy and grants
- flags secret rotation resources
- lists every resource that will *not* be retained

### 2.3 report
The report contains:
- **Fates, closure result and blockers.**
- **A per-stack table:** "deleting this stack would destroy …", before and after the patch.
- **A per-service double-work question:** "does this container run background work or migrations
  on boot?" This matters for rebuild mode only (v0.2).
- **Express fit** (see below).
- **The "keep CloudFormation" baseline:** the zero-risk option, with its caveat that the stacks'
  custom resources can't be recreated after 2027-07-29.

**Express fit predicate.** A service is eligible for Express Mode only if all of these hold,
otherwise it gets the plain `service` form:

- one container, no sidecars, no volumes or EFS
- cpu 256–4096 and memory 512–8192
- HTTP behind an ALB: no NLB, no gRPC-only, no Service Connect or Cloud Map consumers
- the subnet scheme matches the desired exposure (private subnets mean an internal ALB)
- any custom domain is accepted as a documented manual listener-rule step

This is informational in v0.1, since rebuild mode ships in v0.2.

### 2.4 generate
- **Terraform:** flat root-module `aws_*` resources with `import` blocks for everything fated
  `import`. Arguments come from the deployed template plus live reads, never from module internals
  or `-generate-config-out`. Every argument matches live state, so the first plan is import-only.
  - `lifecycle { prevent_destroy = true }` on stateful resources.
  - `deletion_protection` is emitted **only** where it is already on live. The runbook turns it on
    out of band first (§2.5 step 2), then ecsodus re-inventories, so the HCL matches live and the
    import stays import-only.
  - `ignore_changes = [task_definition, desired_count]` on `aws_ecs_service`.
  - Named deploy owner after migration: ecspresso, or CI that registers task-definition
    revisions. This is recorded in RUNBOOK.md. Terraform owns the infrastructure, not the image
    rollout.
  - Backend block: S3 remote state with encryption and native lockfile.
- **Retain patches.** For every stack, ecsodus emits the deployed template with
  `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` on **every resource not fated
  `drop-after-cutover`**. This includes every `Custom::*`, `EnvControllerAction`, and the
  `AddonsStack` nested-stack resource. Otherwise each template is byte-stable. The only other
  change allowed is a nested stack's `TemplateURL`, which points to the patched child template.
  - **Mechanics:** upload the patched child templates to S3 (the Copilot artifact bucket, or
    `--patch-bucket`), and update the root/parent stack with the new `TemplateURL`s. Never update
    a nested stack directly. The same applies to env-level addons under the env stack.
  - **Templates over 51,200 bytes** are passed by S3 URL.
- **Update commands** are generated for each stack: a change set, never a direct update, with:
  - `UsePreviousValue=true` for every parameter
  - the stack's existing capabilities (`CAPABILITY_IAM`/`CAPABILITY_NAMED_IAM`, plus
    `CAPABILITY_AUTO_EXPAND` if a `Transform` is present)
  - a `*_COMPLETE` pre-check
  - an **abort if the change set shows any resource `Modify`, `Add`, `Remove` or `Replace`**
- **Custom-resource neutralizer (fallback, emitted but unused by default).** This is a
  SUCCESS-on-everything responder, with the commands to swap each Copilot custom-resource
  Lambda's code for it before any `delete-stack`. The runbook uses it only if the e2e run shows
  that Retain does not suppress Delete invocations (§6).
- **RUNBOOK.md** (§2.5).

### 2.5 Runbook (adopt in place; v0.1 has no other mode)

1. **Freeze.** No `copilot deploy`, pause pipelines, record the stack `LastUpdatedTime`s.
2. **Protect.** Take snapshots and backups and do a test restore. Turn on RDS and DynamoDB
   deletion protection and S3 versioning where it is absent. Then `ecsodus inventory` again.
3. **Retain patches.** For each stack in order (app stack, then env, then workloads with nested
   addons), create the change set and check it: it must contain no resource changes. Execute it,
   wait for `UPDATE_COMPLETE`, then `get-template` every stack, including nested ones, and confirm
   the policies are on. This goes first so that nothing done later can delete data.
4. **Import.** `terraform plan -out` → `ecsodus check --phase import`, which fails on any action
   other than import or no-op, and on any expected import that is missing → `apply`. Then
   `terraform state list` → `ecsodus check --state`, then a second plan, which must show zero
   changes. Save a state checkpoint (`terraform state pull > checkpoint.tfstate`).
5. **Teardown.** Only for stacks with no remaining consumers, in this order:
   1. workload stacks
   2. orphaned addon stacks
   3. the env stack, but only if every workload in that env has migrated
   4. app StackSet instances with `delete-stack-instances --retain-stacks`, then retain-patch each
      standalone instance stack, delete it, and run `delete-stack-set`. Never `update-stack` a
      StackSet-managed instance.
   5. the app stack, but only if every env of the app has migrated

   `generate` stops the runbook at the first stack that still has a consumer.
6. **Verify.** Every imported resource still exists. A plan shows zero changes
   (`ecsodus check --phase steady`). Sentinel data reads back. List the leftover Lambdas, roles and
   log groups for manual cleanup. Retained resources keep their `aws:cloudformation:*` tags; the
   AWS provider ignores `aws:` tags, so they cause no drift.
7. **Never** run `copilot app delete` or `copilot env delete` after migrating.

**Rollback.** The rollback path depends on how far the runbook got:
- **Before step 5:** `terraform state rm` the imported addresses. CloudFormation still owns
  everything, and the retain patches are harmless.
- **After step 5:** Terraform owns the resources, so there is nothing to roll back to. The
  runbook says so before step 5 starts.

### 2.6 check
- **`--phase import`:** only `import` and `no-op` actions are allowed. It fails on any update,
  create, delete or replace, and on any import-fated resource that is missing from the plan's
  imports.
- **`--phase steady`:** it fails on destroy or replace of any imported address and warns on
  updates.
- **`--state`:** it confirms that every import-fated address is in state.

## 3. Scope

**v0.1 (in):**
- Copilot Load Balanced Web Service and Backend Service.
- Env stack, with a VPC that Copilot created or one that was imported (referenced, not imported).
- Workload and env addons: Aurora/RDS, DynamoDB, S3.
- Secrets and SSM parameters, by reference.
- Aliases and custom domains.
- App stack and StackSet.
- Env-level EFS (import).
- **Adopt in place only.**

**Detected and `blocked`, named in the report:** Worker Service, Scheduled Job, Request-Driven Web
Service, Static Site, NLB, CloudFront CDN, sidecars, Service Connect consumers, `copilot pipeline`,
multi-account environments.

**Later:**
- **v0.2:** rebuild-in-parallel mode and App Runner image-based services. v0.2 must also cover:
  - security-group membership and execution-role secret/KMS carry-over
  - the Express fit predicate applied
  - a DNS pre-flight covering record type and apex (App Runner domains are CNAMEs), atomic change
    batches, ACM issued in advance, and TTL + 24h
  - background consumers disabled until cutover
  - App Runner discovery: custom domains, VPC connector, VPC ingress connection, WAF, IP address
    type, endpoint security groups, TCP health check (needs an HTTP path), port, instance size,
    KMS, roles
  - operator-selected scaling
- **v0.3:** Worker Service and Scheduled Job, rebuild into Express, App Runner source-based (needs
  the repo and `apprunner.yaml`), ADOT tracing.

**Non-goals:** a deploy CLI (ecspresso exists), CloudFormation/CDK output, Proton tooling (one docs
page instead), cost estimation (a static table of line items instead), a hosted service, npm.

## 4. Knowledge base (M0)

- **`docs/knowledge/copilot-custom-resources.md`** covers all 14 custom resources from the
  archived source (Apache-2.0):
  - Resources: `alb-rule-priority-generator`, `backlog-per-task-calculator`, `bucket-cleaner`,
    `cert-replicator`, `custom-domain`, `custom-domain-app-runner`, `desired-count-delegation`,
    `dns-cert-validator`, `dns-delegation`, `env-controller`, `trigger-state-machine`,
    `unique-json-values`, `wkld-cert-validator`, `wkld-custom-domain`.
  - Columns: what it creates out of band, Delete behaviour, Terraform equivalent, fate.
- **`docs/knowledge/copilot-stacks.md`** covers:
  - the app, StackSet, env, workload and addons layering
  - which resources are conditional on `ALBWorkloads`/`NATWorkloads`/`EFSWorkloads`
  - the addon `DeletionPolicy` defaults (Aurora `DBCluster` defaults to `Snapshot`; secrets are
    deleted without recovery)
  - final-snapshot handling
- Both files double as the SEO docs pages.

## 5. Architecture

- **Stack:** Python 3.11+, boto3, a CloudFormation-aware YAML loader, Jinja2. Distributed via PyPI
  (`uvx ecsodus`/`pipx`) only after the AWS e2e run (§6).
- **Support matrix:** exact tested versions of Terraform, the AWS provider and
  terraform-aws-modules/ecs (the last only for new compute, from v0.2). Generated `required_version`
  and `required_providers` constraints are bounded, e.g. `~> 6.41`, not open `>=`.
- **Layout** (see ADR-0010):
  - `sources/copilot`: stack-graph walker, live reads, override detection
  - `model/`: provenance on every field; `disputed` and `unavailable` values
  - `mappers/`: fates and closure, one rule per knowledge-base row
  - `emit/terraform`
  - `emit/retain_patch`
  - `emit/runbook`
  - `check/`
  - `cli`

## 6. Validation

**Offline (v0.1 development, free; the maintainer's decision of 2026-09-29):**
- **Golden tests:** fixtures built from the archived Copilot repo's own templates and its
  integration-test outputs, plus recorded API responses. Snapshot the Terraform, the retain
  patches and the runbook.
- **Retain-patch invariants:** Retain is on every non-drop resource. Nothing else changed except
  `TemplateURL`. The YAML round-trip is stable, including `!Ref`/`!Sub`/`!GetAtt` short forms.
- **Closure and blocker-propagation tests,** including a mixed supported/blocked app and a
  two-env app with one env migrated.
- **`check` tests:** synthetic `terraform show -json` plans covering updates, creates, replaces,
  destroys, missing imports and state gaps.
- **Inventory against moto** (mocked CloudFormation, ECS, ELBv2, Route 53, ACM, RDS, DynamoDB,
  EC2, SSM): pagination, nested stacks, disputed values, freshness refusal.
- **Terraform:** `terraform validate` on generated output in CI.

**Real AWS end-to-end: required before any public release or PyPI publish.** It needs separate
approval; cost is about $1–3. Deploy a Copilot sample with the archived CLI (LBWS + Aurora addon;
custom domain optional) and write sentinel data. Then run ecsodus and the full runbook, and assert
that the sentinel data, ALB, certificate, DNS and ECR images survive. It also settles these
questions:
- **Does `DeletionPolicy: Retain` on `Custom::*` suppress the Delete invocation?** If not, the
  runbook switches to the neutralizer (§2.4). The design does not change.
- **Is a DeletionPolicy-only change set accepted** with no resource changes?
- **Does ACM validation CNAME reuse survive** the old certificate's retention?

It also covers an interrupted handoff and rollback before step 5. Until it passes, the RUNBOOK
teardown section carries an **UNVERIFIED** banner, and `generate` requires
`--i-understand-teardown-is-unverified` to emit steps 5–7. The e2e must run before 2027-07-29
(the `nodejs20.x` create block).

## 7. Milestones

| # | Deliverable |
|---|---|
| M0 | Repo, docs, ADRs, CI, fixture corpus, knowledge base |
| M1 | `inventory` + `report` (useful on their own) |
| M2 | `generate` (Terraform, retain patches, neutralizer, runbook) + `check` |
| M3 | Offline test suite green; private tag v0.1.0-rc |
| M4 | Real AWS e2e (needs approval) → public release, PyPI, docs pages, launch posts |
| M5 | v0.2: rebuild mode + App Runner |

## 8. Success measures (first 90 days after public release)
- 3 completed migrations reported by users. 10 report runs shared as feedback.
- Zero reports of data loss or outage caused by following the output.
- Cited in at least one migration guide. Stars are secondary.

## 9. Risks
- **Small audience.** Ship the report first. Recruit 2–3 design partners (copilot-cli issues,
  Reddit) before public release.
- **Wrong import or teardown causes an outage or data loss.** Mitigations:
  - read-only tool, retain-all patches, closure rule, blocker propagation
  - `prevent_destroy`, deletion protection turned on before import
  - `check` gates, backups with a test restore
  - the UNVERIFIED gate until the e2e passes
- **Provider or module drift.** A bounded support matrix.
- **Competitors:** AWS guides, Encore, fortem.dev, generic MCP tooling. They cover rebuilds. The
  wedge is safe adoption of existing Copilot infrastructure into maintainable Terraform.
- **Repo visibility:** the GitHub repo stays private until the e2e passes and the maintainer
  decides to publish.

## 10. Decisions (each is an ADR in `docs/adr/`)
1. Name: ecsodus.
2. Copilot first; App Runner in v0.2.
3. Adopt in place is the default, and the only mode in v0.1.
4. Retain-all patches applied via change sets, instead of `--retain-resources`.
5. Python.
6. Terraform only: flat root resources for imports, no config generation.
7. No Proton tooling.
8. Offline testing for development; a real AWS e2e gates public release.
9. Private repo until release.
10. Repository layout and documentation standard.

## 11. Round-2 conditions → where addressed

| Condition | Where |
|---|---|
| Astra C1 / Opus C3 / Fable C3: blockers propagate, no stack deleted while a consumer remains, mixed test | §2.2, §2.5 step 5, §6 |
| Astra C2 / Opus C5 / Fable C4: nested mechanics, TemplateURL, change set, UsePreviousValue, capabilities, `*_COMPLETE`, >51,200 B | §2.4, §2.5 step 3 |
| Astra C3 / Opus C5: app stack vs StackSet instances; §1 attribution corrected | §1, §2.5 step 5 |
| Astra C4 / Opus C1: fates for secrets, SSM, roles, policies, rotation, KMS; env-value contract | §2.1, §2.2 |
| Astra C5 / Opus C4 / Fable new-P2: import-phase guard rejects updates, state check, deletion protection turned on before import | §2.4, §2.5 steps 2 and 4, §2.6 |
| Astra C6 / Fable C6: rebuild not in v0.1 | §2.5, §3 |
| Fable C1 / Opus C1: retain-all instead of a whitelist; closure; import list extended | §2.2, §2.4 |
| Fable C2 / Opus C2: Retain-suppresses-Delete fallback (neutralizer); out-of-band objects imported | §2.2, §2.4, §6 |
| Fable C5 / Opus C6: Express predicate written down | §2.3 |
| Opus: `ignore_changes` on `task_definition`, named deploy owner | §2.4 |
| Opus/Astra: remote state, locking, checkpoint | §2.4, §2.5 step 4 |
| Opus/Astra: inventory freshness, account/region | §2.1 |
| Astra/Opus: bounded pins | §5 |
| Astra: disputed/unavailable values | §2.1 |
| Fable: retain before import | §2.5 order |
| Fable: `aws:` tags, `nodejs20.x` dates | §1, §2.3, §2.5 step 6, §6 |
| Fable: final-snapshot handling | §4 |
