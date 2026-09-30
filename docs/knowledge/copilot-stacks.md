# Copilot stack layering: app, StackSet, env, workload and addons

*Source: the archived AWS Copilot CLI repository (Apache-2.0), commit `a0dbe689`. Template paths are
relative to `internal/pkg/template/templates/`. Go paths are relative to the repository root. Anything
not confirmed in the source is marked **(UNCONFIRMED)**. Statements about CloudFormation or AWS
defaults are labelled as such, because they come from AWS behaviour, not Copilot code.*

Copilot templates are Go `text/template` files, so there are two layers of conditionality:
- **Render-time** (`{{ if … }}`): whether a resource appears in the deployed template at all.
  ecsodus must read the **deployed** template (`GetTemplate`), never re-render it.
- **CloudFormation `Condition:`**: whether a resource in the deployed template actually exists.
  In the env stack these conditions are driven by parameters that the env-controller mutates at
  runtime.

```
app account (tools account)                 per env region/account
┌──────────────────────────────┐            ┌───────────────────────────────────────────┐
│ <app>-infrastructure-roles   │  StackSet  │ StackSet-<app>-infrastructure-<id>        │
│  (templates/app/app.yml)     ├──────────► │  (templates/app/cf.yml): KMS, bucket, ECR │
│  AppHostedZone, roles        │            └───────────────────────────────────────────┘
└──────────────────────────────┘            ┌───────────────────────────────────────────┐
                                            │ <app>-<env>  (environment/cf.yml)         │
                                            │  VPC, cluster, ALB?, NAT?, EFS?, certs    │
                                            │  └ AddonsStack (env addons, optional)     │
                                            └───────────▲───────────────────────────────┘
                                                        │ UpdateStack (env-controller)
                                            ┌───────────┴───────────────────────────────┐
                                            │ <app>-<env>-<svc>  (workloads/services/…) │
                                            │  service, taskdef, TG, rules, custom res. │
                                            │  └ AddonsStack (workload addons, optional)│
                                            └───────────────────────────────────────────┘
```

---

## 1. App stack: `templates/app/app.yml`

- **Stack name:** `<app>-infrastructure-roles` (`NameForAppStack`,
  `internal/pkg/deploy/cloudformation/stack/name.go`).
- **Tags:** `copilot-application=<app>` merged with the app's `AdditionalTags` (`AppStackConfig.Tags`).
- **Parameters:** `AdminRoleName`, `ExecutionRoleName`, `DNSDelegationRoleName`,
  `AppDNSDelegatedAccounts`, `AppDomainName`, `AppDomainHostedZoneID`, `AppName`.
- **Condition:** `DelegateDNS: !Not [!Equals [ !Ref AppDomainName, "" ]]`.

| Logical ID | Type | Condition | Notes |
|---|---|---|---|
| `AdministrationRole` | `AWS::IAM::Role` | — | `RoleName: <app>-adminrole`. StackSet admin role. |
| `ExecutionRole` | `AWS::IAM::Role` | — | `RoleName: <app>-executionrole`. StackSet execution role. |
| `DNSDelegationRole` | `AWS::IAM::Role` | `DelegateDNS` | `RoleName: <app>-DNSDelegationRole` (`deploy.DNSDelegationRoleName`). Env accounts assume it to write into `AppHostedZone`/the root zone. |
| `AppHostedZone` | `AWS::Route53::HostedZone` | `DelegateDNS` | `<app>.<domain>`. Holds the env NS delegations that `dns-delegation.js` writes **out of band**, plus alias and validation records. |
| `AppDomainDelegationRecordSet` | `AWS::Route53::RecordSet` | `DelegateDNS` | NS record `<app>.<domain>.` in the customer's root zone `AppDomainHostedZoneID`, TTL 900. |

No resource has a `DeletionPolicy`. CloudFormation behaviour: deleting a hosted zone fails if it
still contains records other than SOA/NS, so an `AppHostedZone` that still holds out-of-band records
blocks the stack delete rather than losing them.

## 2. App StackSet: `templates/app/cf.yml`

- **StackSet name:** `<app>-infrastructure` (`NameForAppStackSet`). Description: "ECS CLI
  Application Resources (ECR repos, KMS keys, S3 buckets)".
- **Admin/execution roles:** `<app>-adminrole` / `<app>-executionrole`.
- **Tags:** the same as the app stack (`WithTags(toMap(appConfig.Tags()))` in
  `internal/pkg/deploy/cloudformation/app.go`).
- **Instances:** one per env region/account. Copilot finds them through `InstanceSummaries`
  (ListStackInstances) and describes them by `StackID`. It does not use a name pattern.
  CloudFormation names instance stacks `StackSet-<stackset-name>-<uuid>` **(UNCONFIRMED:
  CloudFormation behaviour, not in Copilot source)**.

| Logical ID | Type | Notes |
|---|---|---|
| `KMSKey` | `AWS::KMS::Key` | `EnableKeyRotation: true`. Its policy allows the tools account and every env account. Output `KMSKeyARN`, exported as `<app>-ArtifactKey`. |
| `PipelineBuiltArtifactBucket` | `AWS::S3::Bucket` | Versioned, SSE-KMS with `KMSKey`, `BucketOwnerEnforced`. The lifecycle expires `local-assets/` after 30 days. Output `PipelineBucket`. Holds addon templates, env files and custom-resource zips. |
| `PipelineBuiltArtifactBucketPolicy` | `AWS::S3::BucketPolicy` | Allows account principals; denies non-KMS puts and non-TLS access. |
| `ECRRepo<Workload>` | `AWS::ECR::Repository` | One per workload with `WithECR`. `RepositoryName: <app>/<workload>`, tagged `copilot-service=<workload>`. Output `ECRRepo<Workload>`. |

No resource has a `DeletionPolicy`. CloudFormation defaults:
- a KMS key is **scheduled for deletion** (default 30-day window)
- a bucket delete fails if it is not empty
- an ECR repository delete fails if it holds images, because `EmptyOnDelete` is not set

**(UNCONFIRMED: AWS defaults.)** Copilot's own `copilot app delete` empties both before deleting
the StackSet: `cleanUpRegionalResources` in `internal/pkg/deploy/cloudformation/app.go` calls
`s3.EmptyBucket` and `ecr.ClearRepository("<app>/<svc>")`. That is client-side, not a custom
resource.

## 3. Environment stack: `templates/environment/cf.yml` + `environment/partials/*`

- **Stack name:** `<app>-<env>` (`NameForEnv`).
- **Tags:** `copilot-application`, `copilot-environment`, plus the app's tags (`Env.Tags` in
  `stack/env.go`).
- **Bootstrap:** `environment/bootstrap-cf.yml` uses the same stack name, and its only content is
  `bootstrap-resources` (the two roles below).
- **Parameters:** `AppName`, `EnvironmentName`, `ALBWorkloads`, `InternalALBWorkloads`,
  `EFSWorkloads`, `NATWorkloads`, `AppRunnerPrivateWorkloads`, `ToolsAccountPrincipalARN`,
  `AppDNSName`, `AppDNSDelegationRole`, `Aliases`, `CreateHTTPSListener`,
  `CreateInternalHTTPSListener`, `ServiceDiscoveryEndpoint`.

The six env-controller-managed parameters are `ALBWorkloads`, `EFSWorkloads`, `NATWorkloads`,
`InternalALBWorkloads`, `Aliases` and `AppRunnerPrivateWorkloads` (`template.AvailableEnvFeatures()`
in `internal/pkg/template/env.go`). On `copilot env deploy`, `transformEnvControllerParameters`
(`stack/env.go`) keeps their previous values. The `*Workloads` parameters are comma-separated
workload names. `Aliases` is a JSON map of workload to a list of aliases, or `""`.

### 3.1 Conditions (quoted from `environment/cf.yml`)

```yaml
Conditions:
  CreateALB:
    !Not [!Equals [ !Ref ALBWorkloads, "" ]]
  CreateInternalALB:
    !Not [!Equals [ !Ref InternalALBWorkloads, "" ]]
  DelegateDNS:
    !Not [!Equals [ !Ref AppDNSName, "" ]]
  ExportHTTPSListener: !And
    - !Condition CreateALB
    - !Equals [ !Ref CreateHTTPSListener, true ]
  ExportInternalHTTPSListener: !And
    - !Condition CreateInternalALB
    - !Equals [ !Ref CreateInternalHTTPSListener, true ]
  CreateEFS:
    !Not [!Equals [ !Ref EFSWorkloads, ""]]
  CreateNATGateways:
    !Not [!Equals [ !Ref NATWorkloads, ""]]
  CreateAppRunnerVPCEndpoint:
    !Not [!Equals [ !Ref AppRunnerPrivateWorkloads, ""]]
  ManagedAliases: !And
    - !Condition DelegateDNS
    - !Not [!Equals [ !Ref Aliases, "" ]]
    - !Condition CreateALB
```

### 3.2 Every env resource, grouped by condition

`{n}` means one resource per subnet index (1-based) or per extra imported certificate. The
"render" column gives the Go-template gate that decides whether the resource is in the template
at all.

**Unconditional (always exist if rendered):**

| Logical ID | Type | Render gate | Notes |
|---|---|---|---|
| `CloudformationExecutionRole` | `AWS::IAM::Role` | always (`bootstrap-resources`) | **`DeletionPolicy: Retain`** in source. `RoleName: <app>-<env>-CFNExecutionRole`. The partial's comment says the definition "must be immediately followed with DeletionPolicy: Retain" (#1533). |
| `EnvironmentManagerRole` | `AWS::IAM::Role` | always | **`DeletionPolicy: Retain`** in source. `RoleName: <app>-<env>-EnvManagerRole`. |
| `ServiceDiscoveryNamespace` | `AWS::ServiceDiscovery::PrivateDnsNamespace` | always | `Name: !Ref ServiceDiscoveryEndpoint` (`<env>.<app>.local`, or `<app>.local` for envs created before v1.5). |
| `Cluster` | `AWS::ECS::Cluster` | always | FARGATE/FARGATE_SPOT. |
| `EnvironmentSecurityGroup` | `AWS::EC2::SecurityGroup` | always | |
| `EnvironmentSecurityGroupIngressFromSelf` | `AWS::EC2::SecurityGroupIngress` | always | |
| `LogResourcePolicy` | `AWS::Logs::ResourcePolicy` | always | `<app>-<env>-LogResourcePolicy`. |
| `VPC`, `PublicRouteTable`, `DefaultPublicRoute`, `InternetGateway`, `InternetGatewayAttachment`, `PublicSubnet{n}`, `PrivateSubnet{n}`, `PublicSubnet{n}RouteTableAssociation` | EC2 | `not .VPCConfig.Imported` (`vpc-resources.yml`) | Private subnets have **no** route-table association unless NAT is on. |
| `ELBAccessLogsBucket` | `AWS::S3::Bucket` | `.PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket` | Versioned. **No CFN condition:** it survives `CreateALB` turning false. |
| `ELBAccessLogsBucketCleanerAction` | `Custom::BucketCleanerFunction` | same | Its Delete empties the bucket (see `copilot-custom-resources.md`). |
| `BucketCleanerFunction`, `ELBAccessLogsBucketCleanerRole` | Lambda, IAM | same | |
| `CloudFrontOriginAccessControl` | `AWS::CloudFront::OriginAccessControl` | `.CDNConfig.Static` | |
| `VpcFlowLogGroup`, `FlowLog`, `FlowLogRole` | Logs, EC2, IAM | `.VPCConfig.FlowLogs` | |
| `AddonsStack` | `AWS::CloudFormation::Stack` | `.Addons` | Env addons. Parameters `App`, `Env` + extra params. |

**`CreateALB` (`ALBWorkloads` non-empty):**
`PublicHTTPLoadBalancerSecurityGroup`, `EnvironmentHTTPSecurityGroupIngressFromPublicALB`,
`PublicLoadBalancer`, `DefaultHTTPTargetGroup`, `HTTPListener`, `ELBAccessLogsBucketPolicy`
(render: ShouldCreateBucket).

With `.CDNConfig`, the following are also gated on `CreateALB`, and the first three are rendered
only if `or .CDNConfig.ImportedCertificate .DelegateDNS`:
- `UniqueJSONValuesFunctionRole`
- `UniqueJSONValuesFunction`
- `UniqueAliasesAction` (`Custom::UniqueJSONValuesFunction`)
- `CloudFrontDistribution`

**`ExportHTTPSListener` (`CreateALB` and `CreateHTTPSListener == true`):**
`PublicHTTPSLoadBalancerSecurityGroup`, `EnvironmentHTTPSSecurityGroupIngressFromPublicALB`,
`HTTPSListener` (certificate = `!Ref HTTPSCert`, or the first imported cert ARN),
`HTTPSImportCertificate{n}` (`AWS::ElasticLoadBalancingV2::ListenerCertificate`, one per extra
imported cert).

**`CreateInternalALB` (`InternalALBWorkloads` non-empty):**
- `InternalLoadBalancerSecurityGroup`, `EnvironmentSecurityGroupIngressFromInternalALB`,
  `InternalALBIngressFromEnvironmentSecurityGroup`
- `InternalLoadBalancerSecurityGroupIngressFromHttp` (render: `.VPCConfig.AllowVPCIngress`)
- `InternalLoadBalancer`, `DefaultInternalHTTPTargetGroup`, `InternalHTTPListener`
- `InternalWorkloadsHostedZone` (`AWS::Route53::HostedZone` `<env>.<app>.internal`, private to the
  VPC; render: `not .PrivateHTTPConfig.ImportedCertARNs`)

**`ExportInternalHTTPSListener` (`CreateInternalALB` and `CreateInternalHTTPSListener == true`):**
`InternalLoadBalancerSecurityGroupIngressFromHttps` (render: `AllowVPCIngress`),
`InternalHTTPSListener`, `InternalHTTPSImportCertificate{n}`.

**`CreateEFS` (`EFSWorkloads` non-empty):**
`FileSystem` (`AWS::EFS::FileSystem`, encrypted, `BackupPolicy: ENABLED`, IA after 30 days),
`EFSSecurityGroup`, `EFSSecurityGroupIngressFromEnvironment`, `MountTarget{n}` (one per private
subnet).

**`CreateNATGateways` (`NATWorkloads` non-empty; render: `not .VPCConfig.Imported`,
`nat-gateways.yml`):**
`NatGateway{n}Attachment` (`AWS::EC2::EIP`), `NatGateway{n}` (in `PublicSubnet{n}`),
`PrivateRouteTable{n}`, `PrivateRoute{n}` (0.0.0.0/0 → NAT), `PrivateRouteTable{n}Association`.
There is one of each per private subnet.

**`CreateAppRunnerVPCEndpoint` (`AppRunnerPrivateWorkloads` non-empty; render:
`not .VPCConfig.Imported`, `ar-vpc-connector.yml`):**
`AppRunnerVpcEndpointSecurityGroup`, `AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment`,
`AppRunnerVpcEndpoint`.

**`DelegateDNS` (`AppDNSName` non-empty; all rendered only when
`not .PublicHTTPConfig.ImportedCertARNs`):**
- `CustomResourceRole`, `EnvironmentHostedZone` (`<env>.<app>.<domain>`)
- `CertificateValidationFunction`, `DNSDelegationFunction`
- `DelegateDNSAction` (`Custom::DNSDelegationFunction`)
- `HTTPSCert` (`Custom::CertificateValidationFunction`)
- with `.CDNConfig`: `CertificateReplicatorFunction` and `CertificateReplicator`
  (`Custom::CertificateReplicatorFunction`)

**`ManagedAliases` (`DelegateDNS`, `Aliases` non-empty and `CreateALB`; same render gate):**
`CustomDomainFunction`, `CustomDomainAction` (`Custom::CustomDomainFunction`).

**Condition-gated outputs:**
- `CreateALB`: `PublicLoadBalancerDNSName`, `PublicLoadBalancerFullName`,
  `PublicLoadBalancerHostedZone`, `HTTPListenerArn`, `DefaultHTTPTargetGroupArn`,
  `CloudFrontDomainName`, `PublicALBAccessible`
- `ExportHTTPSListener`: `HTTPSListenerArn`
- `CreateInternalALB`: the `InternalLoadBalancer*` outputs, `InternalWorkloadsHostedZone`/`Name`,
  `InternalHTTPListenerArn`, `InternalLoadBalancerSecurityGroup`
- `ExportInternalHTTPSListener`: `InternalHTTPSListenerArn`
- `CreateEFS`: `ManagedFileSystemID`
- `CreateNATGateways`: `PrivateRouteTableIDs`
- `DelegateDNS`: `EnvironmentHostedZone`, `EnvironmentSubdomain`
- `CreateAppRunnerVPCEndpoint`: `AppRunnerVpcEndpointId`

Most outputs are exported as `${AWS::StackName}-<Name>`, for example `<app>-<env>-ClusterId`,
`-VpcId`, `-PrivateSubnets`, `-HostedZone`, `-SubDomain` and `-FilesystemID`. Workload and addon
templates import these, which creates a CloudFormation dependency: the env stack cannot be deleted
while an importer exists. `EnabledFeatures` concatenates all six managed parameters so that a
parameter-only change still updates the stack.

### 3.3 What the env-controller can delete

When a workload stack is deleted, `EnvControllerAction`'s Delete removes the workload from every
`*Workloads` parameter and from `Aliases`, then updates `<app>-<env>` with `UsePreviousTemplate`.
If it was the last workload using a feature, every resource gated on that feature's condition (3.2)
is **deleted by CloudFormation**. This covers:
- the ALB and listeners
- the NAT gateways and EIPs
- the internal ALB and `InternalWorkloadsHostedZone`
- the App Runner endpoint
- **the EFS `FileSystem` and its data**

It also deletes `CustomDomainAction`, whose own Delete handler then removes the alias A records.
An `Aliases` change additionally reissues `HTTPSCert`, and the old cert is deleted. None of these
env resources has a `DeletionPolicy` in source. Only the two bootstrap roles do.

## 4. Workload stacks

- **Stack name:** `<app>-<env>-<svc>`, truncated to 128 characters (`NameForWorkload`).
- **Tags:** `copilot-application`, `copilot-environment`, `copilot-service`, plus the app's tags
  (`stack/workload.go`).
- **Deletion policies:** no workload template or partial contains `DeletionPolicy` (grep of
  `workloads/`).

### 4.1 Load Balanced Web Service: `workloads/services/lb-web/cf.yml`

CFN conditions: `IsGovCloud`, `HasAssociatedDomain` (`DNSDelegated == true`), `HasAddons`
(`AddonsTemplateURL != ""`), `HasEnvFile`, `HasLoggingEnvFile`, `HasEnvFileFor<Sidecar>`.

| Logical ID | Type | Render gate / condition | Source partial |
|---|---|---|---|
| `LogGroup` | `AWS::Logs::LogGroup` | always | `loggroup.yml`. Name `/copilot/<app>-<env>-<svc>`, `RetentionInDays: !Ref LogRetention`. |
| `TaskDefinition` | `AWS::ECS::TaskDefinition` | always | |
| `ExecutionRole`, `TaskRole` | `AWS::IAM::Role` | always | `executionrole.yml`, `taskrole.yml` |
| `DiscoveryService` | `AWS::ServiceDiscovery::Service` | always | `servicediscovery.yml` |
| `DynamicDesiredCountAction` | `Custom::DynamicDesiredCountFunction` | `.Autoscaling` | `autoscaling.yml` |
| `DynamicDesiredCountFunction`, `DynamicDesiredCountFunctionRole`, `AutoScalingRole`, `AutoScalingTarget` | Lambda, IAM, AppAutoScaling | `.Autoscaling` | |
| `AutoScalingPolicyECSServiceAverageCPUUtilization` / `…MemoryUtilization` / `AutoScalingPolicyALBSumRequestCountPerTarget` / `AutoScalingPolicyALBAverageResponseTime` | `AWS::ApplicationAutoScaling::ScalingPolicy` | per manifest field | |
| `CPURollbackAlarm`, `MemoryRollbackAlarm` | `AWS::CloudWatch::Alarm` | per manifest | `rollback-alarms.yml` |
| **`EnvControllerAction`** | **`Custom::EnvControllerFunction`** | always | `env-controller.yml`. `Parameters` = `ALBWorkloads` (if the ALB is enabled and not imported), `Aliases` (if not an imported ALB), `NATWorkloads` (private placement), `EFSWorkloads` (managed EFS). `Aliases:` property only with ALB aliases and no imported ALB. |
| `EnvControllerFunction`, `EnvControllerRole` | Lambda, IAM | always | |
| `Service` | `AWS::ECS::Service` | always | `DependsOn` the listener rules / NLB listeners. `DesiredCount` = `!GetAtt DynamicDesiredCountAction.DesiredCount` with autoscaling (not on Spot), else `!Ref TaskCount`. |
| `TargetGroup{i}` (or `TargetGroupForImportedALB{i}`) | `AWS::ElasticLoadBalancingV2::TargetGroup` | `.ALBListener` | `alb.yml` |
| `RulePriorityFunction`, `RulePriorityFunctionRole` | Lambda, IAM | `.ALBListener` | `alb.yml` |
| HTTP only: `HTTPRulePriorityAction`, `HTTPListenerRule{i}` | `Custom::RulePriorityFunction`, ListenerRule | `.ALBListener`, not HTTPS | `http-listener.yml`. The listener comes from `!GetAtt EnvControllerAction.HTTPListenerArn`. |
| HTTPS: `HTTPSRulePriorityAction`, `HTTPRuleWithDomainPriorityAction`, `HTTPSListenerRule{i}`, `HTTPListenerRuleWithDomain{i}` (HTTP→HTTPS redirect) | Custom, ListenerRule | `.ALBListener.IsHTTPS` | `https-listener.yml` |
| HTTPS without aliases: `LoadBalancerDNSAlias` | `AWS::Route53::RecordSetGroup` | `not .ALBListener.Aliases` | A-alias `<svc>.<env>.<app>.<domain>` in the env zone (import `<app>-<env>-HostedZone`) → public ALB. **CFN-owned.** |
| HTTPS with aliases that have `hosted_zone`: `LoadBalancerDNSAlias<HostedZoneID>` | `AWS::Route53::RecordSetGroup` | per zone in `HostedZoneAliases` | CFN-owned. Aliases **without** `hosted_zone` get their A records from the env `CustomDomainAction` instead (out of band). |
| Imported ALB: `HTTPSRulePriorityAction`/`HTTPSListenerRuleForImportedALB{i}`, `HTTPRedirectRulePriorityAction`/`HTTPListenerRedirectRuleForImportedALB{i}`, or `HTTPRulePriorityAction`/`HTTPListenerRuleForImportedALB{i}`, `LoadBalancerDNSAlias<zone>`, `EnvironmentSecurityGroupIngressFromImportedALB{i}` | various | `.ImportedALB` | `imported-alb-resources.yml` |
| NLB: `PublicNetworkLoadBalancerV2`, `NetworkLoadBalancerSecurityGroup`, `EnvironmentSecurityGroupIngressFromNetworkLoadBalancerSecurityGroup`, `NLBListener{i}`, `NetworkLoadBalancerTargetGroup{i}`, `NLBDNSAlias` (`HasAssociatedDomain`) **or** `NLBCustomDomainAction`/`Function`/`Role` (`HasAssociatedDomain`), `NLBCertValidatorAction`/`Function`/`Role` (`HasAssociatedDomain`, `.NLB.CertificateRequired`) | various | `.NLB` | `nlb.yml` (NLB is `blocked` in ecsodus v0.1) |
| `AccessPoint` | `AWS::EFS::AccessPoint` | `.Storage.ManagedVolumeInfo` | `efs-access-point.yml` (on the env `FileSystem`) |
| `AddonsStack` | `AWS::CloudFormation::Stack` | `Condition: HasAddons` | `addons.yml`. `DependsOn: EnvControllerAction` when the workload requests any env feature. Parameters `App`, `Env`, `Name` + extras. `TemplateURL: !Ref AddonsTemplateURL`. |
| `<Topic>SNSTopic`, `<Topic>SNSTopicPolicy` | SNS | `.Publish` | `publish.yml` |

**Delete order (CloudFormation reverse-dependency behaviour).** The listener rules take their
listener ARN from `!GetAtt EnvControllerAction.*`, and `AddonsStack` depends on it. So
`Service`, the rules, the target groups and the addons are deleted first, and
**`EnvControllerAction`'s Delete runs last**, triggering the env update in §3.3.

### 4.2 Backend Service: `workloads/services/backend/cf.yml`

CFN conditions: `IsGovCloud`, `HasAddons`, `HasEnvFile`, `HasLoggingEnvFile`,
`HasEnvFileFor<Sidecar>`, `ExposePort` (`TargetPort != -1`).

The resources are the same as LBWS, with these differences:
- no NLB, and no `Aliases` passed to the env-controller
- `EnvControllerAction` `Parameters` = `InternalALBWorkloads` (ALB enabled and not imported),
  `NATWorkloads`, `EFSWorkloads`
- `Service` has an explicit `DependsOn: EnvControllerAction` (plus the rules).
  `ServiceRegistries` uses `!If [ExposePort, …]`.
- With `.ALBListener`: `TargetGroup{i}`, `RulePriorityFunction`/`Role`, and the listener rules.
  The listener ARN comes from `EnvControllerAction.InternalHTTPListenerArn`/`InternalHTTPSListenerArn`.
- **`LoadBalancerInternalDNSAlias`** (`AWS::Route53::RecordSetGroup`) in
  `EnvControllerAction.InternalWorkloadsHostedZone`: `<svc>.<env>.<app>.internal` → the internal
  ALB. This is rendered in `http-listener.yml` for Backend Service.
- HTTPS-with-alias records point at `InternalLoadBalancerHostedZone`/`DNSName`.

### 4.3 Other workload kinds (all `blocked` in ecsodus v0.1)

- Worker (`services/worker/cf.yml`): the env-controller, and the backlog calculator when
  `.Autoscaling.QueueDelay` is set.
- Scheduled Job (`jobs/scheduled-job/cf.yml`): the env-controller.
- RDWS (`services/rd-web/cf.yml`): the env-controller and `CustomDomainAction`
  (`custom-domain-app-runner.js`).
- Static Site (`services/static-site/cf.yml`): `Bucket` (no `DeletionPolicy`),
  `TriggerStateMachineAction`, `CustomDomainAction`, `CertificateValidatorAction`.

## 5. Addons: `templates/addons/*`

These are the templates that `copilot storage init` **writes into the user's workspace**
(`copilot/<svc>/addons/` or `copilot/environments/addons/`). Users may have edited them, so
ecsodus must read the deployed nested-stack template and not assume these contents. Workload
addons are a nested `AddonsStack` in the workload stack. Env addons are a nested `AddonsStack` in
the env stack. The child stack name is CloudFormation-generated (`<parent>-AddonsStack-<suffix>`)
**(UNCONFIRMED: CloudFormation behaviour)**.

### 5.1 DeletionPolicy / UpdateReplacePolicy present in source

The **only** policy in any addon template is `DeletionPolicy: Retain` on the S3 **bucket policy**
(`{{Name}}BucketPolicy` in `s3/cf.yml` and `s3/env/cf.yml`). No addon template sets
`UpdateReplacePolicy` anywhere.

| Template | Resource (logical ID) | Type | DeletionPolicy in source | Default that applies (CloudFormation/AWS behaviour) |
|---|---|---|---|---|
| `aurora/serverlessv2.yml` (workload) | `<C>DBSubnetGroup` | `AWS::RDS::DBSubnetGroup` | none | Delete |
| | `<C>SecurityGroup`, `<C>DBClusterSecurityGroup` | `AWS::EC2::SecurityGroup` | none | Delete |
| | `<C>AuroraSecret` | `AWS::SecretsManager::Secret` | none | Delete. The secret is deleted **without a recovery window** (PLAN §1; **UNCONFIRMED against AWS docs in this pass**). |
| | `<C>DBClusterParameterGroup` (unless `.ParameterGroup`) | `AWS::RDS::DBClusterParameterGroup` | none | Delete |
| | **`<C>DBCluster`** | `AWS::RDS::DBCluster` | none | **Snapshot**: CloudFormation takes a final cluster snapshot and deletes the cluster. |
| | `<C>DBWriterInstance` | `AWS::RDS::DBInstance` (has `DBClusterIdentifier`) | none | Delete (the Snapshot default applies only to DB instances *without* `DBClusterIdentifier`) |
| | `<C>SecretAuroraClusterAttachment` | `AWS::SecretsManager::SecretTargetAttachment` | none | Delete |
| `aurora/cf.yml` (Serverless v1, `EngineMode: serverless`) | the same set, no DBInstance | | none | Cluster: **Snapshot**; the rest: Delete |
| `aurora/rdws/*.yml` | the same, plus `AWS::IAM::ManagedPolicy` | | none | as above |
| `aurora/env/serverlessv2.yml`, `aurora/env/rdws/*` | the same (env-level), `WorkloadSecurityGroup`, `SecurityGroupIngress` | | none | as above |
| `ddb/cf.yml` (workload), `ddb/env/cf.yml` | `<Name>` table (`TableName: ${App}-${Env}-${Name}-<table>` for workload, `${App}-${Env}-<table>` for env), `<Name>AccessPolicy` | `AWS::DynamoDB::Table`, `AWS::IAM::ManagedPolicy` | none | **Delete: the table and all items are deleted.** The template sets no `DeletionProtectionEnabled` and no PITR, so nothing survives. |
| `s3/cf.yml`, `s3/env/cf.yml` | `<Name>Bucket` | `AWS::S3::Bucket` (versioned; noncurrent versions expire after 30 days) | none | Delete. **It fails with BucketNotEmpty if any object or version exists**, so the stack ends `DELETE_FAILED` and the bucket survives. |
| | `<Name>BucketPolicy` | `AWS::S3::BucketPolicy` | **Retain** | — |
| | `<Name>AccessPolicy` | `AWS::IAM::ManagedPolicy` | none | Delete |

Templates also set none of: `DeletionProtection`, `BackupRetentionPeriod` or
`SnapshotIdentifier` on the Aurora clusters (so RDS defaults apply; retention is 1 day
**(UNCONFIRMED: RDS default)**), or PITR on DynamoDB.

### 5.2 Final-snapshot handling

- **Aurora `DBCluster` with no policy:** on stack delete, or when the resource is removed from
  the template, CloudFormation deletes the cluster **after** taking a final snapshot. The snapshot
  sits outside any stack, is kept indefinitely, and keeps incurring storage cost. The DB instance
  in the cluster is deleted with no snapshot of its own. Automated backups follow the RDS delete
  defaults and are not kept by CloudFormation **(UNCONFIRMED: AWS behaviour)**.
- **On replacement:** the default `UpdateReplacePolicy` for `DBCluster` is **(UNCONFIRMED)**, and
  Copilot sets none. The retain patch sets `UpdateReplacePolicy: Retain` explicitly, so the
  question is moot for ecsodus.
- **Under the ecsodus retain patch:** `DeletionPolicy: Retain` on the `DBCluster` means no final
  snapshot is taken on teardown, because the cluster itself is kept and imported. Runbook step 2
  takes a manual snapshot and turns on deletion protection before any patch.
- **Secret:** the retain patch keeps `<C>AuroraSecret`. Without it, stack deletion would remove
  the credentials the retained cluster still uses.
- **Other stateful defaults (CloudFormation behaviour):**
  - the env EFS `FileSystem` has no policy, so its Delete destroys the data. AWS Backup recovery
    points from `BackupPolicy: ENABLED` may survive in the backup vault **(UNCONFIRMED)**.
  - `LogGroup`s are deleted along with their log data.
  - the StackSet `KMSKey` is scheduled for deletion (default window 30 days)
    **(UNCONFIRMED: AWS default)**.

## 6. Naming, tags and SSM metadata

### 6.1 Stack names (`internal/pkg/deploy/cloudformation/stack/name.go`)

| Stack | Pattern |
|---|---|
| App stack | `<app>-infrastructure-roles` |
| App StackSet | `<app>-infrastructure` (instance stacks: CloudFormation-generated, `StackSet-<app>-infrastructure-<uuid>`, **UNCONFIRMED**) |
| Env stack | `<app>-<env>` |
| Workload stack | `<app>-<env>-<svc>`, truncated to 128 chars |
| Addons nested stack | child of the env or workload stack, logical ID `AddonsStack` (`template.AddonsStackLogicalID`) |
| One-off task | `task-<name>` |
| Pipeline | `pipeline-<app>-<pipeline>` (legacy: `<pipeline>`) |

### 6.2 Tags (`internal/pkg/deploy/deploy.go`)

`AppTagKey = "copilot-application"`, `EnvTagKey = "copilot-environment"`,
`ServiceTagKey = "copilot-service"`, `PipelineTagKey = "copilot-pipeline"`,
`TaskTagKey = "copilot-task"`.

| Object | Tags |
|---|---|
| App stack, StackSet | `copilot-application` + app `Tags` |
| Env stack | `copilot-application`, `copilot-environment` + app tags |
| Workload stack | `copilot-application`, `copilot-environment`, `copilot-service` + app tags |
| ECR repo (StackSet) | `copilot-service=<workload>` |
| ACM certs from `dns-cert-validator`, `cert-replicator` | `copilot-application`, `copilot-environment` |
| ACM certs from `wkld-cert-validator` | + `copilot-service` |
| SSM app / env / workload params | app: `copilot-application`; env: + `copilot-environment`; workload: `copilot-application`, `copilot-service` |
| `copilot secret init` SecureStrings | `copilot-application`, `copilot-environment` |

CloudFormation propagates stack tags to the resources that support tagging. The env-controller's
IAM policy, the EFS file-system policy and the `desired-count-delegation` lookup all depend on
these tags.

### 6.3 SSM metadata (`internal/pkg/config/store.go`, `app.go`, `env.go`, `workload.go`)

Schema version `"1.0"`. Every parameter is type `String` holding JSON.

| Path | Value (JSON fields) |
|---|---|
| `/copilot/applications/<app>` | `name`, `account`, `permissionsBoundary`, `domain`, `domainHostedZoneID`, `version`, `tags` |
| `/copilot/applications/<app>/environments/<env>` | `app`, `name`, `region`, `accountID`, `registryURL`, `executionRoleARN`, `managerRoleARN` (+ the deprecated `customConfig`, `telemetry`) |
| `/copilot/applications/<app>/components/<workload>` | `app`, `name`, `type` (e.g. `Load Balanced Web Service`, `Backend Service`) |

Secrets from `copilot secret init` (`internal/pkg/cli/secret_init.go`) are SecureStrings at
`/copilot/<app>/<env>/secrets/<name>`. They are created outside CloudFormation, so ecsodus
treats them as `external-reference`.

### 6.4 Other fixed names

- IAM roles: `<app>-adminrole`, `<app>-executionrole`, `<app>-DNSDelegationRole`,
  `<app>-<env>-CFNExecutionRole`, `<app>-<env>-EnvManagerRole`.
- ECR repositories: `<app>/<svc>`.
- Log groups: `/copilot/<app>-<env>-<svc>`.
- Hosted zones:
  - app: `<app>.<domain>`
  - env: `<env>.<app>.<domain>`
  - internal: `<env>.<app>.internal`
- Service discovery namespace: `<env>.<app>.local` (legacy `<app>.local`).
- StackSet export: `<app>-ArtifactKey`.
