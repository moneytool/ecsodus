---
title: Migrate an AWS Copilot Backend Service to Terraform
description: >-
  How ecsodus imports a Copilot Backend Service into Terraform in place: the ECS service, task
  definition, service discovery, Service Connect and, if it has one, the internal load balancer.
---

# Backend Service

**Status: migrates.**

A Backend Service (`backend-svc`) is an ECS service with no public endpoint. Other services
reach it through service discovery (`<name>.<env>.<app>.local`), Service Connect, or an internal
Application Load Balancer that the environment creates for it.

## What is imported

| CloudFormation | Terraform |
|---|---|
| `AWS::ECS::Service` | `aws_ecs_service` (with Service Connect as deployed) |
| `AWS::ECS::TaskDefinition` | `aws_ecs_task_definition` |
| `AWS::ServiceDiscovery::Service` | `aws_service_discovery_service` |
| `AWS::IAM::Role`, `AWS::Logs::LogGroup` | `aws_iam_role`, `aws_cloudwatch_log_group` |
| Target groups and listener rules (internal ALB only) | `aws_lb_target_group`, `aws_lb_listener_rule` |
| Autoscaling and alarms, when configured | `aws_appautoscaling_*`, `aws_cloudwatch_metric_alarm` |

## Cleaned up by hand

`EnvControllerAction` and its Lambda; with an internal ALB, also the rule-priority custom
resources.

## Watch out for

- **The internal load balancer and the NAT gateways** belong to the environment. Copilot creates
  them when a Backend Service asks for them (`InternalALBWorkloads`, `NATWorkloads` in the env
  parameters). They are imported with the environment, and the retain patch stops the
  env-controller from deleting them when the service stack goes.
- **Service Connect consumers.** Clients keep resolving the same names after the hand-off,
  because nothing is recreated.
