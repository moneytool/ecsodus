---
title: AWS Copilot Request-Driven Web Service (App Runner) migration
description: >-
  Why ecsodus keeps Copilot Request-Driven Web Services (AWS App Runner) on Copilot for now,
  why their stacks must never be deleted plainly, and what to do in the meantime.
---

# Request-Driven Web Service

**Status: kept on Copilot.** App Runner support is planned for v0.2.

A Request-Driven Web Service (`rd-web-svc`) is an AWS App Runner service, not ECS. ecsodus
detects it, reports it, and keeps its stack (and the environment and app stacks it needs) on
Copilot.

## Why it is blocked

- `AWS::AppRunner::Service` and `AWS::AppRunner::VpcConnector` have no mapping yet.
- App Runner closed to new customers on 2026-04-30. Existing services keep running, but the
  realistic exit for many teams is a rebuild on ECS rather than an import, and that is a
  different mode (rebuild in parallel, planned for v0.2).

## Do not delete the stack plainly

With a custom domain, the stack's `CustomDomainAction` disassociates the domain from App Runner
and **deletes its CNAME and certificate-validation records** when the stack is deleted
([knowledge base](../knowledge/copilot-custom-resources.md#custom-domain-app-runnerjs-rdws)).
Deleting the last workload in an environment also makes the env-controller remove shared
resources.

## What to do now

1. Keep it on Copilot while migrating everything else:
   `ecsodus inventory ... --keep-on-copilot <env>/<name>`.
2. The service keeps running. Copilot's custom-resource Lambdas run on `nodejs20.x`; updates to
   that runtime are blocked from 2027-08-31, so plan the move before then.
