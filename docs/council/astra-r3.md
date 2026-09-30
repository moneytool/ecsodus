## Vote

**REJECT** — Most round-2 conditions are addressed, but three P1 contradictions remain in retention mechanics, destructive-handler fates, and SecureString adoption.

## Round-2 conditions status

| Condition (reviewer + number) | Status | Note |
|---|---|---|
| Astra C1 | addressed | §2.2 dependency propagation, §2.5 teardown gates, §6 mixed-app tests. |
| Astra C2 | partial | Nested publication and verification specified; blanket `Modify` rejection prevents it. |
| Astra C3 | addressed | Hosted-zone attribution and detached StackSet-instance sequence corrected. |
| Astra C4 | partial | Dependencies and environment reconstruction covered; SecureString no-read import is incorrect. |
| Astra C5 | addressed | Strict import/state checks; protection enabled before re-inventory is a valid alternative. |
| Astra C6 | addressed | v0.1 adoption only; rebuild prerequisites deferred explicitly. |
| Fable C1 | partial | Retain-all and dependency list added; destructive handles still qualify for dropping. |
| Fable C2 | addressed | Neutralizer fallback specified. |
| Fable C3 | addressed | Remaining consumers prevent shared-stack teardown. |
| Fable C4 | partial | Nested mechanics/parameters/capabilities present; change-set gate contradicts them. |
| Fable C5 | addressed | Informational Express predicate written down. |
| Fable C6 | addressed | Rebuild explicitly v0.2. |
| Opus C1 | addressed | Closure, IAM/network dependencies and CMK reporting specified. |
| Opus C2 | partial | External objects and fallback covered; public-release gate replaces literal no-guidance gate, consistent with maintainer decision. |
| Opus C3 | addressed | Consumer-aware truncation covers env/app/StackSet. |
| Opus C4 | partial | Import/state checks and offline partial-migration tests present; real partial-migration case absent. |
| Opus C5 | partial | Mechanics largely present; blanket `Modify` rejection is unworkable. |
| Opus C6 | addressed | Predicate present. |
| Astra new P1: deletion protection | addressed | Live-matching HCL after out-of-band protection. |
| Fable new P1: retain whitelist | partial | Whitelist removed; destructive-handle exception remains. |
| Opus new P1: deletion protection | addressed | Same fix. |
| Opus new P1: IAM/network omissions | addressed | §2.2 explicitly includes them. |

## Blocking issues (only if REJECT)

1. **P1 — §2.4, §2.5 step 3, §6: fix the change-set acceptance rule.** Changing a nested stack’s `TemplateURL` produces a resource modification, which the plan categorically rejects. Require `--include-nested-stacks`, inspect descendants, and narrowly permit verified retention-policy changes and non-replacing wrapper `TemplateURL` changes to verified patched children. Reject other changes. Also check `Replacement=True/Conditional`; `Replace` is not a CloudFormation action. [AWS nested change sets](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/change-sets-for-nested-stacks.html), [ResourceChange API](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChange.html).

2. **P1 — §2.2 versus §2.4: remove destructive custom-resource handles from `drop-after-cutover`.** §2.2 explicitly permits dropping `EnvControllerAction`-style handles, while §2.4 promises to retain every such handle. Make retention unconditional for every custom-resource handle through stack teardown; assign later manual cleanup separately. Otherwise the stated fate rule can re-enable the destructive Delete handler the design must suppress.

3. **P1 — §2.2–2.4: replace the SecureString “imported by name without reading values” promise with an implementable ownership contract.** `aws_ssm_parameter` refresh requests decryption; ordinary value handling also stores the value in state. Import-by-name does not avoid this, and write-only configuration does not eliminate the provider read. For v0.1, retain these parameters under their existing owner and reference their identifiers, blocking affected teardown, unless a tested alternative is specified. Explicitly distinguish ecsodus’s reads from Terraform’s reads and secret-bearing artifacts. [AWS provider implementation](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/ssm/parameter.go).

## Notes (non-blocking)

- **P2 — §2.1/2.5:** Retain updates change `LastUpdatedTime`, making the pre-patch inventory fail freshness checks. Specify re-inventory/regeneration after verified patches.
- **P2 — §6:** Add a real partial-migration case; require a domain-enabled fixture before claiming certificate/DNS survival is validated.
- **P2 — §2.6:** Make the runbook’s zero-change steady gate machine-enforced; the current checker merely warns on updates.
- **P2 — §2.1/2.4:** Extend sensitive-file permissions and ignore rules to generated HCL, plan JSON and state checkpoints containing plaintext environment values.