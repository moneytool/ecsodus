---
title: AWS end-to-end run, 2026-10-20 (private placement behind NAT gateways)
description: >-
  A real AWS run of ecsodus 0.2.2 on a privately placed Copilot service: 41/41 pure imports,
  every Copilot stack deleted, the env-controller never ran, the NAT gateways and their Elastic
  IPs survived, and the service kept reaching the internet through them.
---

# AWS end-to-end run: 2026-10-20 (private placement)

Approved by the maintainer on 2026-10-20, with the condition that nothing billable is left
behind. The run used the sandbox member account (ID omitted), in us-east-1, with AWS Copilot CLI
**v1.34.1** (the official release binary, md5 verified) and ecsodus 0.2.2.

## The app
`ecsodus-e2e3` had 4 stacks and 43 resources:

| Stack | What it holds |
|---|---|
| App stack and StackSet instance | app roles; ECR repository, KMS key and artifact bucket |
| Env stack `ecsodus-e2e3-test` | VPC with public and private subnets, **two NAT gateways with their Elastic IPs**, private route tables, cluster, Cloud Map |
| `ecsodus-e2e3-test-api` | a **Backend Service** with `network.vpc.placement: private` (busybox, no public IP); every minute it fetches `https://aws.amazon.com` and logs `egress-ok` |

The service's env-controller asked the environment for `NATWorkloads=api`, which made the
environment create the NAT gateways. The container logged `egress-ok` before the migration
started.

## Result: passed

| Step | Outcome |
|---|---|
| Inventory and report | 4 stacks, 43 resources: **ready**, all 4 hand off, 41 imports, 2 manual-cleanup handles. |
| Read-only dry plan | **41/41 pure imports on the first try**; the import gate passed. Both NAT Elastic IPs carried `prevent_destroy` (since 0.2.2). |
| 3. Retain patches | StackSet patched (offline template diff, update, verify-retain). App, env and service stacks patched through change sets: **2 + 28 + 9 policy-only changes accepted**; `verify-retain` passed for all four. |
| 4. Import | Plan 41 to import, 0 to change. Applied: **41 imported, 0 changed, 0 destroyed**. State 41/41. Steady plan **41/41 no-op**. |
| 5. Teardown | Service, env, StackSet instance (detached with `--retain-stacks`), StackSet, app stack, each after `verify-retain`. **0 stacks remain.** |
| 6. Verify | Steady plan **41/41 no-op** after teardown. Service ACTIVE, 1/1 running, `assignPublicIp: DISABLED`; the container still logged **`egress-ok`** after teardown. |

**The env-controller never ran its Delete handler.** Its invocation count was 1 (the Create)
before teardown and still 1 after. **The NAT path survived**: both NAT gateways kept their IDs
and their Elastic IPs (`nat-0d96…` / `184.197.77.109`, `nat-04ea…` / `3.226.35.79`) across the
teardown. Without the retain patch, deleting the service stack would have removed `api` from
`NATWorkloads`, and CloudFormation would have deleted both NAT gateways and released their
addresses.

No defects were found: the offline coverage added in 0.2.2 (#32) matched the real account.

## Cleanup
Everything the run created was deleted afterwards:
- the 41 imported resources, by a reviewed `terraform plan -destroy` (after emptying the
  artifact bucket and lifting `prevent_destroy`), in two passes: the first pass hit two
  ordering races (the Cloud Map namespace before its service, and an Elastic IP disassociation
  while its NAT gateway was being deleted), and the second removed the remaining two;
- the env-controller Lambda and its log group, Copilot's SSM parameters, the retain-patch
  bucket and the task definitions.

The account matches its pre-run baseline (only the default VPC) in every region checked, except
for things that cost nothing: the run's customer KMS key is in `PendingDeletion`, and AWS's
managed default keys remain.

## Not covered by this run
- A Load Balanced Web Service with private placement (the same network template; covered
  offline by the synthetic full hand-off app).
- A custom domain and ACM certificate (issue #6).
