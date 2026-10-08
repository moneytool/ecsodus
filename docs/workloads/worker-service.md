---
title: Migrate an AWS Copilot Worker Service to Terraform
description: >-
  How ecsodus imports a Copilot Worker Service into Terraform: SQS queues, SNS subscriptions,
  the KMS key and the backlog-per-task Lambda that drives queue-depth autoscaling, kept running
  instead of deleted.
---

# Worker Service

**Status: migrates** ([ADR-0014](../adr/0014-worker-services.md)). Verified on real AWS
([2026-10-07 run](../e2e/2026-10-07-aws-e2e-workers-jobs.md)).

A Worker Service (`worker-svc`) reads messages from an SQS queue. Copilot creates an events
queue, a dead-letter queue, one queue per topic it subscribes to, and SNS subscriptions from
other services' topics. It scales on **backlog per task**, a metric that a small Lambda publishes
every minute.

## What is imported

| CloudFormation | Terraform | Notes |
|---|---|---|
| `AWS::SQS::Queue`, `AWS::SQS::QueuePolicy` | `aws_sqs_queue`, `aws_sqs_queue_policy` | `prevent_destroy` on queues |
| `AWS::SNS::Subscription` | `aws_sns_topic_subscription` | filter policy and raw delivery checked against live |
| `AWS::KMS::Key` | `aws_kms_key` | the key that encrypts the queues |
| `BacklogPerTaskCalculatorFunction` | `aws_lambda_function` | imported, **not** deleted; its code location is ignored |
| `BacklogPerTaskScheduledRule` | `aws_cloudwatch_event_rule` + `aws_cloudwatch_event_target` | every minute |
| `PermissionToInvokeBacklogPerTaskCalculatorLambda` | `aws_lambda_permission` | |
| Autoscaling policies on `BacklogPerTask` | `aws_appautoscaling_policy` | |
| Service, task definition, roles, alarms, topics | as for any service | |

## Why the backlog Lambda is kept

Every other Lambda in a Copilot stack handles a custom resource and is deleted after the
migration. This one is not a custom resource: it computes
`ceil(messages / running tasks)` for each queue and publishes it as the metric the scaling
policies track. Deleting it would leave the service running at whatever size it was, with no
error anywhere. ecsodus imports it, its role, log group, schedule and permission.

## Cleaned up by hand

`EnvControllerAction` and `DynamicDesiredCountAction` (it only set the starting task count), and
their Lambdas.

## Watch out for

- **Topics owned by other services.** A subscription points at another service's topic. The
  subscription moves to Terraform; the topic stays wherever its service is.
- **EFS from another stack.** Copilot's worker render can mount a file system that a separate
  stack exports. ecsodus reads exactly the exports the templates import by name, and nothing else.
- **Runtime deadline.** The backlog Lambda runs on `nodejs20.x`. AWS blocks updates to that
  runtime from 2027-08-31; move it to a supported runtime before then (the generated Terraform
  carries a note).
