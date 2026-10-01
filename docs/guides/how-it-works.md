# How ecsodus works

## The problem, precisely

To leave Copilot you have to delete its CloudFormation stacks without deleting the
infrastructure. Deleting a healthy stack removes every resource without
`DeletionPolicy: Retain`. Copilot sets Retain almost nowhere. Its custom resources also act when
their stack is deleted, as the [knowledge base](../knowledge/copilot-custom-resources.md) records
from the Copilot source:

| Custom resource | On stack delete |
|---|---|
| `EnvControllerAction` (every service stack) | Removes the service from the env parameters. Once no service needs them, the env stack deletes the ALB, the NAT gateways and the EFS file system. |
| `HTTPSCert` (env) | Deletes the ACM certificate and its validation records. |
| `CustomDomainAction` (env) | Deletes the alias A records. |
| `DelegateDNSAction` (env) | Deletes the NS delegation in the app hosted zone. |
| `ELBAccessLogsBucketCleanerAction` | Deletes every object in the access-logs bucket. |

`delete-stack --retain-resources` does not help: it only applies to stacks already in
`DELETE_FAILED`.

## Adopt in place

A Copilot service already is a plain ECS service behind an ALB in a VPC. ecsodus imports those
exact resources into Terraform, and traffic does not move. Every Terraform argument is a literal
value read from the deployed template and from live state, so the first plan imports and changes
nothing.

## Fates

Every resource gets exactly one fate:

| Fate | Meaning |
|---|---|
| `import` | Becomes a Terraform resource with an `import` block. |
| `retain-under-existing-owner` | Stays in its CloudFormation stack, because the stack is kept. |
| `manual-cleanup` | A Copilot-internal leftover: custom-resource handles, their Lambdas and roles. It is retained by the patch like everything else, and deleted by hand after teardown. |
| `external-reference` | Referenced, never imported. Examples: SSM SecureStrings (a Terraform refresh would decrypt them into state) and imported VPCs. |
| `blocked` | Unsupported. Its stack is kept. |
| `nested-wrapper` / `not-created` | A nested stack's wrapper resource (the child stack is inventoried itself), or a resource whose `Condition` is false. |

## Hand-off is per stack, and atomic

A stack is either **handed off** completely or **kept** completely. It is never split, so no
resource ever has two live owners. Kept status propagates until nothing changes:

- **Workload stack:** kept if the workload stays on Copilot, has an unsupported type, or has a
  blocked resource (including in its addons).
- **Environment stack:** kept if any of its workload stacks is kept.
- **App stack and StackSet instances:** kept if any environment is kept.

Teardown stops before the first kept shared stack.

## Retain patches

For every handed-off stack, ecsodus emits the deployed template with `DeletionPolicy: Retain` and
`UpdateReplacePolicy: Retain` added to **every** resource. The patch edits the original text line
by line and `verify_patch` proves nothing else changed. There are two permitted exceptions: a
nested stack's `TemplateURL` (pointing at its patched child) and the optional `ecsodus:retain`
Metadata fallback.

The patches are applied in two ways:
- **Change sets** (`--include-nested-stacks`). `check --changeset` accepts only policy-only
  `Modify` entries with `Replacement: False`, plus the wrapper's `TemplateURL`. An empty change set
  is not a pass.
- **StackSet:** `update-stack-set`, after an offline `check --template-diff`.

## The checks

| Command | Gate |
|---|---|
| `check --changeset` | The retain patch changes policies and nothing else. |
| `verify-retain` | Every resource in every stack, including nested stacks, carries both Retain policies. |
| `check --phase import` | The plan contains only pure imports (`change.importing`) and no-ops, and every expected import is present. |
| `check --state` | Every import is in Terraform state. |
| `check --phase steady` | The plan has zero changes. |

## Verified on real AWS

The 2026-09-30 end-to-end run ([report](../e2e/2026-09-30-aws-e2e.md)) settled the open
questions:

1. `DeletionPolicy: Retain` on a `Custom::*` resource stops its Delete handler from being
   invoked.
2. Policy-only change sets are reported as `Modify` with `Scope: DeletionPolicy` and
   `UpdateReplacePolicy`, and they are applied.
3. A patched nested stack causes no `Dynamic` entries in its parent's change set.

Not yet covered by a real run: custom domains and ACM certificates, Aurora addons, private
placement with NAT, and partial migrations.
