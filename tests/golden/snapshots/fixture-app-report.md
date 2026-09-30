# Migration readiness: Copilot app `my-app`

ecsodus 0.1.0rc1 · account `123456789012` · region `us-west-2` · inventory captured <ts>

## Summary

- **Verdict:** not ready
- Stacks: 4 (0 hand off, 4 kept on Copilot)
- Resources by fate: manual-cleanup 19, not-created 7, retain-under-existing-owner 133
- Teardown stops before `my-app-test` (a shared stack still has consumers).

**Zero-risk baseline: keep the CloudFormation.** Copilot's stacks keep running without the CLI. You can deploy them with `aws cloudformation deploy` plus a deploy tool such as ecspresso. Caveats: the custom-resource Lambdas run `nodejs20.x`, so creating them is blocked from 2027-07-29, and a stack update that changes their code fails from 2027-08-31. Choose ecsodus if you want Terraform ownership.

## Workloads

| Workload | Status | Express Mode fit (informational; rebuild mode is v0.2) |
|---|---|---|
| `test/be` (Backend Service) | kept: 1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1 | no: cpu/memory not numeric; not a Load Balanced Web Service; service not resolvable offline |
| `test/fe` (Load Balanced Web Service) | kept: 12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount | no: service not resolvable offline; uses volumes |
| `test/worker` (Worker Service) | blocked: type Worker Service | no: not a Load Balanced Web Service; service not resolvable offline; task definition not resolvable offline |

Before any rebuild-in-parallel (v0.2), answer for each service: *does this container run background work, consumers or migrations on boot?* Parallel runs would duplicate it.

## Stacks

### `my-app-test` (env): kept

Kept because: 24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 54 thing(s)</summary>

- VPC (AWS::EC2::VPC): delete
- PublicRouteTable (AWS::EC2::RouteTable): delete
- DefaultPublicRoute (AWS::EC2::Route): delete
- InternetGateway (AWS::EC2::InternetGateway): delete
- InternetGatewayAttachment (AWS::EC2::VPCGatewayAttachment): delete
- PublicSubnet1 (AWS::EC2::Subnet): delete
- PublicSubnet2 (AWS::EC2::Subnet): delete
- PrivateSubnet1 (AWS::EC2::Subnet): delete
- PrivateSubnet2 (AWS::EC2::Subnet): delete
- PublicSubnet1RouteTableAssociation (AWS::EC2::SubnetRouteTableAssociation): delete
- PublicSubnet2RouteTableAssociation (AWS::EC2::SubnetRouteTableAssociation): delete
- NatGateway1Attachment (AWS::EC2::EIP): delete
- NatGateway1 (AWS::EC2::NatGateway): delete
- PrivateRouteTable1 (AWS::EC2::RouteTable): delete
- PrivateRoute1 (AWS::EC2::Route): delete
- PrivateRouteTable1Association (AWS::EC2::SubnetRouteTableAssociation): delete
- NatGateway2Attachment (AWS::EC2::EIP): delete
- NatGateway2 (AWS::EC2::NatGateway): delete
- PrivateRouteTable2 (AWS::EC2::RouteTable): delete
- PrivateRoute2 (AWS::EC2::Route): delete
- PrivateRouteTable2Association (AWS::EC2::SubnetRouteTableAssociation): delete
- ServiceDiscoveryNamespace (AWS::ServiceDiscovery::PrivateDnsNamespace): delete
- Cluster (AWS::ECS::Cluster): delete
- PublicHTTPLoadBalancerSecurityGroup (AWS::EC2::SecurityGroup): delete
- InternalLoadBalancerSecurityGroup (AWS::EC2::SecurityGroup): delete
- EnvironmentSecurityGroup (AWS::EC2::SecurityGroup): delete
- EnvironmentHTTPSecurityGroupIngressFromPublicALB (AWS::EC2::SecurityGroupIngress): delete
- EnvironmentSecurityGroupIngressFromInternalALB (AWS::EC2::SecurityGroupIngress): delete
- EnvironmentSecurityGroupIngressFromSelf (AWS::EC2::SecurityGroupIngress): delete
- InternalALBIngressFromEnvironmentSecurityGroup (AWS::EC2::SecurityGroupIngress): delete
- PublicLoadBalancer (AWS::ElasticLoadBalancingV2::LoadBalancer): delete
- DefaultHTTPTargetGroup (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- HTTPListener (AWS::ElasticLoadBalancingV2::Listener): delete
- InternalLoadBalancer (AWS::ElasticLoadBalancingV2::LoadBalancer): delete
- DefaultInternalHTTPTargetGroup (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- InternalHTTPListener (AWS::ElasticLoadBalancingV2::Listener): delete
- InternalWorkloadsHostedZone (AWS::Route53::HostedZone): delete
- FileSystem (AWS::EFS::FileSystem): delete
- EFSSecurityGroup (AWS::EC2::SecurityGroup): delete
- EFSSecurityGroupIngressFromEnvironment (AWS::EC2::SecurityGroupIngress): delete
- MountTarget1 (AWS::EFS::MountTarget): delete
- MountTarget2 (AWS::EFS::MountTarget): delete
- CustomResourceRole (AWS::IAM::Role): delete
- EnvironmentHostedZone (AWS::Route53::HostedZone): delete
- CertificateValidationFunction (AWS::Lambda::Function): delete
- CustomDomainFunction (AWS::Lambda::Function): delete
- DNSDelegationFunction (AWS::Lambda::Function): delete
- DelegateDNSAction (Custom::DNSDelegationFunction): Delete handler: DELETE the NS record <env>.<app>.<domain> from the app hosted zone (via RootDNSRole) if it exactly matches
- HTTPSCert (Custom::CertificateValidationFunction): Delete handler: if physical id is an ARN: wait up to 10x30s for InUseBy empty (else FAILED); DELETE validation CNAMEs not used by another cert with the same DomainName; DeleteCertificate
- CustomDomainAction (Custom::CustomDomainFunction): Delete handler: DELETE the A-alias record for every alias in Aliases (env/app/root zone); not-found ignored / DELETE the A-alias record for every alias pointing at the current target; not-found and value-mismatch ignored / DisassociateCustomDomain, DELETE the domain CNAME and every certificate validation CNAME, wait until disassociated
- AppRunnerVpcEndpointSecurityGroup (AWS::EC2::SecurityGroup): delete
- AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment (AWS::EC2::SecurityGroupIngress): delete
- AppRunnerVpcEndpoint (AWS::EC2::VPCEndpoint): delete
- LogResourcePolicy (AWS::Logs::ResourcePolicy): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| CloudformationExecutionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| EnvironmentManagerRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| VPC | AWS::EC2::VPC | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PublicRouteTable | AWS::EC2::RouteTable | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| DefaultPublicRoute | AWS::EC2::Route | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| InternetGateway | AWS::EC2::InternetGateway | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| InternetGatewayAttachment | AWS::EC2::VPCGatewayAttachment | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PublicSubnet1 | AWS::EC2::Subnet | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory |
| PublicSubnet2 | AWS::EC2::Subnet | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0000391282978 not in inventory |
| PrivateSubnet1 | AWS::EC2::Subnet | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0002743392758 not in inventory |
| PrivateSubnet2 | AWS::EC2::Subnet | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0000982353996 not in inventory |
| PublicSubnet1RouteTableAssociation | AWS::EC2::SubnetRouteTableAssociation | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PublicSubnet2RouteTableAssociation | AWS::EC2::SubnetRouteTableAssociation | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| NatGateway1Attachment | AWS::EC2::EIP | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AllocationId for 52.74.1.1 not in inventory |
| NatGateway1 | AWS::EC2::NatGateway | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: GetAtt NatGateway1Attachment.AllocationId (AWS::EC2::EIP) not derivable |
| PrivateRouteTable1 | AWS::EC2::RouteTable | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PrivateRoute1 | AWS::EC2::Route | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PrivateRouteTable1Association | AWS::EC2::SubnetRouteTableAssociation | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| NatGateway2Attachment | AWS::EC2::EIP | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AllocationId for 52.153.1.1 not in inventory |
| NatGateway2 | AWS::EC2::NatGateway | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: GetAtt NatGateway2Attachment.AllocationId (AWS::EC2::EIP) not derivable |
| PrivateRouteTable2 | AWS::EC2::RouteTable | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PrivateRoute2 | AWS::EC2::Route | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PrivateRouteTable2Association | AWS::EC2::SubnetRouteTableAssociation | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| ServiceDiscoveryNamespace | AWS::ServiceDiscovery::PrivateDnsNamespace | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| Cluster | AWS::ECS::Cluster | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| PublicHTTPLoadBalancerSecurityGroup | AWS::EC2::SecurityGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0002916443411 not in inventory |
| PublicHTTPSLoadBalancerSecurityGroup | AWS::EC2::SecurityGroup | not-created |  | not created in this deployment |
| InternalLoadBalancerSecurityGroup | AWS::EC2::SecurityGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0004057235420 not in inventory |
| EnvironmentSecurityGroup | AWS::EC2::SecurityGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0001960219168 not in inventory |
| EnvironmentHTTPSecurityGroupIngressFromPublicALB | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentHTTPSecurityGroupIngressFromPublicALB not in inventory |
| EnvironmentHTTPSSecurityGroupIngressFromPublicALB | AWS::EC2::SecurityGroupIngress | not-created |  | not created in this deployment |
| EnvironmentSecurityGroupIngressFromInternalALB | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentSecurityGroupIngressFromInternalALB not in inventory |
| EnvironmentSecurityGroupIngressFromSelf | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentSecurityGroupIngressFromSelf not in inventory |
| InternalALBIngressFromEnvironmentSecurityGroup | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-InternalALBIngressFromEnvironmentSecurityGroup not in inventory |
| PublicLoadBalancer | AWS::ElasticLoadBalancingV2::LoadBalancer | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value LoadBalancerName not in inventory for PublicLoadBalancer |
| DefaultHTTPTargetGroup | AWS::ElasticLoadBalancingV2::TargetGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for DefaultHTTPTargetGroup |
| HTTPListener | AWS::ElasticLoadBalancingV2::Listener | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| HTTPSListener | AWS::ElasticLoadBalancingV2::Listener | not-created |  | not created in this deployment |
| InternalLoadBalancer | AWS::ElasticLoadBalancingV2::LoadBalancer | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value LoadBalancerName not in inventory for InternalLoadBalancer |
| DefaultInternalHTTPTargetGroup | AWS::ElasticLoadBalancingV2::TargetGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for DefaultInternalHTTPTargetGroup |
| InternalHTTPListener | AWS::ElasticLoadBalancingV2::Listener | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| InternalHTTPSListener | AWS::ElasticLoadBalancingV2::Listener | not-created |  | not created in this deployment |
| InternalWorkloadsHostedZone | AWS::Route53::HostedZone | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| FileSystem | AWS::EFS::FileSystem | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| EFSSecurityGroup | AWS::EC2::SecurityGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0003119112918 not in inventory |
| EFSSecurityGroupIngressFromEnvironment | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EFSSecurityGroupIngressFromEnvironment not in inventory |
| MountTarget1 | AWS::EFS::MountTarget | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| MountTarget2 | AWS::EFS::MountTarget | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| CustomResourceRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| EnvironmentHostedZone | AWS::Route53::HostedZone | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| CertificateValidationFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| CustomDomainFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DNSDelegationFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DelegateDNSAction | Custom::DNSDelegationFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPSCert | Custom::CertificateValidationFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| CustomDomainAction | Custom::CustomDomainFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| AppRunnerVpcEndpointSecurityGroup | AWS::EC2::SecurityGroup | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0003224413762 not in inventory |
| AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment not in inventory |
| AppRunnerVpcEndpoint | AWS::EC2::VPCEndpoint | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory) |
| LogResourcePolicy | AWS::Logs::ResourcePolicy | retain-under-existing-owner |  | stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: PolicyName my-app-environmentname-LogResourcePolicy != physical id my-app-test-LogResourcePolicy |

### `my-app-test-be` (workload): kept

Kept because: 1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 9 thing(s)</summary>

- LogGroup (AWS::Logs::LogGroup): delete
- TaskDefinition (AWS::ECS::TaskDefinition): delete
- ExecutionRole (AWS::IAM::Role): delete
- TaskRole (AWS::IAM::Role): delete
- DiscoveryService (AWS::ServiceDiscovery::Service): delete
- Service (AWS::ECS::Service): delete
- EnvControllerAction (Custom::EnvControllerFunction): Delete handler: remove the workload from every *Workloads parameter and from Aliases of stack <app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an Aliases change
- EnvControllerFunction (AWS::Lambda::Function): delete
- EnvControllerRole (AWS::IAM::Role): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| LogGroup | AWS::Logs::LogGroup | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |
| TaskDefinition | AWS::ECS::TaskDefinition | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |
| ExecutionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |
| TaskRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |
| DiscoveryService | AWS::ServiceDiscovery::Service | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |
| Service | AWS::ECS::Service | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1); would be: blocked: cannot resolve exactly: Service Connect is blocked in v0.1 |
| AddonsStack | AWS::CloudFormation::Stack | not-created |  | not created in this deployment |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1) |

### `my-app-test-fe` (workload): kept

Kept because: 12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 30 thing(s)</summary>

- LogGroup (AWS::Logs::LogGroup): delete
- TaskDefinition (AWS::ECS::TaskDefinition): delete
- ExecutionRole (AWS::IAM::Role): delete
- TaskRole (AWS::IAM::Role): delete
- DiscoveryService (AWS::ServiceDiscovery::Service): delete
- DynamicDesiredCountFunction (AWS::Lambda::Function): delete
- DynamicDesiredCountFunctionRole (AWS::IAM::Role): delete
- AutoScalingRole (AWS::IAM::Role): delete
- AutoScalingTarget (AWS::ApplicationAutoScaling::ScalableTarget): delete
- AutoScalingPolicyECSServiceAverageCPUUtilization (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- AutoScalingPolicyALBAverageResponseTime (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- EnvControllerAction (Custom::EnvControllerFunction): Delete handler: remove the workload from every *Workloads parameter and from Aliases of stack <app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an Aliases change
- EnvControllerFunction (AWS::Lambda::Function): delete
- EnvControllerRole (AWS::IAM::Role): delete
- Service (AWS::ECS::Service): delete
- TargetGroupForImportedALB (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- TargetGroupForImportedALB1 (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- RulePriorityFunction (AWS::Lambda::Function): delete
- RulePriorityFunctionRole (AWS::IAM::Role): delete
- LoadBalancerDNSAliasZ08230443CW11KE6JBNUA (AWS::Route53::RecordSetGroup): delete
- HTTPSListenerRuleForImportedALB (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPSListenerRuleForImportedALB1 (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPListenerRedirectRuleForImportedALB (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPListenerRedirectRuleForImportedALB1 (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- EnvironmentSecurityGroupIngressFromImportedALB (AWS::EC2::SecurityGroupIngress): delete
- EnvironmentSecurityGroupIngressFromImportedALB1 (AWS::EC2::SecurityGroupIngress): delete
- givesdogsSNSTopic (AWS::SNS::Topic): delete
- givesdogsSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- mytopicfifoSNSTopic (AWS::SNS::Topic): delete
- mytopicfifoSNSTopicPolicy (AWS::SNS::TopicPolicy): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| LogGroup | AWS::Logs::LogGroup | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| TaskDefinition | AWS::ECS::TaskDefinition | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| ExecutionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| TaskRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| DiscoveryService | AWS::ServiceDiscovery::Service | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| DynamicDesiredCountAction | Custom::DynamicDesiredCountFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| DynamicDesiredCountFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DynamicDesiredCountFunctionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| AutoScalingRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| AutoScalingTarget | AWS::ApplicationAutoScaling::ScalableTarget | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount |
| AutoScalingPolicyECSServiceAverageCPUUtilization | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| AutoScalingPolicyALBAverageResponseTime | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| Service | AWS::ECS::Service | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: service ARN cluster my-app-test-fe-Cluster != template cluster my-app-test-Cluster-cluster |
| TargetGroupForImportedALB | AWS::ElasticLoadBalancingV2::TargetGroup | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for TargetGroupForImportedALB |
| TargetGroupForImportedALB1 | AWS::ElasticLoadBalancingV2::TargetGroup | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for TargetGroupForImportedALB1 |
| RulePriorityFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| RulePriorityFunctionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| LoadBalancerDNSAliasZ08230443CW11KE6JBNUA | AWS::Route53::RecordSetGroup | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| HTTPSRulePriorityAction | Custom::RulePriorityFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPSListenerRuleForImportedALB | AWS::ElasticLoadBalancingV2::ListenerRule | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd |
| HTTPSListenerRuleForImportedALB1 | AWS::ElasticLoadBalancingV2::ListenerRule | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd |
| HTTPRedirectRulePriorityAction | Custom::RulePriorityFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPListenerRedirectRuleForImportedALB | AWS::ElasticLoadBalancingV2::ListenerRule | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd |
| HTTPListenerRedirectRuleForImportedALB1 | AWS::ElasticLoadBalancingV2::ListenerRule | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd |
| EnvironmentSecurityGroupIngressFromImportedALB | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-fe-EnvironmentSecurityGroupIngressFromImportedALB not in inventory |
| EnvironmentSecurityGroupIngressFromImportedALB1 | AWS::EC2::SecurityGroupIngress | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-fe-EnvironmentSecurityGroupIngressFromImportedALB1 not in inventory |
| AddonsStack | AWS::CloudFormation::Stack | not-created |  | not created in this deployment |
| givesdogsSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: TopicName my-app-test-fe-givesdogs != topic ARN name my-app-test-fe-givesdogsSNSTopic |
| givesdogsSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |
| mytopicfifoSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: TopicName my-app-test-fe-mytopic.fifo != topic ARN name my-app-test-fe-mytopicfifoSNSTopic |
| mytopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount) |

### `my-app-test-worker` (workload): kept

Kept because: 25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 53 thing(s)</summary>

- LogGroup (AWS::Logs::LogGroup): delete
- TaskDefinition (AWS::ECS::TaskDefinition): delete
- ExecutionRole (AWS::IAM::Role): delete
- TaskRole (AWS::IAM::Role): delete
- DynamicDesiredCountFunction (AWS::Lambda::Function): delete
- DynamicDesiredCountFunctionRole (AWS::IAM::Role): delete
- AutoScalingRole (AWS::IAM::Role): delete
- AutoScalingTarget (AWS::ApplicationAutoScaling::ScalableTarget): delete
- BacklogPerTaskCalculatorLogGroup (AWS::Logs::LogGroup): delete
- BacklogPerTaskCalculatorFunction (AWS::Lambda::Function): delete
- BacklogPerTaskCalculatorRole (AWS::IAM::Role): delete
- BacklogPerTaskScheduledRule (AWS::Events::Rule): delete
- PermissionToInvokeBacklogPerTaskCalculatorLambda (AWS::Lambda::Permission): delete
- AutoScalingPolicyEventsQueue (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- AutoScalingPolicydogsvcgiveshuskiesEventsQueue (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- AutoScalingPolicymytopicmytopicfifoEventsQueue (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- AutoScalingPolicyyourtopicyourtopicfifoEventsQueue (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- AutoScalingPolicynonfifotopicnonfifotopicEventsQueue (AWS::ApplicationAutoScaling::ScalingPolicy): delete
- Service (AWS::ECS::Service): delete
- EventsKMSKey (AWS::KMS::Key): delete
- EventsQueue (AWS::SQS::Queue): delete
- DeadLetterQueue (AWS::SQS::Queue): delete
- DeadLetterPolicy (AWS::SQS::QueuePolicy): delete
- QueuePolicy (AWS::SQS::QueuePolicy): delete
- dogsvcgivesdogsSNSTopicSubscription (AWS::SNS::Subscription): delete
- dogsvcgiveshuskiesSNSTopicSubscription (AWS::SNS::Subscription): delete
- dogsvcgiveshuskiesEventsQueue (AWS::SQS::Queue): delete
- dogsvcgiveshuskiesQueuePolicy (AWS::SQS::QueuePolicy): delete
- mytopicmytopicfifoSNSTopicSubscription (AWS::SNS::Subscription): delete
- mytopicmytopicfifoEventsQueue (AWS::SQS::Queue): delete
- mytopicmytopicfifoQueuePolicy (AWS::SQS::QueuePolicy): delete
- yourtopicyourtopicfifoSNSTopicSubscription (AWS::SNS::Subscription): delete
- yourtopicyourtopicfifoEventsQueue (AWS::SQS::Queue): delete
- yourtopicyourtopicfifoQueuePolicy (AWS::SQS::QueuePolicy): delete
- nonfifotopicnonfifotopicSNSTopicSubscription (AWS::SNS::Subscription): delete
- nonfifotopicnonfifotopicEventsQueue (AWS::SQS::Queue): delete
- nonfifotopicnonfifotopicQueuePolicy (AWS::SQS::QueuePolicy): delete
- givesOtherdogsSNSTopic (AWS::SNS::Topic): delete
- givesOtherdogsSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- mytopicfifoSNSTopic (AWS::SNS::Topic): delete
- mytopicfifoSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- mytopicSNSTopic (AWS::SNS::Topic): delete
- mytopicSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- yourtopicfifoSNSTopic (AWS::SNS::Topic): delete
- yourtopicfifoSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- nonfifotopicSNSTopic (AWS::SNS::Topic): delete
- nonfifotopicSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- CPURollbackAlarm (AWS::CloudWatch::Alarm): delete
- MemoryRollbackAlarm (AWS::CloudWatch::Alarm): delete
- MessagesDelayedRollbackAlarm (AWS::CloudWatch::Alarm): delete
- EnvControllerAction (Custom::EnvControllerFunction): Delete handler: remove the workload from every *Workloads parameter and from Aliases of stack <app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an Aliases change
- EnvControllerFunction (AWS::Lambda::Function): delete
- EnvControllerRole (AWS::IAM::Role): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| LogGroup | AWS::Logs::LogGroup | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| TaskDefinition | AWS::ECS::TaskDefinition | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory |
| ExecutionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| TaskRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory |
| DynamicDesiredCountAction | Custom::DynamicDesiredCountFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| DynamicDesiredCountFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DynamicDesiredCountFunctionRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| AutoScalingRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| AutoScalingTarget | AWS::ApplicationAutoScaling::ScalableTarget | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: scalable target id service/my-app-test-worker-Cluster/my-app-test-worker-Service/ecs:service:DesiredCount/ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-worker-service/ecs:service:DesiredCount |
| BacklogPerTaskCalculatorLogGroup | AWS::Logs::LogGroup | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| BacklogPerTaskCalculatorFunction | AWS::Lambda::Function | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: Lambda function is not a custom-resource handler (user function) |
| BacklogPerTaskCalculatorRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| BacklogPerTaskScheduledRule | AWS::Events::Rule | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::Events::Rule in v0.1 |
| PermissionToInvokeBacklogPerTaskCalculatorLambda | AWS::Lambda::Permission | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: Lambda permission for a function that is not a custom-resource handler |
| AutoScalingPolicyEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt EventsQueue.QueueName (AWS::SQS::Queue) not derivable |
| AutoScalingPolicydogsvcgiveshuskiesEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt dogsvcgiveshuskiesEventsQueue.QueueName (AWS::SQS::Queue) not derivable |
| AutoScalingPolicymytopicmytopicfifoEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt mytopicmytopicfifoEventsQueue.QueueName (AWS::SQS::Queue) not derivable |
| AutoScalingPolicyyourtopicyourtopicfifoEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt yourtopicyourtopicfifoEventsQueue.QueueName (AWS::SQS::Queue) not derivable |
| AutoScalingPolicynonfifotopicnonfifotopicEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt nonfifotopicnonfifotopicEventsQueue.QueueName (AWS::SQS::Queue) not derivable |
| Service | AWS::ECS::Service | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: Service Connect is blocked in v0.1 |
| EventsKMSKey | AWS::KMS::Key | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| EventsQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| DeadLetterQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| DeadLetterPolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| QueuePolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| dogsvcgivesdogsSNSTopicSubscription | AWS::SNS::Subscription | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1 |
| dogsvcgiveshuskiesSNSTopicSubscription | AWS::SNS::Subscription | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1 |
| dogsvcgiveshuskiesEventsQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| dogsvcgiveshuskiesQueuePolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| mytopicmytopicfifoSNSTopicSubscription | AWS::SNS::Subscription | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1 |
| mytopicmytopicfifoEventsQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| mytopicmytopicfifoQueuePolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| yourtopicyourtopicfifoSNSTopicSubscription | AWS::SNS::Subscription | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1 |
| yourtopicyourtopicfifoEventsQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| yourtopicyourtopicfifoQueuePolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| nonfifotopicnonfifotopicSNSTopicSubscription | AWS::SNS::Subscription | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1 |
| nonfifotopicnonfifotopicEventsQueue | AWS::SQS::Queue | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| nonfifotopicnonfifotopicQueuePolicy | AWS::SQS::QueuePolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| givesOtherdogsSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-givesOtherdogs != topic ARN name my-app-test-worker-givesOtherdogsSNSTopic |
| givesOtherdogsSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| mytopicfifoSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-mytopic.fifo != topic ARN name my-app-test-worker-mytopicfifoSNSTopic |
| mytopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| mytopicSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-mytopic != topic ARN name my-app-test-worker-mytopicSNSTopic |
| mytopicSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| yourtopicfifoSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-yourtopic.fifo != topic ARN name my-app-test-worker-yourtopicfifoSNSTopic |
| yourtopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| nonfifotopicSNSTopic | AWS::SNS::Topic | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-nonfifotopic != topic ARN name my-app-test-worker-nonfifotopicSNSTopic |
| nonfifotopicSNSTopicPolicy | AWS::SNS::TopicPolicy | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |
| AddonsStack | AWS::CloudFormation::Stack | not-created |  | not created in this deployment |
| CPURollbackAlarm | AWS::CloudWatch::Alarm | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackCPUAlarm != physical id my-app-test-worker-CPURollbackAlarm |
| MemoryRollbackAlarm | AWS::CloudWatch::Alarm | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackMemAlarm != physical id my-app-test-worker-MemoryRollbackAlarm |
| MessagesDelayedRollbackAlarm | AWS::CloudWatch::Alarm | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackMsgsDelayedAlarm != physical id my-app-test-worker-MessagesDelayedRollbackAlarm |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | retain-under-existing-owner |  | stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1) |

## Blocked resources

Each one keeps its stack (and everything that stack depends on) on Copilot.

- `my-app-test/PublicSubnet1` (AWS::EC2::Subnet): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory
- `my-app-test/PublicSubnet2` (AWS::EC2::Subnet): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0000391282978 not in inventory
- `my-app-test/PrivateSubnet1` (AWS::EC2::Subnet): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0002743392758 not in inventory
- `my-app-test/PrivateSubnet2` (AWS::EC2::Subnet): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AvailabilityZone for subnet-0000982353996 not in inventory
- `my-app-test/NatGateway1Attachment` (AWS::EC2::EIP): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AllocationId for 52.74.1.1 not in inventory
- `my-app-test/NatGateway1` (AWS::EC2::NatGateway): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: GetAtt NatGateway1Attachment.AllocationId (AWS::EC2::EIP) not derivable
- `my-app-test/NatGateway2Attachment` (AWS::EC2::EIP): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live AllocationId for 52.153.1.1 not in inventory
- `my-app-test/NatGateway2` (AWS::EC2::NatGateway): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: GetAtt NatGateway2Attachment.AllocationId (AWS::EC2::EIP) not derivable
- `my-app-test/PublicHTTPLoadBalancerSecurityGroup` (AWS::EC2::SecurityGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0002916443411 not in inventory
- `my-app-test/InternalLoadBalancerSecurityGroup` (AWS::EC2::SecurityGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0004057235420 not in inventory
- `my-app-test/EnvironmentSecurityGroup` (AWS::EC2::SecurityGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0001960219168 not in inventory
- `my-app-test/EnvironmentHTTPSecurityGroupIngressFromPublicALB` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentHTTPSecurityGroupIngressFromPublicALB not in inventory
- `my-app-test/EnvironmentSecurityGroupIngressFromInternalALB` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentSecurityGroupIngressFromInternalALB not in inventory
- `my-app-test/EnvironmentSecurityGroupIngressFromSelf` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EnvironmentSecurityGroupIngressFromSelf not in inventory
- `my-app-test/InternalALBIngressFromEnvironmentSecurityGroup` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-InternalALBIngressFromEnvironmentSecurityGroup not in inventory
- `my-app-test/PublicLoadBalancer` (AWS::ElasticLoadBalancingV2::LoadBalancer): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value LoadBalancerName not in inventory for PublicLoadBalancer
- `my-app-test/DefaultHTTPTargetGroup` (AWS::ElasticLoadBalancingV2::TargetGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for DefaultHTTPTargetGroup
- `my-app-test/InternalLoadBalancer` (AWS::ElasticLoadBalancingV2::LoadBalancer): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value LoadBalancerName not in inventory for InternalLoadBalancer
- `my-app-test/DefaultInternalHTTPTargetGroup` (AWS::ElasticLoadBalancingV2::TargetGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for DefaultInternalHTTPTargetGroup
- `my-app-test/EFSSecurityGroup` (AWS::EC2::SecurityGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0003119112918 not in inventory
- `my-app-test/EFSSecurityGroupIngressFromEnvironment` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-EFSSecurityGroupIngressFromEnvironment not in inventory
- `my-app-test/AppRunnerVpcEndpointSecurityGroup` (AWS::EC2::SecurityGroup): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live IpPermissionsEgress for sg-0003224413762 not in inventory
- `my-app-test/AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment` (AWS::EC2::SecurityGroupIngress): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment not in inventory
- `my-app-test/LogResourcePolicy` (AWS::Logs::ResourcePolicy): stack kept (24 blocked resource(s), e.g. PublicSubnet1: cannot resolve exactly: live AvailabilityZone for subnet-0002388381848 not in inventory); would be: blocked: cannot resolve exactly: PolicyName my-app-environmentname-LogResourcePolicy != physical id my-app-test-LogResourcePolicy
- `my-app-test-fe/AutoScalingTarget` (AWS::ApplicationAutoScaling::ScalableTarget): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount
- `my-app-test-fe/Service` (AWS::ECS::Service): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: service ARN cluster my-app-test-fe-Cluster != template cluster my-app-test-Cluster-cluster
- `my-app-test-fe/TargetGroupForImportedALB` (AWS::ElasticLoadBalancingV2::TargetGroup): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for TargetGroupForImportedALB
- `my-app-test-fe/TargetGroupForImportedALB1` (AWS::ElasticLoadBalancingV2::TargetGroup): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live value TargetGroupName not in inventory for TargetGroupForImportedALB1
- `my-app-test-fe/HTTPSListenerRuleForImportedALB` (AWS::ElasticLoadBalancingV2::ListenerRule): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd
- `my-app-test-fe/HTTPSListenerRuleForImportedALB1` (AWS::ElasticLoadBalancingV2::ListenerRule): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd
- `my-app-test-fe/HTTPListenerRedirectRuleForImportedALB` (AWS::ElasticLoadBalancingV2::ListenerRule): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd
- `my-app-test-fe/HTTPListenerRedirectRuleForImportedALB1` (AWS::ElasticLoadBalancingV2::ListenerRule): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: template listener MockListenerARN1 != rule ARN listener arn:aws:elasticloadbalancing:us-west-2:123456789012:listener/app/my-app-test-fe/0123456789abcdef/abcd
- `my-app-test-fe/EnvironmentSecurityGroupIngressFromImportedALB` (AWS::EC2::SecurityGroupIngress): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-fe-EnvironmentSecurityGroupIngressFromImportedALB not in inventory
- `my-app-test-fe/EnvironmentSecurityGroupIngressFromImportedALB1` (AWS::EC2::SecurityGroupIngress): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: live SecurityGroupRuleId for my-app-test-fe-EnvironmentSecurityGroupIngressFromImportedALB1 not in inventory
- `my-app-test-fe/givesdogsSNSTopic` (AWS::SNS::Topic): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: TopicName my-app-test-fe-givesdogs != topic ARN name my-app-test-fe-givesdogsSNSTopic
- `my-app-test-fe/mytopicfifoSNSTopic` (AWS::SNS::Topic): stack kept (12 blocked resource(s), e.g. AutoScalingTarget: cannot resolve exactly: scalable target id service/my-app-test-fe-Cluster/my-app-test-fe-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-fe-service/ecs:service:DesiredCount); would be: blocked: cannot resolve exactly: TopicName my-app-test-fe-mytopic.fifo != topic ARN name my-app-test-fe-mytopicfifoSNSTopic
- `my-app-test-be/Service` (AWS::ECS::Service): stack kept (1 blocked resource(s), e.g. Service: cannot resolve exactly: Service Connect is blocked in v0.1); would be: blocked: cannot resolve exactly: Service Connect is blocked in v0.1
- `my-app-test-worker/TaskDefinition` (AWS::ECS::TaskDefinition): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory
- `my-app-test-worker/TaskRole` (AWS::IAM::Role): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory
- `my-app-test-worker/AutoScalingTarget` (AWS::ApplicationAutoScaling::ScalableTarget): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: scalable target id service/my-app-test-worker-Cluster/my-app-test-worker-Service|ecs:service:DesiredCount|ecs != template ecs/service/my-app-test-Cluster-cluster/my-app-test-worker-service/ecs:service:DesiredCount
- `my-app-test-worker/BacklogPerTaskCalculatorFunction` (AWS::Lambda::Function): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: Lambda function is not a custom-resource handler (user function)
- `my-app-test-worker/BacklogPerTaskScheduledRule` (AWS::Events::Rule): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::Events::Rule in v0.1
- `my-app-test-worker/PermissionToInvokeBacklogPerTaskCalculatorLambda` (AWS::Lambda::Permission): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: Lambda permission for a function that is not a custom-resource handler
- `my-app-test-worker/AutoScalingPolicyEventsQueue` (AWS::ApplicationAutoScaling::ScalingPolicy): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt EventsQueue.QueueName (AWS::SQS::Queue) not derivable
- `my-app-test-worker/AutoScalingPolicydogsvcgiveshuskiesEventsQueue` (AWS::ApplicationAutoScaling::ScalingPolicy): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt dogsvcgiveshuskiesEventsQueue.QueueName (AWS::SQS::Queue) not derivable
- `my-app-test-worker/AutoScalingPolicymytopicmytopicfifoEventsQueue` (AWS::ApplicationAutoScaling::ScalingPolicy): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt mytopicmytopicfifoEventsQueue.QueueName (AWS::SQS::Queue) not derivable
- `my-app-test-worker/AutoScalingPolicyyourtopicyourtopicfifoEventsQueue` (AWS::ApplicationAutoScaling::ScalingPolicy): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt yourtopicyourtopicfifoEventsQueue.QueueName (AWS::SQS::Queue) not derivable
- `my-app-test-worker/AutoScalingPolicynonfifotopicnonfifotopicEventsQueue` (AWS::ApplicationAutoScaling::ScalingPolicy): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: GetAtt nonfifotopicnonfifotopicEventsQueue.QueueName (AWS::SQS::Queue) not derivable
- `my-app-test-worker/Service` (AWS::ECS::Service): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: Service Connect is blocked in v0.1
- `my-app-test-worker/dogsvcgivesdogsSNSTopicSubscription` (AWS::SNS::Subscription): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1
- `my-app-test-worker/dogsvcgiveshuskiesSNSTopicSubscription` (AWS::SNS::Subscription): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1
- `my-app-test-worker/mytopicmytopicfifoSNSTopicSubscription` (AWS::SNS::Subscription): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1
- `my-app-test-worker/yourtopicyourtopicfifoSNSTopicSubscription` (AWS::SNS::Subscription): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1
- `my-app-test-worker/nonfifotopicnonfifotopicSNSTopicSubscription` (AWS::SNS::Subscription): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: no Terraform mapping for AWS::SNS::Subscription in v0.1
- `my-app-test-worker/givesOtherdogsSNSTopic` (AWS::SNS::Topic): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-givesOtherdogs != topic ARN name my-app-test-worker-givesOtherdogsSNSTopic
- `my-app-test-worker/mytopicfifoSNSTopic` (AWS::SNS::Topic): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-mytopic.fifo != topic ARN name my-app-test-worker-mytopicfifoSNSTopic
- `my-app-test-worker/mytopicSNSTopic` (AWS::SNS::Topic): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-mytopic != topic ARN name my-app-test-worker-mytopicSNSTopic
- `my-app-test-worker/yourtopicfifoSNSTopic` (AWS::SNS::Topic): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-yourtopic.fifo != topic ARN name my-app-test-worker-yourtopicfifoSNSTopic
- `my-app-test-worker/nonfifotopicSNSTopic` (AWS::SNS::Topic): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: TopicName my-app-test-worker-nonfifotopic != topic ARN name my-app-test-worker-nonfifotopicSNSTopic
- `my-app-test-worker/CPURollbackAlarm` (AWS::CloudWatch::Alarm): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackCPUAlarm != physical id my-app-test-worker-CPURollbackAlarm
- `my-app-test-worker/MemoryRollbackAlarm` (AWS::CloudWatch::Alarm): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackMemAlarm != physical id my-app-test-worker-MemoryRollbackAlarm
- `my-app-test-worker/MessagesDelayedRollbackAlarm` (AWS::CloudWatch::Alarm): stack kept (25 blocked resource(s), e.g. TaskDefinition: cannot resolve exactly: ImportValue stack-fs-12345: export not found in inventory; workload type 'Worker Service' blocked in v0.1); would be: blocked: cannot resolve exactly: AlarmName my-app-test-dogworker-CopilotRollbackMsgsDelayedAlarm != physical id my-app-test-worker-MessagesDelayedRollbackAlarm

## Manual cleanup after teardown

Retained by the patch, so no stack delete invokes a handler. Delete by hand after step 6.

- `my-app-test/CertificateValidationFunction` (AWS::Lambda::Function) my-app-test-CertificateValidationFunction-XYZ
- `my-app-test/CustomDomainFunction` (AWS::Lambda::Function) my-app-test-CustomDomainFunction-XYZ
- `my-app-test/DNSDelegationFunction` (AWS::Lambda::Function) my-app-test-DNSDelegationFunction-XYZ
- `my-app-test/DelegateDNSAction` (Custom::DNSDelegationFunction) my-app-test-DelegateDNSAction
- `my-app-test/HTTPSCert` (Custom::CertificateValidationFunction) my-app-test-HTTPSCert
- `my-app-test/CustomDomainAction` (Custom::CustomDomainFunction) my-app-test-CustomDomainAction
- `my-app-test-fe/DynamicDesiredCountAction` (Custom::DynamicDesiredCountFunction) my-app-test-fe-DynamicDesiredCountAction
- `my-app-test-fe/DynamicDesiredCountFunction` (AWS::Lambda::Function) my-app-test-fe-DynamicDesiredCountFunction-XYZ
- `my-app-test-fe/EnvControllerAction` (Custom::EnvControllerFunction) my-app-test-fe-EnvControllerAction
- `my-app-test-fe/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-fe-EnvControllerFunction-XYZ
- `my-app-test-fe/RulePriorityFunction` (AWS::Lambda::Function) my-app-test-fe-RulePriorityFunction-XYZ
- `my-app-test-fe/HTTPSRulePriorityAction` (Custom::RulePriorityFunction) my-app-test-fe-HTTPSRulePriorityAction
- `my-app-test-fe/HTTPRedirectRulePriorityAction` (Custom::RulePriorityFunction) my-app-test-fe-HTTPRedirectRulePriorityAction
- `my-app-test-be/EnvControllerAction` (Custom::EnvControllerFunction) my-app-test-be-EnvControllerAction
- `my-app-test-be/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-be-EnvControllerFunction-XYZ
- `my-app-test-worker/DynamicDesiredCountAction` (Custom::DynamicDesiredCountFunction) my-app-test-worker-DynamicDesiredCountAction
- `my-app-test-worker/DynamicDesiredCountFunction` (AWS::Lambda::Function) my-app-test-worker-DynamicDesiredCountFunction-XYZ
- `my-app-test-worker/EnvControllerAction` (Custom::EnvControllerFunction) my-app-test-worker-EnvControllerAction
- `my-app-test-worker/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-worker-EnvControllerFunction-XYZ

