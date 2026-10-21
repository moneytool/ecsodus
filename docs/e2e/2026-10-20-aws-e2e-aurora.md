---
title: AWS end-to-end run, 2026-10-20 (Aurora Serverless v2 addon)
description: >-
  A real AWS run of ecsodus on a Copilot service with an Aurora Serverless v2 PostgreSQL addon:
  38/38 pure imports after two fixes, every Copilot stack deleted, the database cluster kept its
  identity and a sentinel row stayed readable throughout.
---

# AWS end-to-end run: 2026-10-20 (Aurora addon)

Approved by the maintainer on 2026-10-20, with the condition that everything is cleaned up
afterwards. The run used the sandbox member account (ID omitted), in us-east-1, with AWS Copilot
CLI **v1.34.1** (the official release binary, md5 verified) and ecsodus from `main` (0.2.2 plus
the fixes below).

## The app
`ecsodus-e2e4` had 5 stacks and 42 resources:

| Stack | What it holds |
|---|---|
| App stack and StackSet instance | app roles; ECR repository, KMS key and artifact bucket |
| Env stack `ecsodus-e2e4-test` | VPC (public placement, no NAT), cluster, Cloud Map |
| `ecsodus-e2e4-test-api` | a **Backend Service** running the official `postgres:16-alpine` image as a client |
| Nested addons stack | an **Aurora Serverless v2 PostgreSQL cluster** (`copilot storage init`, 0.5–8 ACU) with its writer instance, subnet group, cluster parameter group, security groups and the `dbAuroraSecret` |

The container read the credentials Copilot injects (`DB_SECRET`), wrote a sentinel row
(`ecsodus-e2e4`), and then read it back every minute, logging `sentinel=ecsodus-e2e4`.

## Copilot's Aurora template no longer deploys as rendered
Copilot v1.34.1's Aurora addon template pins `EngineVersion: '16.2'`, which AWS has retired:
the first deploy failed with "Cannot find version 16.2 for aurora-postgresql". The generated
`copilot/api/addons/db.yml` was edited to `16.15` (AWS offered 16.11–16.15). Teams still on
Copilot can no longer add a new Aurora addon without editing the template; existing clusters
are not affected.

## Result: passed

| Step | Outcome |
|---|---|
| Inventory and report | 5 stacks, 42 resources: **ready**, all 5 hand off, 38 imports, 3 manual-cleanup handles, 1 nested wrapper. |
| 2. Protect | The runbook's commands ran as generated: a cluster snapshot, then deletion protection turned on. The inventory was refreshed and the Terraform regenerated. |
| Read-only dry plan | 36/38 pure imports; the import gate refused the two below before anything changed. After the fixes: **38/38**. |
| 3. Retain patches | StackSet, app, env, and the service stack **with its nested Aurora addons stack** patched through the parent (2 change sets): **2 + 18 + 18 policy-only changes accepted**; `verify-retain` passed for all five. |
| 4. Import | **38 imported, 0 changed, 0 destroyed**. State 38/38. Steady plan **38/38 no-op**. |
| 5. Teardown | Service, the nested addons stack, env, StackSet instance, StackSet, app stack, each after `verify-retain`. **0 stacks remain.** |
| 6. Verify | Steady plan **38/38 no-op**. The cluster (`cluster-MVG5…`) and its writer instance (`db-NCAO…`) kept the **same resource IDs**, so nothing was recreated; deletion protection stayed on; the container read **`sentinel=ecsodus-e2e4`** after teardown. |

The env-controller's invocation count was 1 (the Create) before and after teardown.

## Defects found and fixed during the run
Each was caught by the import gate before anything changed.

- **Cluster parameter group.** Copilot's template sets `client_encoding: UTF8`, which AWS
  records as a `system` value, not a `user` one, and the provider reads back only user
  parameters, so writing it planned an update. Parameter groups are now read live
  (`DescribeDBClusterParameters` / `DescribeDBParameters`), and the configuration carries
  exactly the live user parameters; a template parameter AWS holds at its default is noted, and
  one AWS holds at another value blocks the resource.
- **Secrets Manager secret.** The provider's Terraform-only defaults
  (`recovery_window_in_days = 30`, `force_overwrite_replica_secret = false`) planned an update
  because ecsodus did not write them, so its ignore-at-import rule did not apply. They are now
  written at their defaults, ignored for the import and hardened in RUNBOOK step 4b.

## Cleanup
Everything the run created was deleted afterwards:
- deletion protection turned off by a reviewed Terraform plan (one in-place change), then the
  38 imported resources by a reviewed `terraform plan -destroy` in three passes (the subnet
  group, the cluster and the namespace raced their dependants' deletion);
- the protect step's cluster snapshot, the env-controller Lambda and its log group, Copilot's
  SSM parameters, the retain-patch bucket and the task definitions. The database secret was
  removed by the destroy.

The account matches its pre-run baseline (only the default VPC; no RDS clusters, snapshots,
subnet groups, parameter groups or secrets) in every region checked, except for things that cost
nothing: the run's customer KMS key is in `PendingDeletion`, and AWS's managed default keys
remain.

## Not covered by this run
- Aurora MySQL, provisioned (non-serverless) Aurora, and RDS instances (covered offline).
- A custom domain and ACM certificate (issue #6).
