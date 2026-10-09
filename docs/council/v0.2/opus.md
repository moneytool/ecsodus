## Verdict
REVISE. Splitting the work into v0.2a then v0.2b is right, and v0.2a is close to ready. v0.2b has gates that do not enforce what the plan says they enforce: scale-to-zero, the retire timing check, and the retire and rollback delete sets. Retirement should not be an inline runbook step in 0.4.0.

## Blocking issues (P0/P1)

1. **P1: `desired_count = 0` does not hold once the scalable target exists (§4.2, §4.6, §4.9 step 3).** Per AWS, registering a new scalable target "changes the resource's current capacity to a value that is inside of this range" ([RegisterScalableTarget](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_RegisterScalableTarget.html)). App Runner's `MinSize` is at least 1, so the step-3 apply starts tasks at once, before `verify-cutover --stage 0` and before anyone confirms the background-work switch. Both sides can then run migrations or jobs against shared data.
   - **Edit:** in the `rebuild` phase, emit `aws_appautoscaling_target` with `min_capacity = 0, max_capacity = 0`, or move the target and policy into a separate later apply.
   - Add a gated step after stage 0 that raises min/max to the App Runner values. Give it its own manifest, or let `check --phase cutover` accept only those two attributes.
   - `verify-cutover --stage 0` must assert live `runningCount == 0` and `desiredCount == 0`.
   - It must read the service's live task definition (`DescribeServices` → `DescribeTaskDefinition`), not the Terraform one, because `ignore_changes = [task_definition]` means Terraform's copy can be stale.

2. **P1: `check --retire` cannot verify "weight not 0 for at least TTL + 24 h" (§4.8).** Route 53 records carry no change timestamp, and Terraform state holds none either. As written, the timing condition depends on the operator's word.
   - **Edit:** name the evidence source. Use CloudTrail `LookupEvents` (us-east-1, `ChangeResourceRecordSets` on the zone ID) to find the change that set `apprunner` to weight 0, and confirm through `GetChange` that it is `INSYNC`.
   - Fail closed if no such event is found within the 90-day Event history.
   - Fix the wording: it should read "the `apprunner` record has had weight 0 for at least TTL + 24 h".
   - Keep the `Requests` check as a second, independent condition. App Runner `Requests` has no per-domain dimension, so it also covers the default URL ([App Runner metrics](https://docs.aws.amazon.com/apprunner/latest/dg/monitor-cw.html)).

3. **P1: The retire delete set can remove records the new ALB certificate depends on; rollback has no gate (§4.7, §4.8).**
   - ACM reuses the same validation CNAME for the same domain within one account, and renewal needs it to stay in place ([ACM DNS validation](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html)). If App Runner's internal certificate lives in the customer account (UNCONFIRMED), or the operator already has a certificate for the hostname, "its validation CNAMEs" collides with the ALB certificate's record. Retire would then delete it, the ALB certificate would fail to renew about 13 months later, and nothing would flag it.
   - **Edit:** `generate` compares `aws_acm_certificate.domain_validation_options` with the imported App Runner validation records. Shared names are emitted once, never in the retire set. `check --phase retire` rejects deleting any `aws_route53_record` whose name matches a validation option of a certificate in state.
   - The retire set also excludes the auto-scaling configuration and the reused SGs.
   - §4.7 rolls back with a "`retire`-style manifest check", but `retire` rejects every delete outside the App Runner set, so rollback cannot pass it. **Edit:** define `check --phase rollback-rebuild`, which allows deletes only and only of the rebuild manifest.
   - Put the rebuild resources in their own root module and state, so rollback is a whole-root destroy rather than `-target`.

4. **P1: Retirement ships unverified and may cost the account App Runner itself (§4.7, §4.9 step 9, §8).**
   - AWS says existing customers keep "creating new resources and services" but does not define "existing customer" ([availability change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)).
   - Deleting the last service may therefore be irreversible for the whole account, not just this service.
   - In §8's eligible-account and design-partner fallbacks, running retire could forfeit that account's eligibility, so the destructive step cannot be tested safely.
   - **Edit:** the 0.4.0 runbook ends at "100 % + window + `check --retire` passes".
   - Retirement becomes a separate opt-in artifact (`generate --retire` → its own manifest and runbook, ADR-0021), shipped behind the `--i-understand-retire-is-unverified` flag until it has run on real App Runner.
   - In any borrowed or eligible test account, keep one sentinel App Runner service until testing is finished.

## Other findings
- **P2: Tracing does not create an `AWS::AppRunner::ObservabilityConfiguration` resource (§3.1, §3.2, ADR-0016).**
  - Copilot sets `ObservabilityConfigurationArn` to the AWS-managed literal `observabilityconfiguration/DefaultConfiguration/1/000…01` ([rd-web/cf.yml](https://github.com/aws/copilot-cli/blob/mainline/internal/pkg/template/templates/workloads/services/rd-web/cf.yml)).
  - Make it `external-reference` and drop the mapper.
  - Private ingress is confirmed: an `AWS::AppRunner::VpcIngressConnection` whose `VpcEndpointId` is `!GetAtt EnvControllerAction.AppRunnerVpcEndpointId`, so it needs a live read.
- **P2: Provider defaults differ from what Copilot deploys (§3.2). The gate would catch each of these, but each makes v0.2a fail. Add them to the knowledge base and emit them explicitly.**
  - `auto_deployments_enabled` defaults to `true` ([apprunner_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/apprunner_service)). Copilot sets `false`.
  - `enable_www_subdomain` defaults to `true` and is `ForceNew` ([provider source](https://github.com/hashicorp/terraform-provider-aws/blob/main/internal/service/apprunner/custom_domain_association.go)). Copilot's handler omits it, so the API default applies. A mismatch means the domain is disassociated and re-associated.
  - Copilot writes the ASC ARN without its revision UUID (`autoscalingconfiguration/high-availability/3`), while the provider's ARNs carry `/<uuid>`. Take the value from `DescribeService`, not from the template.
- **P2: The custom-domain CNAME lives in the root-domain zone, not "under the app domain" (§3.2, §4.5).**
  - RDWS aliases must be one-level subdomains of the root domain ([Copilot domain docs](https://aws.github.io/copilot-cli/docs/developing/domain/)).
  - The handler writes into that zone through `AppDNSRole` with TTL 60 ([custom-domain-app-runner.js](https://github.com/aws/copilot-cli/blob/mainline/cf-custom-resources/lib/custom-domain-app-runner.js)). The "lower TTL to 60" step is therefore normally a no-op.
  - It picks `HostedZones[0]` of `ListHostedZonesByName`. ecsodus must check for an exact-name public zone instead; App Runner does not support private zones.
  - State that a multi-account app (zone in another account) is `blocked`, consistent with v0.1.
  - `CustomResourceRole` (alias case) is missing from §3.1.
  - `VpcConnector` exists only when `network.vpc.placement: private` (otherwise `EgressType: DEFAULT`).
- **P2: The ALB cannot reach the tasks (§4.2).** `ServiceSecurityGroup` has no ingress rules, and `EnvironmentSecurityGroup` only trusts itself and the env ALB. Generate an `aws_vpc_security_group_ingress_rule` from the ALB SG on the container port. v0.1 leaves ingress undeclared on this SG, so a standalone rule will not fight Terraform.
- **P2: Express HTTP behaviour (§4.4).** App Runner redirects HTTP to HTTPS ([2023-02-22 release](https://docs.aws.amazon.com/apprunner/latest/relnotes/release-2023-02-22-http-https-support.html)), and Express creates only a 443 listener ([Express resources](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)). "HTTPS-only matches Express" is therefore wrong: HTTP clients break unless a port 80 redirect is added outside Express.
- **P2: Express conflicts with the existing data-source rule (§4.4).** It requires a data-source lookup of the ALB, but `check/plan.py` fails any plan that contains a data source. Either allow a named data-source type list or pass the ALB ARN in as a decision.
- **P2: Some mutations have no gate.**
  - TTL lowering (§4.9 step 2).
  - Simple-switch `UPSERT` (§4.5).
  - App Runner `update-service` to disable background work (§4.6). Done out of band, it leaves drift that later fails `retire` and `steady`. Make it a Terraform change with its own allowed-attribute gate, or record it as a deliberate out-of-band change with `ignore_changes` on that env var.
- **P2: Weighted import step.** Besides `state rm`, the old record's resource block must be removed from config, or Terraform plans to recreate it. Use a `removed { lifecycle { destroy = false } }` block. The import IDs for the weighted records are `ZONE_name_CNAME_<set-id>` ([route53_record](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route53_record)).
- **P2: Consider reusing the instance role (§4.2, §4.3, §10).** Adding `ecs-tasks.amazonaws.com` to its trust policy is one gated update. It keeps every KMS, S3 and Secrets Manager resource-policy grant that names the role, and removes the "grants don't follow" risk entirely.
- **P2: Health-check translation is incomplete (§4.3).** ALB thresholds max out at 10, while App Runner allows up to 20 ([ALB](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html), [App Runner](https://docs.aws.amazon.com/apprunner/latest/api/API_HealthCheckConfiguration.html)). Add an "unhealthy threshold > 10" row.
- **P2: v0.2a needs a real-plan requirement (§8).** If no eligible account exists, require at least one design-partner `terraform plan` showing import-only before 0.3.0. Otherwise ship v0.2a behind the UNVERIFIED flag too, because the default-diff class of bugs above only shows up against a live plan.
- **P3: Weighted alias A is also an option (§4.5).** App Runner supports Route 53 alias records ([custom domains](https://docs.aws.amazon.com/apprunner/latest/dg/manage-custom-domains.html)), so a weighted pair of alias A records is valid. Your CNAME pair is still correct. AWS's own guide mixes an alias record with "same record type", which is inconsistent.
- **P3: Timeout semantics differ.** ALB `idle_timeout = 120` is an idle timeout, while App Runner's 120 s is a total-request limit. Say so in the report.
- **P3: Other details.**
  - `ECR_PUBLIC` digests need `ecr-public:DescribeImages` (us-east-1).
  - Joining `EnvironmentSecurityGroup` opens the new tasks to all env peers on all ports. App Runner ENIs were egress-only. Report it.
  - Have the report search other workloads' env vars for the service's `*.awsapprunner.com` URL.
- **P3: Contradiction.** §4.9 step 9 says validation CNAMEs are deleted by hand, but §4.8 puts them in the retire set. Pick one.

## Answers to the open questions
1. Release v0.2a as 0.3.0 and v0.2b as 0.4.0. Rename the PLAN scope to "M5: App Runner" so it stops colliding with package version 0.2.0.
2. Keep standalone App Runner report-only in 0.4.0. If standalone rebuild generation is added later, it should stop at 100 % with no retire, since no owner is known.
3. Require v0.2a first. Rebuilding while a Copilot RDWS stack exists reintroduces the risk that the custom-domain and env-controller handlers fire.
4. Agree on plain ECS + ALB as the default, with Express opt-in. Use a new ALB per service by default, because RDWS-only envs usually have no env ALB. Offer a shared env ALB as an opt-in decision, with explicit listener-rule priority.
5. Flat resources.
6. AWS-managed `DefaultConfiguration` → external reference. A customer-created ASC (Copilot only references it by `count: name/rev`) → external reference in v0.2a, listed in the report and never in a retire set. Optional import later.
7. Blocked in rebuild.
8. Allow it with an explicit `tracing: accept-loss` decision. Copilot uses only the AWS-managed X-Ray default, and losing traces is an observability loss, not a correctness one.
9. Maintainer to answer. Run the eligibility probe as a minimal `create-service`, because the AWS text speaks of existing customers creating "resources and services". Whether creating an auto-scaling configuration alone is blocked is unknown.
10. Delegate a subdomain of a domain the maintainer already owns (an NS record pointing to a sandbox zone). This costs nothing to register and also covers v0.1 issue #6. Register a cheap domain only if no such domain exists.
11. Keep retirement out of the default runbook. Provide it as a separate opt-in artifact with its own ADR and gate, marked UNVERIFIED until it has run on real App Runner. See P1-4.
12. Yes. Read CloudWatch alarms and metrics, plus CloudTrail for P1-2, all read-only. List the permissions and fail closed if any is denied. The retire gate cannot work without them.
13. Always require the operator's list. Accept `["sh","-c", …]` only as an explicit decision value, never as a default. Also decide whether the value maps to ECS `command` or `entryPoint`; see Unconfirmed claims.

## Unconfirmed claims
- **Copilot render details for alias, private and tracing (§3.1).** Partly settled from the Copilot source: private = `VpcIngressConnection`; tracing = a literal managed ARN, not a resource (refutes the plan); alias = `CustomDomainFunction`/`Action` + `CustomResourceRole`. Golden renders in M5.0 will confirm.
- **Custom-domain association import ID (§3.2).** Confirmed: `domain_name,service_arn` ([registry](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/apprunner_custom_domain_association)).
- **"App Runner runs amd64 only" (§4.2).** Not confirmed by AWS docs. Confirm with an App Runner docs statement, or check the image manifest platform at inventory time.
- **App Runner → Fargate CPU/memory mapping (§4.3).** The App Runner API values are confirmed ([InstanceConfiguration](https://docs.aws.amazon.com/apprunner/latest/api/API_InstanceConfiguration.html)). The exact App Runner CPU/memory pairings and the Fargate task-size table still need checking against current docs.
- **Health-check ranges (§4.3).** Confirmed as above. Add the threshold > 10 case.
- **Express memory ≤ 8192 MiB (§4.4).** Confirmed: provider doc says 512–8192 MiB and CPU 256–4096 ([ecs_express_gateway_service](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_express_gateway_service)).
- **Express internal ALB on private subnets (§4.2).** Confirmed ([Express resources](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)).
- **Atomic simple → weighted batch (§4.5).** Confirmed: batches are transactional ([ChangeResourceRecordSets](https://docs.aws.amazon.com/Route53/latest/APIReference/API_ChangeResourceRecordSets.html)).
- **Whether deleting the last service ends "existing customer" status (§4.7).** Still unconfirmed, and the AWS page does not define the term. Only an AWS Support answer would confirm it.
- **Which call the closure blocks (§8).** Unconfirmed. The probe answers it; prefer `create-service`.
- **Whether App Runner's internal custom-domain certificate is in the customer account (bears on P1-3).** Confirm with ACM `ListCertificates` in a real RDWS account, or by comparing validation-record names.
- **Whether App Runner health checks count toward `Requests`.** If they do, the retire gate never reaches zero. Confirm from metrics on an idle service.
- **Whether `StartCommand` overrides the image's ENTRYPOINT or its CMD.** AWS only says it "overrides the Docker image's default start command" ([ImageConfiguration](https://docs.aws.amazon.com/apprunner/latest/api/API_ImageConfiguration.html)). This decides whether it maps to ECS `entryPoint` or `command`. Confirm with a test image that has both set.
- **Cost table (§8).** Roughly right at current us-east-1 rates. Confirm against the pricing pages.
