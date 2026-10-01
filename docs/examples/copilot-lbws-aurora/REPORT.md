# Migration readiness: Copilot app `my-app`

ecsodus 0.1.0rc1 · account `123456789012` · region `us-west-2` · inventory captured 2026-10-01T01:39:09+00:00

## Summary

- **Verdict:** ready for adopt-in-place hand-off
- Stacks: 3 (3 hand off, 0 kept on Copilot)
- Resources by fate: import 66, manual-cleanup 12, nested-wrapper 1

**Zero-risk baseline: keep the CloudFormation.** Copilot's stacks keep running without the CLI. You can deploy them with `aws cloudformation deploy` plus a deploy tool such as ecspresso. Caveats: the custom-resource Lambdas run `nodejs20.x`, so creating them is blocked from 2027-07-29, and a stack update that changes their code fails from 2027-08-31. Choose ecsodus if you want Terraform ownership.

## Workloads

| Workload | Status | Express Mode fit (informational; rebuild mode is v0.2) |
|---|---|---|
| `test/fe` (Load Balanced Web Service) | migrating | no: uses volumes |

Before any rebuild-in-parallel (v0.2), answer for each service: *does this container run background work, consumers or migrations on boot?* Parallel runs would duplicate it.

## Stacks

### `my-app-test-fe-AddonsStack-1ABCDEFGHIJKL` (addons): hand off

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 8 thing(s)</summary>

- dbDBSubnetGroup (AWS::RDS::DBSubnetGroup): delete
- dbSecurityGroup (AWS::EC2::SecurityGroup): delete
- dbDBClusterSecurityGroup (AWS::EC2::SecurityGroup): delete
- dbAuroraSecret (AWS::SecretsManager::Secret): delete
- dbDBClusterParameterGroup (AWS::RDS::DBClusterParameterGroup): delete
- dbDBCluster (AWS::RDS::DBCluster): delete
- dbDBWriterInstance (AWS::RDS::DBInstance): delete
- dbSecretAuroraClusterAttachment (AWS::SecretsManager::SecretTargetAttachment): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| dbDBSubnetGroup | AWS::RDS::DBSubnetGroup | import | aws_db_subnet_group.fe_addons_db_dbsubnet_group |  |
| dbSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.fe_addons_db_security_group |  |
| dbDBClusterSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.fe_addons_db_dbcluster_security_group |  |
| dbAuroraSecret | AWS::SecretsManager::Secret | import | aws_secretsmanager_secret.fe_addons_db_aurora_secret |  |
| dbDBClusterParameterGroup | AWS::RDS::DBClusterParameterGroup | import | aws_rds_cluster_parameter_group.fe_addons_db_dbcluster_parameter_group |  |
| dbDBCluster | AWS::RDS::DBCluster | import | aws_rds_cluster.fe_addons_db_dbcluster |  |
| dbDBWriterInstance | AWS::RDS::DBInstance | import | aws_rds_cluster_instance.fe_addons_db_dbwriter_instance |  |
| dbSecretAuroraClusterAttachment | AWS::SecretsManager::SecretTargetAttachment | manual-cleanup |  | SecretTargetAttachment has no Terraform resource: it only wrote the DB endpoint into the secret. Retained by the patch, then listed for manual cleanup (PLAN §13.8) |

### `my-app-test` (env): hand off

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 42 thing(s)</summary>

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
- PublicHTTPSLoadBalancerSecurityGroup (AWS::EC2::SecurityGroup): delete
- EnvironmentSecurityGroup (AWS::EC2::SecurityGroup): delete
- EnvironmentHTTPSecurityGroupIngressFromPublicALB (AWS::EC2::SecurityGroupIngress): delete
- EnvironmentHTTPSSecurityGroupIngressFromPublicALB (AWS::EC2::SecurityGroupIngress): delete
- EnvironmentSecurityGroupIngressFromSelf (AWS::EC2::SecurityGroupIngress): delete
- PublicLoadBalancer (AWS::ElasticLoadBalancingV2::LoadBalancer): delete
- DefaultHTTPTargetGroup (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- HTTPListener (AWS::ElasticLoadBalancingV2::Listener): delete
- HTTPSListener (AWS::ElasticLoadBalancingV2::Listener): delete
- CustomResourceRole (AWS::IAM::Role): delete
- EnvironmentHostedZone (AWS::Route53::HostedZone): delete
- CertificateValidationFunction (AWS::Lambda::Function): delete
- CustomDomainFunction (AWS::Lambda::Function): delete
- DNSDelegationFunction (AWS::Lambda::Function): delete
- DelegateDNSAction (Custom::DNSDelegationFunction): Delete handler: DELETE the NS record <env>.<app>.<domain> from the app hosted zone (via RootDNSRole) if it exactly matches
- HTTPSCert (Custom::CertificateValidationFunction): Delete handler: if physical id is an ARN: wait up to 10x30s for InUseBy empty (else FAILED); DELETE validation CNAMEs not used by another cert with the same DomainName; DeleteCertificate
- CustomDomainAction (Custom::CustomDomainFunction): Delete handler: DELETE the A-alias record for every alias in Aliases (env/app/root zone); not-found ignored / DELETE the A-alias record for every alias pointing at the current target; not-found and value-mismatch ignored / DisassociateCustomDomain, DELETE the domain CNAME and every certificate validation CNAME, wait until disassociated
- LogResourcePolicy (AWS::Logs::ResourcePolicy): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| CloudformationExecutionRole | AWS::IAM::Role | import | aws_iam_role.test_cloudformation_execution_role |  |
| EnvironmentManagerRole | AWS::IAM::Role | import | aws_iam_role.test_environment_manager_role |  |
| VPC | AWS::EC2::VPC | import | aws_vpc.test_vpc |  |
| PublicRouteTable | AWS::EC2::RouteTable | import | aws_route_table.test_public_route_table |  |
| DefaultPublicRoute | AWS::EC2::Route | import | aws_route.test_default_public_route |  |
| InternetGateway | AWS::EC2::InternetGateway | import | aws_internet_gateway.test_internet_gateway |  |
| InternetGatewayAttachment | AWS::EC2::VPCGatewayAttachment | import | aws_internet_gateway_attachment.test_internet_gateway_attachment |  |
| PublicSubnet1 | AWS::EC2::Subnet | import | aws_subnet.test_public_subnet1 |  |
| PublicSubnet2 | AWS::EC2::Subnet | import | aws_subnet.test_public_subnet2 |  |
| PrivateSubnet1 | AWS::EC2::Subnet | import | aws_subnet.test_private_subnet1 |  |
| PrivateSubnet2 | AWS::EC2::Subnet | import | aws_subnet.test_private_subnet2 |  |
| PublicSubnet1RouteTableAssociation | AWS::EC2::SubnetRouteTableAssociation | import | aws_route_table_association.test_public_subnet1_route_table_association |  |
| PublicSubnet2RouteTableAssociation | AWS::EC2::SubnetRouteTableAssociation | import | aws_route_table_association.test_public_subnet2_route_table_association |  |
| NatGateway1Attachment | AWS::EC2::EIP | import | aws_eip.test_nat_gateway1_attachment |  |
| NatGateway1 | AWS::EC2::NatGateway | import | aws_nat_gateway.test_nat_gateway1 |  |
| PrivateRouteTable1 | AWS::EC2::RouteTable | import | aws_route_table.test_private_route_table1 |  |
| PrivateRoute1 | AWS::EC2::Route | import | aws_route.test_private_route1 |  |
| PrivateRouteTable1Association | AWS::EC2::SubnetRouteTableAssociation | import | aws_route_table_association.test_private_route_table1_association |  |
| NatGateway2Attachment | AWS::EC2::EIP | import | aws_eip.test_nat_gateway2_attachment |  |
| NatGateway2 | AWS::EC2::NatGateway | import | aws_nat_gateway.test_nat_gateway2 |  |
| PrivateRouteTable2 | AWS::EC2::RouteTable | import | aws_route_table.test_private_route_table2 |  |
| PrivateRoute2 | AWS::EC2::Route | import | aws_route.test_private_route2 |  |
| PrivateRouteTable2Association | AWS::EC2::SubnetRouteTableAssociation | import | aws_route_table_association.test_private_route_table2_association |  |
| ServiceDiscoveryNamespace | AWS::ServiceDiscovery::PrivateDnsNamespace | import | aws_service_discovery_private_dns_namespace.test_service_discovery_namespace |  |
| Cluster | AWS::ECS::Cluster | import | aws_ecs_cluster.test_cluster | partial argument coverage |
| PublicHTTPLoadBalancerSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.test_public_httpload_balancer_security_group |  |
| PublicHTTPSLoadBalancerSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.test_public_httpsload_balancer_security_group |  |
| EnvironmentSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.test_environment_security_group |  |
| EnvironmentHTTPSecurityGroupIngressFromPublicALB | AWS::EC2::SecurityGroupIngress | import | aws_vpc_security_group_ingress_rule.test_environment_httpsecurity_group_ingress_from_public_alb |  |
| EnvironmentHTTPSSecurityGroupIngressFromPublicALB | AWS::EC2::SecurityGroupIngress | import | aws_vpc_security_group_ingress_rule.test_environment_httpssecurity_group_ingress_from_public_alb |  |
| EnvironmentSecurityGroupIngressFromSelf | AWS::EC2::SecurityGroupIngress | import | aws_vpc_security_group_ingress_rule.test_environment_security_group_ingress_from_self |  |
| PublicLoadBalancer | AWS::ElasticLoadBalancingV2::LoadBalancer | import | aws_lb.test_public_load_balancer |  |
| DefaultHTTPTargetGroup | AWS::ElasticLoadBalancingV2::TargetGroup | import | aws_lb_target_group.test_default_httptarget_group |  |
| HTTPListener | AWS::ElasticLoadBalancingV2::Listener | import | aws_lb_listener.test_httplistener |  |
| HTTPSListener | AWS::ElasticLoadBalancingV2::Listener | import | aws_lb_listener.test_httpslistener |  |
| CustomResourceRole | AWS::IAM::Role | import | aws_iam_role.test_custom_resource_role |  |
| EnvironmentHostedZone | AWS::Route53::HostedZone | import | aws_route53_zone.test_environment_hosted_zone |  |
| CertificateValidationFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| CustomDomainFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DNSDelegationFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DelegateDNSAction | Custom::DNSDelegationFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPSCert | Custom::CertificateValidationFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| CustomDomainAction | Custom::CustomDomainFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| LogResourcePolicy | AWS::Logs::ResourcePolicy | import | aws_cloudwatch_log_resource_policy.test_log_resource_policy |  |
| out-of-band:11111111-2222-3333-4444-555555555555 | OutOfBand::ACM::Certificate | import | aws_acm_certificate.oob_cert_test_my_app_example_com | out-of-band certificate |
| out-of-band:_0123456789abcdef0123456789abcdef.test.my-app.example.com/CNAME | OutOfBand::Route53::Record | import | aws_route53_record.oob_0123456789abcdef0123456789abcdef_test_my_app_example_com_cname | out-of-band record |

### `my-app-test-fe` (workload): hand off

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 23 thing(s)</summary>

- LogGroup (AWS::Logs::LogGroup): delete
- TaskDefinition (AWS::ECS::TaskDefinition): delete
- ExecutionRole (AWS::IAM::Role): delete
- TaskRole (AWS::IAM::Role): delete
- DiscoveryService (AWS::ServiceDiscovery::Service): delete
- EnvControllerAction (Custom::EnvControllerFunction): Delete handler: remove the workload from every *Workloads parameter and from Aliases of stack <app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an Aliases change
- EnvControllerFunction (AWS::Lambda::Function): delete
- EnvControllerRole (AWS::IAM::Role): delete
- Service (AWS::ECS::Service): delete
- TargetGroup (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- TargetGroup1 (AWS::ElasticLoadBalancingV2::TargetGroup): delete
- RulePriorityFunction (AWS::Lambda::Function): delete
- RulePriorityFunctionRole (AWS::IAM::Role): delete
- LoadBalancerDNSAliasmockHostedZone (AWS::Route53::RecordSetGroup): delete
- HTTPListenerRuleWithDomain (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPListenerRuleWithDomain1 (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPSListenerRule (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- HTTPSListenerRule1 (AWS::ElasticLoadBalancingV2::ListenerRule): delete
- AddonsStack (AWS::CloudFormation::Stack): delete
- givesdogsSNSTopic (AWS::SNS::Topic): delete
- givesdogsSNSTopicPolicy (AWS::SNS::TopicPolicy): delete
- mytopicfifoSNSTopic (AWS::SNS::Topic): delete
- mytopicfifoSNSTopicPolicy (AWS::SNS::TopicPolicy): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| LogGroup | AWS::Logs::LogGroup | import | aws_cloudwatch_log_group.fe_log_group |  |
| TaskDefinition | AWS::ECS::TaskDefinition | import | aws_ecs_task_definition.fe_task_definition |  |
| ExecutionRole | AWS::IAM::Role | import | aws_iam_role.fe_execution_role | partial argument coverage |
| TaskRole | AWS::IAM::Role | import | aws_iam_role.fe_task_role |  |
| DiscoveryService | AWS::ServiceDiscovery::Service | import | aws_service_discovery_service.fe_discovery_service |  |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | import | aws_iam_role.fe_env_controller_role | partial argument coverage |
| Service | AWS::ECS::Service | import | aws_ecs_service.fe_service |  |
| TargetGroup | AWS::ElasticLoadBalancingV2::TargetGroup | import | aws_lb_target_group.fe_target_group |  |
| TargetGroup1 | AWS::ElasticLoadBalancingV2::TargetGroup | import | aws_lb_target_group.fe_target_group1 |  |
| RulePriorityFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| RulePriorityFunctionRole | AWS::IAM::Role | import | aws_iam_role.fe_rule_priority_function_role | partial argument coverage |
| LoadBalancerDNSAliasmockHostedZone | AWS::Route53::RecordSetGroup | import | aws_route53_record.fe_load_balancer_dnsaliasmock_hosted_zone |  |
| HTTPSRulePriorityAction | Custom::RulePriorityFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPRuleWithDomainPriorityAction | Custom::RulePriorityFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| HTTPListenerRuleWithDomain | AWS::ElasticLoadBalancingV2::ListenerRule | import | aws_lb_listener_rule.fe_httplistener_rule_with_domain |  |
| HTTPListenerRuleWithDomain1 | AWS::ElasticLoadBalancingV2::ListenerRule | import | aws_lb_listener_rule.fe_httplistener_rule_with_domain1 |  |
| HTTPSListenerRule | AWS::ElasticLoadBalancingV2::ListenerRule | import | aws_lb_listener_rule.fe_httpslistener_rule |  |
| HTTPSListenerRule1 | AWS::ElasticLoadBalancingV2::ListenerRule | import | aws_lb_listener_rule.fe_httpslistener_rule1 |  |
| AddonsStack | AWS::CloudFormation::Stack | nested-wrapper |  | nested stack wrapper; its child stack is inventoried |
| givesdogsSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.fe_givesdogs_snstopic |  |
| givesdogsSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.fe_givesdogs_snstopic_policy |  |
| mytopicfifoSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.fe_mytopicfifo_snstopic |  |
| mytopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.fe_mytopicfifo_snstopic_policy |  |

## Manual cleanup after teardown

Retained by the patch, so no stack delete invokes a handler. Delete by hand after step 6.

- `my-app-test/CertificateValidationFunction` (AWS::Lambda::Function) my-app-test-CertificateValidationFunction-AbC1
- `my-app-test/CustomDomainFunction` (AWS::Lambda::Function) my-app-test-CustomDomainFunction-DeF2
- `my-app-test/DNSDelegationFunction` (AWS::Lambda::Function) my-app-test-DNSDelegationFunction-GhI3
- `my-app-test/DelegateDNSAction` (Custom::DNSDelegationFunction) my-app-test-DelegateDNSAction-JkL4
- `my-app-test/HTTPSCert` (Custom::CertificateValidationFunction) arn:aws:acm:us-west-2:123456789012:certificate/11111111-2222-3333-4444-555555555555
- `my-app-test/CustomDomainAction` (Custom::CustomDomainFunction) my-app-test-CustomDomainAction-MnO5
- `my-app-test-fe/EnvControllerAction` (Custom::EnvControllerFunction) my-app-test-fe-EnvControllerAction-1Q2W3E4R5T6Y
- `my-app-test-fe/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-fe-EnvControllerFunction-M3N4
- `my-app-test-fe/RulePriorityFunction` (AWS::Lambda::Function) my-app-test-fe-RulePriorityFunction-U1V2
- `my-app-test-fe/HTTPSRulePriorityAction` (Custom::RulePriorityFunction) my-app-test-fe-HTTPSRulePriorityAction-7U8I9O0P1A2S
- `my-app-test-fe/HTTPRuleWithDomainPriorityAction` (Custom::RulePriorityFunction) my-app-test-fe-HTTPRuleWithDomainPriorityAction-3D4F5G6H7J8K
- `my-app-test-fe-AddonsStack-1ABCDEFGHIJKL/dbSecretAuroraClusterAttachment` (AWS::SecretsManager::SecretTargetAttachment) arn:aws:secretsmanager:us-west-2:123456789012:secret:dbAuroraSecret-AbCdEfGhIjKl-q1W2e3

## Partial argument coverage

These imports are generated, but `check --phase import` will flag any argument ecsodus could not reproduce. Resolve them before applying.

- `aws_ecs_cluster.test_cluster`: capacity providers are a separate resource (aws_ecs_cluster_capacity_providers, import id "my-app-test-Cluster-Q1w2E3r4T5y6"); not generated in v0.1
- `aws_iam_role.fe_execution_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-ExecutionRole-1A2B3C4D5E6F:my-app-test-feSecretsPolicy"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-ExecutionRole-1A2B3C4D5E6F/arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
- `aws_iam_role.fe_env_controller_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0:EnvControllerStackUpdate"; "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0:EnvControllerRolePass"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.fe_rule_priority_function_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-RulePriorityFunctionRole-W3X4Y5Z6A7B8:RulePriorityGeneratorAccess"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-RulePriorityFunctionRole-W3X4Y5Z6A7B8/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_acm_certificate.oob_cert_test_my_app_example_com`: created out of band by Copilot custom resource my-app-test/HTTPSCert; the custom resource is retained, so it never deletes this certificate

