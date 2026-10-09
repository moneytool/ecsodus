# ecsodus: plan M5, App Runner (r4, approved)

r4 (approved unanimously in council round 3, 2026-10-08)

*App Runner support (M5a) and a rebuild-in-parallel mode (M5b). 2026-10-08.*
*Status: r4, approved. All three reviewers voted APPROVE WITH NOTES on r3 in round 3; r4 folds
every round-3 note into the sections below, and §18 lists them as numbered build requirements.
History (kept in the repository, not on the docs site): `docs/council/v0.2/plan-r1.md`,
`plan-r2.md`, `plan-r3.md`; the council record is
[council/v0.2/README.md](council/v0.2/README.md). Round 1: [brief](council/v0.2/brief.md) and
reviews [gpt-6-astra](council/v0.2/astra.md), [Claude Opus 5.5](council/v0.2/opus.md),
[Claude Fable 5.1](council/v0.2/fable.md), all REVISE (11, 4 and 5 P1s). Round 2:
[brief](council/v0.2/brief-r2.md) and votes [gpt-6-astra](council/v0.2/astra-r2.md) (REJECT,
2 P1s), [Claude Opus 5.5](council/v0.2/opus-r2.md) and [Claude Fable 5.1](council/v0.2/fable-r2.md)
(both APPROVE WITH NOTES). Round 3: [brief](council/v0.2/brief-r3.md) and votes
[gpt-6-astra](council/v0.2/astra-r3.md), [Claude Opus 5.5](council/v0.2/opus-r3.md) and
[Claude Fable 5.1](council/v0.2/fable-r3.md), all APPROVE WITH NOTES. §15, §16 and §17 map every
round-1, round-2 and round-3 finding to the section that addresses it. This plan extends
[PLAN.md](PLAN.md) r4 (approved) and changes no v0.1 decision. Where it relies on behaviour
nobody has verified, it says **(UNCONFIRMED)**.*

**Naming.** [PLAN.md](PLAN.md) §3 and §7 call this scope "v0.2". The package is already at 0.2.0
(Worker Services and Scheduled Jobs, see `CHANGELOG.md`), so this plan does not use "v0.2" for
the scope. The milestones are **M5a** (adopt RDWS in place, release **0.3.0**) and **M5b**
(rebuild in parallel, release **0.4.0**). Retirement of the App Runner service is **M5c**, a
separate artifact with no release until it has run on real App Runner (§5). The items PLAN.md §3
lists under "v0.3" (source-based services, ADOT, Express rebuilds of workers) are "after M5" here;
they are not release 0.3.0. The file name `PLAN-v0.2.md` is historical.

## 1. Problem and who has it

| Fact (2026-10-08) | Consequence |
|---|---|
| App Runner closed to new customers on 2026-04-30. Existing services keep running, with no new features. | No deadline, but no future. Accounts that never used App Runner cannot create a service. |
| Copilot CLI end of support 2026-06-12; repo archived. | Copilot's RDWS stacks keep running. The CLI goes stale. |
| Copilot custom-resource Lambdas run `nodejs20.x`: create blocked from 2027-07-29, update from 2027-08-31. | Every Copilot stack, including RDWS stacks, should be off Copilot before mid-2027. |
| A Copilot Request-Driven Web Service (RDWS) is an `AWS::AppRunner::Service`. | RDWS users have both problems at once. |

**Who has it.**

- **(a) Copilot RDWS users.** Today ecsodus detects the RDWS, keeps its stack, and by kept-status
  propagation (docstring of `src/ecsodus/mappers/fates.py`) also keeps its **env stack and the
  app stack and StackSet**. One RDWS in an environment stops the whole app from leaving Copilot.
  M5a closes this gap.
- **(b) Teams with standalone App Runner services** (console, CloudFormation, CDK, Terraform,
  Pulumi). They have no Copilot landmines. Their exit is "rebuild on ECS", which AWS documents
  (Express Mode plus Route 53 weighted DNS).

**Decision: M5 generates for (a) only. (b) gets read-only `inventory` and `report` in 0.4.0.**

- ecsodus's safety model needs a known owner. Retain patches, the closure rule and the teardown
  order all read CloudFormation stacks. For (b) the owner can be anything.
- The wedge is Copilot ([PLAN.md](PLAN.md) §9). For (b), ecsodus would compete with AWS's own
  guide without an advantage.
- The rebuild model (§4) reads the App Runner API, not the stack. Adding (b) later is a source
  adapter. If it is added, it stops at cutover: with no known owner there is no retirement.

## 2. Two options, evaluated

v0.1's adopt-in-place ([ADR-0003](adr/0003-adopt-in-place.md)) imports an ECS service that
already exists. An RDWS has no ECS service, task definition, target group or ALB. "Adopt in
place to ECS" does not exist for App Runner. There are two real options.

### 2.1 Option A: adopt the App Runner service in place, into Terraform

Import `AWS::AppRunner::Service` as `aws_apprunner_service`, the VPC connector and ingress
connection as their `aws_apprunner_*` resources, the custom-domain association and its CNAMEs as
`aws_apprunner_custom_domain_association` and `aws_route53_record`. The rest of an RDWS stack
(roles, security groups, SNS topics, addons) already has a mapper (`src/ecsodus/mappers/`). Then
the stack hands off like any other, and the env and app stacks can follow.

### 2.2 Option B: rebuild on ECS Fargate in parallel, cut over DNS, retire App Runner

Generate a new ECS service, task definition, target group, ALB and certificate. Run both. Shift
the custom domain with Route 53. Retire App Runner later.

### 2.3 Tradeoffs

| | A: adopt App Runner | B: rebuild on ECS |
|---|---|---|
| Traffic moves | No | Yes (DNS cutover) |
| New infrastructure | None | ECS service, task def, execution role, TG, ALB, cert, SG |
| Fits the existing gates | Yes: retain patches, closure, `check --phase import`, unchanged | Needs new phases (§4.8) |
| Removes Copilot | Yes, the whole app | Only after A (§4.1) |
| Leaves you on App Runner | Yes. Closed to new customers, no new features, no announced end date | No |
| Cost of a mistake | An import plan that is not import-only fails the gate. A replacement of `aws_apprunner_service` would give a new default URL; `check` rejects replacements | Double-running side effects, DNS outage, TLS mismatch |
| Default `*.awsapprunner.com` URL | Kept | **Cannot move.** Clients using it must change URL |
| Operator input needed | None beyond v0.1 | Decisions file (§4.4) |
| Build effort | Small: a few mappers, out-of-band reads, fixtures | Large: new mode, emitter, phases, runbook |
| Testable in our sandbox | Only if the account can create App Runner (§9) | ECS side yes; App Runner side same problem |

**A is not a dead end.** It takes Copilot out of the loop before anything risky happens. After A,
the App Runner service is a plain Terraform resource with no custom-resource Delete handlers and
no env-controller. B then starts from that simpler state.

**A alone is not enough.** App Runner gets no new features. Teams that want to leave it need B.

### 2.4 Recommendation: M5a then M5b

1. **M5a (release 0.3.0): adopt RDWS in place.** Copilot can be removed from apps that have an
   RDWS. No traffic moves.
2. **M5b (release 0.4.0): rebuild in parallel, through cutover.** Input is an App Runner service
   whose Copilot hand-off is **proven complete** (§4.1). There is no path for a still-Copilot
   RDWS. The default runbook stops before retirement.
3. **M5c (no release yet): retirement**, a separate opt-in artifact, unavailable until it has run
   on real App Runner (§5).
4. **Standalone App Runner (b):** read-only inventory and report in 0.4.0.

## 3. M5a: adopt RDWS in place

### 3.1 What an RDWS stack holds

The fixture `tests/fixtures/copilot/rendered/workloads/rdws-test.stack.yml` (Copilot v1.29.0
render) has **14 resources**. Rows marked *alias* or *private* come from the archived Copilot
`rd-web/cf.yml` template (reviewed by Opus and Fable in round 1); M5a.0 adds golden renders for
them.

| Logical ID | Type | Condition | Mapper today | M5a fate |
|---|---|---|---|---|
| `AccessRole` | `AWS::IAM::Role` (trust `build.apprunner.amazonaws.com`, `AWSAppRunnerServicePolicyForECRAccess`) | `NeedsAccessRole` (ECR images) | yes | `import` |
| `InstanceRole` | `AWS::IAM::Role` (trust `tasks.apprunner.amazonaws.com`; inline `DenyIAM`, tag-scoped SSM/Secrets/KMS, `Publish2SNS`) | — | yes | `import` |
| `Service` | `AWS::AppRunner::Service` | — | **no** | `import` (new) |
| `AddonsStack` | `AWS::CloudFormation::Stack` | `HasAddons` | yes | `nested-wrapper` |
| `customersSNSTopic`, `mytopicfifoSNSTopic` | `AWS::SNS::Topic` | — | yes | `import` |
| `customersSNSTopicPolicy`, `mytopicfifoSNSTopicPolicy` | `AWS::SNS::TopicPolicy` | — | yes | `import` |
| `EnvControllerAction` | `Custom::EnvControllerFunction` (`Parameters: [NATWorkloads,]`) | — | yes | `manual-cleanup` (retained) |
| `EnvControllerFunction`, `EnvControllerRole` | `AWS::Lambda::Function` (`nodejs20.x`), `AWS::IAM::Role` | — | yes | `manual-cleanup` (retained) |
| `ServiceSecurityGroup` | `AWS::EC2::SecurityGroup` | — | yes | `import` |
| `EnvironmentSecurityGroupIngressFromServiceSecurityGroup` | `AWS::EC2::SecurityGroupIngress` (env SG trusts `ServiceSecurityGroup`, all ports) | — | yes | `import` |
| `VpcConnector` | `AWS::AppRunner::VpcConnector` (`SecurityGroups: [ServiceSecurityGroup, imported EnvironmentSecurityGroup]`) | only with `network.vpc.placement: private`; otherwise `EgressType: DEFAULT` | **no** | `import` (new) |
| *alias:* `CustomDomainAction` | `Custom::CustomDomainFunction` (`custom-domain-app-runner.js`) | `alias` set | yes (knowledge base) | `manual-cleanup` (retained) |
| *alias:* `CustomDomainFunction`, `CustomResourceRole` | `AWS::Lambda::Function`, `AWS::IAM::Role` | `alias` set | yes | `manual-cleanup` (retained) |
| *private:* ingress connection | `AWS::AppRunner::VpcIngressConnection`; `VpcEndpointId` is `!GetAtt EnvControllerAction.AppRunnerVpcEndpointId` or a literal | `http.private` | **no** | `import` (new); endpoint ID from a live read |

Notes:
- `AutoScalingConfigurationArn` is a literal ARN built from `count` (`autoscalingconfiguration/high-availability/3`):
  a configuration the user created, possibly shared, never owned by the stack. Fate:
  **`external-reference`**, listed in the report, never imported in M5a and never in any delete
  set. The template ARN has no revision UUID; the value comes from `DescribeService` (§3.3).
- Tracing does **not** create a resource. Copilot sets `ObservabilityConfigurationArn` to the
  AWS-managed literal `observabilityconfiguration/DefaultConfiguration/1/00000000000000000000000000000001`.
  Fate: **`external-reference`**. There is no observability mapper.
- App Runner creates its own log groups (`/aws/apprunner/<name>/<id>/application` and
  `/service`). No stack owns them. They survive any stack delete.

### 3.2 New mappers and out-of-band reads

| Source | Terraform | Import ID | Notes |
|---|---|---|---|
| `AWS::AppRunner::Service` | `aws_apprunner_service` | service ARN | every argument from template + `DescribeService`, provider defaults emitted explicitly (§3.3); `prevent_destroy`; `ignore_changes` on the image identifier (deploy owner, §3.5) |
| `AWS::AppRunner::VpcConnector` | `aws_apprunner_vpc_connector` | connector ARN | subnets and `security_groups` from live `DescribeVpcConnector`, so the import keeps the actual membership (both SGs for a Copilot render); the provider marks `security_groups`, `subnets` and `vpc_connector_name` `ForceNew` and updates only tags (provider source, `internal/service/apprunner/vpc_connector.go`), so any argument mismatch plans a replace, which `check` rejects |
| `AWS::AppRunner::VpcIngressConnection` | `aws_apprunner_vpc_ingress_connection` | ARN | private RDWS only |
| custom domain (out of band) | `aws_apprunner_custom_domain_association` | `<domain_name>,<service_arn>` | from `DescribeCustomDomains`; `enable_www_subdomain` read from live (§3.3); `prevent_destroy` |
| domain CNAME (out of band) | `aws_route53_record` (CNAME, TTL 60) | `<zone-id>_<name>_CNAME` | in the **root-domain zone** (an RDWS alias is a one-level subdomain of the app's root domain), written by the handler through `AppDNSRole`; `prevent_destroy` |
| validation CNAMEs (out of band) | `aws_route53_record` (CNAME) each | as above | from `CertificateValidationRecords`; they keep App Runner's certificate renewing |
| env `AppRunnerVpcEndpoint` + SG | `aws_vpc_endpoint` etc. | — | already mapped; present when `AppRunnerPrivateWorkloads` is non-empty (`ENV_CONDITIONS` in `src/ecsodus/knowledge.py`) |
| auto-scaling and observability configurations | — | — | `external-reference` (§3.1) |

**Zone discovery.** The handler takes `HostedZones[0]` of `ListHostedZonesByName`. ecsodus does
not copy that. The zone rules come in two parts:
- **Zone rules (every use):** exactly one **public** zone whose name equals the root domain, in
  the account being migrated, delegated (its NS set matches the parent's delegation, read with a
  public DNS query).
- **Adoption rule (only when adopting an existing custom domain):** the zone also holds a CNAME at
  the alias whose value is the service's `DNSTarget`.

Anything else fails closed. A new hostname for the no-custom-domain branch (`new_host`, §4.9)
can never meet the adoption rule; it is checked against the zone rules, the CAA check (§4.8 #1)
and the absence of any record of any type at that name. A zone in another account (a
multi-account app, where `AppDNSRole` sits in the app account) is **blocked**, consistent with
v0.1 ([PLAN.md](PLAN.md) §3).

New read-only live calls: `apprunner:DescribeService`, `DescribeVpcConnector`,
`DescribeVpcIngressConnection`, `DescribeCustomDomains`, `DescribeAutoScalingConfiguration`,
`ListTagsForResource`; `wafv2:GetWebACLForResource`; `route53:ListHostedZonesByName`,
`GetHostedZone`, `ListResourceRecordSets`. None returns a secret value. `DescribeService` returns
`RuntimeEnvironmentVariables` in plaintext, the same exposure as a task definition's
`environment`; the v0.1 secrets contract applies (`inventory.json` 0600, HCL with env values in
`.gitignore`, encrypted state).

**Blocked in M5a** (fail closed, named in the report): source-code services (`CodeRepository`),
a WAF web ACL whose owner is not discoverable, a zone in another account, any `DescribeService`
field the mapper does not know.

### 3.3 Provider defaults that differ from what Copilot deploys

Each of these would make the import plan non-empty and fail the gate. The knowledge base records
them, and the mapper emits the live value explicitly.

| Argument | Provider default | Copilot / live | Rule |
|---|---|---|---|
| `auto_deployments_enabled` | `true` | Copilot sets `false` | emit the live value |
| `enable_www_subdomain` (ForceNew) | `true` | Copilot's handler omits it, so the API default `true` applies | read `EnableWWWSubdomain` from `DescribeCustomDomains`; never assume. A mismatch would plan a disassociate and re-associate |
| `auto_scaling_configuration_arn` | — | template ARN has no `/<uuid>`; the provider stores the full ARN | take the full ARN from `DescribeService` |
| `observability_configuration_arn` | — | AWS-managed literal | emit the literal; `external-reference` |
| `health_check_configuration` | block defaults TCP, path `/`, interval 5, timeout 2, healthy 1, unhealthy 5 (provider docs) | App Runner default is the same, TCP/5/2/1/5 | emit the live block even when it is the default (**UNCONFIRMED** only that a real import plan shows no diff, §9) |

Every association with `EnableWWWSubdomain: true` also covers `www.<alias>`, with no DNS record
for it. The M5a report says so. M5b does not carry `www.<alias>` to ECS (§4.4).

### 3.4 Safety: what a plain RDWS stack delete destroys

| Resource | Plain delete does | With retain patch |
|---|---|---|
| `Service` | Deletes the App Runner service. Its `*.awsapprunner.com` URL is gone for good | kept |
| `CustomDomainAction` | Delete handler **disassociates the domain and DELETEs the domain CNAME and every validation CNAME**: the custom domain stops resolving | handler not invoked. The 2026-09-30 run ([e2e](e2e/2026-09-30-aws-e2e.md)) verified this for `Custom::EnvControllerFunction`; the mechanism is generic CloudFormation, so the same holds here |
| `EnvControllerAction` | Removes the workload from `NATWorkloads` and `AppRunnerPrivateWorkloads`, then updates the env stack. If it was the last user: **NAT gateways, their routes and the App Runner VPC endpoint are deleted**, breaking every other private workload | handler not invoked |
| `ServiceSecurityGroup` + ingress | Deleted; the env SG rule that trusts it goes too | kept |
| `VpcConnector`, roles | Deleted | kept |
| SNS topics | Deleted; other services' subscriptions break | kept |
| `AddonsStack` | Nested addons with no `DeletionPolicy`: Aurora snapshot-and-delete, DynamoDB and secrets deleted | kept |

The v0.1 mechanics apply unchanged: retain-all patch, change set with `check --changeset`,
`verify-retain`, import, `check --phase import`, `check --state`, teardown, `check --phase steady`.
No exception for App Runner.

### 3.5 Deploy owner after M5a

Copilot deployed by changing the `ContainerImage` parameter. After hand-off the named deploy
owner is CI calling `aws apprunner update-service` (or `start-deployment` for a mutable tag).
Terraform gets `ignore_changes` on
`source_configuration[0].image_repository[0].image_identifier`, the analogue of
`ignore_changes = [task_definition]` on ECS ([PLAN.md](PLAN.md) §2.4). If live
`AutoDeploymentsEnabled` is true, App Runner itself is the deploy owner and the report says so.
(**UNCONFIRMED** that a `start-deployment` leaves the plan empty: import, deploy, then plan, §9.)

The report also searches the other workloads' environment variables for the service's
`*.awsapprunner.com` URL, since those callers cannot follow a DNS cutover later.

## 4. M5b: rebuild-in-parallel mode

### 4.1 Preconditions

**Copilot must be provably gone.** The M5a manifest records an intended hand-off, not a finished
teardown. A new read-only command, `ecsodus verify-handoff --manifest M`, proves it:

1. Every stack in the manifest's `handoff_stacks` is gone (`DescribeStacks`: not found or
   `DELETE_COMPLETE`).
2. No stack tagged with this app and env remains, and the env stack itself was handed off and
   deleted. If any Copilot workload remains in the env, its env-controller can still rewrite the
   env stack (NAT gateways, the App Runner endpoint) that the rebuild depends on, so the rebuild is
   **blocked**. An app stack kept for other envs is allowed; the report names it.
3. `terraform state list` holds the App Runner service at its manifest address, and a fresh plan
   of the M5a root passes `check --phase steady`. If the service has a custom domain, state also
   holds the association and the domain CNAME. With no custom domain (a supported branch, §4.9)
   these two are not required, and `DescribeCustomDomains` must return none.
4. The service ARN in state equals the live service (`DescribeService`), in the same account
   and region, and the state's `image_identifier` equals the live one. After a synchronized
   deployment (below) the HCL still holds the tag; `ignore_changes` plus refresh carries the live
   digest into state, and this check proves it, so `worker-off` (§4.10) sends the digest.

It writes `handoff-complete.json` (account, region, app, env, service ARN, plan hash, time).
`inventory --mode rebuild` requires it and re-runs checks 1, 2 and 4 itself; a record older than
24 h fails, as in v0.1's freshness rule.

**The deployed image must be known.** `DescribeService` returns the configured identifier, not
proof of what runs. If the identifier is a digest (`repo@sha256:…`), ecsodus uses it. If it is a
tag, the running digest cannot be established (the tag may have moved since the last
deployment), and generation **blocks**. The operator then runs a synchronized deployment through
the deploy owner: `update-service` to the digest the tag resolves to now, wait for the operation
to reach `SUCCEEDED` (`ROLLBACK_SUCCEEDED` is a failure: App Runner reverted), then refresh the
M5a state and re-run `verify-handoff` and inventory. Digests come from `ecr:DescribeImages`, or
`ecr-public:DescribeImages` (us-east-1) for `ECR_PUBLIC`. If the digest is a manifest list,
`ecr:BatchGetImage` reads it and ecsodus pins the `linux/amd64` child on the ECS side.

### 4.2 Flow and roots

```
ecsodus verify-handoff --manifest m5a/manifest.json           -> handoff-complete.json
ecsodus inventory --mode rebuild --handoff handoff-complete.json -> inventory.json
ecsodus report    inventory.json                       -> REPORT.md + decisions.template.yml
ecsodus generate  inventory.json --mode rebuild --decisions decisions.yml --out ./rebuild
                  -> rebuild/infra-rebuild/ (new root), rebuild/infra-patches/ (edits to the
                     M5a root), rebuild/staged/taskdef-on.tf (8a, outside the root),
                     rebuild/dns/*.json, rebuild/manifest.json, RUNBOOK.md
ecsodus generate  ... --stage rebuild     --evidence cert-requested.json (after 2a, before 2b)
ecsodus generate  ... --stage worker-on   --evidence taskdef-on.json     (after step 8a)
ecsodus generate  ... --stage taskdef-off --evidence live-revision.json  (rollback after hand-over)
ecsodus check     plan.json --phase <phase> --manifest rebuild/manifest.json [--step N] [--rollback]
ecsodus check     --dns-batch rebuild/dns/convert.json --manifest rebuild/manifest.json
ecsodus verify-cutover --manifest rebuild/manifest.json --step <step>   (read-only)
```

ecsodus stays read-only. It never applies Terraform, never changes DNS, never shifts traffic.
Every mutation is a runbook step behind a gate.

**Staged generation.** Two values the gates need are computed by AWS at apply time: the new
certificate's validation record, and the ARN of the task-definition revision that turns
background work on. ecsodus never gates on an unknown value for them. A small gated phase creates
the one resource (2a, 8a); a read-only `verify-cutover` step reads the real value and writes an
evidence file bound to the ARN; `generate --stage` then emits the next phase's HCL and manifest
entry with that value as a literal. The first `generate` emits only what does not depend on them.
A rollback after hand-over (§4.11) uses the same pattern once more: `verify-cutover --step
live-revision` binds the live service revision, and `generate --stage taskdef-off` emits its off
twin.

**The 8a file.** The first `generate` writes `aws_ecs_task_definition.on` to
`rebuild/staged/taskdef-on.tf`, outside the `infra-rebuild` root. The runbook copies it into
`rebuild/infra-rebuild/` at §4.12 step 9, after cutover and before the 8a plan, and the manifest
records its hash. If it is in the root at step 3, `check --phase rebuild` rejects the plan as a
create outside the manifest (§8 has the must-fail test).

**Two roots, two states.**
- **M5a root** (exists): owns the App Runner service, the association, the domain record (later
  the weighted pair), the instance role and the SGs. M5b only edits it through the `prepare`,
  `import`, `cutover`, `switch` and `worker-off` phases.
- **`infra-rebuild` root** (new, own state): owns everything M5b creates. Rollback is a destroy
  of this whole root, never `-target`.
- With a shared ALB only (§4.7), a third root is edited: the one whose state holds the env ALB.

`manifest.json` records, per phase, the exact addresses, allowed attributes and expected
before/after values, with the SHA-256 of every generated file.

### 4.3 What ecsodus generates

**Default target: a plain ECS Fargate service behind a dedicated new ALB, as flat resources in
the `infra-rebuild` root.** A shared ALB (§4.7) and Express (§4.6) are opt-in.

| Generated | Resource | Notes |
|---|---|---|
| Task definitions | `aws_ecs_task_definition` `off` (step 3) and `on` (step 8a), two addresses of one family | one container; `X86_64`; image pinned by digest (§4.1); `off` carries background work **off** (§4.10), `on` differs only in that env var. `skip_destroy = true` on both, so a replaced or destroyed revision stays `ACTIVE` and rollback can re-reference it (`UpdateService` cannot use an `INACTIVE` revision) |
| Service | `aws_ecs_service` | in the env cluster; `desired_count = 0`; `ignore_changes = [desired_count]`. Created with `task_definition = aws_ecs_task_definition.off.arn`; step 8c replaces that with the literal ARN of `on`. Terraform owns `task_definition` during the migration (CI deploys stay frozen, §4.12 step 1); the hand-over step adds `ignore_changes = [task_definition]` and names CI. `health_check_grace_period_seconds` from a decision (pre-filled 60). `deployment_circuit_breaker { enable = true, rollback = false }`: a failing deployment stops and shows `FAILED`, which `ready` and 8c catch; ECS never reverts `task_definition` behind Terraform's back, so state and the gates stay true. `depends_on` the 443 listener (and, shared ALB, the listener rule): the target group must be attached first |
| Scaling | `aws_appautoscaling_target` + target-tracking policy | created at **`min_capacity = 0`, `max_capacity = 0`** (**UNCONFIRMED** that `RegisterScalableTarget` accepts `MaxCapacity = 0` for ECS; `MinCapacity = 0` is documented; tested offline and on the stand-in, §8, §9); the `start` phase raises them (§4.8). An `ALBRequestCountPerTarget` policy `depends_on` the listener and rule too |
| Task role | **the App Runner instance role, reused** | `prepare` adds `ecs-tasks.amazonaws.com` to its trust policy with an `aws:SourceAccount` condition. Every key, bucket and secret policy that names the role keeps working |
| Execution role | `aws_iam_role` (new) | ECR pull, logs; per `RuntimeEnvironmentSecrets` ARN, `secretsmanager:GetSecretValue` (Secrets Manager) or `ssm:GetParameters` (SSM Parameter Store); `kms:Decrypt` only for a customer-managed key, scoped to that key (App Runner fetched these with the instance role; ECS fetches them with the execution role) |
| Log group | `aws_cloudwatch_log_group` | retention copied from the App Runner application log group; kept on rollback (§4.11) |
| Target group | `aws_lb_target_group` | `ip` targets; health check from §4.4 |
| ALB | `aws_lb`, listener 443 + 80→443 redirect, ALB SG | `idle_timeout` from the decision (§4.4); the 443 listener takes `aws_acm_certificate_validation.certificate_arn`, so it is created only after the certificate is `ISSUED` |
| Certificate | `aws_acm_certificate` (step 2a, alone) + validation record if absent + `aws_acm_certificate_validation` (step 3) | see "Validation record" below. `aws_acm_certificate_validation` takes the literal `validation_record_fqdns`, which gives no implicit edge to the created record, so it `depends_on` that record when one is created |
| `new_host` record (no custom domain only, §4.9) | `aws_route53_record`, alias A to the ALB | created in step 3 with `allow_overwrite = false`; gated on name, type and alias target (§4.8 #3); deleted by the rollback destroy (§4.11) |
| Task SG | `aws_security_group` + `aws_vpc_security_group_ingress_rule` | new; ingress only from the ALB SG on the container port |
| WAF | `aws_wafv2_web_acl_association` | same regional web ACL, on the new ALB; the ACL is `external-reference` |

**Security groups.** Copilot's VPC connector carries **both** `ServiceSecurityGroup` and the
imported `EnvironmentSecurityGroup` (the RDWS fixture, and Copilot's `vpc-connector.yml`
partial). M5a imports the connector with its actual membership and changes nothing. For the
ECS tasks, ecsodus reads live `DescribeVpcConnector.SecurityGroups`:
- Tasks always join `ServiceSecurityGroup` (reused, so rules that trust it, including Copilot's
  addon rules and the env SG's ingress from it, still match) and the new task SG (so the ALB can
  reach them).
- If the connector holds any other SG (normally `EnvironmentSecurityGroup`), `decisions.yml` must
  answer `env_sg: join | omit` per extra SG; a missing answer blocks. The report lists, for each
  extra SG, the closure rules whose source is that SG (they stop matching the tasks under `omit`)
  and the inbound exposure of `join` (the env SG admits traffic from every env peer, so the tasks
  become reachable from them on all ports; App Runner ENIs never accepted inbound traffic).
- `verify-cutover --step created` checks the live service's SGs equal this decision.

**Validation record.** ACM uses one DNS-validation CNAME per FQDN per account, and every
certificate for that FQDN renews through it. App Runner's managed certificate may live in the
customer account (**UNCONFIRMED**). The new certificate's `domain_validation_options` exist only
after `RequestCertificate`, so the comparison runs in two stages:

1. **Predictor (read-only, `generate` and `verify-cutover --step pre-create`).** `acm:ListCertificates`
   (all statuses), then `DescribeCertificate` on every certificate whose domain or SANs cover the
   FQDN. Because ACM reuses the record per FQDN per account, an existing certificate's
   `ResourceRecord` is the one the new certificate will get. ecsodus compares it, the imported
   `CertificateValidationRecords` and live `ListResourceRecordSets` for that name. A conflict
   (same name, different value, or a non-CNAME at the name) blocks early. With no existing
   certificate the prediction is "unknown", which is allowed. The predictor only reports; it never
   decides what is created.
2. **Certificate request (gated, step 2a).** A plan that creates only `aws_acm_certificate`
   (`check --phase cert-request`). Then `verify-cutover --step cert-requested` reads the actual
   `DescribeCertificate` validation options and compares each with live DNS and both states.
   It writes `cert-requested.json` (certificate ARN, record name, type, value, outcome), and
   `generate --stage rebuild` emits from it, record name and value as literals, both the 2b
   import block and manifest entry (when the outcome needs them) and step 3. It therefore runs
   before 2b:

| Live record at the name | Outcome |
|---|---|
| absent | `infra-rebuild` creates it, with `allow_overwrite = false` emitted explicitly (the provider then sends `CREATE`, which fails safely if a record appears meanwhile; `true` would send `UPSERT`). `check --phase rebuild` rejects any other value |
| present, same value, owned by the M5a root (an imported `CertificateValidationRecords` entry) | no record created; the validation's `validation_record_fqdns` is the literal name |
| present, same value, in neither ecsodus state | ownership unknown (below); with `validation_record: import`, imported into the M5a root (step 2b, import-only plan, `check --phase import`, `prevent_destroy`), then referenced as above; with `validation_record: reference`, not imported, and the validation references the literal FQDN |
| present, different value or type | **blocked**; the certificate from 2a is removed by the rollback destroy (§4.11) |

**Ownership of an unowned matching record (2b).** "In neither ecsodus state" does not mean no
owner: another Terraform state or a CloudFormation stack may hold the record, and matching DNS
values establish compatibility, not ownership. The report says the owner is unknown and that a
deletion by another owner stops renewal for every certificate on that FQDN, the old owner's and
ours. `decisions.yml` must answer `validation_record: import | reference`; `import` also takes a
`provenance` note in which the operator confirms no other IaC owns the record. A missing answer
blocks.

**72-hour validation window.** ACM moves a certificate to `VALIDATION_TIMED_OUT` if it is not
validated within 72 hours. For the "absent" outcome, step 3 must apply within 72 h of 2a.
`generate --stage rebuild` and `check --phase rebuild` read `DescribeCertificate` and fail unless
the status is `PENDING_VALIDATION` (or `ISSUED`, for the reference and adopt outcomes) and the
certificate is younger than 72 h; `VALIDATION_TIMED_OUT` or `FAILED` fails. Recovery: the rebuild
gate forbids a replace, so the runbook runs the rollback destroy (§4.11) and then 2a again. A
validation record created by an earlier attempt and forgotten by that rollback still matches the
new certificate (ACM reuses it per FQDN), so the second attempt normally takes the 2b row.

Listener activation needs `ISSUED`: the listener references `aws_acm_certificate_validation`,
and `verify-cutover --step created` checks the certificate is `ISSUED` and on the listener. No
gate may ever delete a record that matches a validation option of any certificate in either
state, including a validation record `infra-rebuild` created itself: the rollback destroy forgets
it (§4.11), and the retire set never names one (§5.3).

*Why both stages:* the predictor catches most conflicts before anything is created, but it cannot
see a certificate that does not exist yet and rests on documented ACM behaviour. The gated request
is the binding check: it compares the real value, and it creates one free, inert resource that
the rollback destroy removes.

**Why a plain service by default:** Copilot's RDWS egresses through a VPC connector in
**private** subnets. Express puts an internal ALB in front of private subnets, so a public RDWS on
private subnets cannot be expressed in Express without moving tasks to public subnets with
public IPs ([council/fable.md](council/fable.md) finding 4).

**Why a dedicated ALB by default:** an RDWS-only env usually has no env ALB, and a shared ALB
needs updates (timeout, certificate, WAF, rules) that a create-only gate cannot allow.

Flat resources, not `terraform-aws-modules/ecs`: one emitter, one `terraform validate` harness,
no module version in the support matrix.

### 4.4 Config translation

Every value comes from `DescribeService` and related reads, or from `decisions.yml`. Nothing is
guessed. A missing decision **blocks** generation, with the key named in the report.

| App Runner | ECS | Rule |
|---|---|---|
| `ImageRepository.ImageIdentifier`, `ECR` / `ECR_PUBLIC` | container `image` | digest only (§4.1) |
| `CodeRepository` (source-based) | — | **blocked** (after M5; needs the repo and `apprunner.yaml`) |
| `ImageConfiguration.Port` | `containerPort`, TG port, task SG rule port | literal |
| `StartCommand` set | `command` or `entryPoint` | **decision required, always.** App Runner takes one string; ECS takes lists, and whether App Runner overrides ENTRYPOINT or CMD is **UNCONFIRMED**. The operator gives `command` (and `entry_point` if needed). The template pre-fills `["sh","-c","<StartCommand>"]` with a `# confirm` marker; it is never a default |
| `StartCommand` absent | — | image defaults kept |
| `RuntimeEnvironmentVariables` | `environment` | literal; secrets contract |
| `RuntimeEnvironmentSecrets` | `secrets[].valueFrom` | literal ARNs; execution role gets `secretsmanager:GetSecretValue` or `ssm:GetParameters` per ARN, `kms:Decrypt` only for a customer-managed key (§4.3; §4.5 checks it) |
| `InstanceRoleArn` | task role | same role (§4.3) |
| `AuthenticationConfiguration.AccessRoleArn` | execution role | ECR pull |
| `InstanceConfiguration.Cpu/Memory` | task `cpu`/`memory` | lookup table: 0.25 vCPU → 256 with 512/1024; 0.5 → 512/1024; 1 → 1024 with 2048/3072/4096; 2 → 2048 with 4096/6144; 4 → 4096 with 8192/10240/12288. All are valid Fargate pairs |
| egress `VPC` | `awsvpc` in the connector's subnets | same subnets, so the same NAT EIPs; outbound allowlists keep working |
| connector SGs beyond `ServiceSecurityGroup` | task SGs | **decision required**: `env_sg` is `join` or `omit` per extra SG (§4.3) |
| egress `DEFAULT` | — | **decision required**: subnets and public-IP choice. The report warns the source IP changes from App Runner's shared ranges to yours |
| `IsPubliclyAccessible: false` + ingress connection | — | **blocked**: App Runner custom domains do not support private zones, so clients use the connection's AWS-generated domain, which cannot move. The report gives the manual path |
| `IpAddressType: DUAL_STACK` | ALB `dualstack` | blocked if the VPC has no IPv6 CIDR |
| health check HTTP, in ALB range | TG health check | literal |
| health check TCP (App Runner default) | — | **decision required**: ALB needs an HTTP path |
| interval < 5 s, timeout < 2 s, timeout ≥ interval, healthy threshold 1, or any threshold > 10 | — | **decision required**. ALB: interval 5–300, timeout 2–120, thresholds 2–10. App Runner: 1–20 each; default TCP/5/2/1/5 |
| `MinSize`/`MaxSize` | scalable target min/max | literal, applied in `start` (§4.8) |
| — | `health_check_grace_period_seconds` | **decision required**, pre-filled 60 (App Runner has no equivalent) |
| `MaxConcurrency` | — | **decision required**: concurrency is not requests per target or CPU; the operator picks metric and target |
| `ObservabilityConfiguration` (AWS-managed X-Ray default) | — | **decision required**: `tracing: accept-loss`. The report states that traces stop on ECS. ADOT is after M5 |
| `EncryptionConfiguration.KmsKey` | — | reported; no ECS equivalent beyond Fargate ephemeral-storage keys |
| WAF association | `aws_wafv2_web_acl_association` | same ACL, dedicated ALB only (§4.7) |
| custom domain | certificate + listener + DNS cutover (§4.9) | required for a gradual cutover |
| `EnableWWWSubdomain: true` | — | **not carried.** The report states that `www.<alias>` stops working once App Runner is gone |
| default `*.awsapprunner.com` URL | — | **cannot move.** The report states it |
| background work | task env | **decision required** (§4.10) |
| request timeout | ALB `idle_timeout` | **decision required**, pre-filled 120. App Runner's 120 s is a total-request limit; the ALB value is an idle timeout. They are different quantities, and the report says so |

**Runtime behaviour that differs, stated in the report:**
- App Runner throttles CPU on idle instances. On ECS a container runs at full CPU, so background
  loops that barely ran on App Runner run for real.
- App Runner terminates TLS and redirects HTTP to HTTPS (since 2023-02-22). The ALB has both
  listeners.
- App Runner runs images as amd64. There is no official statement (**UNCONFIRMED**), only
  community reports; pinning the `linux/amd64` digest (§4.1) makes both sides run the same bits
  either way.

### 4.5 Networking and authorization checks

`verify-cutover --step created` checks, read-only, before any task starts:
- **Routes.** Each task subnet passes one of three paths: its route table has `0.0.0.0/0` to an
  `available` NAT gateway; or `0.0.0.0/0` to an attached internet gateway **and** the service
  assigns a public IP (`assign_public_ip = true`, the §4.4 public-subnet decision for egress
  `DEFAULT`); or the VPC has endpoints for `ecr.api`, `ecr.dkr`, S3 (gateway), `logs`, and
  `secretsmanager` / `ssm` as the secrets need. VPC DNS support and hostnames are on.
- **Security groups.** The live service's SGs equal the task SG, `ServiceSecurityGroup`, and each
  extra connector SG whose decision is `join` (§4.3).
- **Ingress.** The task SG rule from the ALB SG on the container port exists, and the ALB SG
  allows 443 and 80 from the declared sources.
- **Authorization.** `iam:SimulatePrincipalPolicy` on the execution role for each secret ARN and
  KMS key, and on the reused task role for its existing actions. Simulation cannot evaluate every
  resource policy; the report lists the key, bucket and secret policies found in the closure that
  name the instance role, and says the list is closure-limited, not exhaustive.

The first real proof is the task starting: a secret it cannot fetch stops it with
`ResourceInitializationError`, which the `ready` step catches.

### 4.6 Express (opt-in, not available in 0.4.0)

The predicate is [PLAN.md](PLAN.md) §2.3, plus:
- egress `DEFAULT`, or the operator accepts tasks in public subnets with public IPs;
- memory ≤ 8192 MiB and CPU ≤ 4096 (excludes App Runner 4 vCPU / 10 and 12 GB);
- `tracing: accept-loss` if tracing is on; health-check path given.

Three gaps keep `--target express` **failing closed** in 0.4.0:
1. **No demonstrated zero-task start.** The scale-to-zero interlock (§4.8) is not shown for
   `aws_ecs_express_gateway_service` and its scaling.
2. **HTTP clients break.** App Runner redirects HTTP to HTTPS; Express creates only a 443
   listener. A port-80 redirect would have to live outside Express.
3. **Ownership outside the manifest.** Express creates and deprovisions the ALB, rules and
   certificate attachment itself. Terraform would need that ALB's ARN. `check` rejects every data
   source today, so the ARN would come in as a decision after Express creates it, and the gate
   could not see those resources.

Express is unlocked only after a real run closes all three. The translation table is shared.

### 4.7 Shared env ALB (opt-in)

`alb: shared` in `decisions.yml` uses the env's Terraform-owned ALB instead of a new one. It is
allowed only when the ALB is in the state of a root ecsodus generated, has a 443 listener, and
the host header is not already routed. That root is usually the **v0.1 env root** (the env stack
handed off by v0.1), not the M5a root; `inventory --mode rebuild` finds it by the ALB's ARN in
`terraform state` and the manifest records its path and state lineage. The operator gives the
rule priority (checked against existing rules with the v0.1 priority knowledge).
- In `infra-rebuild` (creates only): `aws_lb_listener_certificate`, `aws_lb_listener_rule` at the
  given priority, the task SG rule. The listener ARN is a literal from inventory, not a data
  source.
- In the ALB's root, through its own `prepare-alb` plan (`check --phase prepare` against that
  root's manifest entry): `idle_timeout` only, and only if the decision differs from the live
  value. It applies to every service behind that ALB, and the report says so.
- **WAF:** blocked if the ALB has a different web ACL, or none while App Runner has one;
  associating an ACL would change protection for every other service on the ALB.

### 4.8 Transitions and gates

Every phase has a manifest entry: the plan must touch **exactly** its addresses (a targeted or
incomplete plan fails), with the listed actions and after-values; unknown (computed) values on a
gated attribute fail; data sources and other providers fail, as in v0.1. In a create phase only
the listed after-values are gated; other computed values (ARNs, DNS names, the service's first
`task_definition`) are allowed because nothing can run at 0/0 and step 4 reads the live values.
The computed values a later gate depends on, the validation record, the `on` revision's ARN and
(rollback after hand-over) the off twin's ARN, come in as literals through staged generation
(§4.2).

| # | Transition | Root | Gate | Allowed | Fails on |
|---|---|---|---|---|---|
| 0 | Copilot gone | — | `verify-handoff` | — | §4.1 |
| 1 | pre-create | — | `verify-cutover --step pre-create` | — | image not a digest; validation-record predictor conflict (§4.3). With a custom domain also: zone not exact/public/delegated/in-account; record not a simple CNAME to `DNSTarget`; weighted set already present; CAA forbids Amazon; App Runner validation records missing. With no custom domain instead: `new_host` declared; its zone fails the §3.2 zone rules (the adoption rule does not apply); any record of any type already at `new_host`; CAA forbids Amazon |
| 2 | prepare | M5a (and, shared ALB, the ALB's root as `prepare-alb`, §4.7) | `check --phase prepare` | update instance role `assume_role_policy` to the exact expected document; update domain record `ttl` to 60 if higher; (shared ALB) `idle_timeout` to the decided value | anything else, including any other attribute on those addresses |
| 2a | cert-request | `infra-rebuild` | `check --phase cert-request`, then `verify-cutover --step cert-requested` | create of `aws_acm_certificate` only, with the manifest's `domain_name`, `validation_method = "DNS"`, and `subject_alternative_names == [domain_name]` (the provider adds `domain_name` to the SANs at plan time, as ACM does) | anything else, including any other SAN or an empty list. Verify: the §4.3 outcome table; writes `cert-requested.json` |
| 2b | adopt validation record (only for "present, same value, in neither ecsodus state" with `validation_record: import`, §4.3) | M5a | `check --phase import` | import of exactly that record, emitted by `generate --stage rebuild` | v0.1 import rule; a missing `validation_record` answer blocks generation |
| 3 | rebuild (create) | `infra-rebuild` | `check --phase rebuild` | creates of exactly the manifest addresses (from `generate --stage rebuild`), plus no-ops of exactly the addresses already in the `infra-rebuild` state (the 2a certificate); `desired_count = 0`; scalable target min = max = 0; validation record (if created) with the literal name and value and `allow_overwrite = false`; (no custom domain) the `new_host` alias A record with the manifest's name, type and ALB alias target and `allow_overwrite = false`; task definition `off` with the off value and `skip_destroy = true`. Live certificate `PENDING_VALIDATION` (or `ISSUED`) and younger than 72 h (§4.3) | any update, delete, replace or import; a no-op of any other address; a create outside the manifest (including `aws_ecs_task_definition.on`, §4.2); any other after-value on those attributes |
| 4 | created | — | `verify-cutover --step created` | — | live `runningCount`, `pendingCount` or `desiredCount` not 0; scalable target not 0/0; live task definition (`DescribeServices` → `DescribeTaskDefinition`, not Terraform's copy) lacks the background-off value or the pinned digest; certificate not `ISSUED`, not covering the host, or not on the listener; §4.5 checks |
| 5 | start | `infra-rebuild` | `check --phase start` | update `min_capacity`/`max_capacity` on the one scalable target to App Runner's `MinSize`/`MaxSize` | anything else |
| 6 | ready | — | `verify-cutover --step ready` | — | running < `MinSize` or ≠ desired; primary deployment not `COMPLETED` (`FAILED` from the circuit breaker fails); healthy targets < `MinSize` (never vacuous); listener rule not forwarding the host to the TG; TLS handshake with SNI = host fails or the cert does not match; GET on the declared safe path not the expected status; live task definition as in step 4 |
| 7a | convert to weighted | DNS, then M5a | `check --dns-batch`, then `check --phase import` | one atomic batch (§4.9); then imports of the two weighted records and, for exactly the simple record's manifest address (`removed` block), either a `forget` or a `no-op` with null before and after together with a `resource_drift` delete entry for that address (§4.9 step 5). After apply, `check --state` asserts the address is absent | batch: anything but DELETE of the exact live simple record + CREATE of the two expected weighted records. Import: v0.1 rule, plus a `forget`, null no-op or drift entry for any other address |
| 7b | shift | M5a | `verify-cutover --step shift`, then `check --phase cutover --step N` | update `weight` only to the manifest's next pair; a record whose weight the manifest pair leaves unchanged (the waypoint steps) appears as a `no-op`, and only then | §4.9 pair rules |
| 7c | simple switch (alternative to 7a–b) | M5a | `check --phase switch` | one in-place update of the simple record's `records` from `DNSTarget` to the ALB DNS name (reverse with `--rollback`) | a replace (it would change the record's identity in state); any change to `ttl`, `name`, `type`; anything else |
| 8a | register `on` revision (ECS) | `infra-rebuild` | `check --phase taskdef-on`, then `verify-cutover --step taskdef-on` | create of `aws_ecs_task_definition.on` only, whose `container_definitions`, compared as parsed JSON (the provider normalizes the string), equal `off`'s except the declared env var's on value; `skip_destroy = true`. The service does not reference it, so nothing runs it | anything else, including any change to the service. Verify: revision `ACTIVE`; live definition differs from the service's live one only in that env var; digest pinned; writes `taskdef-on.json` (ARN, family, revision) |
| 8b | worker-off (App Runner) | M5a | `check --phase worker-off`, then `verify-cutover --step worker-off` | one in-place update of `aws_apprunner_service` changing only the declared env var to its off value | anything else. Verify: latest `UPDATE_SERVICE` operation `SUCCEEDED` (`ROLLBACK_SUCCEEDED` fails) and started after the plan; status `RUNNING`; live env var off; idle evidence (§4.10) |
| 8c | worker-on (ECS) | `infra-rebuild` | `check --phase worker-on`, then `verify-cutover --step worker-on` | update of `aws_ecs_service.task_definition` only, from the exact live `off` ARN to the literal `on` ARN from `taskdef-on.json` (emitted by `generate --stage worker-on`) | anything else, including an unknown `task_definition`. Verify: deployment `COMPLETED`; live task definition is the `on` ARN |
| 9 | window | — | `ecsodus retire-evidence` (read-only, §5.2) | — | the default runbook ends here |
| 8a′ | register off twin (rollback after hand-over only, §4.11) | `infra-rebuild` | `verify-cutover --step live-revision`, `check --phase taskdef-off`, then `verify-cutover --step taskdef-off` | create of `aws_ecs_task_definition.off_live` only, whose parsed `container_definitions` equal those of the live revision bound in `live-revision.json` except the declared env var's off value; `skip_destroy = true`. The service does not reference it | anything else; a binding to any ARN other than the service's live revision. Verify: revision `ACTIVE`; differs from the live revision only in that env var; digest pinned; writes `taskdef-off.json` |
| R | rollback | both | §4.11 | | |
| — | hand-over | `infra-rebuild` | `check --phase steady` after adding `ignore_changes = [task_definition]` | none | any change |

8a runs **before** 8b, so App Runner workers are never turned off while the ECS side still
depends on an unapplied or unknown revision. If 8a or its verification fails, App Runner is
untouched.

### 4.9 DNS cutover

**Pre-flight facts.** Copilot's handler writes the domain CNAME with TTL 60, so `prepare` is
normally a no-op for TTL. If it was raised, `prepare` lowers it and the runbook waits the old TTL.

**Simple record → weighted pair: one atomic batch (7a).** A simple CNAME and weighted CNAMEs of
the same name cannot coexist, and Terraform would delete and create in separate calls, leaving a
window where the name does not resolve. `generate` writes `dns/convert.json`: `DELETE` the simple
record (exact live value and TTL), `CREATE` weighted `apprunner` (weight 100, `DNSTarget`) and
`ecs` (weight 0, ALB DNS name), TTL 60. Batches are transactional.
1. `terraform state pull > pre-convert.tfstate`.
2. `check --dns-batch` compares the batch with live `ListResourceRecordSets`.
3. Apply the batch; `aws route53 wait resource-record-sets-changed --id <change-id>` (INSYNC).
4. **No Terraform apply in the M5a root until step 5 passes.** State still holds the simple
   record; an apply would try to recreate it (Route 53 would refuse, but the runbook forbids it).
5. Swap in `infra-patches/convert.tf`: a `removed { from = <simple record>; lifecycle { destroy = false } }`
   block and import blocks for the two weighted records, IDs `ZONEID_NAME_CNAME_SETID`. Plan →
   `check --phase import --forgotten <simple-record address>` → apply. One plan, so state never
   holds neither or both. Today `src/ecsodus/check/plan.py` accepts `forget` only in the steady
   phase and only for `aws_ecs_task_definition`; M5b **extends the import phase** to accept a
   `forget` of exactly the addresses the manifest names for this step (and for its rollback,
   §4.11), alongside the imports. Any other `forget` fails. (Splitting it into an import plan and
   a later steady plan was rejected: between the two, state would hold the simple record and the
   weighted pair at once.)

   **A refreshed plan shows no `forget`.** After the batch, the refresh of the simple record
   looks it up by name, type and set identifier; `""` does not match `apprunner`, so the provider
   finds nothing and clears the ID, and Terraform plans a `no-op` with null before and after
   instead of a `forget` (provider `internal/service/route53/record.go`; Terraform `planForget`).
   The same holds for the two weighted records in the reverse conversion. The extended import
   gate therefore accepts, for exactly the manifest-named addresses, either a `forget` (the
   `-refresh=false` case, for which the `removed` block stays) or a `no-op` with null before and
   after together with a `resource_drift` entry showing that address deleted. `--forgotten`
   coverage stays exact: every named address must show one of the two forms, and no other address
   may. After apply, `check --state` asserts every named address is absent from state.

**Recovery.** If the run stops between steps 3 and 5, `verify-cutover --step converted` sees the
live weighted pair, and the runbook resumes at step 5. From then on `generate` emits only the
converted config; the old simple-record block is never applied again unless rolling back
(§4.11), which re-adds and imports it.

Both targets are CNAMEs. A weighted pair of alias A records (App Runner supports Route 53 alias
targets for services created after 2022-08-01) is also valid and has no TTL. 0.4.0 offers only
the CNAME pair, so one path is tested; alias A is a candidate later.

**Weight-pair rules (7b).** Route 53 treats a set whose weights are all 0 as equal weights, so
(0, 0) sends about half the traffic to each side. Terraform updates the two records in separate
calls, so a plan from (a, b) to (a′, b′) can pass through (a′, b) or (a, b′). `check --phase
cutover` accepts a plan only if:
- both weighted addresses are in the plan, `name`, `type`, `set_identifier`, `records` and `ttl`
  are unchanged on both, and only `weight` changes. A record whose weight the manifest pair leaves
  unchanged (the waypoint steps (0, 100) → (100, 100) and (100, 100) → (100, 0)) appears as a
  manifest-bound `no-op`; a `no-op` on a record whose weight the pair changes fails;
- the before pair equals the live pair (read during the check) and the after pair is the
  manifest's next pair, or with `--rollback` the next pair on the rollback path the manifest lists
  for the before pair;
- none of (a′, b′), (a′, b), (a, b′) is (0, 0).

The default sequence (`apprunner`, `ecs`) is (100, 0) → (90, 10) → (50, 50) → (10, 90) →
(0, 100); every step satisfies the last rule. The manifest lists the rollback path from each
pair explicitly: from (90, 10), (50, 50) or (10, 90), one plan to (100, 0); from (0, 100), two
plans through the waypoint (100, 100), then (100, 0). A direct (0, 100) → (100, 0) could pass
through (0, 0), so it is not listed and fails. Before each step, `verify-cutover --step shift`: live weights equal the expected
pair, targets healthy, the ALB 5xx alarm and the App Runner 5xx alarm `OK` (`ALARM` or
`INSUFFICIENT_DATA` fails), and the runbook waits one TTL after the previous step. DNS weights
are not exact percentages and resolvers cache; the runbook says so.

**Provider behaviour (from the provider source, `internal/service/route53/record.go`).** An
update that keeps `name`, `type` and `set_identifier` is sent as one `UPSERT`; a change of type
or set identifier is sent as `DELETE` + `CREATE` in one transactional batch. Create and update
both wait for `INSYNC`. So each weight step and the 7c switch is atomic per record and
INSYNC-waited. The support matrix pins the provider version, and an offline test asserts this
behaviour at that version.

**Simple switch (7c).** For low-traffic services: one in-place `records` update, sent as an
`UPSERT`. The gate still rejects a replace, because a replace changes the record's identity in
state, not because of a resolution gap. No gradual shift.

**No custom domain.** No DNS cutover is possible. The custom-domain checks of steps 1, 7 and
§4.11 do not apply. The certificate (2a–2b) needs a hostname: the operator declares a new one in
`decisions.yml` (`new_host`), or generation blocks. Its zone must pass the §3.2 zone rules
(exact name, public, delegated, same account) and the CAA check; the adoption rule (a CNAME to
`DNSTarget`) cannot apply to a new name. `pre-create` requires that no record of any type exists
at `new_host`.
- **Traffic record.** `infra-rebuild` creates `new_host` as an alias A record to the ALB in step
  3, with `allow_overwrite = false` (the provider then sends `CREATE`, which fails if a record
  appears meanwhile), gated on name, type and alias target. Its owner is the `infra-rebuild`
  root; `ready` checks TLS with SNI = `new_host` and the safe-path probe through that name.
- **Clients.** The runbook is "start ECS, give clients the new URL", and the retirement evidence
  (§5.2) is the only measure of what still reaches App Runner.
- **Rollback.** The rollback destroy deletes the `new_host` record with the ALB, so clients
  already given the new URL lose it. `verify-cutover --step rolled-back` prints the ALB's
  `RequestCount` since step 5 and requires an explicit operator answer before the destroy
  proceeds.

### 4.10 Background work and side effects

Both sides run the same image against the same databases, queues and topics.

- **Declaration.** `decisions.yml` must answer, per service, the [PLAN.md](PLAN.md) §2.3
  question: "does this container run background work or migrations on boot?" Answers:
  - `none`;
  - `switch`: the env var name, its off and on values, and a statement that the switch also
    stops boot-time migrations. Plus one of `lock: <how the app holds a distributed lock>` or
    `idle-check: <command that exits 0 only when no job is in flight>`.
  Migrations that run on boot outside the switch are **blocked**: every App Runner configuration
  deployment (including `worker-off`) reboots instances and would rerun them.
- **Start off.** The ECS task definition carries the off value from the first apply. Step 4
  verifies it on the live task definition before any task can start.
- **Transfer (steps 8a–8c), App Runner side first.** Register and verify the ECS `on` revision
  (8a, nothing runs it). Then turn work off on App Runner (8b), wait for the operation to reach
  `SUCCEEDED`, run the idle check (or confirm the lock), then point the ECS service at the known
  `on` ARN (8c).
- **Rollback, reverse order.** Reverse 8c: `check --phase worker-on --rollback` updates
  `task_definition` only, from the live `on` ARN back to the literal `off` ARN (still `ACTIVE`,
  `skip_destroy`); deployment `COMPLETED`, idle check. After hand-over the source is the live
  revision and the target is its off twin from `taskdef-off.json` (§4.8 #8a′, §4.11). Then reverse 8b: `check --phase worker-off
  --rollback` sets the env var to its on value on App Runner; operation `SUCCEEDED`
  (`ROLLBACK_SUCCEEDED` fails). 8a needs no reverse: the `on` revision stays registered, unused,
  until the rollback destroy.
- **Migrations** must be backward compatible for the whole window.
- **HTTP is not side-effect free.** Verification uses only the declared safe path.
- **SNS publish.** Both sides may publish during the window. Consumers must be idempotent; the
  report lists the topics the instance role can publish to.

`worker-off` is a Terraform change, not an out-of-band `update-service`, so it leaves no drift.
Its in-place update sends the full source configuration from state; the deploy freeze keeps that
equal to live, and `verify-handoff` check 4 proved the image identifier in state is the live one.

### 4.11 Rollback

Rollback has its own phase, `rollback-rebuild`, and its own order. It is allowed at any point
before retirement.

| From | Steps |
|---|---|
| Before 7a | destroy `infra-rebuild` (below). App Runner untouched |
| During 7b | `check --phase cutover --rollback` back to (100, 0), as two plans if needed (§4.9) |
| After hand-over (§4.12 step 11) | first restore the migration's controls, before any worker change: re-freeze deploys to App Runner and ECS; refresh both states; remove `ignore_changes = [task_definition]` and set the service's literal `task_definition` to the live ARN (the plan must be empty, `check --phase steady`), so Terraform owns deployment again. Then `verify-cutover --step live-revision` writes `live-revision.json` (the service's live revision ARN, its digest, account, region, service ARN, manifest hash), so the fresh rollback manifest and evidence are bound to that revision before any worker mutation. If the live revision is `on`, the target is the existing `off`. Otherwise `generate --stage taskdef-off --evidence live-revision.json` emits `aws_ecs_task_definition.off_live`, the off twin of the live revision, registered through the `taskdef-off` gate (§4.8 #8a′) and recorded in `taskdef-off.json`; it becomes the target of the reverse 8c. Then continue with the rows below |
| After 8a–8c | reverse background work first (§4.10), then the weights |
| Weighted pair at (100, 0) | `check --dns-batch --rollback` on `dns/revert.json` (DELETE both weighted records with their live values, CREATE the simple record to `DNSTarget`), wait INSYNC, then `removed` blocks for the weighted records and an import of the simple record in one plan (`check --phase import --forgotten` the two weighted addresses, §4.9) |
| After 7c | `check --phase switch --rollback` |
| DNS back on App Runner only (or before 7a) | plan the `infra-rebuild-rollback/` config → `check --phase rollback-rebuild` → apply. Then optionally `prepare --rollback` to remove `ecs-tasks.amazonaws.com` from the instance role's trust |

**The rollback destroy keeps the logs and the validation record.** `generate` writes
`infra-rebuild-rollback/`: the same backend and state, no resource blocks, and `removed { from =
<address>; lifecycle { destroy = false } }` for the log group and, in the "absent" outcome
(§4.3), for the validation record `infra-rebuild` created. Its ordinary plan deletes every other
address and forgets those two, so the ECS logs stay for forensics and the validation CNAME stays
in place: ACM reuses it for any later certificate on that FQDN in the account, and deleting it
would stop renewal of every certificate that uses it. The report lists the forgotten record as
unowned. The two task-definition revisions plan as deletes, but
`skip_destroy` (read from state) leaves them registered; the report lists them for manual
deregistration.

`check --phase rollback-rebuild` allows only: deletes of **exactly** the addresses in the
`infra-rebuild` state except the log group and the created validation record, each of which must
be a manifest address (the state may hold only the certificate from 2a, or everything), and
`forget` of exactly those two where they are in state. Nothing else; a plan that deletes the
validation record fails. It runs `verify-cutover --step rolled-back` first: background work is on in App Runner and
off in ECS (or never transferred), and, with a custom domain, the live record is the simple CNAME
to `DNSTarget`. With no custom domain, it prints the ALB's `RequestCount` since step 5 and
requires an explicit operator answer (§4.9). A validation record shared with App Runner's
certificate is in the M5a root, so the destroy cannot touch it.

### 4.12 Runbook outline (0.4.0 default)

1. **Freeze** deploys to App Runner and ECS (record the deploy owner; auto-deploy off).
2. **Hand-off proof** `verify-handoff`; image is a digest or a synchronized deployment is done
   (§4.1).
3. **Pre-flight** `verify-cutover --step pre-create` (includes the validation-record predictor).
4. **Prepare** plan → `check --phase prepare` → apply; wait the old TTL if it changed. Shared ALB
   only: `prepare-alb` in the ALB's root, same gate.
5. **Certificate request** (2a) plan → `check --phase cert-request` → apply; `verify-cutover
   --step cert-requested`; `generate --stage rebuild` (it emits the 2b import as well); then 2b
   if needed. The 72-hour validation window starts at 2a (§4.3).
6. **Create** plan → `check --phase rebuild` → apply, within 72 h of 2a. Then `verify-cutover
   --step created`. If the certificate timed out: rollback destroy (§4.11), then step 5 again.
7. **Start** plan → `check --phase start` → apply. Then `verify-cutover --step ready`.
8. **Cut over**: 7a and 7b in steps, or 7c.
9. **Transfer background work**, if declared: copy `rebuild/staged/taskdef-on.tf` into
   `rebuild/infra-rebuild/` (§4.2), 8a, `generate --stage worker-on`, 8b, 8c (§4.10).
10. **Window**: TTL + 24 h at least, operator may extend. Rollback stays possible (§4.11).
11. **Hand-over**: `ignore_changes = [task_definition]`, CI named as the ECS deploy owner, freeze
    lifted.
12. **End.** The runbook ends with App Runner still running at weight 0. Its last section, "Before
    you retire App Runner", shows the `retire-evidence` output (§5.2) and the never-delete list
    (§5.3), and states that ecsodus 0.4.0 does not generate retirement.

## 5. M5c: retirement (separate artifact, unavailable until verified)

### 5.1 Position

Retirement is the first destructive step ecsodus would ever write; v0.1 never deletes anything
([PLAN.md](PLAN.md) §2.2). The reviewers differed in strength: keep it unavailable until real
testing (gpt-6-astra), ship it behind an acknowledgement flag (Opus), or ship it as an opt-in
section marked UNVERIFIED (Fable). This plan takes the most conservative position all three can
accept:

- It is **not** in the default 0.4.0 runbook.
- It is a separate artifact, `generate --retire`, with its own manifest, runbook and ADR
  (ADR-0023).
- Until a run on real App Runner is recorded in `docs/e2e/`, `generate --retire` **refuses**. No
  flag unlocks it; an acknowledgement does not validate an irreversible step. The ADR-0012
  precedent applied *after* a real run, not instead of one.
- Deleting the last App Runner service may end the account's "existing customer" status
  (**UNCONFIRMED**: AWS does not define the term). The retirement runbook says this first.
- In any eligible or borrowed test account, one sentinel App Runner service is kept until testing
  is finished.

### 5.2 Evidence (`ecsodus retire-evidence`, read-only, ships in 0.4.0 as advisory)

The evidence does not rely on the operator's word for timing. It writes `retire-evidence.json`
bound to the service ARN, account, region, the hash of the live weighted record set, the
observation interval and (for `--retire`) the SHA-256 of the saved retire plan.

1. **Weight 0 since when.** CloudTrail `LookupEvents` in us-east-1 (Route 53 is global).
   `LookupEvents` takes one lookup attribute and allows 2 requests per second per account and
   region, so ecsodus looks up `EventName = ChangeResourceRecordSets` over the window, paginates
   with backoff, and matches the zone ID, record name and `apprunner` set identifier client-side
   from each event's `CloudTrailEvent` JSON. A change touches the set as an `UPSERT` or as a
   `DELETE` + `CREATE` pair in one batch; both are parsed. Find the latest event touching the set;
   it must set weight 0. Take its change ID from the response and confirm `GetChange` is
   `INSYNC`; `GetChange` documents no retention period, and `NoSuchChange` fails closed. Now minus
   the event time must be ≥ TTL + 24 h (or the operator's longer window). Fail closed if no event
   is found within the 90-day history, if a later event touched the set, or if live
   `ListResourceRecordSets` disagrees.
   Simple switch: the same, for the UPSERT that set the ALB value. No custom domain: no DNS
   evidence; the metric and log evidence stand alone, and the report says so.
2. **Residual traffic.** `Requests` is service-wide with no per-host dimension, and
   `*.awsapprunner.com` is scanned continuously, so it never reaches zero. The gate uses
   `2xxStatusResponses`, `Sum`, 5-minute periods, dimensions `ServiceName` and `ServiceID`, from
   the weight-0 event plus one TTL to now minus 15 minutes (late data), via paginated
   `GetMetricData`. The total must be ≤ an operator threshold (decision, no default), and the
   hourly series is printed. A period with no datapoint counts as **unsafe** unless the
   service-level `ActiveInstances` series has a datapoint for it, in which case it counts as
   zero (**UNCONFIRMED**: how App Runner publishes metrics at zero traffic, and whether its health
   checks count, are settled only by a real run). A service ID change (redeploy as a new service)
   resets the window.
3. **Host sample.** The operator samples the App Runner application log group for `Host` values
   during the window (query given in the runbook) and records the result in the evidence file.
   This is attestation, and the file says so. It cannot attribute traffic to the default URL by
   itself.

Missing IAM permission, `INSUFFICIENT_DATA`, a throttled call or a truncated result fails closed.

### 5.3 Retire set and never-delete list

**Deleted (only):** the App Runner service, its custom-domain association, and the `apprunner`
weighted record. `prevent_destroy` comes off these three in a reviewed edit that `generate
--retire` writes as a separate file.

**Forgotten, never deleted** (`removed { lifecycle { destroy = false } }`, then listed for manual
review): VPC connector (it can serve other services), access role, App Runner validation CNAMEs,
App Runner log groups.

**Never touched:** the instance role (now the ECS task role), `ServiceSecurityGroup` and its env
ingress rule, the env `AppRunnerVpcEndpoint` and its SG, auto-scaling and observability
configurations (`external-reference`), any `aws_route53_record` whose name matches a validation
option of any certificate in either state.

### 5.4 Gate

`check --phase retire` requires a fresh (< 1 h) `retire-evidence.json` whose bindings match the
saved plan and live state, and allows only deletes of exactly the three addresses above plus
`forget` of the listed ones. Anything else fails. Afterwards `check --phase steady` on both roots.

## 6. Scope

**M5a (0.3.0, in):** Copilot RDWS with image source (ECR or ECR Public), public ingress,
`DEFAULT` or `VPC` egress, custom domain (zone in the same account), private ingress (import
only), tracing (external reference), the env App Runner VPC endpoint, addons.

**M5b (0.4.0, in):** rebuild of App Runner image services whose Copilot hand-off is proven
complete, with public ingress, into plain ECS + dedicated ALB (shared ALB opt-in); weighted or
simple DNS cutover; rollback; `retire-evidence` (advisory). Read-only `inventory`/`report` for
standalone App Runner services.

**Detected and `blocked`:** source-code services; private ingress (rebuild); tracing without
`accept-loss` (rebuild); a tagged image with no synchronized deployment (rebuild); boot
migrations outside the switch; a validation record with a conflicting value; an extra connector
SG with no `env_sg` answer; a matching validation record in neither ecsodus state with no
`validation_record` answer; no custom domain and no `new_host`, or a record already at
`new_host`; dual-stack without IPv6; WAF ACL not discoverable, or conflicting
on a shared ALB; root zone in another account; a Copilot workload left in the env; any unknown
field; `--target express`; `generate --retire`.

**Non-goals:** generating for standalone App Runner services; Dockerfile generation; App Runner
→ Lambda or EKS; choosing scaling targets; moving the default URL or `www.<alias>`; shifting
traffic from inside ecsodus.

## 7. Architecture

- `sources/apprunner.py`: live reads, shared by the Copilot path and the standalone report.
- `model.py`: an `AppRunnerServiceSpec` with provenance on every field, independent of the stack.
- `mappers/tf_apprunner.py`: M5a imports and the §3.3 defaults.
- `mappers/rebuild.py`: the §4.4 table, one rule per row, blocking on missing decisions.
- `emit/terraform`: `infra-rebuild` root, `infra-patches`, DNS batch files, per-phase manifest.
- `emit/runbook`: rebuild branch; retire branch behind the refusal (§5.1).
- `check/plan.py`: the §4.8 phases and `--dns-batch`. `--forgotten` today accepts only
  `aws_ecs_task_definition`, and `forget` only in the steady phase. It is extended so that the
  import phase accepts, for exactly the record addresses the manifest names for 7a and its
  rollback (§4.9), a `forget` or a null-before/after `no-op` with a matching `resource_drift`
  delete entry, and `rollback-rebuild` a `forget` of the log group and the created validation
  record (§4.11). The exact coverage check stays: every `--forgotten` address must show one of
  the accepted forms, and no other address may. `check --state` gains an absence assertion for
  those addresses after apply. The no-data-source rule stays.
- `cli.py`: the `--forgotten` validation there (today "not an imported task definition in the
  manifest") is extended in step with `check/plan.py`, so it accepts exactly the addresses the
  manifest names for the current phase and step, and nothing else.
- `generate --stage rebuild | worker-on | taskdef-off --evidence <file>`: staged generation
  (§4.2). It checks the evidence file's bindings (account, region, ARN, manifest hash) before
  emitting; `rebuild` also checks the certificate's status and age (§4.3).
- `verify-handoff`, `verify-cutover`, `retire-evidence`: read-only. Their IAM actions, listed in
  the runbook: `cloudformation:DescribeStacks`, `ListStacks`; `apprunner:DescribeService`,
  `ListOperations`, `DescribeCustomDomains`, `ListServices`; `ecs:DescribeServices`,
  `DescribeTaskDefinition`; `application-autoscaling:DescribeScalableTargets`;
  `elasticloadbalancing:Describe*`; `acm:DescribeCertificate`, `ListCertificates`;
  `route53:ListResourceRecordSets`, `GetHostedZone`, `ListHostedZonesByName`, `GetChange`;
  `cloudwatch:DescribeAlarms`, `GetMetricData`; `cloudtrail:LookupEvents`;
  `ec2:DescribeRouteTables`, `DescribeNatGateways`, `DescribeVpcEndpoints`, `DescribeVpcAttribute`,
  `DescribeSecurityGroupRules`; `ecr:DescribeImages`, `BatchGetImage`; `ecr-public:DescribeImages`;
  `iam:SimulatePrincipalPolicy`, `GetRole`; `wafv2:GetWebACLForResource`; `sts:GetCallerIdentity`.
  Any denial fails closed.
- Support matrix: pin the provider version used for the App Runner and Route 53 behaviours above;
  bounded as in v0.1.

## 8. Validation (offline)

- **Golden fixtures** from the archived Copilot source: RDWS plain (have), with `alias`, private,
  with tracing, with addons, with and without `placement: private`. M5a.0 renders them.
- **moto has no App Runner backend** and no Express gateway (moto 5.2.3). botocore 1.43.105
  ships the `apprunner` model (37 operations). Plan: botocore `Stubber` with synthetic responses
  validated against that model.
- **moto covers the rest:** ECS, ELBv2, Route 53, ACM, IAM, EC2, CloudWatch, CloudTrail.
  `terraform plan` against a local moto server for the `infra-rebuild` creates and the weighted
  records, the same moto approach that produced the worker and job evidence in ADR-0014 and
  ADR-0015 (those ADRs record that evidence, not a moto architecture decision).
- **`terraform validate`** on every generated variant against the pinned provider schema.
- **check tests**, synthetic plans per phase. Must fail: a weight change plus one stray attribute;
  each (0, 0) path, including (100, 0) → (0, 100) in one plan; a wrong-direction step without
  `--rollback`; a `ttl` or `set_identifier` change; a scalable target created above 0; a `start`
  plan that touches anything but min/max; a `switch` plan that replaces; a `worker-on` plan that
  changes a second env var; a rollback destroy with one address missing or one extra; a retire
  plan that deletes a validation record; an import plan that replaces `aws_apprunner_service`;
  a `cert-request` plan that creates anything besides the certificate; a validation record with
  `allow_overwrite = true` or a name/value other than `cert-requested.json`; a `taskdef-on` plan
  that touches the service; a `worker-on` plan with an unknown `task_definition` or an ARN other
  than `taskdef-on.json`; an import-phase `forget` of an address the manifest does not name; a
  rollback from (0, 100) straight to (100, 0); a rollback-rebuild plan that deletes the log group;
  a rollback-rebuild plan that deletes the created validation record; a `cert-request` plan whose
  `subject_alternative_names` is anything but `[domain_name]`; a `rebuild` plan with a no-op of an
  address not already in the `infra-rebuild` state; a `rebuild` plan that contains
  `aws_ecs_task_definition.on`; a `rebuild` gate run against a certificate that is
  `VALIDATION_TIMED_OUT` or older than 72 h; a `new_host` record with `allow_overwrite = true` or
  another name, type or alias target; a `pre-create` with any record already at `new_host`; a 7a
  import plan with a null no-op but no matching `resource_drift` delete, or with either form on
  an address the manifest does not name; a `check --state` after 7a that still lists the simple
  record; a waypoint plan with a no-op on the record whose weight the pair changes; a
  `taskdef-off` plan bound to an ARN other than the live revision, or differing from it in a
  second env var; a 2b import with no `validation_record: import` answer; a `--forgotten` address
  that `cli.py` accepts but the manifest does not name. Must pass: `cert-request` with
  `subject_alternative_names == [domain_name]`; a 7a import plan in the refreshed form (null
  no-op plus drift) and in the `-refresh=false` form (`forget`); the two waypoint plans; a
  `taskdef-on` plan whose `container_definitions` differ from `off` only in key order and the
  env var.
- **Rollback config:** `infra-rebuild-rollback/` plans cleanly (its `removed` blocks included)
  when only the 2a certificate is in state, and when everything is.
- **Stand-in checks:** `RegisterScalableTarget` with `MinCapacity = 0`, `MaxCapacity = 0` for an
  ECS service (moto, then the stand-in run in §9), and the provider's `UPSERT`/INSYNC behaviour
  at the pinned version.
- **Evidence tests:** recorded CloudTrail and metric responses for: no event, a later event,
  missing datapoints with and without `ActiveInstances`, pagination, throttling.
- **Translation tests:** each "decision required" row blocks without its key.
- **Runbook under shell stubs:** a failed gate stops the mutation (existing harness).

## 9. Real AWS end-to-end, and the eligibility risk

**Key risk: our sandbox account probably cannot create an App Runner service.** It never ran App
Runner before 2026-04-30. If so, M5a cannot be tested with a real Copilot RDWS there, and the App
Runner side of M5b (association behaviour, `worker-off`, metrics) cannot either.

**Eligibility probe (M5a.0, maintainer decision, cost ~$0).** Only a real `create-service`
attempt is decisive: `public.ecr.aws/aws-containers/hello-app-runner:latest`, 0.25 vCPU, then
`delete-service` at once. `create-auto-scaling-configuration` might succeed for an ineligible
account and prove nothing. Which call the closure blocks is **UNCONFIRMED**; the probe records the
error code.

**If eligible:** M5a e2e with the archived Copilot v1.34.1: app with `--domain`, env with private
placement (NAT), RDWS with `alias`, a DynamoDB addon with sentinel data. Assert the service URL,
the custom domain, the CNAMEs, the NAT gateways and the sentinel data survive. Then M5b on the
adopted service through cutover and rollback. A second, sentinel App Runner service stays until
the end, so the account keeps its status even when M5c retirement is exercised.

**If not eligible, in order of preference:**
1. **A design partner's account with an existing RDWS.** Inventory, report, generate and an
   import `terraform plan` (read-only). This validates the M5a mapping, not the hand-off; it is
   labelled "plan validation", never "e2e". Their apply is their decision.
2. **An older account the maintainer controls** that used App Runner before 2026-04-30.
3. **Sandbox stand-in** for M5b mechanics: a second ALB behind a CNAME as the "source", to
   exercise the atomic batch, weight pairs, gates, scale-to-zero and rollback. App Runner reads
   come from recorded responses.

**Release bars.**
- **0.3.0:** a real import-only plan of an RDWS (eligible account or design partner) is required.
  Without one, RDWS hand-off ships behind an UNVERIFIED banner and flag, because the
  provider-default class of bugs (§3.3) shows only against a live plan.
- **0.4.0:** the rebuild through cutover and rollback runs on real AWS (eligible account or the
  stand-in). App Runner-side steps not run for real (`worker-off`, association reads) are marked
  UNVERIFIED in the runbook.
- **M5c:** unavailable until a real App Runner retirement is recorded (§5.1).

**A real domain is needed** for ACM DNS validation and the custom-domain path. The v0.1 e2e never
covered one (issue #6). See §13.

**Cost estimate (eligible case, one 4-hour run, us-east-1)** **(UNCONFIRMED: current prices)**:

| Item | Estimate |
|---|---|
| App Runner 1 instance, 0.25 vCPU / 0.5 GB, mostly idle (×2 with the sentinel) | < $0.20 |
| NAT gateways ×2, 4 h + data | ~$0.40 |
| ALB 4 h + LCU | ~$0.10 |
| Fargate 0.25 vCPU / 0.5 GB, 1–2 tasks, 2 h | < $0.05 |
| Public IPv4 addresses | ~$0.10 |
| Route 53 hosted zone (free if deleted within 12 h) | $0 |
| Domain, if one must be registered | ~$3–15 / year |
| **Total** | **~$1–3**, plus any domain |

Every artifact is cleaned up afterwards, as in the 2026-10-07 run.

## 10. Milestones

| # | Deliverable |
|---|---|
| M5a.0 | Maintainer decisions (§13); RDWS fixtures; knowledge-base rows incl. §3.3 defaults; ADRs 0017–0025 |
| M5a.1 | M5a mappers and out-of-band reads; report and generate; offline suite |
| M5a.2 | M5a real plan or e2e (§9) → release 0.3.0 |
| M5b.1 | `verify-handoff`, rebuild inventory and report, `decisions.yml`; standalone read-only report |
| M5b.2 | Rebuild generate, §4.8 phases, `--dns-batch`, `verify-cutover`, `retire-evidence`, runbook; offline suite |
| M5b.3 | Rebuild e2e through cutover and rollback (§9) → release 0.4.0 |
| M5c | Retirement artifact, after a real App Runner run; Express unlock after its three gaps close (§4.6) |

## 11. Risks

- **No App Runner-capable test account** (§9). Highest risk. Mitigation: probe; design partner;
  stand-in source; release bars; retirement unavailable.
- **Wrong translation causes an outage after cutover.** Mitigation: no guessed values, decisions
  file, scale-to-zero, `ready` step, gated weight pairs, rollback phase.
- **Double-running side effects.** Mitigation: required declaration, off at start, App Runner
  off before ECS on, idle check or lock, blocked boot migrations.
- **DNS gap or split traffic.** Mitigation: one atomic batch, pair rules (no (0, 0) path), INSYNC
  waits, recovery path.
- **Copilot still acting.** Mitigation: `verify-handoff`; blocked if any Copilot workload remains
  in the env.
- **Grants that name the instance role.** Mitigation: the role is reused as the task role; the
  execution role's secret access is simulated and then proven by the task start.
- **Losing App Runner for the account.** Mitigation: retirement unavailable in 0.4.0; sentinel
  service in test accounts; the retirement runbook warns first.
- **App Runner deprecated further.** M5a then becomes a waypoint; M5b is the exit.
- **Small audience.** RDWS is one of five Copilot workload types. The read-only report measures
  demand before more is built.

## 12. Decisions on the round-1 open questions

Council consensus unless noted.

| # | Question | Decision |
|---|---|---|
| 1 | Release numbering | 0.3.0 (M5a) and 0.4.0 (M5b); the scope is "M5", milestones M5a/M5b/M5c; "v0.2" is no longer used for it |
| 2 | Standalone App Runner | report-only in 0.4.0. If generation comes later, it stops at cutover (no owner, no retirement) |
| 3 | Still-Copilot RDWS | no; M5a first, and `verify-handoff` proves it (§4.1) |
| 4 | Target and ALB | plain ECS + **dedicated** ALB by default. Shared ALB opt-in with a bounded `prepare` (§4.7). Express opt-in but failing closed in 0.4.0 (§4.6) |
| 5 | Modules | flat resources |
| 6 | Auto-scaling configuration | `external-reference`, always; never imported in M5a, never in a delete set. An `--adopt-shared` import may come later |
| 7 | Private ingress | blocked in rebuild; manual path documented |
| 8 | Tracing | allowed with `tracing: accept-loss` and a report banner |
| 9 | Eligible account | open (§13) |
| 10 | e2e domain | open (§13) |
| 11 | Retirement | not in the default runbook; separate `generate --retire` artifact, refused until verified (§5.1) |
| 12 | Metrics and alarms | yes, read-only, with the IAM actions listed (§7). Alarms and target health are hard gates; any unavailable or ambiguous evidence fails closed; the operator's safe-path probe stays mandatory |
| 13 | `StartCommand` | always the operator's list; `["sh","-c", …]` only as an explicit, confirmed value (§4.4) |

## 13. Open for the maintainer

1. **An eligible App Runner account.** Do you control an account that ran App Runner before
   2026-04-30 (check the console for existing services or a working Create button)? If not, the
   design-partner path in §9 applies.
2. **The e2e domain.** You do not own a domain today. The reviewers' advice: register one cheap
   domain dedicated to ecsodus e2e (~$3–15 a year through Route 53 Domains, kept year to year),
   never a personal or production domain; it also closes v0.1 issue #6. Registration is billable
   and needs your yes.
3. **The eligibility probe.** Run the `create-service` / `delete-service` probe (§9) in the
   sandbox? It is a mutation with near-zero cost and needs your explicit yes.

## 14. Draft ADR outlines (not yet files)

ADR-0016 is the hatchling build backend, on branch `build-hatchling` (PR #26); `docs/adr/` on
`main` ends at 0015. M5 ADRs start at 0017. If PR #26 has not merged when M5a.0 writes them, the
build checks again and renumbers.

- **ADR-0017: Copilot RDWS hands off in adopt-in-place.** `AWS::AppRunner::Service`,
  `VpcConnector` and `VpcIngressConnection` import; the association, domain CNAME and validation
  CNAMEs import as out-of-band objects from an exact-name public zone in the same account.
  Auto-scaling and observability configurations are external references. Provider defaults that
  differ are emitted explicitly. `prevent_destroy` on service, association and domain CNAME. CI
  is the named deploy owner. Source-code services stay blocked.
- **ADR-0018: Rebuild starts only from a proven hand-off.** `verify-handoff` proves every hand-off
  stack is gone, no Copilot workload remains in the env, and Terraform owns the service. No
  still-Copilot path.
- **ADR-0019: Rebuild target is plain ECS behind a dedicated ALB, in its own root and state.**
  Shared ALB is an opt-in with a bounded `prepare`. Express is opt-in and fails closed until its
  start interlock, HTTP listener and ownership gaps close. The instance role is reused as the task
  role. Flat resources.
- **ADR-0020: Rebuild values come from live reads or an operator decisions file, never guesses.**
  Includes the deployed digest (block on a tag without a synchronized deployment), start command,
  health checks, scaling target, timeout, egress, tracing loss and background work.
- **ADR-0021: Rebuild is a sequence of gated transitions with exact allowed changes.** Prepare,
  certificate request, create at zero capacity, start, ready, convert, shift or switch, register
  the `on` revision, worker-off, worker-on, hand-over; values computed at apply time reach later
  gates only as literals through staged generation (including the off twin of a live revision
  for a rollback after hand-over); rollback is its own phase that destroys only the rebuild root
  and keeps its logs and any validation record it created.
- **ADR-0022: Cutover by an atomic Route 53 batch, then gated weight pairs.** No (0, 0) state on
  any path; exact before/after pairs; INSYNC waits; documented recovery. The default URL and
  `www.<alias>` cannot move. Without a custom domain, a gated `new_host` alias record is created
  instead, and there is no cutover.
- **ADR-0023: Retirement is a separate artifact, unavailable until verified on real App Runner.**
  Evidence from CloudTrail, `GetChange`, `2xxStatusResponses` with fail-closed missing-data rules
  and an attested host sample, bound to the service, account, region and plan. Deletes only the
  service, association and `apprunner` record; never anything that may be shared.
- **ADR-0024: Standalone App Runner services are report-only in M5.** Shared source adapter and
  model; any later generation stops at cutover.
- **ADR-0025: Testing App Runner without an eligible account.** botocore `Stubber` offline;
  `create-service` eligibility probe with approval; design-partner plans labelled as plan
  validation; a stand-in source for cutover mechanics; release bars per milestone.

## 15. Round-1 findings and where they are addressed

### P1s

| Reviewer, # | Finding | Where | How |
|---|---|---|---|
| Astra 1 | "Terraform-owned" is not proof Copilot is gone | §4.1, §4.8 #0, ADR-0018 | `verify-handoff`: stacks gone, no Copilot workload in the env, state and live identity, fresh plan; record re-checked at inventory |
| Astra 2 | `desired_count = 0` is not an interlock; Express has no zero-task contract | §4.3, §4.8 #3–5, §4.6 | scalable target created at 0/0; `start` raises it; step 4 asserts live counts 0; Express fails closed |
| Astra 3 | background transfer can double-run; rollback incomplete | §4.10, §4.8 #8a–8c, §4.11 | App Runner off, deployment done, idle check or lock, then ECS on; reverse on rollback; boot migrations outside the switch blocked |
| Astra 4 | missing transitions; vacuous stage 0 | §4.8 | explicit pre-create, prepare (TTL), create, created, start, ready, convert, shift, switch, worker-off/on, rollback, hand-over; `ready` needs positive counts, completed deployment, routing, TLS and probe |
| Astra 5 | "only weight changes" permits unsafe DNS states | §4.9 | exact pairs against live, no (0, 0) in after or intermediate states, identity/TTL/records fixed, INSYNC waits |
| Astra 6 | retirement evidence underspecified | §5.2, §5.4 | CloudTrail + `GetChange`; metric name, statistic, dimensions, pagination, late and missing data; bound evidence consumed by `check --phase retire`; simple-switch and no-domain rules |
| Astra 7 | retire allowlist includes shared resources | §5.3 | delete only service, association, `apprunner` record; connector, roles, validation CNAMEs forgotten or untouched |
| Astra 8 | today's tag is not the deployed digest | §4.1 | digest identifier required; otherwise synchronized deployment then re-inventory; ECR Public path; amd64 child pin |
| Astra 9 | networking and authorization incomplete | §4.3, §4.5 | new task SG with ALB ingress rule; routes, NAT/endpoints, DNS checks; role reuse; simulation plus closure-limited report |
| Astra 10 | shared ALB does not fit a create-only gate | §4.3, §4.7 | dedicated ALB default; shared ALB opt-in with listener-certificate resource, bounded `prepare`, WAF conflict block |
| Astra 11 | an acknowledgement flag cannot validate retirement | §5.1, §9 | `generate --retire` refuses until a real run; no flag; plan validation distinguished from e2e |
| Opus 1 | scalable target overrides desired count 0 | §4.3, §4.8 #3–5 | min = max = 0 at create; gated `start`; live counts and live task definition checked |
| Opus 2 | "weight 0 for TTL + 24 h" unverifiable | §5.2 | CloudTrail `LookupEvents` + `GetChange` INSYNC; fail closed beyond 90 days; wording fixed |
| Opus 3 | retire can delete the new cert's validation record; rollback has no gate | §4.3, §4.11, §5.3 | `domain_validation_options` vs `CertificateValidationRecords`; no gate deletes a matching record; `rollback-rebuild` phase; own root and state |
| Opus 4 | retirement unverified and may cost App Runner eligibility | §4.12, §5.1, §9 | default runbook ends before retirement; separate artifact; sentinel service in test accounts |
| Fable 1 | scalable target bypasses the background-work gate | §4.3, §4.8 #5 | as Opus 1; ADR-0021 |
| Fable 2 | `Requests` is service-wide and scanned | §5.2 | `2xxStatusResponses` below an operator threshold plus attested host sample; wording "cannot attribute to the default URL" |
| Fable 3 | ACM validation-CNAME collision | §4.3, §5.3 | compare at generate and pre-create; reference the imported record on a match; never delete it |
| Fable 4 | cutover gate under-specified | §4.9 | rejects (0, 0), TTL/`records`/`set_identifier` changes, wrong direction without `--rollback` |
| Fable 5 | `enable_www_subdomain` | §3.3, §4.4, ADR-0017 | read from `DescribeCustomDomains`; `www.<alias>` reported as not carried; import ID confirmed |

### P2/P3 groups

- **Copilot render facts** (Opus, Fable): observability is an AWS-managed literal → external
  reference; private ingress connection shape; `CustomResourceRole`; `VpcConnector` conditional
  → §3.1, §3.2.
- **Provider defaults** (Opus): `auto_deployments_enabled`, ASC ARN with UUID,
  `enable_www_subdomain` → §3.3.
- **DNS zone** (Opus, Fable, Astra): root-domain zone, `AppDNSRole`, TTL 60, exact-name public
  delegated zone, multi-account blocked (Opus suggested a provider alias; this plan keeps v0.1's
  block) → §3.2, §4.9.
- **`prevent_destroy`** on association and domain CNAME (Fable) → §3.2.
- **Weighted import and recovery** (Opus, Fable, Astra): `removed` block, `ZONEID_NAME_TYPE_SETID`,
  no applies in between, resumable recovery → §4.9.
- **Express** (Opus, Astra, Fable): HTTP-only-443 gap, data-source conflict, ownership outside
  the manifest → §4.6.
- **ALB ingress and SG membership** (Opus): task SG rule → §4.3. Connector membership is
  corrected in r3 (§16).
- **Instance role reuse** (Opus) → §4.3.
- **Health checks** (Opus, Fable, Astra): threshold > 10 row; ranges confirmed → §4.4.
- **Timeouts** (all three): idle vs total; decision applies to a shared ALB too → §4.4, §4.7.
- **Ungated mutations** (Opus): TTL, simple switch, App Runner `update-service` → §4.8.
- **Alias A pair** (Opus, Fable): valid; not offered in 0.4.0 to keep one tested path → §4.9.
- **Eligibility probe** (all three): `create-service`, not `create-auto-scaling-configuration` → §9.
- **Release bar for 0.3.0** (Opus) → §9.
- **Wording** (Fable): Retain verification was for `Custom::EnvControllerFunction` → §3.4.
- **Report additions** (Opus): ECR Public digests, default-URL callers in other workloads →
  §3.5, §4.1.
- **Contradiction** (Opus): manual validation-CNAME deletion removed → §5.3.
- **UNCONFIRMED tags dropped** (confirmed with sources by reviewers): custom-domain import ID,
  health-check ranges, App Runner/Fargate CPU-memory pairs, Express memory limit and internal
  ALB, atomic batches, HTTP redirect, 120 s request limit, `nodejs20.x` dates. **Kept:** amd64
  only, last-service eligibility, which call is blocked, metric publication and health checks in
  metrics, App Runner certificate location, `StartCommand` ENTRYPOINT vs CMD, connector
  replacement, default health-check import, `start-deployment` drift, prices. r3 drops provider
  INSYNC wait and UPSERT and adds `MaxCapacity = 0` (§16). r4 drops connector replacement
  (§17).

## 16. Round-2 findings and where they are addressed

| Reviewer, level | Finding | Where | How |
|---|---|---|---|
| Astra P1-1 (Opus P2) | certificate collision detection precedes certificate creation | §4.2, §4.3, §4.8 #1, #2a–2b, #3, §4.12 | read-only predictor (`ListCertificates`/`DescribeCertificate`, live DNS, imported records) at generate and pre-create; gated `cert-request` phase creates only the certificate; `cert-requested` reads the real validation option; `generate --stage rebuild` emits create / reference / adopt / block as literals; `allow_overwrite = false` emitted and gated; listener needs `ISSUED` |
| Astra P1-2 (Fable P2) | worker-on conflicts with the unknown-value rule | §4.3, §4.8 #8a–8c, §4.10, §4.11 | `on` revision as its own address, created and verified in `taskdef-on` before App Runner workers go off; `worker-on` gates the service update against the literal ARN from `taskdef-on.json`; reverse phases defined; `skip_destroy = true` keeps revisions `ACTIVE`. Codex's approach, chosen over Fable's unknown-ARN exception because no gate then accepts an unknown value |
| Fable P2, Astra P2 | connector carries both `ServiceSecurityGroup` and `EnvironmentSecurityGroup`; r2 was wrong | §3.1, §3.2, §4.3, §4.4, §4.5, §15 | r1's statement restored; live `DescribeVpcConnector.SecurityGroups`; `env_sg: join` or `omit` per extra SG, report lists source-SG rules and join exposure; M5a keeps actual membership; the §15 sentence deleted |
| Opus P2, Fable P2 | `check --phase import` rejects `forget` | §4.9, §4.11, §7 | import phase extended to accept `forget` of exactly the manifest's record addresses; split rejected (state would hold both) |
| Opus P2 | rollback waypoint (100, 100) not an "earlier" pair | §4.9 | manifest lists the rollback path per pair; direct (0, 100) → (100, 0) fails |
| Opus P2, Fable P3, Astra P3 | provider UPSERT and INSYNC settled by source | §4.9, §8, §15 | UNCONFIRMED tags dropped; behaviour stated; 7c rejects a replace for identity, not a gap; provider pinned and asserted offline |
| Opus P3 | CloudTrail `LookupEvents` limits; `GetChange` retention | §5.2 | one attribute (`EventName`), 2 rps with backoff, client-side zone/set match, DELETE+CREATE pairs parsed, `NoSuchChange` fails closed |
| Opus P3 | build ordering | §4.3 | service and request-count policy `depends_on` listener and rule; `health_check_grace_period_seconds` decision; circuit breaker on, auto-rollback off (state stays true) |
| Opus P3 | rollback destroys the log group | §4.11 | `infra-rebuild-rollback/` with `removed { destroy = false }` for the log group |
| Opus P3 | which root `idle_timeout` `prepare` edits | §4.2, §4.7 | the root whose state holds the ALB, usually the v0.1 env root; `prepare-alb`; path and lineage in the manifest |
| Astra P2 | public-subnet egress path | §4.5 | IGW route plus assigned public IP accepted |
| Astra P2 | association/CNAME checks for the no-custom-domain branch | §4.1, §4.8 #1, §4.9, §4.11 | DNS and association checks conditional; certificate needs a declared `new_host` or blocks |
| Astra P2 | rollback after hand-over | §4.11 | re-freeze, refresh, restore Terraform deployment ownership before any worker change |
| Fable P3 | `MaxCapacity = 0` undocumented | §4.3, §8, §15 | UNCONFIRMED; moto and stand-in checks |
| Fable P3 | synchronized deployment vs "state equals live" | §4.1, §4.10 | `verify-handoff` check 4 asserts state `image_identifier` == live |
| Fable P3 | execution role permissions | §4.3, §4.4 | `ssm:GetParameters` for SSM, `secretsmanager:GetSecretValue` for Secrets Manager, `kms:Decrypt` only for customer-managed keys |
| Fable P3 | `ROLLBACK_SUCCEEDED` | §4.1, §4.8 #8b, §4.10 | treated as failure |
| Fable P3 | health-check defaults | §3.3 | provider block defaults equal App Runner's; UNCONFIRMED only for the real plan |
| Fable P3, Astra P3, Opus P3 | ADR-0016 numbering | §14 | ADR-0016 on `build-hatchling` (PR #26); M5 starts at 0017; renumber if unmerged |
| Opus P3, Fable P3 | confirmed facts (14 resources, `removed` support, end of support, App Runner availability, Delete handler, zero weights, trust policy, Fargate sizes) | — | no change |

## 17. Round-3 findings and where they are addressed

All three reviewers voted APPROVE WITH NOTES on r3. No note was P0 or P1. Notes are numbered per
reviewer and level in bullet order (Opus P3-2 is Opus's second P3 note).

| Reviewer + note | Finding | Where | How |
|---|---|---|---|
| Astra P2-1; Opus P2-1 | rollback deletes a validation record that the never-delete rule protects | §4.3, §4.11, §8, §18 #1 | `infra-rebuild-rollback/` forgets (`removed { destroy = false }`) the created validation record; `rollback-rebuild` allows that `forget` and fails a delete; must-fail test |
| Astra P2-2 | post-hand-over rollback cannot register the off twin of a CI revision through the 8a gate | §4.2, §4.8 #8a′, §4.10, §4.11, §18 #2 | `verify-cutover --step live-revision` binds the live revision; `generate --stage taskdef-off`; `taskdef-off` gate creates only `off_live`; reverse 8c targets it |
| Astra P2-3; Opus P2-2; Fable P2-2 | `new_host` has no traffic record and inherits the adoption zone rule | §3.2, §4.3, §4.8 #1, #3, §4.9, §18 #3–4 | zone rules split from the adoption rule; `pre-create` requires no record at `new_host`; step 3 creates an alias A to the ALB with `allow_overwrite = false`, gated on name, type, target; `ready` checks TLS through it |
| Opus P2-2 (third part) | rollback in the no-domain branch strands clients given the new URL | §4.9, §4.11, §18 #5 | `rolled-back` prints ALB `RequestCount` since start and requires an operator answer |
| Astra P2-4; Opus P3-5; Fable P3-1 | "in no state" is not an ownership boundary for 2b | §4.3, §4.8 #2b, §6, §18 #6 | report warns owner unknown and that a foreign delete breaks renewal for both; `validation_record: import` (with provenance) or `reference`; missing answer blocks |
| Fable P2-1 | a refreshed 7a plan shows a null `no-op`, never a `forget` | §4.8 #7a, §4.9 step 5, §4.11, §7, §8, §18 #7 | import gate accepts `forget` or null no-op plus `resource_drift` delete for exactly the manifest addresses; `check --state` asserts absence after apply; `removed` block kept for `-refresh=false` |
| Astra P3-1 (first part) | waypoint plans leave one weight unchanged | §4.8 #7b, §4.9, §8, §18 #8 | manifest-bound `no-op` of the unchanged record allowed; a no-op where the pair changes the weight fails |
| Astra P3-1 (second part) | `--forgotten` validation also lives in `src/ecsodus/cli.py` | §7, §8, §18 #9 | extended in `cli.py` and `check/plan.py` together; exact coverage kept |
| Opus P3-2 | the provider adds `domain_name` to the SANs, so "no SANs" fails every valid 2a plan | §4.8 #2a, §8, §18 #10 | gate `subject_alternative_names == [domain_name]` |
| Opus P3-1 | ACM times out validation after 72 h | §4.3, §4.8 #3, §4.12 steps 5–6, §8, §18 #11 | status and age checked by `generate --stage rebuild` and `check --phase rebuild`; recovery is rollback destroy then 2a again |
| Opus P3-3 | 2b depends on `cert-requested.json`, so generation must precede it | §4.2, §4.3, §4.12 step 5, §18 #12 | `generate --stage rebuild` runs before 2b and emits its import block |
| Opus P3-4 | the 8a file is unnamed | §4.2, §4.8 #3, §4.12 step 9, §8, §18 #13 | `rebuild/staged/taskdef-on.tf`, copied into the root at step 9; the step-3 gate rejects it as a create outside the manifest |
| Fable P3-2 | `aws_acm_certificate_validation` has no implicit edge to the created record | §4.3, §18 #14 | `depends_on` the created validation record |
| Fable P3-3 | after 2a the certificate is a `no-op` in the rebuild plan | §4.8 #3, §8, §18 #15 | rebuild gate allows no-ops of exactly the addresses already in the `infra-rebuild` state |
| Fable P3-4 | string compare of `container_definitions` can fail spuriously | §4.8 #8a, #8a′, §8, §18 #16 | compared as parsed JSON |
| Opus P3-6 | rollback config must plan with only the 2a certificate in state | §8, §18 #17 | offline test for both state shapes |
| Fable P3-5 | VPC connector replacement is settled by the provider source | §3.2, §15, §18 #18 | UNCONFIRMED dropped; `ForceNew` fields named; `check` rejects the replace |
| Fable P3-7 | "never applied again" contradicts the rollback | §4.9, §18 #19 | "unless rolling back" |
| Astra P3-2 | ADR-0014/0015 record worker and job moto evidence, not a moto architecture decision | §8, §18 #19 | reference tightened |
| Fable P3-6; Fable P3-8; Astra P3-2 (second part) | checked, no change: `ignore_changes` path, `auto_deployments_enabled` default, ForceNew fields of the service, `TERRAFORM_CONSTRAINT`, `handoff_stacks`, ADR numbering, ARN form of `task_definition`, connector membership against the fixture | — | no change |

## 18. Build requirements from the approval round (binding for M5)

All three reviewers approved r3. Their notes are fail-closed refinements, and the build
implements each of them. A requirement is met only when its gate fails closed and the named test
exists.

1. **Rollback keeps validation records (Astra P2-1, Opus P2-1).** `infra-rebuild-rollback/`
   carries `removed { destroy = false }` for a validation record `infra-rebuild` created, as for
   the log group. `check --phase rollback-rebuild` allows its `forget` and fails a delete of it.
   The report lists it as unowned. Must-fail test: a rollback plan that deletes it.
2. **Off twin after hand-over (Astra P2-2).** Before any worker mutation, `verify-cutover --step
   live-revision` writes `live-revision.json` bound to the service's live revision ARN, digest,
   account, region, service and manifest hash. `generate --stage taskdef-off` refuses without it.
   The `taskdef-off` gate creates only `aws_ecs_task_definition.off_live`, whose parsed
   `container_definitions` equal the live revision's except the env var's off value, with
   `skip_destroy = true`. The reverse 8c targets the ARN from `taskdef-off.json`. Must-fail
   tests: a binding to a non-live ARN; a second env var differs.
3. **`new_host` traffic record (Astra P2-3, Opus P2-2, Fable P2-2).** Step 3 creates `new_host`
   as an alias A record to the ALB with `allow_overwrite = false`; `check --phase rebuild` gates
   name, type and alias target; the rollback destroy deletes it; `ready` checks TLS with SNI =
   `new_host`. Must-fail test: `allow_overwrite = true` or another name, type or target.
4. **`new_host` zone rules (Astra P2-3, Opus P2-2, Fable P2-2).** `new_host` is checked against
   the §3.2 zone rules (exact name, public, delegated, same account) and CAA, not the adoption
   rule, and `pre-create` fails if any record of any type exists at the name. Must-fail test.
5. **No-domain rollback notice (Opus P2-2).** `verify-cutover --step rolled-back` prints the
   ALB's `RequestCount` since step 5 and the destroy does not proceed without an explicit operator
   answer.
6. **2b ownership (Astra P2-4, Opus P3-5, Fable P3-1).** For a matching record in neither ecsodus
   state, the report states the owner is unknown and that a deletion by another owner breaks
   renewal for both. `decisions.yml` must answer `validation_record: import | reference`;
   `import` requires a `provenance` note. A missing answer blocks generation; 2b runs only with
   `import`.
7. **7a import gate (Fable P2-1).** For exactly the manifest-named record addresses of 7a and its
   reverse, `check --phase import` accepts a `forget` or a `no-op` with null before and after
   plus a `resource_drift` delete entry for that address. After apply, `check --state` asserts
   each named address is absent. Must-pass tests for both forms; must-fail for a null no-op with
   no drift entry, either form on an unnamed address, and a state that still lists the address.
8. **Waypoint no-op (Astra P3-1).** `check --phase cutover` allows a `no-op` on a weighted record
   exactly when the manifest pair leaves its weight unchanged, and fails one where the pair
   changes it.
9. **`--forgotten` in both places (Astra P3-1).** `src/ecsodus/cli.py` and
   `src/ecsodus/check/plan.py` are extended together to accept exactly the addresses the manifest
   names for the current phase and step; coverage stays exact in both directions.
10. **2a SANs (Opus P3-2).** `check --phase cert-request` requires
    `subject_alternative_names == [domain_name]`. Must-pass test for that value; must-fail for any
    other list, including empty.
11. **72-hour validation window (Opus P3-1).** `generate --stage rebuild` and `check --phase
    rebuild` fail unless the certificate is `PENDING_VALIDATION` (or `ISSUED`) and younger than
    72 h. The runbook states the recovery: rollback destroy, then 2a again. Must-fail test for
    `VALIDATION_TIMED_OUT` and for age.
12. **Generate before 2b (Opus P3-3).** `generate --stage rebuild` runs after `cert-requested`
    and before 2b, and emits the 2b import block and manifest entry.
13. **8a file (Opus P3-4).** `aws_ecs_task_definition.on` is generated into
    `rebuild/staged/taskdef-on.tf` and copied into `rebuild/infra-rebuild/` only at runbook step
    9. Must-fail test: a step-3 plan that contains it.
14. **Validation dependency (Fable P3-2).** `aws_acm_certificate_validation` `depends_on` the
    created validation record.
15. **Rebuild no-ops (Fable P3-3).** `check --phase rebuild` allows no-ops of exactly the
    addresses already in the `infra-rebuild` state and fails a no-op of any other address.
16. **Parsed JSON (Fable P3-4).** The `taskdef-on` and `taskdef-off` gates compare
    `container_definitions` as parsed JSON. Must-pass test: key order differs, only the env var
    changes.
17. **Rollback config shapes (Opus P3-6).** Offline test: `infra-rebuild-rollback/` plans cleanly
    with only the 2a certificate in state and with everything in state.
18. **Connector replace (Fable P3-5).** `check --phase import` rejects any replace of
    `aws_apprunner_vpc_connector`; the plan no longer marks this UNCONFIRMED.
19. **Wording (Fable P3-7, Astra P3-2, Opus P3-5, Fable P3-1).** "Never applied again unless
    rolling back" (§4.9); the ADR-0014/0015 reference names worker and job moto evidence (§8);
    "in neither ecsodus state" replaces "in no state" (§4.3, §4.8).
