# ecsodus: plan (r4, APPROVED)

*Safe exit from AWS Copilot CLI to Terraform-managed ECS. 2026-09-29.*
*History: [r1](council/plan-r1.md), [r2](council/plan-r2.md), [r3](council/plan-r3.md). Council reviews and votes are in
[`council/`](council/README.md). r3 folded in every round-2 condition (§11); r4 folds in the round-3 blockers and notes (§12).
Round 4 (2026-09-29): **unanimous APPROVE WITH NOTES** (gpt-6-astra, Claude Fable 5.1, Claude Opus 5.5). The notes are binding build requirements in §13.*

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
ecsodus check     --changeset changeset.json [--allow-metadata-key]
ecsodus verify-retain --app myapp [--env prod]                       -> read-only get-template on every stack
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
- `manual-cleanup`: Copilot-internal leftovers (custom-resource Lambdas, their roles and log
  groups, and `Custom::*` handles). They are **still retained by the patch** like everything else,
  so no stack delete ever removes them or triggers their handlers. The runbook lists them for
  manual deletion after the teardown and verify steps.
- `external-reference`: something that is referenced but not owned. Terraform refers to it by ARN
  or data source and never imports it. Examples: SSM SecureString parameters (see below) and
  imported VPCs.
- `blocked`: unsupported. ecsodus refuses to generate anything for it.

No fate deletes anything during teardown, because the retain patch has **no exceptions**.

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
- plain `String` SSM parameters that a stack owns
- the Copilot artifact bucket (it holds addon templates and `env_file` objects that task
  definitions reference through `environmentFiles`)
- Secrets Manager secrets: the `aws_secretsmanager_secret` resource only, never a
  `secret_version`, so Terraform never reads the value; rotation schedules are imported, and
  rotation Lambdas are imported or documented as manually owned
- KMS keys that any of the above use

**Secrets contract.**
- **SSM `SecureString` parameters are `external-reference`, never imported.** Terraform's
  `aws_ssm_parameter` refresh decrypts the value and writes it to state. Copilot creates
  `copilot secret init` parameters outside CloudFormation anyway, so no stack owns them, and task
  definitions keep referencing them by ARN in `secrets.valueFrom`.
- **ecsodus's own reads:** it never calls `GetParameter(WithDecryption)` or `GetSecretValue`.
- **Terraform's reads:** documented in RUNBOOK.md: state contains plaintext env values, so state
  must be encrypted.
- **Secret-bearing artifacts** are written 0600 and listed in `.gitignore`: `inventory.json`,
  generated HCL containing env values, `plan.json`, `state.txt` and checkpoints.

**References count through ARN strings, not only `Ref`/`GetAtt`.** The closure scan also follows
ARN and name strings in `environmentFiles`, `TemplateURL`, IAM policy `Resource`s, `valueFrom` and
listener certificates.

**Blockers propagate.** If a workload is `blocked` or not being migrated, everything it depends
on is `retain-under-existing-owner`, including its env and the app. The runbook is cut short
before any stack that still has a consumer (§2.5). This covers:

- other environments of the same app
- workloads owned by other teams
- externally owned (imported) VPCs, which are referenced by data source and never imported

The report also:
- flags customer-managed KMS keys, with their key policy and grants
- lists the `manual-cleanup` and `external-reference` sets

### 2.3 report
The report contains:
- **Fates, closure result and blockers.**
- **A per-stack table:** "deleting this stack would destroy …", before and after the patch.
- **A per-service double-work question:** "does this container run background work or migrations
  on boot?" This matters for rebuild mode only (v0.2).
- **Express fit** (see below).
- **The "keep CloudFormation" baseline:** the zero-risk option, with its caveat that the stacks'
  custom resources can't be recreated after 2027-07-29, and a stack update that changes their Lambda code fails after 2027-08-31.

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
  - Backend block: S3 remote state with encryption and `use_lockfile` (Terraform ≥ 1.10).
  - The imported task-definition revision uses a `removed { lifecycle { destroy = false } }`
    hand-off: once the deploy owner registers a new revision, Terraform forgets the old one
    instead of planning to recreate it. The runbook includes this step.
- **Retain patches.** For every stack, ecsodus emits the deployed template with
  `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` on **every resource, with no
  exceptions**. This includes every `Custom::*`, `EnvControllerAction`, and the `AddonsStack`
  nested-stack resource. Otherwise each template is byte-stable. The only other
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
  - `--include-nested-stacks`, with every descendant change set inspected
  - **an acceptance rule, which the runbook runs as `ecsodus check --changeset <json>`.** Every
    `ResourceChange` must satisfy all of:
    - `Action: Modify` and `Replacement: False`;
    - every `Details[].Target` is `Attribute` ∈ {`DeletionPolicy`, `UpdateReplacePolicy`}, **or**
      `Attribute: Properties, Name: TemplateURL, RequiresRecreation: Never` on an
      `AWS::CloudFormation::Stack` whose new child template's SHA-256 matches the one `generate`
      recorded.

    Reject any `Add`, `Remove`, `Import` or `Dynamic` change, any other `Properties`/`Tags` target,
    or any `Replacement` ≠ `False`. Apply the same rule to every nested change set. A completely
    empty change set counts as **failure**, not success: it means CloudFormation treated the patch
    as a no-op (coverage-roadmap #1543). In that case, use the documented fallback: add an
    `ecsodus:retain` `Metadata` key to each resource, which is the only other carve-out from
    byte-stability, and re-check.
- **Custom-resource neutralizer (fallback, emitted but unused by default).** This is a
  SUCCESS-on-everything responder, with the commands to swap each Copilot custom-resource
  Lambda's code for it before any `delete-stack` (a function update: blocked for `nodejs20.x` from 2027-08-31). The runbook uses it only if the e2e run shows
  that Retain does not suppress Delete invocations (§6).
- **RUNBOOK.md** (§2.5).

### 2.5 Runbook (adopt in place; v0.1 has no other mode)

1. **Freeze.** No `copilot deploy`, pause pipelines, record the stack `LastUpdatedTime`s.
2. **Protect.** Take snapshots and backups and do a test restore. Turn on RDS and DynamoDB
   deletion protection and S3 versioning where it is absent. This drifts from CloudFormation; the
   step-3 change set does not revert it, because the template property is unchanged. Then
   `ecsodus inventory` again.
3. **Retain patches.** For each stack in order (the app StackSet through `update-stack-set` with
   the patched template, so the instance resources (ECR, KMS, artifact bucket) are protected before
   they are detached; then the app stack, then env, then workloads with nested addons), create the change set with `--include-nested-stacks` and run
   `ecsodus check --changeset` on it (acceptance rule in §2.4). Execute it, wait for
   `UPDATE_COMPLETE`, then run `ecsodus verify-retain`, which calls `get-template` on every stack
   including nested ones and confirms the policies are on. This goes first so that nothing done
   later can delete data. **End with `ecsodus inventory` again and regenerate.** The patch changed
   every stack's `LastUpdatedTime`, so the step-2 inventory now fails the freshness check, and it
   should.
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
   (`ecsodus check --phase steady`). Sentinel data reads back. Delete the `manual-cleanup` list:
   leftover Lambdas, roles and log groups. Retained resources keep their `aws:cloudformation:*`
   tags; the AWS provider ignores `aws:` tags, so they cause no drift.
7. **Never** run `copilot app delete`, `copilot env delete`, `copilot env deploy` or
   `copilot app upgrade` against a retained or migrated stack. These commands re-render templates
   without the Retain policies and can modify imported resources.
   - **After a partial migration:** only `copilot svc deploy` of *unmigrated* workloads is
     allowed.
   - **After any Copilot operation:** re-run `ecsodus verify-retain`.

**Rollback.** The rollback path depends on how far the runbook got:
- **Before step 5:** `terraform state rm` the imported addresses. CloudFormation still owns
  everything, and the retain patches are harmless.
- **After step 5:** Terraform owns the resources, so there is nothing to roll back to. The
  runbook says so before step 5 starts.

### 2.6 check
- **`--phase import`:** only `import` and `no-op` actions are allowed. It fails on any update,
  create, delete or replace, and on any import-fated resource that is missing from the plan's
  imports.
- **`--phase steady`:** it fails on **any** action other than no-op. The runbook requires a
  zero-change plan, and the check enforces it.
- **`--state`:** it confirms that every import-fated address is in state.
- **`--changeset`:** the CloudFormation change-set acceptance rule (§2.4), applied recursively to
  nested change sets.
- **`verify-retain`** (its own subcommand): read-only `get-template` calls on every stack and nested
  stack. It fails if any resource lacks `DeletionPolicy: Retain` or `UpdateReplacePolicy: Retain`,
  or if a patched child's SHA-256 doesn't match.

## 3. Scope

**v0.1 (in):**
- Copilot Load Balanced Web Service and Backend Service.
- Env stack, with a VPC that Copilot created or one that was imported (referenced, not imported).
- Workload and env addons: Aurora/RDS, DynamoDB, S3.
- Secrets Manager secrets (resource only) and plain SSM parameters; SecureStrings as external references.
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
- **Support matrix:** Terraform floor 1.10 (`use_lockfile`); exact tested versions of Terraform, the AWS provider and
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
- **Retain-patch invariants:** Retain is on every resource. Nothing else changed except
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
- **Does a policy-only change set produce `Modify` entries with `DeletionPolicy`/`UpdateReplacePolicy` targets and apply them,** or does CloudFormation treat it as a no-op (then the Metadata fallback, §2.4)?
- **Does ACM validation CNAME reuse survive** the old certificate's retention?

It also covers an interrupted handoff and rollback before step 5, a partial migration (one workload migrated, one left on Copilot), and a custom-domain variant before any claim that certificate and DNS survival is validated. Until it passes, the RUNBOOK
teardown section carries an **UNVERIFIED** banner, and `generate` requires
`--i-understand-teardown-is-unverified` to emit step 5 (steps 6–7 are always emitted). The e2e must run before 2027-07-29
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

## 12. Round-3 blockers and notes → where addressed

| Item | Where |
|---|---|
| Astra B1 / Fable B1 / Opus N1: change-set rule (policy attributes, `TemplateURL`, nested, `Replacement`, empty change set = failure, Metadata fallback) | §2.4 acceptance rule, §2.6 `--changeset`, §6 |
| Astra B2 / Fable B2: no fate may re-enable destructive handlers | §2.2 `manual-cleanup` (still retained), retain patch has no exceptions (§2.4) |
| Astra B3: SecureString import reads values | §2.2 secrets contract: SecureStrings are `external-reference`; secrets resource-only |
| Astra N / Opus N2: freshness vs step 3 | §2.5 step 3 ends with re-inventory |
| Astra N: steady gate machine-enforced | §2.6 `--phase steady` fails on any action |
| Astra N: sensitive artifacts beyond inventory | §2.2 secrets contract |
| Opus N3: artifact bucket referenced by `environmentFiles`; ARN-string closure | §2.2 closure list and ARN rule |
| Opus N4: coexistence after partial migration | §2.5 step 7 |
| Opus N5: gate only step 5 | §6 |
| Opus N6: rotation resources fated | §2.2 closure list |
| Opus N7: Terraform ≥ 1.10 for `use_lockfile` | §2.4, §5 |
| Opus N8: imported task-definition revision | §2.4 `removed` hand-off |
| Astra N: real partial-migration and domain-enabled e2e | §6 (e2e scope, when approved) |
| Fable N: StackSet instances protected before detach | §2.5 step 3 (`update-stack-set`) |
| Fable N: neutralizer and Lambda-update date 2027-08-31 | §2.3, §2.4 |
| Fable N: out-of-band protection drift not reverted | §2.5 step 2 |

## 13. Round-4 notes: build requirements (binding for v0.1)

All three reviewers approved r4. Their notes are fail-closed refinements, and the build
implements them:

1. **StackSet path (all three).** `update-stack-set` has no change set. Instead:
   - Diff the patched template offline against `describe-stack-set`'s template; only the policy
     attributes may differ.
   - Pass `--administration-role-arn` and `--execution-role-name` copied from
     `describe-stack-set`, `UsePreviousValue=true` for every parameter, the existing
     capabilities, and `--operation-preferences FailureToleranceCount=0`.
   - Wait until the operation and every instance report `SUCCEEDED`, then run `verify-retain` on
     each instance stack.
   - Step 5.4 runs `verify-retain` on the detached stack and patches only if that fails.
2. **Metadata fallback (all three).** In `--allow-metadata-key` mode, `check --changeset` also
   accepts `Attribute: Metadata` targets whose only change is the `ecsodus:retain` key.
3. **Repeatability (Astra, Opus).** An empty change set passes only if `verify-retain` proves that
   the stack is already fully retained; the runbook skips those stacks. `SyncWithActual` and
   `Dynamic` evaluations are rejected. The one exception is `Dynamic`/`ResourceAttribute`
   entries caused by a patched nested stack whose own change set is policy-only. That exception
   is an e2e question (§6).
4. **Closure targets (Astra, Opus).** `external-reference` is an allowed closure target. A
   resource that a discovered stack owns can never be labelled external.
5. **Post-teardown checks (Astra).** The steady check uses the handoff record (the
   `inventory.json` import set) and live identity reads. It does not require deleted stacks.
6. **Terraform JSON (Astra).** Detect imports through `change.importing`, not
   `change.actions`.
7. **Task-definition hand-off (all three).** `aws_ecs_service.task_definition` becomes a literal
   ARN. The `removed` block is added in the same change that deletes the resource and import
   blocks.
8. **Aurora `SecretTargetAttachment` (Opus, Fable)** is `manual-cleanup`, retained.
9. **Regeneration stability (Astra).** After step 3, re-generating must produce the same
   Terraform, apart from the recorded hashes.
10. **Wording (Fable, Opus).** §6 says "every resource". The command list in §2 includes
    `check --changeset` and `verify-retain`.
