# Council review of the ecsodus plan

Three models reviewed the plan independently and read-only in every round:

- **gpt-6-astra** (Codex CLI, no network)
- **Claude Fable 5.1** (web access, checked against the Copilot source and AWS docs)
- **Claude Opus 5.5** (web access, checked against the Copilot source and AWS docs)

The final plan is [`../PLAN.md`](../PLAN.md) (r4, approved).

## Outcome by round

| Round | Plan | gpt-6-astra | Fable 5.1 | Opus 5.5 | Brief |
|---|---|---|---|---|---|
| 1 (review) | [r1](plan-r1.md) | [revise](astra.md) | [revise](fable.md) | [revise](opus.md) | [brief](brief.md) |
| 2 (vote) | [r2](plan-r2.md) | [REJECT](astra-r2.md) | [approve w/ conditions](fable-r2.md) | [approve w/ conditions](opus-r2.md) | [brief](brief-r2.md) |
| 3 (vote) | [r3](plan-r3.md) | [REJECT (3 P1)](astra-r3.md) | [REJECT (2 P1)](fable-r3.md) | [approve w/ notes](opus-r3.md) | [brief](brief-r3.md) |
| 4 (vote) | r4 = [PLAN.md](../PLAN.md) | [**APPROVE w/ notes**](astra-r4.md) | [**APPROVE w/ notes**](fable-r4.md) | [**APPROVE w/ notes**](opus-r4.md) | [brief](brief-r4.md) |

Every file is kept verbatim. The Fable round-3 file condenses the round-2 status table, and the
condensed part is marked.

## What the council changed

**Round 1.** The draft would have destroyed data:
- `delete-stack --retain-resources` only works on stacks in `DELETE_FAILED`.
- Copilot's custom-resource Delete handlers delete certificates, DNS records and bucket contents.
- The env-controller removes the shared ALB, NAT gateways and EFS when the last service stack is
  deleted.
- Addon databases sit in nested stacks with no `DeletionPolicy`.
- The app stack and the StackSet were missing from the plan.

These led to four changes: retain patches, adopt in place, flat root imports instead of module
internals, and Copilot first.

**Round 2.**
- Blockers propagate: no shared stack is deleted while any consumer remains.
- The retain patch covers every resource, not a whitelist.
- Nested-stack and StackSet mechanics were specified.
- Secrets, IAM and KMS got explicit fates.
- An import-only plan gate was added.
- Deletion protection is turned on before import.

**Round 3.**
- Exact change-set acceptance rules: policy attributes plus the nested `TemplateURL` change.
- No fate can re-enable a destructive handler.
- SSM SecureStrings are external references and are never imported.
- Freshness is re-checked after patching.
- Rules for coexisting with Copilot after a partial migration.

**Round 4.** Unanimous approval. Ten fail-closed notes became build requirements (PLAN §13).

## Questions only a real AWS run can settle (PLAN §6)

1. Does `DeletionPolicy: Retain` on a `Custom::*` resource stop CloudFormation from invoking its
   Delete handler? If not, the runbook uses the neutralizer.
2. How does a change set that only changes deletion policies show up, and is it applied? If it
   is treated as a no-op, the runbook uses the Metadata fallback.
3. Does a patched nested stack produce `Dynamic` entries in its parent's change set?
4. Does the ACM validation CNAME that certificates share survive?
5. Can this account create App Runner services after 2026-04-30? This matters only for v0.2.
