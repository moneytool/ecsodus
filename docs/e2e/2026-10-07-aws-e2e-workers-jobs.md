---
title: AWS end-to-end run, 2026-10-07 (Worker Service and Scheduled Job)
description: >-
  A real AWS run of ecsodus 0.2.0 on a Copilot Worker Service and Scheduled Job: 63/63 pure
  imports, all Copilot stacks deleted, the worker's backlog Lambda and the job's state machine
  still working under Terraform, and the account cleaned back to its baseline.
---

# AWS end-to-end run: 2026-10-07 (Workers and Jobs)

Approved by the maintainer on 2026-10-07, with the condition that nothing billable is left
behind. The run used the sandbox member account (ID omitted), in us-east-1, with AWS Copilot CLI
**v1.34.1** (the official release binary, md5 verified) and ecsodus from the 0.2.0 release
branch.

## The app
`ecsodus-e2e2` had 5 stacks and 67 resources:

| Stack | What it holds |
|---|---|
| App stack and StackSet instance | app roles; ECR repositories, KMS key and artifact bucket |
| Env stack `ecsodus-e2e2-test` | VPC with public subnets only (no NAT, no load balancer), cluster, Cloud Map, and the **managed EFS** file system with two mount targets |
| `ecsodus-e2e2-test-job` | a **Scheduled Job** (busybox, `rate(1 day)`): Events rule with a role, Step Functions state machine, an SNS topic it publishes, and an EFS access point |
| `ecsodus-e2e2-test-worker` | a **Worker Service** subscribed to the job's topic: SQS queue, KMS key, SNS subscription, and queue-depth autoscaling with the backlog-per-task Lambda |

## Result: passed

| Step | Outcome |
|---|---|
| Inventory and report | 5 stacks, 67 resources. After the fixes below: **ready**, all 5 stacks hand off, 63 imports, 6 manual-cleanup handles. |
| Read-only dry plan | 60/63 pure imports, then **63/63** after fixes. The import gate refused the three mismatches before anything changed. |
| 3. Retain patches | StackSet patched (offline template diff, update, verify-retain). App, env, job and worker stacks patched through change sets: **2 + 23 + 14 + 23 policy-only changes accepted**. `verify-retain` passed for all five. Regenerated Terraform byte-identical. |
| 4. Import | `verify-fresh` ok. Plan: 63 to import, 0 to change. Applied: **63 imported, 0 changed, 0 destroyed**. State 63/63. Steady plan **63/63 no-op**. |
| 5. Teardown | Job, worker, env, StackSet instance (detached with `--retain-stacks`), StackSet, app stack, each after `verify-retain`. **0 stacks remain.** |
| 6. Verify | Steady plan **63/63 no-op** after teardown. Worker service ACTIVE, 1/1 running. A manual run of the Terraform-owned state machine **SUCCEEDED**; its task (which lists the EFS mount) exited 0. |

**No Delete handler ran.** The env-controller and desired-count handlers had 1 invocation each
(their Create) before teardown and still had 1 after. **The backlog Lambda kept running**: its
invocation count rose from 17 to 20 across the teardown, now driven by the Terraform-owned rule.

## Defects found and fixed during the run
Each was caught by a gate before anything changed.

- **Env-controller outputs.** The job's access point reads
  `GetAtt EnvControllerAction.ManagedFileSystemID`, which ecsodus could not resolve, so the job
  was kept. Copilot's env-controller returns the environment stack's outputs; the resolver now
  reads them there.
- **State machine definition text.** The provider compares the definition as a string, so the
  re-serialised JSON planned an update. The deployed text is now written verbatim (after a
  JSON-equality check against the template).
- **Scalable target tags.** CloudFormation propagates stack tags onto scalable targets. The live
  read now adds `ListTagsForResource`, and the mapper writes the tags.
- **SQS maximum message size.** AWS's default is now 1 MiB, while the provider assumes 256 KiB, so
  a queue created without `MaximumMessageSize` planned an update. Queue attributes are now read
  live, and the live size is used when the template omits it.

Confirmed on the way: the `AWS::Lambda::Permission` physical ID is the plain statement ID (one
of the two forms the mapper accepts), and every new resource type (subscription, Lambda function
and permission, Events rule and targets, state machine, access point) imports cleanly.

## Cleanup
Everything the run created was deleted afterwards:

- the 63 imported resources, by a reviewed `terraform plan -destroy` (after emptying the artifact
  bucket and lifting `prevent_destroy`), applied in two passes (EFS waited for its mount targets);
- the three Copilot handler Lambdas and their log groups, Copilot's SSM parameters, the
  retain-patch bucket, the `StepFunctionsGetEventsForECSTaskRule` rule Step Functions creates,
  and the inactive task definitions.

The account matches its pre-run baseline (only the default VPC), except for things that cost
nothing and cannot be removed right away: the run's two customer KMS keys are in
`PendingDeletion`; AWS created its managed default keys (`aws/lambda`, `aws/elasticfilesystem`,
`aws/backup`); and AWS Backup's managed `aws/efs/automatic-backup-vault` and plan remain, empty
(no backup job ran) and protected from deletion by an AWS resource policy.

## Not covered by this run
- A custom domain and ACM certificate (issue #6).
- A Worker Service with a dead-letter queue, multiple topics, or FIFO topics (covered offline).
- Private placement with NAT gateways.
