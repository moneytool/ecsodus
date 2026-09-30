# Council review: Claude Opus 5.5

(Verbatim final report of the Opus 5.5 reviewer, read-only, web access; 2026-09-29.)

## Verdict

**Revise before building.** The idea holds up, but the plan's core safety mechanism is wrong, and its default target doesn't fit most of the v1 scope. Three problems:

1. The teardown step `--retain-resources` only works on stacks already in `DELETE_FAILED`.
2. Copilot's own custom resources run destructive Delete handlers during teardown. Deleting a service stack makes the env-controller update the env stack, which removes the shared ALB, the NAT gateways and the managed EFS once no workload references them.
3. The Terraform Express Mode resource has no task-definition, sidecar, volume or custom-domain arguments, so "Express where it fits" fits very few Copilot LBWS apps and no service with a custom domain.

**Single most important change:** redesign cutover and teardown around a generated, reviewable "retain patch" for every Copilot stack. It sets `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` on every imported resource and on every `Custom::*` resource, and it is applied with `update-stack` before any delete. Make "adopt in place" (import the existing ECS/ALB/VPC, no parallel run) the default Copilot mode. Keep "rebuild in parallel behind weighted DNS" as the App Runner mode.

## Findings

1. **[P0] `--retain-resources` does not work the way the runbook assumes** — §2.4, §9. `DeleteStack` `RetainResources` applies only "for stacks in the `DELETE_FAILED` state" (https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DeleteStack.html). A normal delete of a healthy stack deletes everything that has no `DeletionPolicy: Retain`. Inducing a failure first to unlock retain is fragile and unsafe. **Fix:** for each stack, including the nested addons stack, emit a patched template that adds Retain policies to imported resources and custom resources. The runbook applies it (`update-stack` with the patched template and the same parameters), checks it (`get-template` diff and `describe-stack-resources`), and only then runs `delete-stack`. ecsodus stays read-only because it only emits the patched template.

2. **[P0] Service-first teardown makes the env-controller delete shared env infrastructure** — §4 "Stack ownership order". Every workload stack contains `Custom::EnvControllerFunction`. On Delete it calls `controlEnv(envStack, workload, [])`, which removes the workload from the env stack's `ALBWorkloads`, `EFSWorkloads` and `NATWorkloads` parameters (https://github.com/aws/copilot-cli/blob/mainline/cf-custom-resources/lib/env-controller.js). The env template gates the ALB, the managed EFS file system and the NAT gateways on those parameters being non-empty (https://github.com/aws/copilot-cli/blob/mainline/internal/pkg/template/templates/environment/cf.yml, conditions `CreateALB`, `CreateEFS`, `CreateNATGateways`). Deleting the last service stack therefore makes CloudFormation delete the env ALB, the EFS (data loss) and the NAT gateways. That causes an egress outage for new tasks that were placed in the imported private subnets. This happens before the plan ever touches the env stack. **Fix:** the retain patch must put `DeletionPolicy: Retain` on `EnvControllerAction` in every service stack (CloudFormation then sends no Delete to the custom resource) and on the env-stack ALB, EFS, NAT and EIP resources. The report should list "resources that will be deleted as a side effect of deleting stack X".

3. **[P0] Other custom-resource Delete handlers destroy data or DNS/TLS** — §4 Custom resources. These are from the source (https://github.com/aws/copilot-cli/tree/mainline/cf-custom-resources/lib):
   - `bucket-cleaner.js` empties the bucket on Delete. It is used for the env ELB access-logs bucket (`environment/partials/elb-access-logs.yml`), so retaining the bucket is not enough; the objects are still wiped.
   - `wkld-cert-validator.js` and `dns-cert-validator.js` on Delete remove validation records and call `DeleteCertificate`. If the new ALB reuses that cert, deletion fails and the stack goes to `DELETE_FAILED`. The validation CNAME for a domain is shared by certs in the same account, so removing it can break renewal of the new cert. (UNSURE on the exact ACM CNAME reuse behaviour; verify.)
   - `wkld-custom-domain.js` and `custom-domain.js` delete the alias A record, but only when its value still matches the old ALB, so this is safe only if the record was already repointed.
   - `dns-delegation.js` removes the NS delegation for `env.app.domain`.

   **Fix:** a Retain policy on every `Custom::*` in the patch, plus an explicit "leftover Lambdas/log groups to delete manually" list in the runbook.

4. **[P0] Stateful addons live in a nested stack under the service stack, not beside it** — §3 v1, §4. Workload addons are `AddonsStack` (`AWS::CloudFormation::Stack`) inside the service stack (https://github.com/aws/copilot-cli/blob/mainline/internal/pkg/template/templates/workloads/partials/cf/addons.yml). The generated Aurora and DynamoDB addon templates have no `DeletionPolicy`; only the S3 addon has `Retain` (grep of `internal/pkg/template/templates/addons`). So deleting the service stack deletes the DynamoDB table and the Aurora secret. Aurora falls back to the `Snapshot` default for `DBCluster`, which means the cluster is gone and a restore is required (https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html). **Fix:** walk nested stacks in inventory, and patch nested templates through the parent (the nested stack's `TemplateURL` must change). Treat environment-level addons (`copilot/environments/addons/`) separately, since they belong to the env stack.

5. **[P0] The Copilot app stack and StackSet are missing from the model** — §3, §4. The app-level StackSet (`templates/app/cf.yml`) owns the per-workload **ECR repositories**, the KMS key and the pipeline bucket. The app stack (`templates/app/app.yml`) owns the `app.domain` **hosted zone** and its NS delegation. None of these have a Retain policy. A later `copilot app delete` or StackSet cleanup deletes the image repos the new ECS tasks pull from, and the hosted zone that aliases and ACM validation depend on. **Fix:** inventory the app stack and StackSet instances, and import or retain the ECR repos and hosted zone. The runbook should say explicitly: never run `copilot app delete` or `copilot env delete` after migration.

6. **[P1] Express Mode in Terraform cannot express most of v1** — §2.3, §3, §10 Q3. `aws_ecs_express_gateway_service` supports only `primary_container`, cpu (max 4096), memory (max 8192), `network_configuration`, `scaling_target`, roles and `health_check_path`. It has no `task_definition_arn`, no sidecars, no volumes/EFS, no port or protocol options, no custom domain, and it does not export the ALB or target-group ARNs, only `ingress_paths[].endpoint` (https://github.com/hashicorp/terraform-provider-aws/blob/main/website/docs/r/ecs_express_gateway_service.html.markdown). The module wraps exactly that resource (https://github.com/terraform-aws-modules/terraform-aws-ecs/blob/master/modules/express-service/main.tf). The ECS API does accept `taskDefinitionArn` (https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html), but Terraform does not expose it. Custom domains need an edit of the ECS-managed listener rule plus a listener cert on a shared, ECS-managed ALB (https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-advanced-customization.html). Express also has no NLB, canary-only deployments, and no LB config updates. **Fix:**
   - Make plain `service` plus your own ALB the default.
   - Choose Express only when all of these hold: one container, no volumes, ≤4 vCPU/8 GB, HTTP/ALB, and either no custom domain or a documented manual domain step.
   - Your own ADOT-sidecar plan (§4) automatically rules out Express.

7. **[P1] The Copilot "rebuild + parallel run" design is the riskier choice** — §2.3–2.4. A Copilot LBWS already is a plain ECS service, ALB, target group and VPC. Recreating the service behind a new ALB adds a DNS cutover, double running, a second ALB, security-group rewiring and custom-domain cert churn, with no benefit. **Fix:** default Copilot mode is "adopt in place": import the cluster, service, task definition family, ALB, listeners, rules, target groups, SGs, VPC and subnets, service-discovery namespace and services, log groups and addons into Terraform. Then retain-patch and delete the stacks, with zero traffic movement. Keep parallel/weighted as an opt-in for users who also want to change shape (for example to Express).

8. **[P1] Weighted DNS on Copilot and App Runner domains is not a simple edit** — §2.4, §4 App Runner.
   - Copilot aliases are simple-routing alias A records owned by a custom resource. Route 53 does not allow simple and weighted records with the same name and type, so the switch must be one atomic `ChangeResourceRecordSets` batch (DELETE simple + CREATE two weighted).
   - App Runner custom domains are **CNAMEs** to `*.awsapprunner.com`. Weighted records must share a type, so the ECS side must be a weighted CNAME to the ALB DNS name, not an alias A record. That can't work at a zone apex. AWS's own guide glosses over this (https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html).
   - A new ACM cert must be issued and validated **before** the shift, because App Runner's cert is service-managed.

   **Fix:** the runbook emits the exact change batches and a pre-flight "record type/apex" check.

9. **[P1] Parallel run double-executes work even in v1** — §2.4, §4. LBWS and Backend Services often run in-process schedulers, queue consumers, or DB migrations on boot. Weighted DNS also leaves the old side serving traffic after weight 0 (TTL plus client caching). **Fix:** the report asks one question per service ("does this container do background work or run migrations on start?"). The runbook scales the new side's workers to zero or feature-flags them until cutover, and keeps the old side alive for at least TTL plus 24h before teardown.

10. **[P1] Security-group and secrets wiring breaks the parallel service** — §4. The Aurora addon's DB SG only admits the addon's client SG, which Copilot attaches to tasks (`addons/aurora/serverlessv2.yml`, `SourceSecurityGroupId`). New tasks without that SG can't reach the DB. Copilot's execution role grants SSM/Secrets Manager access by `copilot-application`/`copilot-environment` tag conditions, and App Runner's instance role holds the secret and KMS grants. **Fix:** the mapper must carry SG membership, execution-role secret ARNs and KMS key grants into the new task/execution roles. The report should flag any CMK.

11. **[P1] Import into terraform-aws-modules is brittle** — §2.3, §10 Q3. Importing live resources to module-internal addresses (`module.x.aws_...this[0]`) depends on module internals and defaults, so the first plan tends to show in-place changes or replacements on tags, names and defaults. `-generate-config-out` is still labelled experimental and may produce invalid config (https://developer.hashicorp.com/terraform/language/import/generating-configuration). As far as I know it only generates config for root-module resources (UNSURE, verify). **Fix:** emit imported resources as plain root-module `aws_*` resources built from ecsodus's model, not generated config. Use modules only for newly created resources. CI gate: `terraform plan` on the golden fixtures must show 0 `destroy`/`replace` on imported addresses; add `lifecycle { prevent_destroy = true }` on all stateful imports.

12. **[P1] Dual ownership during the transition** — §4, §2.4. Between `terraform apply` (imports) and stack deletion, CloudFormation and Terraform both manage the same resources. Any `copilot deploy`, pipeline run or env-controller-triggered env update reverts Terraform changes, and the reverse also happens. **Fix:** runbook step 0 freezes Copilot pipelines and CLI use. The first apply should be import-only, with no attribute changes, until the stacks are gone.

13. **[P2] The custom-resource inventory is incomplete** — §4. The actual `cf-custom-resources/lib` list is: `alb-rule-priority-generator`, `backlog-per-task-calculator`, `bucket-cleaner`, `cert-replicator`, `custom-domain`, `custom-domain-app-runner`, `desired-count-delegation`, `dns-cert-validator`, `dns-delegation`, `env-controller`, `trigger-state-machine`, `unique-json-values`, `wkld-cert-validator`, `wkld-custom-domain`. The plan omits `cert-replicator` and the env CloudFront CDN (`environment/partials/cdn-resources.yml`), NLB variants and `unique-json-values`. The table in M0 is good; seed it with this list.

14. **[P2] EFS and other env features are not in scope** — §3. The env stack holds the managed EFS (`CreateEFS`), public and private hosted zones, the Cloud Map private namespace, optional CloudFront, imported-VPC mode (the VPC may not be in the stack at all) and internal ALBs. **Fix:** v1 must at least detect these, and block with a report line if it can't handle them.

15. **[P2] App Runner inventory is under-specified** — §4, §5.
    - `ListOperations` is useless here. The inventory needs `DescribeCustomDomains`, `DescribeVpcConnector`, `DescribeVpcIngressConnection` (private App Runner services exist, so the "public endpoint" assumption is wrong), auto-scaling and observability configs, WAF association and tags.
    - For source-based services with `ConfigurationSource: REPOSITORY`, the build and run config lives in `apprunner.yaml` in the repo, so the tool must read it.
    - App Runner's default health check is **TCP**, while the ALB needs an HTTP path, so tasks can fail health checks. The default port is 8080 with `PORT` injected, and Express defaults to port 80.
    - Concurrency-based scaling is not request rate. Convert using concurrency ÷ p50 latency and label the result as an estimate.

16. **[P2] NAT and networking defaults inflate cost** — §4 Networking. Private subnets plus NAT are not required. The Copilot default places tasks in public subnets with a public IP, and Express does the same with public subnets. **Fix:** default to the source's current placement. Suggest NAT only when the App Runner VPC connector implied private egress.

17. **[P2] Version pins are wrong** — §3. The `express-service` module requires Terraform ≥ 1.5.7 and AWS provider ≥ 6.41 (https://github.com/terraform-aws-modules/terraform-aws-ecs/blob/master/modules/express-service/versions.tf). The latest release is v7.6.1 (2026-09-18).

18. **[P2] LocalStack plan tests have little value** — §6. ECS/ELB are LocalStack Pro features, Express Mode support is doubtful (UNSURE), and import plans need real reads. **Fix:** drop LocalStack. Rely on golden snapshot tests, a planned-action assertion over `terraform show -json` from fixtures, and one budget-approved real e2e per source. Note that the archived Copilot CLI must still be able to deploy the sample, so do that e2e first.

19. **[P2] Scope versus 6 weeks** — §7. Both sources, runbook, `verify`, cost estimate and two real e2e runs in 6 weeks of evenings is roughly 2× over. Findings 1–5 add real work, mainly the retain-patch generator and nested-stack walking. **Fix:** see §10 Q1. Cut `verify` (use curl in the runbook) and the cost estimator (a static line-item table instead) from v0.1.

20. **[P3] Distribution inconsistency** — §2 says "PyPI, npm"; §5 is PyPI only. Drop npm.

21. **[P3] Missing option: "keep CloudFormation"** — §1. AWS explicitly lists adopting the generated CloudFormation as-is as an option (https://aws.amazon.com/blogs/containers/announcing-the-end-of-support-for-the-aws-copilot-cli). The report should present it honestly as the zero-risk baseline. That builds trust and sharpens the pitch: "you want Terraform".

## Open questions (§10)

1. **v1 scope:** ship Copilot first (LBWS + Backend Service, adopt-in-place), with `report` released on its own around week 3, and App Runner in v0.2. App Runner's migration is about 30 lines of Terraform, and AWS's own guide plus `amazon-ecs-deploy-express-service` already cover it. Copilot's teardown landmines (findings 1–5) are the real, unserved differentiator. Backend Service costs almost nothing extra once LBWS exists.
2. **Python vs Go:** Python. Output is text codegen, the maintainer is fluent in it, and `uvx`/`pipx` distribution is fine for this audience. Go only matters for a Homebrew single binary, and that isn't the bottleneck.
3. **Terraform strategy:** emit your own plain root-module resources for everything imported. Use terraform-aws-modules `service` for newly created services, and `express-service` only when the strict fit test in finding 6 passes. Emit no CloudFormation or CDK: AWS already lets users keep the CloudFormation, and CDK adds a second emitter for no wedge.
4. **Proton:** no tooling. The deadline is in 8 days, the provisioned infrastructure stays as plain CloudFormation stacks, and generic cf2tf covers it. At most, write one SEO docs page pointing to the generic path.
5. **Name:** keep "ecsodus" if the PyPI/GitHub names are free. Avoiding "Copilot" in the name is correct, and discovery comes from the page titles anyway. Put "AWS Copilot / App Runner to Terraform" in the repo description and PyPI summary.

## Missing from the plan

- A "side-effects of deletion" analysis per stack: conditions flipped by the env-controller, custom-resource Delete handlers, nested stacks.
- The app-level stack and StackSet (ECR repos, hosted zone, KMS, pipeline bucket), and a "never run `copilot app/env delete`" rule.
- Environment addons, managed EFS, CloudFront CDN, imported-VPC environments, internal ALBs, NLB services.
- Adopt-in-place mode for Copilot, and an explicit "keep CloudFormation" baseline in the report.
- `prevent_destroy` on stateful imports, and a CI or runbook gate that parses `terraform show -json` for delete/replace actions on imported addresses.
- A freeze on Copilot deploys and pipelines during the transition window.
- Moving SG membership (addon client SGs, env SG) and secret/KMS permissions into the new roles.
- DNS record-type and apex handling for weighted cutover, ACM issuance ahead of time, and a TTL-based decommission wait.
- A double-work checklist for background jobs, schedulers and boot-time migrations.
- App Runner private services (VPC ingress connections), WAF association, health-check protocol and port defaults, reading `apprunner.yaml` from the repo.
- Handling leftover retained Lambda functions, roles and log groups after the stacks are deleted, and the fact that retained resources keep their `aws:cloudformation:*` tags.
- Budget and domain requirements for the e2e runs: a Route 53 zone or domain and an ACM cert are needed to test the custom-domain paths in the sandbox account.
