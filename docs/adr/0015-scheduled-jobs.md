# ADR-0015: Scheduled Jobs hand off in adopt-in-place

- Status: accepted
- Date: 2026-10-02
- Deciders: maintainer

## Context
PLAN §3 blocked Scheduled Jobs (issue #5). A Copilot Scheduled Job has no ECS service. Its
stack holds the task definition and roles, plus:

- an `AWS::Events::Rule` on the job's schedule, whose target **assumes a role** (`RuleRole`) to
  start a state machine;
- an `AWS::StepFunctions::StateMachine` that runs the task (`ecs:runTask.sync`) with retries and
  a timeout. Its definition is a string with `${...}` placeholders, filled in from
  `DefinitionSubstitutions` (cluster, task definition, subnets, security groups);
- `StateMachineRole`, and an `AWS::EFS::AccessPoint` when the job mounts the environment's
  managed file system (`EnvControllerAction.ManagedFileSystemID`).

The only custom resource is the env-controller, as with services.

## Decision
- **Scheduled Job is a supported workload type.** The atomic per-stack hand-off, retain patches
  and checks apply unchanged.
- **Events targets may carry `RoleArn`** (`role_arn` on `aws_cloudwatch_event_target`). The
  live targets must still match the template exactly, role included.
- **The state machine is imported as deployed** as `aws_sfn_state_machine`:
  - the definition is the template's `DefinitionString` (or `Definition`) with every
    substitution applied, written as `jsonencode(...)`. Any placeholder left without a value
    blocks the resource;
  - when the inventory read the state machine, the live definition must be JSON-equal to that,
    and the role and type must match. A definition edited outside CloudFormation blocks the
    stack rather than being overwritten;
  - logging and tracing configuration are copied; `publish`, a Terraform-only argument, is
    written at its default, ignored for the import and hardened afterwards (RUNBOOK step 4b).
- **Live read:** `states:DescribeStateMachine` and `ListTagsForResource`. The definition holds
  only orchestration and resource identifiers, no secret values.

## Evidence
- The synthetic full-handoff app includes Copilot's verbatim job render (with an nginx sidecar,
  secrets, and values from other stacks' exports) and turns on the environment's managed EFS
  for it. All five stacks hand off, with a clean closure, and the generated Terraform passes
  `terraform validate`.
- `terraform plan` against moto: the rule and its role-assuming target plan as `2 to import,
  0 to add, 0 to change, 0 to destroy`. Moto does not implement `ListStateMachineVersions`,
  which the provider calls when it reads a state machine, so that import was unverified offline.
- **Real AWS, 2026-10-07** ([report](../e2e/2026-10-07-aws-e2e-workers-jobs.md)): 63/63 pure
  imports, every Copilot stack deleted, and the Terraform-owned state machine ran the job
  successfully afterwards. The run found that the provider compares the definition as text, so
  the deployed text is now written verbatim, and that `ManagedFileSystemID` must be read from
  the environment stack's outputs.

## Consequences
After the hand-off, Terraform owns the schedule and the state machine. A new task definition
revision needs the state machine definition updated too, because it names the revision
literally. The runbook's guidance on task-definition rollouts applies to jobs as well.
