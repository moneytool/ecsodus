---
title: Migrate each AWS Copilot workload type to Terraform
description: >-
  What ecsodus does with every AWS Copilot workload type — Load Balanced Web Service, Backend
  Service, Worker Service, Scheduled Job, Request-Driven Web Service and Static Site — and what
  to do with the types it cannot migrate yet.
---

# Copilot workload types

Every Copilot workload is one CloudFormation stack (plus an optional addons stack). ecsodus reads
the stack, gives every resource a [fate](../guides/how-it-works.md#fates), and hands the stack
off to Terraform only if every resource can be imported exactly. A stack that cannot is kept on
Copilot, together with the shared stacks it needs.

| Workload type | ecsodus | Guide |
|---|---|---|
| Load Balanced Web Service | Migrates | [Load Balanced Web Service](load-balanced-web-service.md) |
| Backend Service | Migrates | [Backend Service](backend-service.md) |
| Worker Service | Migrates (unreleased, [ADR-0014](../adr/0014-worker-services.md)) | [Worker Service](worker-service.md) |
| Scheduled Job | Migrates (unreleased, [ADR-0015](../adr/0015-scheduled-jobs.md)) | [Scheduled Job](scheduled-job.md) |
| Request-Driven Web Service | Kept on Copilot | [Request-Driven Web Service](request-driven-web-service.md) |
| Static Site | Kept on Copilot | [Static Site](static-site.md) |

## Mixed applications

An app can mix types. Run the inventory once; the report says, per workload, whether it hands
off. Workloads that cannot, or that you are not ready to move, stay on Copilot:

```bash
ecsodus inventory --app my-app --region us-east-1 --keep-on-copilot test/my-site -o inventory.json
```

Their environment and the app stack are then kept too, because Copilot still needs them. The
other workloads hand off normally.

## What every type has in common

- **The env-controller.** Every service and job stack has an `EnvControllerAction`. On a plain
  stack delete it removes the workload from the environment's parameters, and the environment
  then deletes the load balancer, NAT gateways or EFS file system once nothing needs them. The
  retain patch stops that handler from running (verified on AWS); the handle and its Lambda are
  cleaned up by hand afterwards.
- **Task definitions** are imported at their current revision. After the migration, new
  revisions come from your deploy tool; the runbook explains how to retire the imported one.
- **The import-only gate.** `ecsodus check --phase import` accepts the first plan only if every
  change is a pure import. Anything else stops the migration before AWS changes.
