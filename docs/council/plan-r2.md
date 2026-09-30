# ecsodus: plan (r2, final after council)

*Safe exit from AWS Copilot CLI (and later App Runner) to Terraform-managed ECS. 2026-09-29.*
*The r1 draft and the three council reviews are in [`council/`](council/README.md).*

## 1. Problem and timing

| Tool | Status (2026-09-29) | Deadline | AWS path |
|---|---|---|---|
| Copilot CLI | End of support 2026-06-12, repo archived 2026-06-22 (3.7k stars, 446 forks) | None. Stacks keep running, the CLI goes stale | ECS Express Mode, CDK L3, or keep the CloudFormation |
| App Runner | Closed to new customers 2026-04-30. Existing services run, no new features | None | ECS Express Mode + Route 53 weighted DNS |
| Proton | End of support **2026-10-07** | Yes, 8 days away | CloudFormation Git Sync, CodePipeline, GitHub Actions |

**The gap.** Leaving Copilot for Terraform means importing what Copilot built and then deleting
Copilot's CloudFormation stacks without deleting the infrastructure. Doing that naively destroys
data and takes production down:

- **Custom resources.** Copilot's Lambda custom resources delete ACM certificates, DNS records
  and NS delegations, and empty buckets, when their stack is deleted.
- **Env controller.** Deleting the last service stack makes the env controller delete the shared
  ALB, the NAT gateways and the EFS.
- **Addons.** Addon databases sit in nested stacks with no `DeletionPolicy`.
- **App stack.** The app-level StackSet owns the ECR repositories and the hosted zone.

Generic tools cover none of this: extract-cf2tf, `-generate-config-out` and AWS's prose guides.
**ecsodus is the tool that knows where Copilot's landmines are.** That is the product.

## 2. Product

`ecsodus` is a read-only Python CLI. It never applies Terraform, never modifies or deletes AWS
resources, never shifts traffic and never reads secret values.

```
ecsodus inventory --app myapp --env prod [--copilot-dir ./copilot]   -> inventory.json
ecsodus report    inventory.json                                     -> REPORT.md
ecsodus generate  inventory.json --out ./infra                       -> Terraform + retain patches + RUNBOOK.md
ecsodus check     plan.json --inventory inventory.json               -> exit 1 if any import-fated address would be destroyed/replaced
```

- **inventory.** Walks the app stack and StackSet instances, the env stack, the workload stacks
  and their nested addon stacks, recursively and with pagination. Reads the live service state
  and SSM metadata (`/copilot/applications/...`). Finds out-of-band resources created by custom
  resources (ACM certificates, Route 53 records) through the ACM and Route 53 APIs. Records
  provenance, account, region and a timestamp for every field.
- **report.** Assigns every resource a fate: `import`, `recreate`, `retain-under-existing-owner`,
  `drop-after-cutover` or `blocked`. `blocked` means unsupported, and ecsodus refuses to generate
  anything for it, so nothing is ever dropped silently. The report also lists:
  - per stack, what deleting it would destroy as a side effect,
  - which services could run Express Mode, and why the others can't,
  - a double-work question for each service,
  - "keep CloudFormation" as the zero-risk baseline.
- **generate.**
  - Flat root-module `aws_*` resources with `import` blocks for everything fated `import`. Their
    arguments come from the deployed template and the live reads, not from module internals.
  - `prevent_destroy` and `deletion_protection` on stateful resources.
  - `ignore_changes` on `desired_count`, and on the image when CI deploys.
  - **Retain-patch templates** for every stack, nested stacks included: the deployed template with
    `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` on every imported resource and every
    `Custom::*` resource, including `EnvControllerAction`.
  - `RUNBOOK.md`.
- **check.** Parses `terraform show -json` and fails if any imported address would be destroyed
  or replaced. The runbook requires `check` to pass before every apply.

### Two modes
- **Adopt in place (default for Copilot).** Import the existing cluster, service, task definition
  family, ALB, listeners, rules, target groups, security groups, VPC, subnets, Cloud Map, log
  groups, addons, ECR repos and hosted zone. Traffic does not move.
- **Rebuild in parallel (opt-in).** For changing shape, for example to Express Mode, and later for
  App Runner. Adds new compute, a new ALB where needed, an ACM certificate issued ahead of time,
  atomic Route 53 change batches, and weighted cutover with the source kept alive for TTL + 24h.

### Runbook order (adopt in place)
1. Freeze all Copilot use: no `copilot deploy`, pipelines paused. Take backups and snapshots, and
   verify that they restore.
2. `terraform plan` → `ecsodus check` → import-only `apply`, with no attribute changes. Then a
   second plan must show zero changes.
3. Apply the retain patches with `update-stack` and the same parameters, in this order: app, env,
   then each workload with its nested addons. Verify with `get-template` that the policies are
   present.
4. Delete the workload stacks, then any orphaned addon stacks, then the env stack. For the app
   stack, delete StackSet instances with `--retain-stacks`, then the retain-patched stack.
5. After the teardown, confirm that every imported resource still exists. Plan again: zero
   changes. List the leftover Lambdas, roles and log groups for manual cleanup. Note that retained
   resources keep their `aws:cloudformation:*` tags.
6. Never run `copilot app delete` or `copilot env delete` after migrating.

## 3. Scope

**v0.1 (in):**
- Copilot Load Balanced Web Service and Backend Service, with their env stack (created or
  imported VPC), workload and env addons (Aurora, RDS, DynamoDB, S3), secrets by reference,
  aliases and custom domains, the app stack and StackSet, and adopt-in-place mode.
- Detected but `blocked`, so the report names them: Worker Service, Scheduled Job, Request-Driven
  Web Service, Static Site, NLB, CloudFront CDN, sidecars, Service Connect consumers, managed EFS
  (supported if time allows), `copilot pipeline`, and multi-account environments.

**Later:**
- **v0.2:** App Runner image-based services in rebuild-in-parallel mode. The inventory covers
  custom domains, VPC connectors, VPC ingress connections (private services), WAF, health check
  (TCP by default, so the target needs an HTTP path), port, instance size, KMS key and roles.
  Scaling is operator-selected, because concurrency cannot be converted to a request-count target.
- **v0.3:** Worker Service and Scheduled Job, rebuild mode into Express, App Runner source-based
  (requires the repo and its `apprunner.yaml`), ADOT tracing.

**Non-goals:**
- A deploy CLI (ecspresso exists).
- CloudFormation or CDK output.
- Proton tooling. Instead, one docs page that points to generic CloudFormation adoption.
- Cost estimation. The report gives a static table of line items instead.
- A hosted service, and npm.

## 4. Knowledge base (M0, its own deliverable)

`docs/copilot-custom-resources.md` is a table of Copilot's 14 custom resources, built from the
archived source (Apache-2.0):

- **Columns:** the resource; what it creates outside CloudFormation; what its Delete handler
  does; the Terraform equivalent; the fate.
- **Resources:** `alb-rule-priority-generator`, `backlog-per-task-calculator`, `bucket-cleaner`,
  `cert-replicator`, `custom-domain`, `custom-domain-app-runner`, `desired-count-delegation`,
  `dns-cert-validator`, `dns-delegation`, `env-controller`, `trigger-state-machine`,
  `unique-json-values`, `wkld-cert-validator`, `wkld-custom-domain`.

A second table covers the conditional env resources and addon `DeletionPolicy` defaults.

These tables double as the SEO docs pages.

## 5. Architecture

- **Stack:** Python 3.11+, boto3, a CloudFormation-aware YAML loader, Jinja2. Distributed with
  `uvx ecsodus` or `pipx`.
- **Pins:** Terraform ≥ 1.5.7 and AWS provider ≥ 6.41 (tested together);
  terraform-aws-modules/ecs v7.x, used only for newly created compute.
- **Modules:**
  - `sources/copilot`: stack graph walker, manifest-vs-template override detection, live reads.
  - `model/`: target-neutral, with provenance on every field.
  - `mappers/`: fate and gap rules, one per knowledge-base row.
  - `emit/terraform`: resource blocks plus import blocks.
  - `emit/retain_patch`: rewrites each template, keeping it byte-stable otherwise.
  - `emit/runbook`.
  - `check/`: the plan guard.
- **Rules:** never fetch secret values, and redact the environment from `inventory.json`.

## 6. Validation

- **Golden tests:** fixtures from real Copilot-generated templates (the archived repo's
  integration templates) and recorded API responses; snapshot the generated Terraform and retain
  patches; run `terraform validate` and `tflint` in CI.
- **`check` tests:** synthetic `terraform show -json` plans with destroy and replace actions.
- **One real end-to-end run, early (M1), not at the end:**
  - Deploy a Copilot sample app (LBWS + Aurora addon + custom domain) with the archived CLI, and
    write sentinel data to it.
  - Run ecsodus, apply, retain-patch and tear down.
  - Assert that the sentinel data, the ALB, the certificate, the DNS and the ECR images all
    survive.
  - Settle the three unverified questions listed in [council/README.md](council/README.md).
  - Test an interrupted handoff and a rollback.
  - Needs a Route 53 domain and costs a few dollars (ALB, NAT, Aurora): propose the run, get
    approval, and tear down the same day.

## 7. Milestones (≈6 weeks of evenings)

| # | Deliverable | Est. |
|---|---|---|
| M0 | Repo, CI, fixture corpus, custom-resource knowledge base | 1 wk |
| M1 | `inventory` + `report` for Copilot (report usable on its own); first real e2e deploy of the sample | 1.5 wk |
| M2 | `generate` (Terraform + retain patches + runbook) + `check`; e2e teardown with sentinel data | 2 wk |
| M3 | v0.1 release: docs pages titled for the searches people make, PyPI, launch posts (r/aws, dev.to, HN "Show") | 0.5 wk |
| M4 | App Runner image-based (v0.2) | 1 wk, if time allows |

Ship the `report` publicly after M1 even if `generate` slips. A readiness report that lists the
landmines is useful on its own.

## 8. Success measures (first 90 days)
- 3 completed migrations reported by users. 10 reports run and shared as feedback issues.
- Zero reports of lost data or a production outage caused by following the output.
- Cited in at least one migration guide or thread. Stars are secondary.

## 9. Risks
- **Small audience.** Keep v0.1 narrow and ship the report first. Recruit 2–3 design partners from
  the copilot-cli issues and discussions, and from Reddit threads, before M2.
- **Wrong import or teardown causes an outage.** Mitigations: read-only tool, retain patches,
  `prevent_destroy`, the `check` gate, backups in runbook step 1, `blocked` over guessing, and
  the sentinel e2e test.
- **Provider or module drift.** Pin versions and publish a support matrix for each release.
- **Competitors:** AWS guides, Encore, fortem.dev, generic MCP tooling. They cover rebuilds. The
  wedge is safe adoption of existing Copilot infrastructure into maintainable Terraform, with no
  rewrite of the application code.

## 10. Decisions (from council)
1. Copilot first, adopt in place. App Runner image-only goes to v0.2.
2. Python.
3. Terraform only. Flat root resources for imports, terraform-aws-modules for new compute, and
   Express only under the fit test.
4. No Proton tooling. One docs page.
5. Name: **ecsodus**. Tagline: "Safely migrate AWS Copilot apps to Terraform." Put the exact
   search phrases in the repo description, the PyPI summary and the docs titles.
