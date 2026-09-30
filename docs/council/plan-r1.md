# ecsodus: plan (draft r1, for council review)

*Exit kit for retired AWS container tools. 2026-09-29.*

## 1. Problem and timing

AWS is retiring three container front-ends at once:

| Tool | Status (as of 2026-09-29) | Hard deadline? | AWS-recommended path |
|---|---|---|---|
| Copilot CLI | End of support 2026-06-12; repo archived 2026-06-22 (3.7k stars, 446 forks) | No: deployed CloudFormation stacks keep running, but no fixes, and the CLI will drift from AWS APIs | ECS Express Mode or CDK L3 constructs |
| App Runner | Closed to new customers 2026-04-30; existing services keep running, no new features | No | ECS Express Mode (blue/green via Route 53 weighted records) |
| Proton | End of support **2026-10-07** (8 days away); console and Proton resources become inaccessible, provisioned infrastructure stays | Yes, but the window for tooling *before* it is closed | CloudFormation Git Sync, CodePipeline, GitHub Actions, Harmonix |

What exists: generic converters (extract-cf2tf: CloudFormation stack to Terraform `import` blocks),
Terraform target modules (terraform-aws-modules/ecs incl. an `express-service` submodule), a
deploy CLI (ecspresso, 1.1k stars, Express Mode support), prose migration guides (AWS docs, Encore,
fivexl, dev.to), commercial platforms courting the users (Encore, fortem.dev, Bunnyshell), and
AWS's own AI-assisted path (Kiro CLI + MCP servers).

What does not exist: a tool that reads *your* Copilot app or App Runner service and emits a
working, importable Terraform project plus a cutover runbook, handling the edge cases that make
generic conversion fail. That is the gap.

## 2. Product

**ecsodus** (ECS + exodus; free on PyPI, npm, GitHub). A read-only CLI that:

1. **inventories** a Copilot workspace (`copilot/` manifests + deployed stacks) or an App Runner
   service (read-only AWS API calls; never mutates),
2. **reports** a migration readiness assessment: every resource, its fate (import / recreate /
   replace / drop), and every gap that needs a human decision,
3. **generates** a Terraform project: `import` blocks for stateful and shared resources, the ECS
   service via terraform-aws-modules/ecs (`express-service` when the app fits Express Mode, plain
   `service` otherwise), CI workflow, and replacements for Copilot custom resources and App Runner
   built-ins,
4. **writes a cutover runbook**: parallel run, weighted DNS shift, verification checks, rollback,
   and the safe teardown of old stacks (`--retain-resources` for anything imported).

It never applies Terraform, never deletes, never shifts traffic. The user runs `terraform plan`.

Name and discoverability: the name deliberately avoids "Copilot" (search results are dominated
by GitHub Copilot). Discovery comes from docs pages titled with the exact searches:
"migrate AWS Copilot CLI to Terraform", "App Runner to ECS Express Mode", "Copilot custom
resources Terraform", "Proton stacks after end of support".

## 3. Scope

### v1 (in)
- **Copilot**: Load Balanced Web Service and Backend Service (the bulk of real usage), the
  environment stack (VPC, subnets, ALB, cluster, service discovery), addons (`addons/*.yml`
  CloudFormation: RDS/Aurora, DynamoDB, S3), secrets (SSM/Secrets Manager refs), custom domains
  and aliases.
- **App Runner**: image-based and source-based services, VPC connector, custom domains,
  auto-scaling configuration, observability configuration, auto-deploy from ECR.
- Output: Terraform (>= 1.5 for `import` blocks), GitHub Actions workflow, markdown runbook and
  report.

### Later
- Copilot Worker Service (SNS/SQS), Scheduled Job, Request-Driven Web Service (which *is* App
  Runner: route to the App Runner path), Static Site, pipelines (`copilot pipeline`).
- Proton: adoption of orphaned Proton-provisioned CloudFormation stacks after 2026-10-07
  (generic: CFN stack to Terraform import, plus a report of what Proton was managing).
- Other targets (Cloud Run, CDK L3) only if demand shows up.

### Non-goals
- A deploy CLI (ecspresso exists). A hosted platform. Applying changes. Terraform module authoring
  beyond thin wrappers (use terraform-aws-modules).

## 4. The edge cases (the differentiation)

### Copilot
- **Custom resources.** Copilot templates use Lambda-backed custom resources (e.g. env
  controller, DNS delegation / certificate validation, ALB rule priority allocation, alias
  handling, bucket cleanup, desired-count "dynamic" lookups). None map to a Terraform resource.
  For each one: a documented replacement (native TF resource, data source, or deletion) and an
  explicit report line. Build the table from the archived repo's `cf-custom-resources/` source
  (Apache-2.0), not guesswork.
- **Manifest overrides and environment inheritance** (`environments:` blocks, `taskdef_overrides`,
  CDK/YAML patch overrides). Resolve from the *deployed* stack, not only the manifest: the
  deployed template is the truth.
- **Service Connect / service discovery namespaces** shared across services in an env.
- **Stack ownership order**: env stack exports consumed by service stacks; teardown must be
  service-first, env last, imported resources retained.

### App Runner
- **Build-from-source loss**: generate a Dockerfile (from the runtime and build/start commands
  in the App Runner config) and a CI workflow that builds and pushes to ECR.
- **Tracing**: App Runner's built-in X-Ray observability becomes an ADOT collector sidecar (or
  the report says "not configured, nothing to replace"). Must be in place before cutover.
- **Auto-scaling**: concurrency-based scaling maps to target tracking on
  `ALBRequestCountPerTarget` (approximate: say so in the report).
- **Networking**: public App Runner endpoint + VPC connector becomes tasks in private subnets
  behind an ALB; egress now needs NAT or VPC endpoints (a cost line in the report).
- **Custom domains**: App Runner-managed certificate becomes ACM + ALB listener.
- **Auto-deploy on image push**: replaced by the CI workflow.

### Cost transparency
Express Mode / ALB / NAT change the bill (App Runner idle pricing vs always-on Fargate + ALB).
The report estimates the monthly delta from the inventory.

## 5. Architecture

Python 3.11+, distributed via PyPI (`pipx install ecsodus` / `uvx ecsodus`). Reasons: maintainer's
stack, no compiled dependency needed (codegen is text), fast iteration.

```
ecsodus inventory  --copilot-dir ./copilot --env prod      -> inventory.json
ecsodus inventory  --apprunner-arn arn:...                 -> inventory.json
ecsodus report     inventory.json                          -> REPORT.md (fates + gaps + cost)
ecsodus generate   inventory.json --out ./infra            -> Terraform + workflow + RUNBOOK.md
ecsodus verify     --old URL --new URL                     -> smoke parity checks (read-only HTTP)
```

- `sources/`: Copilot (manifest parser + `cloudformation:GetTemplate`/`DescribeStackResources`),
  App Runner (`DescribeService`, `ListOperations`, auto-scaling and observability configs).
- `model/`: a target-neutral intermediate model (service, network, lb, domain, secrets, stateful
  resources, observability, scaling, CI) with a provenance pointer per field (which stack
  resource or config it came from).
- `mappers/`: per-edge-case rules producing fates and gaps.
- `emit/terraform/`: Jinja templates over the model; pins module versions.
- Every generated file carries a header naming the source and ecsodus version.

## 6. Validation

- **Offline golden tests**: fixtures from real Copilot-generated templates (the archived repo's
  integration test templates) and recorded App Runner API responses; snapshot the generated
  Terraform; `terraform validate` and `tflint` in CI.
- **Plan tests**: `terraform plan` against LocalStack where it covers the resources.
- **One real end-to-end migration per source** (Copilot sample app, App Runner sample) in an AWS
  account: deploy the old stack, run ecsodus, `terraform plan` shows imports with zero replacements
  of stateful resources, cutover, teardown. This costs money (ALB, NAT, Fargate hours): approve
  per run, tear down the same day.

## 7. Milestones

| # | Deliverable | Est. |
|---|---|---|
| M0 | Repo, CI, fixtures corpus, custom-resource mapping table (research doc) | 1 wk |
| M1 | Copilot LB Web Service + env + addons: inventory, report, generate | 2 wk |
| M2 | App Runner image + source: inventory, report, generate (Dockerfile, ADOT, CI) | 1.5 wk |
| M3 | Runbook generator + `verify`; first real e2e for both | 1 wk |
| M4 | v0.1 release, docs site pages targeting search phrases, launch posts | 0.5 wk |
| M5 | Backend/Worker services, Proton stack adoption | later |

## 8. Success measures (first 90 days)
- 3 real migrations reported by users (issues/discussions), 150 GitHub stars, one inbound link
  from a migration guide.
- Zero reports of a stateful resource destroyed by following the generated plan and runbook.

## 9. Risks
- **Small audience** (Copilot adoption was low; App Runner has no deadline). Mitigation: keep v1
  small; the App Runner half is the larger pool.
- **AWS or Encore ships the same thing** (AWS already has a Kiro+MCP migration path). Mitigation:
  deterministic, reviewable output and edge-case depth; AI assistants can call ecsodus.
- **Express Mode Terraform support is young**; module or provider changes. Pin versions; fall back
  to the plain `service` submodule.
- **Wrong import = outage/data loss.** Read-only tool, `import` blocks only for identified
  resources, runbook requires `plan` review showing no destroys on stateful resources.

## 10. Open questions for the council
1. Is v1 scope right (Copilot LBWS + App Runner), or should it be App Runner-only first?
2. Python vs Go.
3. Generate our own Terraform vs wrap terraform-aws-modules/ecs `express-service` vs emit
   CloudFormation/CDK too.
4. Is Proton worth anything given the 2026-10-07 deadline?
5. Is the name right?
