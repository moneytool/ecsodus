# ecsodus: plan v0.2, App Runner (r1, DRAFT for council)

*App Runner support and a rebuild-in-parallel mode. 2026-10-08.*
*Status: draft r1, not reviewed. It extends [PLAN.md](PLAN.md) r4 (approved) and does not change
any v0.1 decision. Where this draft relies on behaviour it has not verified, it says
**(UNCONFIRMED)**.*

**Naming.** "v0.2" here is the PLAN scope from [PLAN.md](PLAN.md) §3 and §7 (M5). The package is
already at 0.2.0 (Worker Services and Scheduled Jobs, [CHANGELOG.md](../CHANGELOG.md)). This
draft proposes releasing v0.2a as **0.3.0** and v0.2b as **0.4.0** (open question 1).

## 1. Problem and who has it

| Fact (2026-10-08) | Consequence |
|---|---|
| App Runner closed to new customers on 2026-04-30. Existing services keep running, with no new features. | No deadline, but no future. Accounts that never used App Runner cannot create a service. |
| Copilot CLI end of support 2026-06-12; repo archived. | Copilot's RDWS stacks keep running. The CLI goes stale. |
| Copilot custom-resource Lambdas run `nodejs20.x`: create blocked from 2027-07-29, update from 2027-08-31. | Every Copilot stack, including RDWS stacks, should be off Copilot before mid-2027. |
| A Copilot Request-Driven Web Service (RDWS) is an `AWS::AppRunner::Service`. | RDWS users have both problems at once. |

**Who has it.**

- **(a) Copilot RDWS users.** Today ecsodus detects the RDWS, keeps its stack, and by kept-status
  propagation ([src/ecsodus/mappers/fates.py](../src/ecsodus/mappers/fates.py) docstring) also
  keeps its **env stack and the app stack and StackSet**. One RDWS in an environment stops the
  whole app from leaving Copilot. This is the gap v0.2 closes.
- **(b) Teams with standalone App Runner services** (console, CloudFormation, CDK, Terraform,
  Pulumi). They have no Copilot landmines. Their exit is "rebuild on ECS", which AWS documents
  (Express Mode plus Route 53 weighted DNS).

**Decision: v0.2 generates for (a) only. (b) gets read-only `inventory` and `report` in v0.2b.**

- ecsodus's safety model needs a known owner. Retain patches, the closure rule and the teardown
  order all read CloudFormation stacks. For (b) the owner can be anything, and ecsodus cannot
  patch or reason about it.
- The wedge is Copilot ([PLAN.md](PLAN.md) §9). For (b), ecsodus would compete with AWS's own
  guide and generic tools without an advantage.
- Testing (b) needs an App Runner-capable account too (§8), with no extra coverage gained.
- The rebuild model (§4) is source-agnostic: it reads the App Runner API, not the stack. Adding
  (b) later is a source adapter, not a redesign. A read-only report for (b) is cheap and tells us
  whether there is demand.

## 2. Two options, evaluated

v0.1's adopt-in-place ([ADR-0003](adr/0003-adopt-in-place.md)) imports an ECS service that
already exists. An RDWS has no ECS service, task definition, target group or ALB. "Adopt in
place to ECS" does not exist for App Runner. There are two real options.

### 2.1 Option A: adopt the App Runner service in place, into Terraform

Import `AWS::AppRunner::Service` as `aws_apprunner_service`, the VPC connector as
`aws_apprunner_vpc_connector`, the custom-domain association and its CNAMEs as
`aws_apprunner_custom_domain_association` and `aws_route53_record`. Everything else in an RDWS
stack (roles, security groups, SNS topics, addons) already has a mapper
(`src/ecsodus/mappers/`, 64 types). Then the stack hands off like any other, and the env and app
stacks can follow.

### 2.2 Option B: rebuild on ECS Fargate in parallel, cut over DNS, retire App Runner

Generate a new ECS service, task definition, target group, ALB listener rule and certificate.
Run both. Shift the custom domain with Route 53. Retire App Runner after a rollback window.

### 2.3 Tradeoffs

| | A: adopt App Runner | B: rebuild on ECS |
|---|---|---|
| Traffic moves | No | Yes (DNS cutover) |
| New infrastructure | None | ECS service, task def, roles, TG, listener rule, cert, maybe ALB |
| Fits the existing gates | Yes: `check --phase import`, retain patches, closure, unchanged | Needs new gates (§4.8) |
| Removes Copilot | Yes, the whole app | Yes, but only after cutover and retirement |
| Leaves you on App Runner | Yes. Closed to new customers, no new features, no announced end date | No |
| Cost of a mistake | An import plan that is not import-only is caught by the gate. A replacement of `aws_apprunner_service` would give a new default URL; `check` already rejects replacements | Double-running side effects, DNS outage, TLS mismatch, rollback window |
| Default `*.awsapprunner.com` URL | Kept | **Cannot move.** Clients using it must change URL |
| Operator input needed | None beyond v0.1 | Scaling target, health-check path, start command, background-work declaration, hostname (§4.3) |
| Build effort | Small: ~5 mappers, out-of-band discovery, fixtures | Large: new mode, new emitter, new checks, new runbook |
| Testable in our sandbox | Only if the account can create App Runner (§8) | ECS side yes; App Runner side same problem |

**A is not a dead end.** It takes Copilot out of the loop before anything risky happens. After A,
the App Runner service is a plain Terraform resource with no custom-resource Delete handlers and
no env-controller. B then works on a simpler starting state.

**A alone is not enough.** App Runner gets no new features. Teams that want to leave it still need B.

### 2.4 Recommendation: v0.2a then v0.2b

1. **v0.2a (release 0.3.0): adopt RDWS in place.** Copilot can be removed from apps that have an
   RDWS. No traffic moves. Small, fits every existing gate.
2. **v0.2b (release 0.4.0): rebuild in parallel.** Input is an App Runner service that **Terraform
   already owns** (the v0.2a hand-off record). Rebuild mode never operates on a stack that
   Copilot still owns, so no Copilot custom resource can fire during a cutover.
3. **Standalone App Runner (b):** read-only inventory and report in v0.2b. Generation later, on
   demand.

The one-path rule (rebuild requires adopt first) costs Copilot users a second, import-only run.
It removes a whole class of states: Copilot stack plus new ECS plus weighted DNS at the same time
(open question 3).

## 3. v0.2a: adopt RDWS in place

### 3.1 What an RDWS stack holds

The fixture [tests/fixtures/copilot/rendered/workloads/rdws-test.stack.yml](../tests/fixtures/copilot/rendered/workloads/rdws-test.stack.yml)
(Copilot v1.29.0 render) has **14 resources**:

| Logical ID | Type | Condition | Mapper today | v0.2a fate |
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
| `EnvironmentSecurityGroupIngressFromServiceSecurityGroup` | `AWS::EC2::SecurityGroupIngress` | — | yes | `import` |
| `VpcConnector` | `AWS::AppRunner::VpcConnector` | — | **no** | `import` (new) |

Notes on the fixture:
- `AutoScalingConfigurationArn` is a **literal ARN** (`autoscalingconfiguration/high-availability/3`),
  not a resource in the stack. It is `external-reference` if AWS-managed, otherwise an
  out-of-band object to import (open question 6).
- The fixture has **no** custom domain, private ingress or observability resources. Per
  [docs/knowledge/copilot-custom-resources.md](knowledge/copilot-custom-resources.md), an RDWS
  with `alias` adds `CustomDomainFunction` and `CustomDomainAction`
  (`Custom::CustomDomainFunction`, `custom-domain-app-runner.js`). A private RDWS adds a VPC
  ingress connection, and tracing adds an observability configuration **(UNCONFIRMED: render
  details not in our fixtures)**. M5.0 adds fixtures for each from the archived Copilot source.
- App Runner creates its own log groups (`/aws/apprunner/<name>/<id>/application` and
  `/service`). No stack owns them. They survive any stack delete.

### 3.2 New mappers and out-of-band reads

| Source | Terraform | Import ID | Notes |
|---|---|---|---|
| `AWS::AppRunner::Service` | `aws_apprunner_service` | service ARN | every argument from template + `DescribeService`; `prevent_destroy`; `ignore_changes` on the image identifier (deploy owner, §3.4) |
| `AWS::AppRunner::VpcConnector` | `aws_apprunner_vpc_connector` | connector ARN | immutable resource: any argument mismatch is a replacement, which `check` rejects |
| `AWS::AppRunner::VpcIngressConnection` | `aws_apprunner_vpc_ingress_connection` | ARN | private RDWS only |
| `AWS::AppRunner::ObservabilityConfiguration` | `aws_apprunner_observability_configuration` | ARN | tracing only |
| custom domain (out of band, `custom-domain-app-runner.js`) | `aws_apprunner_custom_domain_association` | `<domain>,<service-arn>` **(UNCONFIRMED: provider ID format)** | from `DescribeCustomDomains`; `enable_www_subdomain` must match live |
| domain CNAME (out of band) | `aws_route53_record` (CNAME) | `<zone>_<name>_CNAME` | found in the app hosted zone through `ListHostedZonesByName(AppDNSName)`, as the handler does |
| validation CNAMEs (out of band) | `aws_route53_record` (CNAME) each | as above | from `CertificateValidationRecords`; they keep App Runner's managed certificate renewing |
| env `AppRunnerVpcEndpoint` + SG | `aws_vpc_endpoint` etc. | — | already mapped; present when `AppRunnerPrivateWorkloads` is non-empty ([src/ecsodus/knowledge.py](../src/ecsodus/knowledge.py) `ENV_CONDITIONS`) |

New read-only live calls: `apprunner:DescribeService`, `DescribeVpcConnector`,
`DescribeVpcIngressConnection`, `DescribeCustomDomains`, `DescribeAutoScalingConfiguration`,
`DescribeObservabilityConfiguration`, `ListTagsForResource`; `wafv2:GetWebACLForResource`. None
returns a secret value. `DescribeService` returns `RuntimeEnvironmentVariables` in plaintext, the
same exposure as a task definition's `environment`; the v0.1 secrets contract applies
(`inventory.json` 0600, HCL with env values in `.gitignore`, encrypted state).

**Blocked in v0.2a** (fail closed, named in the report): source-code services
(`CodeRepository`), a WAF web ACL whose owner is not discoverable, any `DescribeService` field the
mapper does not know.

### 3.3 Safety: what a plain RDWS stack delete destroys

| Resource | Plain delete does | With retain patch |
|---|---|---|
| `Service` | Deletes the App Runner service. Its `*.awsapprunner.com` URL is gone for good; a new service gets a new random URL | kept |
| `CustomDomainAction` | Delete handler **disassociates the domain and DELETEs the domain CNAME and every validation CNAME**: the custom domain stops resolving | handler not invoked (Retain suppresses Delete: verified 2026-09-30, [e2e](e2e/2026-09-30-aws-e2e.md)) |
| `EnvControllerAction` | Removes the workload from `NATWorkloads` and `AppRunnerPrivateWorkloads`, then updates the env stack. If it was the last user: **NAT gateways and their routes, and the App Runner VPC endpoint, are deleted**, breaking every other private workload | handler not invoked |
| `ServiceSecurityGroup` + ingress | Deleted; anything that allows ingress from this SG (addon DBs) loses the rule | kept |
| `VpcConnector`, roles | Deleted | kept |
| SNS topics | Deleted; other services' subscriptions break | kept |
| `AddonsStack` | Nested addons with no `DeletionPolicy`: Aurora snapshot-and-delete, DynamoDB and secrets deleted | kept |

The v0.1 mechanics apply unchanged: retain-all patch, change set with `check --changeset`,
`verify-retain`, import, `check --phase import`, `check --state`, teardown, `check --phase steady`.
No exception for App Runner.

### 3.4 Deploy owner after v0.2a

Copilot deployed by changing the `ContainerImage` parameter. After hand-off, the named deploy
owner is CI calling `aws apprunner update-service` (or `start-deployment` for a mutable tag).
Terraform gets `ignore_changes` on
`source_configuration[0].image_repository[0].image_identifier`, the analogue of
`ignore_changes = [task_definition]` on ECS ([PLAN.md](PLAN.md) §2.4). If
`AutoDeploymentsEnabled` is true, App Runner itself is the deploy owner and the runbook says so.
Copilot sets it to `false`.

## 4. v0.2b: rebuild-in-parallel mode

### 4.1 Flow

```
ecsodus inventory --app myapp --env prod --apprunner-from-handoff handoff.json -> inventory.json
ecsodus report    inventory.json                       -> REPORT.md + decisions.template.yml
ecsodus generate  inventory.json --mode rebuild --decisions decisions.yml --out ./infra
                                                         -> Terraform (new compute) + RUNBOOK.md
ecsodus check     plan.json --phase rebuild|cutover|retire|steady --inventory inventory.json
ecsodus verify-cutover --inventory inventory.json --stage N   (read-only)
```

ecsodus stays read-only. It never applies Terraform, never changes DNS, never shifts traffic.
Every mutation is a runbook step behind a gate.

### 4.2 What ecsodus generates

**Default target: a plain ECS Fargate service behind an ALB, as flat root resources.** Express
Mode is opt-in, only when the predicate in §4.4 holds.

| Generated | Resource | Notes |
|---|---|---|
| Task definition | `aws_ecs_task_definition` | one container; `X86_64` **(UNCONFIRMED: App Runner runs amd64 images only)**; image pinned by digest (§4.3) |
| Service | `aws_ecs_service` | in the env cluster (imported in v0.1/v0.2a); `ignore_changes = [task_definition, desired_count]`; **`desired_count = 0` until the background-work gate passes** (§4.6) |
| Task role | `aws_iam_role` + copied inline policies and managed attachments | new role: trust `ecs-tasks.amazonaws.com`. The App Runner instance role is not edited |
| Execution role | `aws_iam_role` | ECR pull, logs, **plus the secret/KMS statements** the instance role used to fetch `RuntimeEnvironmentSecrets` |
| Log group | `aws_cloudwatch_log_group` | `awslogs`; retention copied from the App Runner application log group |
| Target group | `aws_lb_target_group` | `ip` target type; health check from §4.3 |
| Listener rule | `aws_lb_listener_rule` (host header) | on the ALB chosen in §4.3 |
| Certificate | `aws_acm_certificate` + validation `aws_route53_record` + `aws_acm_certificate_validation` | issued before cutover; covers the custom domain |
| ALB (if new) | `aws_lb`, `aws_lb_listener` 443 + 80→443 redirect, SG | `idle_timeout = 120` (App Runner's request timeout is 120 s; the ALB default 60 s would turn long requests into 504s) |
| Scaling | `aws_appautoscaling_target` + policy | min/max from App Runner; target from the operator (§4.3) |
| WAF | `aws_wafv2_web_acl_association` | same regional web ACL, now on the ALB; the ACL is `external-reference` |
| Security groups | **reused, not new** | the service joins the VPC connector's SGs (`ServiceSecurityGroup`, `EnvironmentSecurityGroup`), so DB rules that trust them still match |

Why plain service by default: Copilot's RDWS egresses through a VPC connector in **private**
subnets. Express Mode puts an internal ALB in front of private subnets, so a public RDWS on
private subnets cannot be expressed in Express without moving tasks to public subnets with
public IPs. That is a security change ecsodus should not make by default
([council/fable.md](council/fable.md) finding 4).

Flat resources, not `terraform-aws-modules/ecs`, keep one emitter, one `terraform validate`
harness and no module version in the support matrix (open question 5).

### 4.3 Config translation

Every value comes from `DescribeService` and related reads, or from `decisions.yml`. Nothing is
guessed. A missing decision **blocks** generation, with the key named in the report.

| App Runner | ECS | Rule |
|---|---|---|
| `ImageRepository.ImageIdentifier`, type `ECR` / `ECR_PUBLIC` | container `image` | resolved to `repo@sha256:…` via `ecr:DescribeImages` (read-only), so both sides run the same bits |
| `CodeRepository` (source-based) | — | **blocked** ([PLAN.md](PLAN.md) §3: v0.3, needs the repo and `apprunner.yaml`) |
| `ImageConfiguration.Port` | `containerPort`, TG port | literal |
| `StartCommand` | `command` | **decision required**: App Runner takes one string; ECS takes a list. Splitting it is a guess. Operator gives the list, or confirms `["sh","-c", …]` |
| `RuntimeEnvironmentVariables` | `environment` | literal; values follow the secrets contract |
| `RuntimeEnvironmentSecrets` (SSM / Secrets Manager ARNs) | `secrets[].valueFrom` | literal ARNs; the **execution** role gets the read and `kms:Decrypt` statements (in App Runner the instance role fetched them) |
| `InstanceRoleArn` | task role | new role, same policies. The report lists every key policy, bucket policy and secret resource policy in the closure that names the instance role ARN, since those grants do not follow |
| `AuthenticationConfiguration.AccessRoleArn` | execution role | ECR pull |
| `InstanceConfiguration.Cpu/Memory` | task `cpu`/`memory` | every App Runner combination maps to a valid Fargate one (0.25/0.5–1, 0.5/1, 1/2–4, 2/4–6, 4/8–12 GB) **(UNCONFIRMED: verify against the current tables)** |
| `NetworkConfiguration.EgressConfiguration` `VPC` | `awsvpc` in the connector's subnets and SGs | same subnets, so the same NAT EIPs: outbound allowlists keep working |
| `EgressType: DEFAULT` | — | **decision required**: subnets and public-IP choice. Report warns the source IP changes from App Runner's shared ranges to yours |
| `IngressConfiguration.IsPubliclyAccessible: false` + ingress connection | internal ALB | **blocked in v0.2b** (open question 7): clients use the ingress connection's AWS-generated domain, which cannot move |
| `IpAddressType: DUAL_STACK` | ALB `dualstack` | blocked if the VPC has no IPv6 CIDR |
| `HealthCheckConfiguration` HTTP | TG health check | literal where in range |
| `HealthCheckConfiguration` TCP (App Runner default) | — | **decision required**: ALB needs an HTTP path |
| health check out of ALB range (interval < 5 s, healthy threshold 1, timeout ≥ interval) | — | **decision required**: App Runner defaults (interval 5, timeout 2, healthy 1, unhealthy 5) include a healthy threshold of 1; ALB's minimum is 2 **(UNCONFIRMED: current ranges)** |
| `AutoScalingConfiguration` `MinSize`/`MaxSize` | scalable target min/max | literal |
| `MaxConcurrency` | — | **decision required**: concurrency is not requests per minute or CPU. Operator picks the metric and target ([council/astra.md](council/astra.md) finding 8) |
| `ObservabilityConfiguration` (X-Ray) | — | **blocked**: ADOT is v0.3 ([PLAN.md](PLAN.md) §3) |
| `EncryptionConfiguration.KmsKey` | — | reported; no ECS equivalent beyond Fargate ephemeral-storage keys |
| WAF association | `aws_wafv2_web_acl_association` | same ACL |
| custom domain | ACM cert + listener rule + DNS cutover (§4.5) | required for gradual cutover |
| default `*.awsapprunner.com` URL | — | **cannot move.** Report states it; the retire gate (§4.8) measures remaining traffic |

**Runtime behaviour that differs and the report must say so:**
- App Runner throttles CPU on idle instances. On ECS a container runs at full CPU all the time,
  so background loops that barely ran on App Runner run for real.
- App Runner terminates TLS and redirects HTTP. The ALB needs both listeners.
- App Runner's 120 s request limit vs the ALB idle timeout (set to 120).

### 4.4 Express fit predicate for App Runner sources

[PLAN.md](PLAN.md) §2.3, plus:
- egress `DEFAULT`, or the operator accepts tasks in public subnets with public IPs;
- memory ≤ 8192 MiB (excludes App Runner 4 vCPU/10 GB and 12 GB);
- no tracing; health-check path given;
- the custom domain is a host-header rule and listener certificate on the Express-owned ALB.
  Terraform must look that ALB up by data source; deleting the last Express service in the VPC
  deprovisions the ALB and those rules ([council/fable.md](council/fable.md) finding 6).

App Runner is HTTPS-only, which matches Express's 443-only listener. When the predicate holds,
`--target express` emits `aws_ecs_express_gateway_service` with the same translation table and
`ignore_changes` on the primary container image.

### 4.5 Traffic cutover

**Pre-flight (`verify-cutover --stage 0`, read-only):**
- the hostname has a Route 53 record in a zone in this account, of type CNAME, not apex.
  Copilot RDWS domains are CNAMEs under the app domain;
- current TTL recorded; the runbook lowers it to 60 s and waits for the old TTL;
- the ACM certificate is `ISSUED`, covers the hostname, and is on the listener;
- CAA records, if any, allow Amazon;
- target group: healthy targets ≥ desired count;
- App Runner's own validation CNAMEs are still present (its certificate must keep renewing
  during the window).

**Simple record → weighted pair: one atomic change batch.** A simple CNAME and weighted CNAMEs of
the same name cannot coexist. Terraform would delete and create in separate calls, leaving a
window where the name does not resolve (and negative caching extends it). So the runbook runs one
`aws route53 change-resource-record-sets` batch: `DELETE` the simple record, `CREATE` weighted
`apprunner` (weight 100) and `ecs` (weight 0). Then `terraform state rm` the old address and
import the two weighted records (`check --phase import`). Both targets are CNAMEs (App Runner
`DNSTarget`, ALB DNS name): a weighted set must share one type, so an ALB alias A record is not
used.

**Steps.** Weight changes are Terraform applies of a tfvars change, gated by
`check --phase cutover` (only `weight` on the two expected records may change). Suggested steps
0 → 10 → 50 → 100, each after `verify-cutover --stage N`: target health, ALB 5xx and App Runner
5xx alarms not in ALARM, an operator `curl --resolve` against a declared safe path. DNS weights
are not exact percentages and cached resolvers lag; the runbook says so.

**Simple switch (alternative).** One `UPSERT` of the CNAME value. No gradual shift. Rollback is
the reverse `UPSERT`. Offered for low-traffic services.

**No custom domain.** No gradual shift is possible. The runbook becomes "deploy ECS, give clients
the new URL, wait until App Runner traffic is zero". The report flags it.

### 4.6 Data and side effects of a parallel run

Both sides run the same image against the same databases, queues and topics.

- **Background work.** `decisions.yml` must answer, per service, the [PLAN.md](PLAN.md) §2.3
  question: "does this container run background work or migrations on boot?" Allowed answers:
  `none`, or `disable-until-cutover` with the env var or flag that turns it off. Generation
  blocks without an answer.
- **Desired count 0 at create.** The ECS service is created with zero tasks. The runbook scales
  it up only after the operator confirms the disable switch is set (`verify-cutover --stage 0`
  checks the env var is present in the task definition).
- **At 100 %:** the runbook re-enables background work on ECS and confirms it is off on App
  Runner (an App Runner `update-service`, a mutation, gated and listed).
- **Migrations** must be backward compatible for the whole window; the runbook says so.
- **HTTP is not side-effect free.** Verification uses only the declared safe path.
- **SNS publish.** Both sides may publish to the same topics during the window. Consumers must be
  idempotent; the report lists the topics the instance role can publish to.

### 4.7 Rollback

| When | Rollback |
|---|---|
| Before the weighted batch | `terraform destroy` of the rebuild manifest addresses only (gated: §4.8 `retire`-style manifest check). App Runner untouched |
| During steps | set weights back to 100/0 (one apply). Clients see App Runner again within the TTL |
| After step 100, before retirement | same as above. Window: TTL + 24 h minimum ([PLAN.md](PLAN.md) §3), operator may extend |
| After retirement | **none.** The App Runner service and its URL are gone, and the account may not be able to create App Runner services again **(UNCONFIRMED: whether deleting the last service ends "existing customer" status)**. The runbook says this before the retire step |

### 4.8 Gates

| Check | Phase | Fails on |
|---|---|---|
| `check --phase rebuild` | create new compute | any update, delete, replace or import of an existing address; any create not in the generated manifest (address list + SHA-256 recorded by `generate`); any change to `aws_apprunner_*` |
| `check --phase import` | weighted records adopted after the atomic batch | unchanged v0.1 rule |
| `check --phase cutover` | each weight step | any change other than `weight` on the two expected `aws_route53_record` addresses |
| `verify-cutover --stage N` | before each step | unhealthy targets, missing certificate, record type or TTL wrong, alarms in ALARM, background-work switch missing |
| `check --retire` | before retirement | App Runner `Requests` metric above zero (or an operator threshold) in the last 24 h; weight not 0 for at least TTL + 24 h. This also catches clients still on the default URL |
| `check --phase retire` | retirement apply | any action other than delete; any delete outside the App Runner set (service, VPC connector, custom-domain association, its validation CNAMEs, the `apprunner` weighted record, access role; instance role only if no other principal references it) |
| `check --phase steady` | end | unchanged v0.1 rule |

**Retirement is the first destructive Terraform step ecsodus has ever written into a runbook.**
v0.1 never deletes anything ([PLAN.md](PLAN.md) §2.2). It needs its own ADR, its own gate, and
`prevent_destroy` removed explicitly in a reviewed edit. App Runner log groups are kept (history)
and listed for manual deletion.

### 4.9 Runbook outline (rebuild)

1. **Freeze** deploys to the App Runner service (record the deploy owner; disable auto-deploy if on).
2. **Pre-flight** `verify-cutover --stage 0`; lower TTL; wait the old TTL.
3. **Create** new compute: plan → `check --phase rebuild` → apply. Service at `desired_count = 0`.
4. **Start** ECS tasks with background work disabled; health checks pass; safe-path probe with
   `curl --resolve`.
5. **Weighted batch** (atomic), then import the weighted records.
6. **Shift** in steps, each gated.
7. **Swap background work** to ECS.
8. **Window**: TTL + 24 h at least; `check --retire`.
9. **Retire**: plan → `check --phase retire` → apply. Delete leftover validation CNAMEs and log
   groups by hand.
10. **Verify**: `check --phase steady`; the hostname resolves only to the ALB.

## 5. Scope

**v0.2a (in):** Copilot RDWS with image source (ECR), public ingress, `DEFAULT` or `VPC` egress,
custom domain, private ingress (import only), the env App Runner VPC endpoint, addons.

**v0.2b (in):** rebuild of Terraform-owned (post-v0.2a) App Runner image services with public
ingress into plain ECS + ALB; Express opt-in under §4.4; weighted or simple DNS cutover;
retirement. Read-only `inventory`/`report` for standalone App Runner services.

**Detected and `blocked`:** source-code services; tracing (rebuild only); private ingress
(rebuild only); dual-stack without IPv6; WAF ACL not discoverable; any unknown field.

**Non-goals:** generating for standalone App Runner services; Dockerfile generation; App Runner
→ Lambda or EKS; choosing scaling targets; moving the default URL; shifting traffic from inside
ecsodus.

## 6. Architecture

- `sources/apprunner.py`: live reads, shared by the Copilot path and the standalone report.
- `model/`: an `AppRunnerServiceSpec` with provenance on every field, independent of the stack.
- `mappers/tf_apprunner.py`: v0.2a imports.
- `mappers/rebuild.py`: the §4.3 table, one rule per row, blocking on missing decisions.
- `emit/terraform`: rebuild resources; manifest with hashes.
- `emit/runbook`: rebuild branch.
- `check/plan.py`: `rebuild`, `cutover`, `retire` phases; `verify-cutover` reads Route 53, ACM,
  ELBv2, CloudWatch alarms and metrics, all read-only.
- Support matrix: add the provider version that has `aws_ecs_express_gateway_service` and the
  App Runner resources' current schemas; pin bounded as in v0.1.

## 7. Validation (offline)

- **Golden fixtures** from the archived Copilot source: RDWS plain (have), with `alias`,
  private, with tracing, with addons. M5.0 renders them.
- **moto has no App Runner backend** and no Express gateway (checked locally: moto 5.2.3 has no
  `apprunner` module; its ECS responses have no Express operations). botocore 1.43.105 does ship
  the `apprunner` model (37 operations, including every `Describe*`/`List*` we need) and the ECS
  `*ExpressGatewayService` operations. Plan: botocore `Stubber` with synthetic responses that are
  validated against that service model.
- **moto still covers the rest:** ECS, ELBv2, Route 53, ACM, IAM, EC2, CloudWatch. `terraform
  plan` against a local moto server for the rebuild resources (creates only) and the weighted
  records, as in ADR-0014/0015.
- **`terraform validate`** on every generated variant against the real provider schema.
- **check tests:** synthetic plans for each new phase, including a weight change plus one stray
  attribute (must fail), a retire plan that deletes one extra resource (must fail), and an import
  plan that replaces `aws_apprunner_service` (must fail).
- **Translation tests:** each §4.3 "decision required" row blocks without its key.
- **Runbook under shell stubs:** a failed gate stops the mutation (existing harness).

## 8. Real AWS end-to-end, and the eligibility risk

**Key risk: our sandbox account probably cannot create an App Runner service.** It was created
for ecsodus and, as far as recorded, never ran App Runner before 2026-04-30. "Closed to new
customers" means such accounts cannot create services. This was already open question 5 in
[council/README.md](council/README.md) and Astra's round-1 finding 15. If it holds:

- v0.2a cannot be tested with a real Copilot RDWS in our account (deploying one creates an App
  Runner service).
- v0.2b's App Runner side (custom-domain disassociation, retirement, the `Requests` metric gate)
  cannot be tested in our account.

**Step 1 (M5.0, needs approval, ~$0):** an eligibility probe. Read-only calls tell us nothing, so
the probe is one `create-auto-scaling-configuration` or a minimal `create-service` attempt,
deleted at once **(UNCONFIRMED: which call the closure blocks)**. Per the maintainer's rules it
needs an explicit yes.

**If eligible:** v0.2a e2e with the archived Copilot v1.34.1: app with `--domain`, env with
private placement (NAT), RDWS with `alias`, a DynamoDB addon with sentinel data. Run the full
v0.2a runbook; assert the service URL, the custom domain, the CNAMEs, the NAT gateways and the
sentinel data survive. Then v0.2b on the adopted service through retirement.

**If not eligible, in order of preference:**
1. A design partner's account with an existing RDWS: v0.2a inventory, report, generate and
   `terraform plan` (read-only; import plans do not mutate). Their apply is their decision.
2. An older account the maintainer controls that used App Runner before 2026-04-30 (open
   question 9).
3. Fallback in our sandbox: test v0.2b mechanics with a stand-in source: any HTTPS endpoint
   behind a CNAME (for example a second ALB) to exercise the atomic batch, weights, gates and
   rollback; App Runner reads from recorded responses. App Runner retirement then ships behind an
   **UNVERIFIED** banner and an `--i-understand-retire-is-unverified` flag, the ADR-0012
   precedent.

**A real domain is also needed** for ACM DNS validation and the custom-domain path. The v0.1
e2e never covered one (issue #6). Open question 10.

**Cost estimate (eligible case, one 4-hour run, us-east-1)** **(UNCONFIRMED: current prices)**:

| Item | Estimate |
|---|---|
| App Runner 1 instance, 0.25 vCPU / 0.5 GB, mostly idle | < $0.10 |
| NAT gateways ×2, 4 h + data | ~$0.40 |
| ALB 4 h + LCU | ~$0.10 |
| Fargate 0.25 vCPU / 0.5 GB, 1–2 tasks, 2 h | < $0.05 |
| Public IPv4 addresses | ~$0.10 |
| Route 53 hosted zone (free if deleted within 12 h) | $0 |
| Domain, if one must be registered | ~$3–15 / year |
| **Total** | **~$1–3**, plus any domain |

Every artifact is cleaned up afterwards, as in the 2026-10-07 run.

## 9. Milestones

| # | Deliverable |
|---|---|
| M5.0 | Eligibility probe (approval); RDWS fixtures (alias, private, tracing, addons); knowledge-base rows for App Runner resources; ADRs 0016–0023 |
| M5.1 | v0.2a mappers and out-of-band reads; report and generate; offline suite |
| M5.2 | v0.2a e2e (eligible account or design partner) → release 0.3.0 |
| M5.3 | Rebuild inventory, report, `decisions.yml`, Express predicate; standalone read-only report |
| M5.4 | Rebuild generate, `check` phases, `verify-cutover`, runbook; offline suite |
| M5.5 | Rebuild e2e (§8) → release 0.4.0 |

## 10. Risks

- **No App Runner-capable test account** (§8). Highest risk. Mitigation: probe first; design
  partner; stand-in source; UNVERIFIED gate.
- **Wrong translation causes an outage after cutover.** Mitigation: no guessed values, decisions
  file, desired count 0, gated weight steps, rollback window.
- **Double-running side effects.** Mitigation: required declaration, disabled until cutover.
- **DNS gap during conversion.** Mitigation: one atomic batch, never Terraform delete-then-create.
- **Grants that name the App Runner instance role do not follow the new task role.** Mitigation:
  report lists them; operator updates them before step 4.
- **App Runner deprecated further** (an end-of-support date). v0.2a then becomes a waypoint;
  v0.2b is the exit. The plan does not depend on App Runner's future.
- **Small audience.** RDWS is one of five Copilot workload types; standalone users are not
  served by generation. The read-only report measures demand before more is built.

## 11. Open questions for the council

1. Release numbering: v0.2a as 0.3.0 and v0.2b as 0.4.0, or rename the PLAN scope?
2. Is (b) read-only in v0.2b the right line, or should rebuild generation cover standalone
   image-based services from the start, since the rebuild does not need the owner until retirement?
3. Should rebuild require v0.2a first for Copilot users, or also accept a still-Copilot RDWS (with
   its stack retain-patched but kept)?
4. Default target: plain ECS + ALB, Express opt-in. Agree? And new ALB per service, or a host
   rule on the env's (Terraform-owned) ALB, which saves an ALB but couples them?
5. Flat resources for new compute, or `terraform-aws-modules/ecs` as PLAN §5 allows?
6. `AutoScalingConfigurationArn`: import custom configurations as
   `aws_apprunner_auto_scaling_configuration_version`, or reference them? AWS-managed ones are
   external references.
7. Private App Runner services (ingress connection): blocked in rebuild, or support with an
   internal ALB and a private hosted zone the operator owns?
8. Tracing: block in rebuild until ADOT (v0.3), or allow with an explicit "tracing will stop"
   acknowledgement?
9. Does the maintainer have an AWS account that used App Runner before 2026-04-30?
10. Which domain do we use for the custom-domain e2e (v0.1 issue #6 has the same need)?
11. Is retirement inside ecsodus's runbook at all, or should the runbook stop at 100 % and leave
    deletion to the operator, so ecsodus never writes a destructive step?
12. Should `verify-cutover` read CloudWatch metrics and alarms (read-only, but new IAM
    permissions for the operator), or leave health judgement to the operator?
13. `StartCommand`: always require the operator's list, or accept `["sh","-c", …]` when the image
    has a shell (which ecsodus cannot see)?

## 12. Draft ADR outlines (not yet files)

- **ADR-0016: Copilot RDWS hands off in adopt-in-place.** RDWS becomes a supported workload type.
  `AWS::AppRunner::Service`, `VpcConnector`, `VpcIngressConnection` and
  `ObservabilityConfiguration` import as their `aws_apprunner_*` resources; the custom-domain
  association, its CNAME and validation CNAMEs import as out-of-band objects. The retain patch,
  change-set rule and gates apply unchanged. The image identifier is ignored after import; CI is
  the named deploy owner. Source-code services stay blocked.
- **ADR-0017: Rebuild mode starts from a Terraform-owned App Runner service.** Copilot users run
  v0.2a first. Rebuild never runs while a Copilot stack owns the service, so no custom-resource
  handler or env-controller can act during a cutover.
- **ADR-0018: Rebuild target is a plain ECS service behind an ALB; Express is opt-in.** Copilot
  RDWS egress uses private subnets, which Express maps to an internal ALB. Express is offered
  only when the extended predicate holds. New compute is flat root resources.
- **ADR-0019: Rebuild values come from live reads or an operator decisions file, never guesses.**
  Scaling target, TCP-to-HTTP health checks, out-of-range health settings, start command, egress
  for `DEFAULT` services and background work are decisions. A missing decision blocks generation.
- **ADR-0020: Cutover by an atomic Route 53 batch, then Terraform-managed weights.** The simple
  record becomes a weighted pair in one change batch; weights then change by gated applies. ecsodus
  never shifts traffic. The default App Runner URL cannot move, and the retire gate measures it.
- **ADR-0021: Retirement is a separate, gated destructive phase.** Only the App Runner manifest set
  may be deleted, only after TTL + 24 h and zero App Runner requests, with `prevent_destroy`
  removed in a reviewed edit. The runbook states that there is no rollback afterwards.
- **ADR-0022: Standalone App Runner services are report-only in v0.2.** The source adapter and
  model are shared; generation waits for demand and an owner model.
- **ADR-0023: Testing App Runner without an eligible account.** botocore `Stubber` against the
  shipped service model offline; eligibility probe with approval; design-partner plans; a
  stand-in source for cutover mechanics; UNVERIFIED gate for anything not run on real App Runner.
