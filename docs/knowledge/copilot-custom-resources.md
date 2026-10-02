# Copilot custom resources: what they do, and what their Delete handlers destroy

*Source: the archived AWS Copilot CLI repository (Apache-2.0), commit `a0dbe689` ("fix __inner override").
Everything below comes from reading that source. File paths are relative to the repository root. Anything
we could not confirm in the source is marked **(UNCONFIRMED)**. Statements about how CloudFormation or
AWS behaves in general (not Copilot's own code) are labelled as CloudFormation or AWS behaviour.*

Copilot ships 14 Node.js files in `cf-custom-resources/lib/`. Thirteen of them back `Custom::*`
resources. One, `backlog-per-task-calculator.js`, is a Lambda that runs on a schedule and is not a
custom resource. `make package-custom-resources` minifies each file into
`internal/pkg/template/templates/custom-resources/`. At deploy time
`internal/pkg/deploy/upload/customresource/customresource.go` zips each one as `index.js` and uploads it
to the app's artifact bucket. The templates then reference the zip through
`{{ index .CustomResources "<FunctionName>" }}` (`S3Bucket`/`S3Key`). Every custom-resource Lambda
runs on `nodejs20.x`.

## How files map to Lambda functions and `Custom::` types

`customresource.go` maps a **function logical ID** to a **source file**, and the mapping differs
by stack kind. Two `Custom::` type names each map to more than one file, depending on the stack:

| Stack kind (function in `customresource.go`) | Function logical ID → file |
|---|---|
| Env (`Env`) | `CertificateValidationFunction` → `dns-cert-validator.js`; `CustomDomainFunction` → `custom-domain.js`; `DNSDelegationFunction` → `dns-delegation.js`; `CertificateReplicatorFunction` → `cert-replicator.js`; `BucketCleanerFunction` → `bucket-cleaner.js`; `UniqueJSONValuesFunction` → `unique-json-values.js` |
| Load Balanced Web Service (`LBWS`) | `DynamicDesiredCountFunction` → `desired-count-delegation.js`; `EnvControllerFunction` → `env-controller.js`; `RulePriorityFunction` → `alb-rule-priority-generator.js`; `NLBCustomDomainFunction` → `wkld-custom-domain.js`; `NLBCertValidatorFunction` → `wkld-cert-validator.js` |
| Backend Service (`Backend`) | `DynamicDesiredCountFunction` → `desired-count-delegation.js`; `RulePriorityFunction` → `alb-rule-priority-generator.js`; `EnvControllerFunction` → `env-controller.js` |
| Worker Service (`Worker`) | `DynamicDesiredCountFunction` → `desired-count-delegation.js`; `BacklogPerTaskCalculatorFunction` → `backlog-per-task-calculator.js`; `EnvControllerFunction` → `env-controller.js` |
| Request-Driven Web Service (`RDWS`) | `EnvControllerFunction` → `env-controller.js`; `CustomDomainFunction` → **`custom-domain-app-runner.js`** |
| Static Site (`StaticSite`) | `TriggerStateMachineFunction` → `trigger-state-machine.js`; `CertificateValidationFunction` → **`wkld-cert-validator.js`**; `CustomDomainFunction` → **`wkld-custom-domain.js`** |
| Scheduled Job (`ScheduledJob`) | `EnvControllerFunction` → `env-controller.js` |

**Ambiguous type names.** `Custom::CustomDomainFunction` is backed by three different files, and
`Custom::CertificateValidationFunction` by two. A tool must use the stack kind to tell them apart,
not just the type. The resource properties also differ:
- env `CustomDomainAction` has `PublicAccessHostedZone` and a JSON-string `Aliases`
- RDWS has `ServiceARN`/`CustomDomain`
- static site has `PublicAccessHostedZoneID`/`ServiceName`
- the env `CertificateValidationFunction` has `Handler: index.certificateRequestHandler`, while
  static site uses `index.handler`

## Summary table

"Destructive" means the Delete handler removes or changes something that outlives the handle:
a certificate, a DNS record, bucket contents, or resources in another stack. ecsodus fate, from
PLAN.md §2.2:
- Every `Custom::*` handle and its Lambda, role and log group are `manual-cleanup`, and
  **always retain-patched**, so no stack delete ever invokes a Delete handler.
- The out-of-band objects a handler created are `import`.

| File | `Custom::` type (logical IDs) | Stack | Creates outside CloudFormation | Delete handler | Destructive | Terraform equivalent | v0.1 scope |
|---|---|---|---|---|---|---|---|
| `alb-rule-priority-generator.js` | `Custom::RulePriorityFunction` (`HTTPRulePriorityAction`, `HTTPSRulePriorityAction`, `HTTPRuleWithDomainPriorityAction`, `HTTPRedirectRulePriorityAction`) | LBWS, Backend | nothing | no-op | no | literal `priority` on `aws_lb_listener_rule` | in |
| `backlog-per-task-calculator.js` | none (scheduled Lambda `BacklogPerTaskCalculatorFunction`) | Worker | CloudWatch EMF metric `BacklogPerTask` | none (not a custom resource) | no | `aws_lambda_function` + `aws_cloudwatch_event_rule`/`_target` + `aws_lambda_permission`, or a metric-math scaling policy | blocked (Worker) |
| `bucket-cleaner.js` | `Custom::BucketCleanerFunction` (`ELBAccessLogsBucketCleanerAction`) | env | nothing | **deletes every object version and delete marker** in the ELB access-logs bucket | **yes** | none (`aws_s3_bucket` with `force_destroy = false`) | in |
| `cert-replicator.js` | `Custom::CertificateReplicatorFunction` (`CertificateReplicator`) | env (CDN) | ACM certificate in `us-east-1` | waits until unused, then **`DeleteCertificate` (us-east-1)** | **yes** | `aws_acm_certificate` (us-east-1 provider alias) | blocked (CDN) |
| `custom-domain.js` | `Custom::CustomDomainFunction` (`CustomDomainAction`) | env | Route 53 A-alias records for each alias, in the env, app or root zone | **DELETEs every alias A record** | **yes** | `aws_route53_record` (A, alias) | in |
| `custom-domain-app-runner.js` | `Custom::CustomDomainFunction` (`CustomDomainAction`) | RDWS | App Runner custom-domain association; CNAME for the domain; ACM validation CNAMEs | **disassociates the domain, DELETEs the CNAME and the validation CNAMEs** | **yes** | `aws_apprunner_custom_domain_association` + `aws_route53_record` (CNAME) | blocked (RDWS) |
| `desired-count-delegation.js` | `Custom::DynamicDesiredCountFunction` (`DynamicDesiredCountAction`) | LBWS, Backend, Worker | nothing | no-op | no | `aws_ecs_service.desired_count` + `ignore_changes` | in |
| `dns-cert-validator.js` | `Custom::CertificateValidationFunction` (`HTTPSCert`) | env | ACM certificate `env.app.domain` + `*.env.app.domain` + aliases; validation CNAMEs in the env, app or root zone | waits until unused, **DELETEs validation CNAMEs not used by a newer cert, then `DeleteCertificate`** | **yes** | `aws_acm_certificate` + `aws_route53_record` (validation) (+ `aws_acm_certificate_validation`) | in |
| `dns-delegation.js` | `Custom::DNSDelegationFunction` (`DelegateDNSAction`) | env | NS record `env.app.domain` in the **app** hosted zone (through the app-account DNS role) | **DELETEs the NS delegation record** | **yes** | `aws_route53_record` (NS) in the app zone (app-account provider) | in |
| `env-controller.js` | `Custom::EnvControllerFunction` (`EnvControllerAction`) | every ECS workload, RDWS, job | nothing outside CFN, but it **updates the env stack's parameters** | **removes the workload from every `*Workloads` parameter and from `Aliases`, then runs `UpdateStack` on the env stack** | **yes (indirect)** | none: env resources become static Terraform resources | in |
| `trigger-state-machine.js` | `Custom::TriggerStateMachine` (`TriggerStateMachineAction`) | Static Site | S3 objects (through the `CopyAssetsStateMachine` execution) | no-op | no | none (CI `aws s3 sync`) | blocked (Static Site) |
| `unique-json-values.js` | `Custom::UniqueJSONValuesFunction` (`UniqueAliasesAction`) | env (CDN) | nothing | no-op | no | literal `aliases` list on `aws_cloudfront_distribution` | blocked (CDN) |
| `wkld-cert-validator.js` | `Custom::NLBCertValidatorFunction` (`NLBCertValidatorAction`); `Custom::CertificateValidationFunction` (`CertificateValidatorAction`) | LBWS (NLB); Static Site | ACM certificate (static site: us-east-1) tagged with app/env/svc; validation CNAMEs | **DELETEs this service's unshared validation CNAMEs, waits until unused, `DeleteCertificate`** | **yes** | `aws_acm_certificate` + `aws_route53_record` (validation) | blocked (NLB, Static Site) |
| `wkld-custom-domain.js` | `Custom::NLBCustomDomainFunction` (`NLBCustomDomainAction`); `Custom::CustomDomainFunction` (`CustomDomainAction`) | LBWS (NLB); Static Site | A-alias records for the aliases (to the NLB or CloudFront) | **DELETEs every alias A record** that still points at this target | **yes** | `aws_route53_record` (A, alias) | blocked (NLB, Static Site) |

**Nine of the thirteen custom resources have destructive Delete handlers.** The env-controller is
the most dangerous: its Delete never touches a resource directly, but the env-stack update it
triggers can delete the shared ALB, NAT gateways, internal ALB and **the EFS file system along with
its data**. That update can also cascade into `HTTPSCert` and `CustomDomainAction` (see below).

**How retain works for custom resources (CloudFormation behaviour).** With `DeletionPolicy: Retain`
on a `Custom::*` resource, CloudFormation does not send the Lambda a Delete request when the
resource leaves the stack. PLAN.md §2.4/§6 treats this as a hypothesis for the e2e run to confirm.
The "neutralizer" fallback exists in case it proves false. **(UNCONFIRMED here: not in the
Copilot source.)**

---

## alb-rule-priority-generator.js

- **Used by.** `workloads/partials/cf/alb.yml` defines `RulePriorityFunction` (handler
  `index.nextAvailableRulePriorityHandler`) and `RulePriorityFunctionRole`. The custom resources are in:
  - `http-listener.yml`: `HTTPRulePriorityAction`
  - `https-listener.yml`: `HTTPSRulePriorityAction`, `HTTPRuleWithDomainPriorityAction`
  - `imported-alb-resources.yml`: `HTTPSRulePriorityAction`, `HTTPRedirectRulePriorityAction`,
    `HTTPRulePriorityAction`

  All are `Type: Custom::RulePriorityFunction` with `ServiceToken: !GetAtt RulePriorityFunction.Arn`.
  They appear in LBWS and Backend stacks that have an ALB listener.
- **Properties.** `RulePath` (list), and `ListenerArn`, which comes from
  `!GetAtt EnvControllerAction.HTTPListenerArn`/`HTTPSListenerArn`, or the internal variants for
  Backend, or a literal imported-listener ARN.
- **Create/Update.** Calls `DescribeRules` on the listener (paginated).
  - Root paths (`/`): priority counts down from 50000. It is the lowest existing priority ≥ 48000,
    minus 1, or 50000 if none.
  - Other paths: it is the highest existing priority below 48000, plus 1, or 1.
  - Returns `Priority`, `Priority1`, `Priority2`, …, one per entry in `RulePath`. The
    `ListenerRule`s use them via `!GetAtt …PriorityAction.Priority{i}`.
  - Physical ID: `alb-rule-priority-<LogicalResourceId>`.
- **Out of band.** Nothing.
- **Delete.** `case "Delete": break;`, a no-op.
- **Destructive.** No.
- **Terraform.** The output is just a number. Read the live rule's priority and write it as a
  literal `priority` on the imported `aws_lb_listener_rule`.
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched. There is nothing
  out-of-band to import.

## backlog-per-task-calculator.js

- **Used by.** `workloads/partials/cf/autoscaling.yml` renders it only under
  `{{- if .Autoscaling.QueueDelay }}` (Worker Service):
  - `BacklogPerTaskCalculatorFunction` (`index.handler`)
  - `BacklogPerTaskCalculatorRole`
  - `BacklogPerTaskCalculatorLogGroup`
  - `BacklogPerTaskScheduledRule` (`AWS::Events::Rule`, `rate(1 minute)`)
  - `PermissionToInvokeBacklogPerTaskCalculatorLambda`

  **It is not a custom resource.** It has no `Custom::` type and no CloudFormation handler.
- **What it does.** Each minute it reads the ECS service's `runningCount` and each SQS queue's
  `ApproximateNumberOfMessages`. It logs an EMF record for the metric `BacklogPerTask`
  (dimension `QueueName`, namespace from `NAMESPACE`), computed as
  `ceil(messages / max(runningCount,1))`. The step/target-tracking scaling policies
  (`AutoScalingPolicyEventsQueue`, `AutoScalingPolicy<svc><topic>EventsQueue`) scale on that
  metric.
- **Out of band.** CloudWatch metric data only.
- **Delete.** None.
- **Destructive.** No. But note that removing it silently breaks queue-based scaling, because
  the metric stops being published.
- **Terraform.** Keep it as `aws_lambda_function` + `aws_cloudwatch_event_rule` +
  `aws_cloudwatch_event_target` + `aws_lambda_permission`, or replace it with a target-tracking
  policy that uses metric math over SQS and ECS metrics **(UNCONFIRMED design option)**.
- **ecsodus fate.** Imported (ADR-0014): the function (code ignored after import), the rule and
  its target, and the permission. It is load-bearing, so it is never `manual-cleanup`.

## bucket-cleaner.js

- **Used by.** `environment/partials/elb-access-logs.yml`, which is included in
  `environment/cf.yml` only when `.PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket` is true:
  - `ELBAccessLogsBucketCleanerAction`: `Type: Custom::BucketCleanerFunction`,
    `ServiceToken: !GetAtt BucketCleanerFunction.Arn`, `BucketName: !Ref ELBAccessLogsBucket`
  - `BucketCleanerFunction` (Timeout 900)
  - `ELBAccessLogsBucketCleanerRole`, which is granted `s3:ListBucket`, `s3:ListBucketVersions`,
    `s3:DeleteObject` and `s3:DeleteObjectVersion` on the bucket
- **Create/Update.** No-op. Physical ID: `bucket-cleaner-<LogicalResourceId>`.
- **Out of band.** Nothing.
- **Delete.**
  1. `HeadBucket`, then loop `ListObjectVersions` → `DeleteObjects` (Quiet) over **all `Versions`
     and all `DeleteMarkers`**, following `NextKeyMarker`/`NextVersionIdMarker` until
     `IsTruncated` is false.
  2. If any object fails to delete, it throws an `AggregateError` and the stack reports FAILED.
  3. It returns early only if `HeadBucket` throws `ResourceNotFoundException`. S3's `HeadBucket`
     normally reports a missing bucket as `NotFound`, so a bucket that is already gone probably
     makes the Delete fail **(UNCONFIRMED: SDK error name)**.
- **Destructive.** **Yes.** It permanently empties the versioned access-logs bucket, so CloudFormation
  can then delete the bucket, which has no `DeletionPolicy`.
- **Terraform.** No equivalent is needed. Import the bucket (`aws_s3_bucket` + versioning,
  encryption, public-access-block and policy sub-resources) and never set `force_destroy`.
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched. `ELBAccessLogsBucket` and
  `ELBAccessLogsBucketPolicy` are `import`.

## cert-replicator.js

- **Used by.** `environment/partials/cdn-resources.yml` (only when `.CDNConfig` is set, and only
  when not `.PublicHTTPConfig.ImportedCertARNs`):
  - `CertificateReplicatorFunction` (`index.certificateReplicateHandler`, `Condition: DelegateDNS`)
  - `CertificateReplicator`: `Type: Custom::CertificateReplicatorFunction`,
    `Condition: DelegateDNS`, `TargetRegion: "us-east-1"`, `EnvRegion: !Ref AWS::Region`,
    `CertificateArn: !Ref HTTPSCert`

  `CloudFrontDistribution` uses `AcmCertificateArn: !Ref CertificateReplicator`.
- **Create/Update.**
  1. Runs `DescribeCertificate` on the env cert, then `RequestCertificate` in `us-east-1` with the
     same `DomainName` and SANs, `ValidationMethod: DNS`, and tags
     `copilot-application`/`copilot-environment`.
  2. Waits up to 570 s for `CertificateValidated`. It writes no DNS records of its own, so it
     relies on the validation CNAMEs that `HTTPSCert` already created **(UNCONFIRMED: this is an
     inference; the code only waits)**.
  3. Physical ID = the new certificate ARN. **Every Update requests a new certificate**, and
     CloudFormation then sends Delete for the old physical ID.
- **Out of band.** An ACM certificate in us-east-1.
- **Delete.** Runs only if the physical ID starts with `arn:`.
  1. Polls `DescribeCertificate` until `InUseBy` is empty: up to 10 attempts, 30 s apart. If the
     cert is still in use, it throws and the stack reports FAILED.
  2. `DeleteCertificate` in us-east-1. `ResourceNotFoundException` is ignored.
- **Destructive.** **Yes.** It deletes the CloudFront certificate.
- **Terraform.** `aws_acm_certificate` with a `provider = aws.us_east_1` alias.
- **ecsodus fate.** The CDN is `blocked` in v0.1. If migrated later: the handle is
  `manual-cleanup` and retain-patched, and the us-east-1 cert is `import`.

## custom-domain.js (env stack)

- **Used by.** `environment/partials/lambdas.yml` defines `CustomDomainFunction`
  (`Condition: ManagedAliases`, `index.handler`). `environment/partials/custom-resources.yml`
  defines `CustomDomainAction`:
  - `Type: Custom::CustomDomainFunction`, `Condition: ManagedAliases`
  - `Aliases: !Ref Aliases` (the env parameter the env-controller maintains, a JSON map of
    workload → aliases)
  - `AppDNSRole: !Ref AppDNSDelegationRole`
  - `PublicAccessDNS`/`PublicAccessHostedZone`: the public ALB's `DNSName` and
    `CanonicalHostedZoneID`, or CloudFront's domain and `Z2FDTNDATAQYW2` when a CDN is configured

  Both are rendered only when not `.PublicHTTPConfig.ImportedCertARNs`.
- **Create.** For every alias in the flattened `Aliases` JSON, it classifies the alias by regex:
  - env zone `^([^.]+.)?env.app.domain`: uses the env-account Route 53 client
  - app zone `app.domain`: uses the client that assumes `AppDNSDelegationRole`
  - root zone `domain`: uses the same app-role client
  - other: skipped

  It looks up the zone with `ListHostedZonesByName(MaxItems 1)`, without checking that the
  returned name matches exactly, then UPSERTs an **A alias** record to
  `PublicAccessDNS`/`PublicAccessHostedZone` with `EvaluateTargetHealth: true`. Physical ID =
  `LogicalResourceId`.
- **Update.** UPSERTs the current aliases, then DELETEs the aliases that were in
  `OldResourceProperties.Aliases` but are no longer present.
- **Out of band.** One A-alias record per alias, in the env, app or root hosted zone. Records in
  the app and root zones live in the **app (DNS) account**.
- **Delete.** DELETEs the A-alias record for **every** current alias, pointing at the current
  target. A "Tried to delete resource record set … but it was not found" error is ignored.
- **Destructive.** **Yes.** Custom domains stop resolving.
- **Terraform.** `aws_route53_record` (type `A`, `alias {}`), one per alias, in the right zone and
  provider (the app-account provider for app and root zones).
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched. Each alias record is
  `import`. Inventory must find them through Route 53, because no stack owns them.

## custom-domain-app-runner.js (RDWS)

- **Used by.** `workloads/services/rd-web/cf.yml`:
  - `CustomDomainFunction` (`index.handler`)
  - `CustomDomainAction`: `Type: Custom::CustomDomainFunction`,
    `ServiceARN: !GetAtt Service.ServiceArn`, `CustomDomain`, `AppDNSRole`, `AppDNSName`
- **Create/Update.**
  1. `AssociateCustomDomain` (an "already associated" error is tolerated and
     `DescribeCustomDomains` is used instead).
  2. In parallel:
     - UPSERT a **CNAME** `CustomDomain → DNSTarget`
     - poll up to 10 times for `pending_certificate_dns_validation`, then UPSERT every
       `CertificateValidationRecords` CNAME

     Both go into the hosted zone found by `ListHostedZonesByName(AppDNSName)`, using the
     app-role client.
  3. Physical ID: `/associate-domain-app-runner/<CustomDomain>`.
- **Out of band.** The App Runner custom-domain association (with its App Runner-managed
  certificate), the domain CNAME, and the validation CNAMEs.
- **Delete.**
  1. `DisassociateCustomDomain`. If the error is "No custom domain … found", it returns.
  2. DELETE the domain CNAME and every validation CNAME. Not-found errors are ignored.
  3. Poll (up to 20 attempts, with backoff) until the domain is no longer listed. `delete_failed`
     throws.
- **Destructive.** **Yes.**
- **Terraform.** `aws_apprunner_custom_domain_association` + `aws_route53_record` (CNAME, and the
  validation CNAMEs).
- **ecsodus fate.** RDWS is `blocked` in v0.1. App Runner is covered in v0.2.

## desired-count-delegation.js

- **Used by.** `workloads/partials/cf/autoscaling.yml` (only when `.Autoscaling` is set):
  - `DynamicDesiredCountAction`: `Type: Custom::DynamicDesiredCountFunction`, with `Cluster`
    (import `${AppName}-${EnvName}-ClusterId`), `App`, `Env`, `Svc`,
    `DefaultDesiredCount: !Ref TaskCount`, and `UpdateID: {{ randomUUID }}`, which forces an
    Update on every deploy
  - `DynamicDesiredCountFunction`
  - `DynamicDesiredCountFunctionRole`

  `service-base-properties.yml` sets `DesiredCount: !GetAtt DynamicDesiredCountAction.DesiredCount`
  when autoscaling is on and `DesiredCountOnSpot` is not.
- **Create/Update.**
  1. Tagging API `GetResources(ecs:service)` filtered on `copilot-application`,
     `copilot-environment` and `copilot-service`. If exactly one match, runs `DescribeServices`
     and returns its `desiredCount`; otherwise `DefaultDesiredCount`.
  2. **Any error still reports SUCCESS**, with `DefaultDesiredCount`.
  3. Physical ID: `copilot/apps/<app>/envs/<env>/services/<svc>/autoscaling`.
- **Out of band.** Nothing.
- **Delete.** No-op.
- **Destructive.** No.
- **Terraform.** `aws_ecs_service.desired_count` with
  `lifecycle { ignore_changes = [desired_count] }` (PLAN §2.4). The live count is authoritative,
  and the template's `TaskCount` is recorded as `disputed`.
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched.

## dns-cert-validator.js (env `HTTPSCert`)

- **Used by.** `environment/partials/lambdas.yml` defines `CertificateValidationFunction`
  (`Condition: DelegateDNS`, `index.certificateRequestHandler`, Timeout 900).
  `environment/partials/custom-resources.yml` defines `HTTPSCert`:
  - `Type: Custom::CertificateValidationFunction`, `Condition: DelegateDNS`
  - `DependsOn` `DelegateDNSAction` and `EnvironmentHostedZone`
  - properties `AppName`, `EnvName`, `DomainName: !Ref AppDNSName`, `Aliases: !Ref Aliases`,
    `EnvHostedZoneId`, `Region`, `RootDNSRole: !Ref AppDNSDelegationRole`

  `HTTPSListener` uses `CertificateArn: !Ref HTTPSCert` (unless imported certs are used).
  `CertificateReplicator` copies it.
- **Create.**
  1. `RequestCertificate`:
     - `DomainName = <env>.<app>.<domain>`
     - SANs = that name, `*.<env>.<app>.<domain>`, and every alias from the `Aliases` JSON that
       falls in the env, app or root zone
     - DNS validation, tagged `copilot-application`/`copilot-environment`
  2. Physical ID = the cert ARN, set immediately.
  3. Waits for `DomainValidationOptions`, then UPSERTs each validation CNAME:
     - env-zone names into `EnvHostedZoneId` (env account)
     - app and root names into the zone found by name, through the `RootDNSRole` client
  4. Waits up to 570 s for `CertificateValidated`.
- **Update.** Does nothing unless the alias set changed. If it changed, it requests a **new**
  certificate (new physical ID) and validates it. CloudFormation then sends **Delete for the old
  certificate** during cleanup.
- **Out of band.** The ACM certificate and its validation CNAMEs (env zone; app and root zones in
  the app account).
- **Delete.** Runs only if the physical ID starts with `arn:`.
  1. Polls up to 10 × 30 s until `InUseBy` is empty and every option has a `ResourceRecord`. If
     the cert is still in use, it throws.
  2. `deleteHostedZoneRecords`:
     - It runs `ListCertificates` for another certificate with the same `DomainName` (a "new"
       cert).
     - It **DELETEs every validation CNAME of the old cert whose domain is not a SAN of that new
       cert**, de-duplicated by name and value.
     - On a plain stack delete there is usually no newer cert, so **all** its validation records
       are deleted.
  3. `DeleteCertificate`. `ResourceNotFoundException` is swallowed.

  (The error path in `deleteHostedZoneRecords` references an undefined `option` variable, so any
  unexpected Route 53 error surfaces as a `ReferenceError`. Either way the stack reports FAILED.)
- **Destructive.** **Yes.** It deletes the listener's certificate and the DNS validation records.
  Deleting a validation record also stops ACM from auto-renewing any cert that shares it.
- **Terraform.** `aws_acm_certificate` (import), `aws_route53_record` for each validation CNAME
  (import), and optionally `aws_acm_certificate_validation`. That last one is a wait-only
  resource: it cannot be imported and creates no AWS object **(UNCONFIRMED: provider behaviour)**.
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched. The certificate and each
  validation record are `import`.

## dns-delegation.js (env `DelegateDNSAction`)

- **Used by.** `environment/partials/lambdas.yml` defines `DNSDelegationFunction`
  (`Condition: DelegateDNS`, `index.domainDelegationHandler`).
  `environment/partials/custom-resources.yml` defines `DelegateDNSAction`:
  - `Type: Custom::DNSDelegationFunction`, `Condition: DelegateDNS`
  - `DomainName: !Sub ${AppName}.${AppDNSName}`
  - `SubdomainName: !Sub ${EnvironmentName}.${AppName}.${AppDNSName}`
  - `NameServers: !GetAtt EnvironmentHostedZone.NameServers`
  - `RootDNSRole: !Ref AppDNSDelegationRole`
- **Create/Update.**
  1. Assumes `RootDNSRole`, which is the app account's `<app>-DNSDelegationRole` (from
     `templates/app/app.yml`, `DNSDelegationRole`).
  2. Runs `ListHostedZonesByName(DomainName)` and takes `HostedZones[0]` **without checking an
     exact name match**.
  3. UPSERTs an **NS** record `SubdomainName` (TTL 60) with the env zone's name servers.
  4. Physical ID = `SubdomainName`.
- **Out of band.** The NS delegation record for `env.app.domain` inside the **app hosted zone**
  (`AppHostedZone` in the app stack, in the app account). CloudFormation never sees this record.
- **Delete.**
  1. Same zone lookup.
  2. `ListResourceRecordSets(StartRecordName=SubdomainName, StartRecordType=NS, MaxItems=1)`. If
     the first record is exactly `SubdomainName.` of type NS, it **DELETEs it** and waits for the
     change. Otherwise it returns.
- **Destructive.** **Yes.** Once the delegation is removed, every name under `env.app.domain`
  (the service default aliases, and `HTTPSCert` renewals) stops resolving publicly.
- **Terraform.** `aws_route53_record` (type `NS`) in the app zone, managed with the app-account
  provider.
- **ecsodus fate.** The handle is `manual-cleanup` and retain-patched. The NS record is `import`.
  Note that it lives in the app/DNS account, not the env account.

## env-controller.js (`EnvControllerAction`)

- **Used by.** `workloads/partials/cf/env-controller.yml`, included by the templates for lb-web,
  backend, worker, rd-web and scheduled-job:
  - `EnvControllerAction`: `Type: Custom::EnvControllerFunction`,
    `ServiceToken: !GetAtt EnvControllerFunction.Arn`
  - `EnvControllerFunction` (Timeout 900)
  - `EnvControllerRole`: `cloudformation:DescribeStacks`/`UpdateStack` on
    `stack/${AppName}-${EnvName}/*`, plus `iam:PassRole` on `${AppName}-${EnvName}-CFNExecutionRole`,
    both conditioned on the copilot tags

  The properties of `EnvControllerAction`:
  - `Workload: !Ref WorkloadName`
  - `EnvStack: !Sub '${AppName}-${EnvName}'`
  - `Parameters: {{ envControllerParams . }}`
  - `EnvVersion`
  - `Aliases`, only for an LBWS with ALB aliases and no imported ALB

  `internal/pkg/deploy/cloudformation/cloudformation.go` references the type
  (`envControllerResourceType`) for progress rendering.
- **Which parameters a workload requests.** From `envControllerParameters` in
  `internal/pkg/template/workload.go`:
  - LBWS without an imported ALB: `ALBWorkloads` (if the ALB is enabled) and `Aliases`
  - Backend with an ALB and no imported ALB: `InternalALBWorkloads`
  - RDWS that is private without an existing endpoint: `AppRunnerPrivateWorkloads`
  - any workload with `network.vpc.placement: private` (`PrivateSubnets`): `NATWorkloads`
  - any workload with a Copilot-managed EFS volume (`Storage.ManagedVolumeInfo != nil`):
    `EFSWorkloads`
- **Create/Update.** `controlEnv`:
  1. `DescribeStacks` the env stack.
  2. For every parameter ending in `Workloads`: add this workload to the comma list if it was
     requested, and remove it if it was not.
  3. Rewrite the `Aliases` JSON if this workload's alias list changed. An empty list removes the
     key, and an empty map becomes `""`.
  4. If nothing changed, return the env Outputs (minus `EnabledFeatures` and `LastForceDeployID`,
     to stay under 4 KB) without updating.
  5. Otherwise run `UpdateStack` with `UsePreviousTemplate: true`, the same capabilities, and
     `RoleARN` = the env's `CFNExecutionRoleARN` output. If the stack is already
     `UPDATE_IN_PROGRESS`, wait and retry.
  6. Wait for `StackUpdateComplete` (up to 870 s) and return the new env Outputs. Workload
     templates consume these through `!GetAtt EnvControllerAction.<Output>`, for example
     `HTTPListenerArn`, `PublicLoadBalancerDNSName`, `EnvironmentSecurityGroup` and
     `InternalWorkloadsHostedZone`.
  7. There is a 14.5-minute deadline. Physical ID: `envcontoller/<EnvStack>/<Workload>` (sic).
- **Out of band.** Nothing outside CloudFormation. It **mutates another stack**: every shared env
  feature (the ALB, internal ALB, NAT gateways, EFS, App Runner VPC endpoint) exists only while at
  least one workload's name is in the matching parameter (see `copilot-stacks.md`, env
  conditions).
- **Delete.** `controlEnv(EnvStack, Workload, [])`, with no `Parameters` argument:
  - the workload is **removed from every `*Workloads` parameter** it appears in
  - its key is removed from `Aliases`
  - then the env stack runs `UpdateStack` with `UsePreviousTemplate: true`
- **What that env update deletes, when this was the last workload using a feature:**
  - `ALBWorkloads` → "" makes `CreateALB` false. Deleted: `PublicLoadBalancer`, `HTTPListener`,
    `HTTPSListener`, `DefaultHTTPTargetGroup`, both public-LB security groups and their ingress
    rules, `ELBAccessLogsBucketPolicy`, `UniqueAliasesAction`/`UniqueJSONValuesFunction`/role,
    and `CloudFrontDistribution`. `ManagedAliases` also becomes false, which deletes
    `CustomDomainAction` and fires the destructive `custom-domain.js` Delete handler that removes
    the A records.
  - `InternalALBWorkloads` → "": deleted: `InternalLoadBalancer`, the internal listeners,
    `DefaultInternalHTTPTargetGroup`, `InternalLoadBalancerSecurityGroup` and its ingress rules,
    and `InternalWorkloadsHostedZone`.
  - `NATWorkloads` → "": deleted: every `NatGateway{n}`, `NatGateway{n}Attachment` (EIP),
    `PrivateRouteTable{n}`, `PrivateRoute{n}` and `PrivateRouteTable{n}Association`.
  - `EFSWorkloads` → "": deleted: **`FileSystem` (the data too)**, `MountTarget{n}`,
    `EFSSecurityGroup` and `EFSSecurityGroupIngressFromEnvironment`.
  - `AppRunnerPrivateWorkloads` → "": deleted: `AppRunnerVpcEndpoint` and its security group and
    ingress rule.
  - An `Aliases` change (the workload had aliases) updates `HTTPSCert`, which requests a new cert.
    CloudFormation then sends Delete for the old cert (the `dns-cert-validator.js` Delete).
    `CertificateReplicator` updates too.
- **Destructive.** **Yes, indirectly.** This is PLAN §1's "env-controller" landmine.
- **Terraform.** None. After migration these env resources are plain, unconditional Terraform
  resources. The outputs the workload consumed become references to them.
- **ecsodus fate.** The handle is `manual-cleanup` and **must be retain-patched in every
  workload stack before any workload stack is deleted**.

  Note (CloudFormation behaviour): the env-controller uses `UsePreviousTemplate: true`, so an
  env-controller update after the env stack is retain-patched keeps the patch. And a resource
  whose condition turns false during an update is removed from the stack under its
  `DeletionPolicy`, so with `Retain` it is orphaned rather than deleted. Retaining
  `EnvControllerAction` itself is still what stops the parameter change from happening at all.

## trigger-state-machine.js

- **Used by.** `workloads/services/static-site/cf.yml`:
  - `TriggerStateMachineFunction`
  - `TriggerStateMachineAction`: `Type: Custom::TriggerStateMachine` (note: no `Function`
    suffix), with `StateMachineARN: !GetAtt CopyAssetsStateMachine.Arn` and
    `AssetMappingFilePath`
- **Create/Update.** `StartSyncExecution` on the state machine, which copies the site assets
  into `Bucket`. It fails if the status is not `SUCCEEDED`. Deadline 14 min. Physical ID =
  `LogicalResourceId`.
- **Out of band.** S3 objects in the static-site bucket, written by the state machine.
- **Delete.** No-op (the comment says "this isn't a 'real' resource").
- **Destructive.** No.
- **Terraform.** None. Asset upload becomes a CI step.
- **ecsodus fate.** Static Site is `blocked` in v0.1.

## unique-json-values.js

- **Used by.** `environment/partials/cdn-resources.yml` (CDN, and imported cert or DelegateDNS):
  - `UniqueJSONValuesFunctionRole`, `Condition: CreateALB`
  - `UniqueJSONValuesFunction`, `Condition: CreateALB`
  - `UniqueAliasesAction`: `Type: Custom::UniqueJSONValuesFunction`, `Condition: CreateALB`,
    `Aliases: !Ref Aliases`, `FilterFor: !Ref ALBWorkloads`, and optional `AdditionalStrings`
    (the static CDN alias)
- **Create/Update.** Parses the `Aliases` JSON and keeps the keys listed in `FilterFor`.
  Returns `UniqueValues`: the sorted, de-duplicated union of their aliases plus
  `AdditionalStrings`. `CloudFrontDistribution` uses it as
  `Aliases: !GetAtt UniqueAliasesAction.UniqueValues`.
- **Out of band.** Nothing.
- **Delete.** No-op.
- **Destructive.** No.
- **Terraform.** A literal `aliases = [...]` on `aws_cloudfront_distribution`.
- **ecsodus fate.** The CDN is `blocked` in v0.1.

## wkld-cert-validator.js

- **Used by.**
  - `workloads/partials/cf/nlb.yml` (LBWS with an NLB, when `.NLB.CertificateRequired`):
    `NLBCertValidatorAction`: `Type: Custom::NLBCertValidatorFunction`,
    `Condition: HasAssociatedDomain`, `LoadBalancerDNS`, `Aliases`; plus
    `NLBCertValidatorFunction`/`Role`
  - `workloads/services/static-site/cf.yml`: `CertificateValidatorAction`:
    `Type: Custom::CertificateValidationFunction`, `IsCloudFrontCertificate: true`; plus
    `CertificateValidationFunction`/`CertificateValidatorRole`
- **Create/Update.** Update does nothing unless the alias set changed; otherwise it behaves like
  Create.
  1. Validate the aliases: an existing A record that is not this LB's alias throws "already in
     use".
  2. `RequestCertificate`:
     - `DomainName` = `<svc>-nlb.<env>.<app>.<domain>`, or `<svc>.<env>.<app>.<domain>` for
       CloudFront, where the ACM client is pinned to `us-east-1`
     - SANs = the aliases
     - tagged `copilot-application`, `copilot-environment`, `copilot-service`
     - IdempotencyToken = md5(`/<svc>/<sorted aliases>`)
  3. UPSERT the validation CNAMEs (env zone in the env account; app and root zones through
     `RootDNSRole`).
  4. Wait for validation.
  5. Physical ID = the cert ARN.
- **Out of band.** The ACM certificate and its validation CNAMEs.
- **Delete.** Runs only if the physical ID starts with `arn:`.
  1. `unusedValidationOptions`:
     - find this service's certificates through the tagging API (app/env/svc tags,
       `acm:certificate`)
     - drop validation records shared with the service's other certs
     - for each remaining one, keep it if the alias's A record points at a *different* LB.
       Unrecognised domains are kept, and for CloudFront every existing record counts as "mine".
  2. `devalidate`: DELETE the remaining validation CNAMEs. "Not found" is ignored.
  3. `deleteCertificate`: poll up to 12 × 30 s for `InUseBy` to be empty (still in use → throw),
     then `DeleteCertificate`.
- **Destructive.** **Yes.**
- **Terraform.** `aws_acm_certificate` (us-east-1 provider for CloudFront) + `aws_route53_record`
  for each validation CNAME.
- **ecsodus fate.** NLB and Static Site are `blocked` in v0.1.

## wkld-custom-domain.js

- **Used by.**
  - `workloads/partials/cf/nlb.yml` (NLB with `.NLB.Aliases`): `NLBCustomDomainAction`:
    `Type: Custom::NLBCustomDomainFunction`, `Condition: HasAssociatedDomain`,
    `PublicAccessDNS`/`PublicAccessHostedZoneID` = the NLB; plus `NLBCustomDomainFunction`/`Role`
  - `workloads/services/static-site/cf.yml` (alias without an imported cert):
    `CustomDomainAction`: `Type: Custom::CustomDomainFunction`, pointing at CloudFront
    (`Z2FDTNDATAQYW2`)
- **Create.** Validates the aliases (same "already in use" check as above), then UPSERTs an
  **A alias** record for each alias in the env, app or root zone. Physical ID =
  `LogicalResourceId`.
- **Update.** Returns early if the aliases, target DNS and hosted zone are all unchanged.
  Otherwise it validates, UPSERTs the new records, and DELETEs aliases that are no longer present
  (using the old target).
- **Out of band.** The A-alias records.
- **Delete.** DELETEs the A record for every alias, using the current target. Errors are
  ignored in two cases:
  - "not found"
  - "values provided do not match", meaning the record now points elsewhere and is left alone
- **Destructive.** **Yes.**
- **Terraform.** `aws_route53_record` (A, alias).
- **ecsodus fate.** NLB and Static Site are `blocked` in v0.1.
