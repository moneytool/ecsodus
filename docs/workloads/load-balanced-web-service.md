---
title: Migrate an AWS Copilot Load Balanced Web Service to Terraform
description: >-
  How ecsodus imports a Copilot Load Balanced Web Service into Terraform in place: the ECS
  service, task definition, target groups, listener rules with their live priorities, alias
  records and Service Connect, without moving traffic.
---

# Load Balanced Web Service

**Status: migrates.** Verified on real AWS ([2026-09-30 run](../e2e/2026-09-30-aws-e2e.md)).

A Load Balanced Web Service (`lb-web-svc`) is an ECS service behind the environment's public
Application Load Balancer. ecsodus imports the service stack, and the load balancer, listeners
and certificate with the environment stack. Traffic never moves.

## What is imported

| CloudFormation | Terraform | Notes |
|---|---|---|
| `AWS::ECS::Service` | `aws_ecs_service` | `task_definition` and `desired_count` are ignored after import |
| `AWS::ECS::TaskDefinition` | `aws_ecs_task_definition` | the current revision, as ECS returns it; sidecars included |
| `AWS::ElasticLoadBalancingV2::TargetGroup` | `aws_lb_target_group` | live name and attributes |
| `AWS::ElasticLoadBalancingV2::ListenerRule` | `aws_lb_listener_rule` | the priority Copilot's custom resource chose, read live |
| `AWS::Route53::RecordSetGroup` | `aws_route53_record` | alias records |
| `AWS::ServiceDiscovery::Service` | `aws_service_discovery_service` | |
| `AWS::IAM::Role`, `AWS::Logs::LogGroup` | `aws_iam_role`, `aws_cloudwatch_log_group` | managed-policy attachments are noted, not generated |
| `AWS::SNS::Topic`, `AWS::SNS::TopicPolicy` | `aws_sns_topic`, `aws_sns_topic_policy` | topics the service publishes to |
| Autoscaling target, policies, rollback alarms | `aws_appautoscaling_*`, `aws_cloudwatch_metric_alarm` | |

Copilot's default **Service Connect** is imported exactly as deployed, read from the service's
primary deployment ([ADR-0011](../adr/0011-service-connect-adopt-in-place.md)).

## Cleaned up by hand

`EnvControllerAction`, `HTTPSRulePriorityAction` / `HTTPRulePriorityAction` (they only chose rule
priorities) and their Lambdas. They are retained by the patch, so deleting the stack runs none of
their Delete handlers; the runbook lists them for deletion afterwards.

## Watch out for

- **The shared load balancer.** It belongs to the environment stack, so the environment must hand
  off too. If any workload in the environment stays on Copilot, the environment stays, and so does
  the load balancer.
- **Custom domains.** The certificate and its validation records were created by a custom
  resource, outside CloudFormation. ecsodus imports them with the environment; their survival
  through teardown on a real account is still being verified (issue #6).
- **Network Load Balancer.** An LBWS with an `nlb` section is kept on Copilot: the network
  load balancer is blocked until a migration of one has been exercised, which keeps its stack
  (and the environment it needs).
