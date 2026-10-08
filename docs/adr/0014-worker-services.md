# ADR-0014: Worker Services hand off in adopt-in-place

- Status: accepted
- Date: 2026-10-01
- Deciders: maintainer

## Context
PLAN §3 blocked Worker Services in v0.1 and scheduled them for v0.3 (issue #4). A Worker
Service stack has what a Backend Service has (task definition, service, roles, autoscaling,
alarms, Service Connect), plus:

- an events queue, a dead-letter queue and one queue per subscribed topic, with their queue
  policies and a KMS key;
- an `AWS::SNS::Subscription` per subscribed topic (topics usually belong to other services);
- the **backlog-per-task calculator**: a Lambda (`BacklogPerTaskCalculatorFunction`), its role
  and log group, an every-minute `AWS::Events::Rule` and an `AWS::Lambda::Permission`.

v0.1 sends every Lambda in a Copilot stack to manual cleanup, because they were all
custom-resource handlers. The backlog calculator is not one: it publishes the `BacklogPerTask`
metric that the queue-depth scaling policies track. Deleting it breaks scaling silently.

Copilot's worker render also mounts EFS volumes from another stack's export
(`Fn::ImportValue stack-fs-12345`), which the resolver could not see.

## Decision
- **Worker Service is a supported workload type.** The atomic per-stack hand-off, retain
  patches and checks apply unchanged.
- **The backlog calculator is imported**, not cleaned up and not replaced:
  - `aws_lambda_function` with the deployed configuration (role, handler, runtime, timeout,
    memory, environment) and the `Code` S3 object Copilot uploaded, under a permanent
    `ignore_changes = [s3_bucket, s3_key]`: the provider does not read code location back, and
    re-uploading identical code is not an import;
  - `aws_cloudwatch_event_rule` plus one `aws_cloudwatch_event_target` per target, and
    `aws_lambda_permission`.
  - `knowledge.RUNTIME_FUNCTIONS` names the Copilot Lambdas that run a workload. Every other
    Lambda keeps the v0.1 rule (handler: manual cleanup; anything else: blocked).
  - Replacing it with metric math over SQS and ECS metrics changes behaviour, which
    adopt-in-place never does. That stays a later option.
- **One CloudFormation resource may import several Terraform resources** (`TfSpec.companions`).
  An Events rule's targets are separate Terraform resources; each becomes its own planned row,
  manifest import and import block, so the import-only gate covers it.
- **SNS subscriptions** import as `aws_sns_topic_subscription`. The Terraform-only arguments
  `confirmation_timeout_in_minutes` and `endpoint_auto_confirms` are written at their defaults,
  ignored for the import and hardened afterwards (RUNBOOK step 4b), like the other
  import-unread arguments.
- **External exports:** the inventory keeps the exports of stacks outside the app whose names
  appear literally in the app's templates (`Inventory.external_exports`), and the resolver
  falls back to them. Copilot's own imports use computed names and are unaffected; the
  account's other exports are never recorded.
- **Live reads stay read-only and secret-free:** `events:DescribeRule`, `ListTargetsByRule`,
  `ListTagsForResource`; `lambda:ListTags` and `GetPolicy` (statement ids only); and
  `sns:GetSubscriptionAttributes`. `lambda:GetFunction` and `GetFunctionConfiguration` stay
  forbidden because they return environment variables; the function's environment comes
  from the deployed template.

## Evidence
- The synthetic full-handoff app now includes Copilot's verbatim worker render with consistent
  live reads: all four stacks hand off, 51 worker imports, closure clean, and the generated
  Terraform passes `terraform validate` against the real provider.
- `terraform plan` against a local moto server, with the generated blocks for the function,
  permission, rule, target and a filtered subscription: `5 to import, 0 to add, 0 to change,
  0 to destroy`.
- **Real AWS, 2026-10-07** ([report](../e2e/2026-10-07-aws-e2e-workers-jobs.md)): 63/63 pure
  imports, every Copilot stack deleted, no Delete handler ran, and the backlog Lambda kept
  publishing under Terraform. The run added live SQS attributes (AWS's 1 MiB default message
  size) and scalable-target tags.

## Consequences
Queue-based scaling keeps working after the hand-off, and Terraform owns the calculator. The
calculator runs on `nodejs20.x`, which AWS Lambda blocks for updates from 2027-08-31; the
generated Terraform carries a note to move it to a supported runtime.
