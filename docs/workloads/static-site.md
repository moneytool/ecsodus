---
title: AWS Copilot Static Site migration (S3 and CloudFront)
description: >-
  Why ecsodus keeps Copilot Static Sites (S3 bucket plus CloudFront distribution) on Copilot,
  which of their resources are destructive on delete, and how to keep them running.
---

# Static Site

**Status: kept on Copilot.**

A Static Site (`static-site`) is an S3 bucket served by a CloudFront distribution. Copilot also
creates a Step Functions state machine that copies your files into the bucket on every deploy.

## Why it is blocked

`AWS::CloudFront::Distribution`, `AWS::CloudFront::Function` and
`AWS::CloudFront::OriginAccessControl` have no mapping yet, so the stack is kept. The asset copy
(state machine and `TriggerStateMachineAction`) would become a CI step after a migration, not a
Terraform resource.

## Do not delete the stack plainly

The bucket holds your site. With a custom domain, the workload's certificate validator and
custom-domain resources **delete the ACM certificate, its validation records and the alias
records** when the stack is deleted
([knowledge base](../knowledge/copilot-custom-resources.md#wkld-cert-validatorjs)).

## What to do now

Keep it on Copilot while migrating everything else:
`ecsodus inventory ... --keep-on-copilot <env>/<name>`. The site keeps serving. Your other
workloads hand off, but the environment and app stacks stay with Copilot as long as the site
does.
