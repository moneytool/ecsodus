---
title: How to migrate AWS Copilot to Terraform (step by step, no downtime)
description: >-
  Step-by-step guide to migrating an AWS Copilot CLI application to Terraform: inventory the
  CloudFormation stacks, import every resource in place, retain-patch the stacks, and delete
  them without deleting your ECS services, load balancer, VPC or data.
---

# How to migrate AWS Copilot to Terraform

This guide moves a Copilot application (Load Balanced Web Services, Backend Services, Worker
Services, Scheduled Jobs, their environment and addons) to Terraform **in place**. No traffic moves, and nothing is recreated.

## 1. Install and inventory (read-only)

```bash
pipx install ecsodus
ecsodus inventory --app my-app --region us-east-1 -o inventory.json
ecsodus report inventory.json -o REPORT.md
```

The inventory reads your stacks, templates and live state. It never changes anything; every AWS
call it can make is a `Describe`, `List` or `Get`, and it never reads secret values.

The report covers:

- whether each stack can be handed off, and why or why not
- **what deleting each stack without protection would destroy**
- anything ecsodus can't migrate yet, which stays on Copilot

## 2. Generate Terraform and the runbook

```bash
ecsodus generate inventory.json --out infra/
```

You get:

- **Terraform files** with `import` blocks for every resource, using the exact deployed values,
  so the first plan imports and changes nothing
- **retain patches**: each stack's template with `DeletionPolicy: Retain` on every resource
- **`RUNBOOK.md`**: the exact commands for the remaining steps

## 3. Follow the runbook

1. **Freeze.** Stop Copilot deploys and pipelines.
2. **Protect.** Take snapshots and backups, and turn on deletion protection.
3. **Retain-patch** every stack through CloudFormation change sets. `ecsodus check --changeset`
   accepts a change set only if it changes the deletion policies and nothing else.
4. **Import** into Terraform. `ecsodus check --phase import` accepts only pure imports, and then
   `--phase steady` requires a zero-change plan.
5. **Delete the Copilot stacks.** `ecsodus verify-retain` runs before each delete. Because every
   resource is retained, CloudFormation deletes nothing and invokes no custom-resource Delete
   handler (verified on AWS).
6. **Verify.** The plan must still show zero changes. Then delete the leftover Copilot Lambdas.

Every block in the runbook is fail-fast: if a check fails, the mutation after it does not run.

## What is supported

- **Supported in v0.1:**
  - Load Balanced Web Services and Backend Services (including Copilot's default Service Connect)
  - Worker Services: queues, SNS subscriptions, and the backlog-per-task Lambda that drives their
    queue-depth autoscaling (imported, not deleted)
  - Scheduled Jobs: the schedule and the Step Functions state machine that runs the task
  - sidecar containers and EFS volumes
  - environments, whether Copilot created the VPC or you imported one
  - addons: Aurora/RDS, DynamoDB, S3
  - the app stack and StackSet
- **Detected and kept on Copilot** (reported, never dropped): Request-Driven Web Services,
  Static Sites, NLB, CloudFront, pipelines, and multi-account environments.

See [how it works](guides/how-it-works.md) for the fates, the atomic per-stack hand-off and the
checks, and the [AWS end-to-end report](e2e/2026-09-30-aws-e2e.md) for evidence.
