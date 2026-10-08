---
title: Migrate an AWS Copilot Scheduled Job to Terraform
description: >-
  How ecsodus imports a Copilot Scheduled Job into Terraform: the EventBridge schedule, the
  Step Functions state machine that runs the ECS task, their roles, and the EFS access point.
---

# Scheduled Job

**Status: migrates** ([ADR-0015](../adr/0015-scheduled-jobs.md)). Verified on real AWS
([2026-10-07 run](../e2e/2026-10-07-aws-e2e-workers-jobs.md)).

A Scheduled Job (`scheduled-job`) has no ECS service. An EventBridge rule fires on the job's
schedule and, assuming a role, starts a Step Functions state machine. The state machine runs the
task (`ecs:runTask.sync`) with the job's retries and timeout.

## What is imported

| CloudFormation | Terraform | Notes |
|---|---|---|
| `Rule` (`AWS::Events::Rule`) | `aws_cloudwatch_event_rule` + `aws_cloudwatch_event_target` | the target keeps its `role_arn` |
| `StateMachine` | `aws_sfn_state_machine` | the definition as deployed |
| `RuleRole`, `StateMachineRole`, task roles | `aws_iam_role` | |
| `TaskDefinition` | `aws_ecs_task_definition` | sidecars included |
| `AccessPoint` | `aws_efs_access_point` | on the environment's managed EFS |
| Log group, topics | as for any service | |

## The state machine definition

Copilot writes the definition with placeholders (`${Cluster}`, `${TaskDefinition}`,
`${Subnets}`, ...) and fills them from `DefinitionSubstitutions`. ecsodus does the same
substitution and then requires the result to equal the live definition. If someone edited the
state machine by hand, the job's stack is kept on Copilot rather than overwritten.

## Cleaned up by hand

`EnvControllerAction` and its Lambda.

## Watch out for

- **New task definition revisions.** The definition names the task definition revision
  literally. When you ship a new revision, update the state machine definition in the same
  change.
- **Managed EFS.** If the job mounts a Copilot-managed volume, the file system belongs to the
  environment and is imported with it (`prevent_destroy`). The retain patch stops the
  env-controller from deleting it when the job's stack goes.
