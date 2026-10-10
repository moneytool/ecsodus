# Migration readiness: Copilot app `my-app`

ecsodus 0.2.1 · account `123456789012` · region `us-west-2` · inventory captured 2026-10-09T03:00:15+00:00

## Summary

- **Verdict:** ready for adopt-in-place hand-off
- Stacks: 5 (5 hand off, 0 kept on Copilot)
- Resources by fate: external-reference 1, import 135, manual-cleanup 18, nested-wrapper 1

**Zero-risk baseline: keep the CloudFormation.** Copilot's stacks keep running without the CLI. You can deploy them with `aws cloudformation deploy` plus a deploy tool such as ecspresso. Caveats: the custom-resource Lambdas run `nodejs20.x`, so creating them is blocked from 2027-07-29, and a stack update that changes their code fails from 2027-08-31. Choose ecsodus if you want Terraform ownership.

## Workloads

| Workload | Status | Express Mode fit (informational; rebuild mode is v0.2) |
|---|---|---|
| `test/dogworker` (Worker Service) | migrating | no: not a Load Balanced Web Service; service not resolvable offline; uses volumes |
| `test/fe` (Load Balanced Web Service) | migrating | no: uses volumes |
| `test/job` (Scheduled Job) | migrating | no: more than one container (sidecars); not a Load Balanced Web Service; uses volumes |

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

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 47 thing(s)</summary>

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
| FileSystem | AWS::EFS::FileSystem | import | aws_efs_file_system.test_file_system | partial argument coverage |
| EFSSecurityGroup | AWS::EC2::SecurityGroup | import | aws_security_group.test_efssecurity_group |  |
| EFSSecurityGroupIngressFromEnvironment | AWS::EC2::SecurityGroupIngress | import | aws_vpc_security_group_ingress_rule.test_efssecurity_group_ingress_from_environment |  |
| MountTarget1 | AWS::EFS::MountTarget | import | aws_efs_mount_target.test_mount_target1 |  |
| MountTarget2 | AWS::EFS::MountTarget | import | aws_efs_mount_target.test_mount_target2 |  |
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
| out-of-band:_00112233445566778899aabbccddeeff.example.com/CNAME | OutOfBand::Route53::Record | external-reference |  | ACM validation record for example.com (certificate arn:aws:acm:us-west-2:123456789012:certificate/11111111-2222-3333-4444-555555555555) is in a hosted zone ecsodus does not import (not a Copilot zone, such as the root domain's). Its handler is retained, so nothing deletes it, but Terraform will not manage it: keep it, or import it yourself. |

### `my-app-test-dogworker` (workload): hand off

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
| LogGroup | AWS::Logs::LogGroup | import | aws_cloudwatch_log_group.dogworker_log_group |  |
| TaskDefinition | AWS::ECS::TaskDefinition | import | aws_ecs_task_definition.dogworker_task_definition |  |
| ExecutionRole | AWS::IAM::Role | import | aws_iam_role.dogworker_execution_role | partial argument coverage |
| TaskRole | AWS::IAM::Role | import | aws_iam_role.dogworker_task_role |  |
| DynamicDesiredCountAction | Custom::DynamicDesiredCountFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| DynamicDesiredCountFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| DynamicDesiredCountFunctionRole | AWS::IAM::Role | import | aws_iam_role.dogworker_dynamic_desired_count_function_role | partial argument coverage |
| AutoScalingRole | AWS::IAM::Role | import | aws_iam_role.dogworker_auto_scaling_role | partial argument coverage |
| AutoScalingTarget | AWS::ApplicationAutoScaling::ScalableTarget | import | aws_appautoscaling_target.dogworker_auto_scaling_target |  |
| BacklogPerTaskCalculatorLogGroup | AWS::Logs::LogGroup | import | aws_cloudwatch_log_group.dogworker_backlog_per_task_calculator_log_group |  |
| BacklogPerTaskCalculatorFunction | AWS::Lambda::Function | import | aws_lambda_function.dogworker_backlog_per_task_calculator_function |  |
| BacklogPerTaskCalculatorRole | AWS::IAM::Role | import | aws_iam_role.dogworker_backlog_per_task_calculator_role | partial argument coverage |
| BacklogPerTaskScheduledRule | AWS::Events::Rule | import | aws_cloudwatch_event_rule.dogworker_backlog_per_task_scheduled_rule |  |
| BacklogPerTaskScheduledRule/target_BacklogPerTaskCalculatorFunctionTrigger | AWS::Events::Rule | import | aws_cloudwatch_event_target.dogworker_backlog_per_task_scheduled_rule_target_backlog_per_task_calculator_function_trigger | deployed by BacklogPerTaskScheduledRule |
| PermissionToInvokeBacklogPerTaskCalculatorLambda | AWS::Lambda::Permission | import | aws_lambda_permission.dogworker_permission_to_invoke_backlog_per_task_calculator_lambda |  |
| AutoScalingPolicyEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | import | aws_appautoscaling_policy.dogworker_auto_scaling_policy_events_queue |  |
| AutoScalingPolicydogsvcgiveshuskiesEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | import | aws_appautoscaling_policy.dogworker_auto_scaling_policydogsvcgiveshuskies_events_queue |  |
| AutoScalingPolicymytopicmytopicfifoEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | import | aws_appautoscaling_policy.dogworker_auto_scaling_policymytopicmytopicfifo_events_queue |  |
| AutoScalingPolicyyourtopicyourtopicfifoEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | import | aws_appautoscaling_policy.dogworker_auto_scaling_policyyourtopicyourtopicfifo_events_queue |  |
| AutoScalingPolicynonfifotopicnonfifotopicEventsQueue | AWS::ApplicationAutoScaling::ScalingPolicy | import | aws_appautoscaling_policy.dogworker_auto_scaling_policynonfifotopicnonfifotopic_events_queue |  |
| Service | AWS::ECS::Service | import | aws_ecs_service.dogworker_service |  |
| EventsKMSKey | AWS::KMS::Key | import | aws_kms_key.dogworker_events_kmskey |  |
| EventsQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_events_queue |  |
| DeadLetterQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_dead_letter_queue |  |
| DeadLetterPolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_dead_letter_policy |  |
| QueuePolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_queue_policy |  |
| dogsvcgivesdogsSNSTopicSubscription | AWS::SNS::Subscription | import | aws_sns_topic_subscription.dogworker_dogsvcgivesdogs_snstopic_subscription |  |
| dogsvcgiveshuskiesSNSTopicSubscription | AWS::SNS::Subscription | import | aws_sns_topic_subscription.dogworker_dogsvcgiveshuskies_snstopic_subscription |  |
| dogsvcgiveshuskiesEventsQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_dogsvcgiveshuskies_events_queue |  |
| dogsvcgiveshuskiesQueuePolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_dogsvcgiveshuskies_queue_policy |  |
| mytopicmytopicfifoSNSTopicSubscription | AWS::SNS::Subscription | import | aws_sns_topic_subscription.dogworker_mytopicmytopicfifo_snstopic_subscription |  |
| mytopicmytopicfifoEventsQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_mytopicmytopicfifo_events_queue |  |
| mytopicmytopicfifoQueuePolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_mytopicmytopicfifo_queue_policy |  |
| yourtopicyourtopicfifoSNSTopicSubscription | AWS::SNS::Subscription | import | aws_sns_topic_subscription.dogworker_yourtopicyourtopicfifo_snstopic_subscription |  |
| yourtopicyourtopicfifoEventsQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_yourtopicyourtopicfifo_events_queue |  |
| yourtopicyourtopicfifoQueuePolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_yourtopicyourtopicfifo_queue_policy |  |
| nonfifotopicnonfifotopicSNSTopicSubscription | AWS::SNS::Subscription | import | aws_sns_topic_subscription.dogworker_nonfifotopicnonfifotopic_snstopic_subscription |  |
| nonfifotopicnonfifotopicEventsQueue | AWS::SQS::Queue | import | aws_sqs_queue.dogworker_nonfifotopicnonfifotopic_events_queue |  |
| nonfifotopicnonfifotopicQueuePolicy | AWS::SQS::QueuePolicy | import | aws_sqs_queue_policy.dogworker_nonfifotopicnonfifotopic_queue_policy |  |
| givesOtherdogsSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.dogworker_gives_otherdogs_snstopic |  |
| givesOtherdogsSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.dogworker_gives_otherdogs_snstopic_policy |  |
| mytopicfifoSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.dogworker_mytopicfifo_snstopic |  |
| mytopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.dogworker_mytopicfifo_snstopic_policy |  |
| mytopicSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.dogworker_mytopic_snstopic |  |
| mytopicSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.dogworker_mytopic_snstopic_policy |  |
| yourtopicfifoSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.dogworker_yourtopicfifo_snstopic |  |
| yourtopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.dogworker_yourtopicfifo_snstopic_policy |  |
| nonfifotopicSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.dogworker_nonfifotopic_snstopic |  |
| nonfifotopicSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.dogworker_nonfifotopic_snstopic_policy |  |
| CPURollbackAlarm | AWS::CloudWatch::Alarm | import | aws_cloudwatch_metric_alarm.dogworker_cpurollback_alarm |  |
| MemoryRollbackAlarm | AWS::CloudWatch::Alarm | import | aws_cloudwatch_metric_alarm.dogworker_memory_rollback_alarm |  |
| MessagesDelayedRollbackAlarm | AWS::CloudWatch::Alarm | import | aws_cloudwatch_metric_alarm.dogworker_messages_delayed_rollback_alarm |  |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | import | aws_iam_role.dogworker_env_controller_role | partial argument coverage |

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

### `my-app-test-job` (workload): hand off

<details><summary>Deleting this stack <b>without</b> the retain patch would destroy 14 thing(s)</summary>

- LogGroup (AWS::Logs::LogGroup): delete
- EnvControllerAction (Custom::EnvControllerFunction): Delete handler: remove the workload from every *Workloads parameter and from Aliases of stack <app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an Aliases change
- EnvControllerFunction (AWS::Lambda::Function): delete
- EnvControllerRole (AWS::IAM::Role): delete
- TaskDefinition (AWS::ECS::TaskDefinition): delete
- ExecutionRole (AWS::IAM::Role): delete
- TaskRole (AWS::IAM::Role): delete
- Rule (AWS::Events::Rule): delete
- RuleRole (AWS::IAM::Role): delete
- StateMachine (AWS::StepFunctions::StateMachine): delete
- StateMachineRole (AWS::IAM::Role): delete
- AccessPoint (AWS::EFS::AccessPoint): delete
- mytopicfifoSNSTopic (AWS::SNS::Topic): delete
- mytopicfifoSNSTopicPolicy (AWS::SNS::TopicPolicy): delete

</details>

With the retain patch: **nothing**. Every resource is retained.

| Logical ID | Type | Fate | Terraform | Note |
|---|---|---|---|---|
| LogGroup | AWS::Logs::LogGroup | import | aws_cloudwatch_log_group.job_log_group |  |
| EnvControllerAction | Custom::EnvControllerFunction | manual-cleanup |  | custom-resource handle: retained, then cleaned up |
| EnvControllerFunction | AWS::Lambda::Function | manual-cleanup |  | Copilot custom-resource handler: retained by the patch, deleted manually after teardown |
| EnvControllerRole | AWS::IAM::Role | import | aws_iam_role.job_env_controller_role | partial argument coverage |
| TaskDefinition | AWS::ECS::TaskDefinition | import | aws_ecs_task_definition.job_task_definition |  |
| ExecutionRole | AWS::IAM::Role | import | aws_iam_role.job_execution_role | partial argument coverage |
| TaskRole | AWS::IAM::Role | import | aws_iam_role.job_task_role |  |
| Rule | AWS::Events::Rule | import | aws_cloudwatch_event_rule.job_rule |  |
| Rule/target_statemachine | AWS::Events::Rule | import | aws_cloudwatch_event_target.job_rule_target_statemachine | deployed by Rule |
| RuleRole | AWS::IAM::Role | import | aws_iam_role.job_rule_role |  |
| StateMachine | AWS::StepFunctions::StateMachine | import | aws_sfn_state_machine.job_state_machine |  |
| StateMachineRole | AWS::IAM::Role | import | aws_iam_role.job_state_machine_role |  |
| AccessPoint | AWS::EFS::AccessPoint | import | aws_efs_access_point.job_access_point |  |
| mytopicfifoSNSTopic | AWS::SNS::Topic | import | aws_sns_topic.job_mytopicfifo_snstopic |  |
| mytopicfifoSNSTopicPolicy | AWS::SNS::TopicPolicy | import | aws_sns_topic_policy.job_mytopicfifo_snstopic_policy |  |

## Manual cleanup after teardown

Retained by the patch, so no stack delete invokes a handler. Delete by hand after step 6.

- `my-app-test/CertificateValidationFunction` (AWS::Lambda::Function) my-app-test-CertificateValidationFunction-AbC1
- `my-app-test/CustomDomainFunction` (AWS::Lambda::Function) my-app-test-CustomDomainFunction-DeF2
- `my-app-test/DNSDelegationFunction` (AWS::Lambda::Function) my-app-test-DNSDelegationFunction-GhI3
- `my-app-test-fe/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-fe-EnvControllerFunction-M3N4
- `my-app-test-fe/RulePriorityFunction` (AWS::Lambda::Function) my-app-test-fe-RulePriorityFunction-U1V2
- `my-app-test-fe-AddonsStack-1ABCDEFGHIJKL/dbSecretAuroraClusterAttachment` (AWS::SecretsManager::SecretTargetAttachment) arn:aws:secretsmanager:us-west-2:123456789012:secret:dbAuroraSecret-AbCdEfGhIjKl-q1W2e3
- `my-app-test-dogworker/DynamicDesiredCountFunction` (AWS::Lambda::Function) my-app-test-dogworker-DynamicDesiredCountFunct-Mn8Bv4
- `my-app-test-dogworker/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-dogworker-EnvControllerFunction-Pq1Ws3
- `my-app-test-job/EnvControllerFunction` (AWS::Lambda::Function) my-app-test-job-EnvControllerFunction-Zx9Cv8

Custom-resource handles are not AWS resources: they disappear with their stack, so there is nothing to delete. Never delete anything by a handle's physical ID: `HTTPSCert`'s is the imported certificate's ARN, and `DelegateDNSAction`'s names the env zone's NS delegation.

- `my-app-test/DelegateDNSAction` (Custom::DNSDelegationFunction)
- `my-app-test/HTTPSCert` (Custom::CertificateValidationFunction)
- `my-app-test/CustomDomainAction` (Custom::CustomDomainFunction)
- `my-app-test-fe/EnvControllerAction` (Custom::EnvControllerFunction)
- `my-app-test-fe/HTTPSRulePriorityAction` (Custom::RulePriorityFunction)
- `my-app-test-fe/HTTPRuleWithDomainPriorityAction` (Custom::RulePriorityFunction)
- `my-app-test-dogworker/DynamicDesiredCountAction` (Custom::DynamicDesiredCountFunction)
- `my-app-test-dogworker/EnvControllerAction` (Custom::EnvControllerFunction)
- `my-app-test-job/EnvControllerAction` (Custom::EnvControllerFunction)

## External references (never imported)

- `my-app-test/out-of-band:_00112233445566778899aabbccddeeff.example.com/CNAME` (OutOfBand::Route53::Record): ACM validation record for example.com (certificate arn:aws:acm:us-west-2:123456789012:certificate/11111111-2222-3333-4444-555555555555) is in a hosted zone ecsodus does not import (not a Copilot zone, such as the root domain's). Its handler is retained, so nothing deletes it, but Terraform will not manage it: keep it, or import it yourself.

## Partial argument coverage

These imports are generated, but `check --phase import` will flag any argument ecsodus could not reproduce. Resolve them before applying.

- `aws_ecs_cluster.test_cluster`: capacity providers are a separate resource (aws_ecs_cluster_capacity_providers, import id "my-app-test-Cluster-Q1w2E3r4T5y6"); not generated in v0.1
- `aws_efs_file_system.test_file_system`: file-system sub-configurations are separate resources and are not generated in v0.1: aws_efs_backup_policy (import id "fs-0a1b2c3d4e5f60081", status ENABLED); aws_efs_file_system_policy (import id "fs-0a1b2c3d4e5f60081")
- `aws_iam_role.fe_execution_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-ExecutionRole-1A2B3C4D5E6F:my-app-test-feSecretsPolicy"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-ExecutionRole-1A2B3C4D5E6F/arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
- `aws_iam_role.fe_env_controller_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0:EnvControllerStackUpdate"; "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0:EnvControllerRolePass"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-EnvControllerRole-O5P6Q7R8S9T0/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.fe_rule_priority_function_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-fe-RulePriorityFunctionRole-W3X4Y5Z6A7B8:RulePriorityGeneratorAccess"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-fe-RulePriorityFunctionRole-W3X4Y5Z6A7B8/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.dogworker_execution_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-dogworker-ExecutionRole-0326928404:my-app-test-dogworkerSecretsPolicy"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-dogworker-ExecutionRole-0326928404/arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
- `aws_iam_role.dogworker_dynamic_desired_count_function_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-dogworker-DynamicDesiredCountFunctionRole-0286234772:DelegateDesiredCountAccess"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-dogworker-DynamicDesiredCountFunctionRole-0286234772/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.dogworker_auto_scaling_role`: managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-dogworker-AutoScalingRole-0748259709/arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceAutoscaleRole"
- `aws_iam_role.dogworker_backlog_per_task_calculator_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-dogworker-BacklogPerTaskCalculatorRole-3192178377:BacklogPerTaskCalculatorAccess"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-dogworker-BacklogPerTaskCalculatorRole-3192178377/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.dogworker_env_controller_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-dogworker-EnvControllerRole-1906381098:EnvControllerStackUpdate"; "my-app-test-dogworker-EnvControllerRole-1906381098:EnvControllerRolePass"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-dogworker-EnvControllerRole-1906381098/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.job_env_controller_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-job-EnvControllerRole-1906381098:EnvControllerStackUpdate"; "my-app-test-job-EnvControllerRole-1906381098:EnvControllerRolePass"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-job-EnvControllerRole-1906381098/arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
- `aws_iam_role.job_execution_role`: inline policies are emitted as inline_policy blocks (deprecated in provider 6.x but exact: the live role has exactly these inline policies). To move to aws_iam_role_policy later, import ids: "my-app-test-job-ExecutionRole-0326928404:my-app-test-jobSecretsPolicy"; managed policy attachments (managed_policy_arns is deprecated in provider 6.x) are separate aws_iam_role_policy_attachment resources, not generated in v0.1; import ids: "my-app-test-job-ExecutionRole-0326928404/arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
- `aws_acm_certificate.oob_cert_test_my_app_example_com`: created out of band by Copilot custom resource my-app-test/HTTPSCert; the custom resource is retained, so it never deletes this certificate

