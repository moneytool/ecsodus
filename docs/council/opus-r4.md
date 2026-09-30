# Round 4 vote: Claude Opus 5.5

(Verbatim; read-only; 2026-09-29.)

## Vote
**APPROVE WITH NOTES.** r4 fixes all three round-3 blockers from Astra and both from Fable, and folds in every round-3 note. I found no remaining P0 or P1. The problems r4 introduces all fail closed: they can stop the runbook but cannot delete anything. They are listed below as P2/P3 notes to fold in during M2.

## Round-3 items status
| Condition (reviewer + number) | Status | Note |
|---|---|---|
| Astra B1 / Fable B1 / Opus N1: change-set acceptance rule | addressed | §2.4 now requires `Modify` with `Replacement: False`. Allowed targets are `DeletionPolicy`/`UpdateReplacePolicy`, plus `TemplateURL` with `RequiresRecreation: Never` and a SHA-256 match. The rule runs on nested change sets through `--include-nested-stacks`. An empty change set counts as failure, and the check is machine-run (`check --changeset`). The Metadata fallback, the StackSet step and output-driven dynamic entries are gaps (notes 1–3). |
| Astra B2 / Fable B2: no fate may drop destructive handles | addressed | `drop-after-cutover` is gone. `manual-cleanup` stays retained, and the patch has "no exceptions", with `Custom::*`/`EnvControllerAction`/`AddonsStack` named (§2.2, §2.4). |
| Astra B3: SecureString import reads values | addressed | SecureStrings are now `external-reference`. This is accurate: `copilot secret init` writes them outside CloudFormation, and `AWS::SSM::Parameter` cannot create `SecureString`. Secrets Manager is resource-only (no `secret_version`). ecsodus reads, Terraform reads and secret-bearing artifacts are listed separately. |
| Astra N: freshness vs step 3 | addressed | §2.5 step 3 ends with a fresh inventory and regeneration. |
| Astra N: steady gate machine-enforced | addressed | §2.6 `--phase steady` fails on any action other than no-op. |
| Astra N: sensitive artifacts beyond inventory | addressed | HCL, `plan.json`, `state.txt` and checkpoints are written 0600 and git-ignored. |
| Astra N: real partial-migration and domain e2e | addressed | Both are in §6 e2e scope. |
| Fable N: freshness | addressed | Same fix as Astra's. |
| Fable N: StackSet instances protected before detach | partial | Step 3 now uses `update-stack-set`, but StackSets have no change sets, so the §2.4 rule cannot run there (note 2). |
| Fable N: neutralizer / 2027-08-31 | addressed | §2.3, §2.4. |
| Fable N: out-of-band protection drift not reverted | addressed | §2.5 step 2. |
| Fable N: keep-CloudFormation caveat | addressed | §2.3. |
| Opus N2: freshness | addressed | Step 3 re-inventory. |
| Opus N3: artifact bucket / ARN-string closure | addressed | §2.2 closure list and ARN rule. |
| Opus N4: coexistence after partial migration | addressed | §2.5 step 7. |
| Opus N5: gate only step 5 | addressed | §6 always emits steps 6–7. |
| Opus N6: rotation fated | addressed | Rotation schedules are imported; rotation Lambdas are imported or documented as manually owned. |
| Opus N7: Terraform ≥ 1.10 | addressed | §2.4, §5. `removed` also needs ≥ 1.7, which the 1.10 floor covers. |
| Opus N8: imported task-definition revision | addressed | `removed { lifecycle { destroy = false } }` hand-off (see note 5). |

## Blocking issues (only if REJECT)
None.

## Notes (non-blocking)
1. **P2 – §2.4, the Metadata fallback breaks the acceptance rule.** The fallback adds an `ecsodus:retain` `Metadata` key. That shows up as a `Metadata` scope/target, which the rule rejects, so the fallback can never pass `check --changeset`. Add a `--allow-metadata-key ecsodus:retain` mode that also accepts `Attribute: Metadata` targets; confirm in the e2e that a `Metadata` change combined with a policy change is actually applied.
2. **P2 – §2.5 step 3, the StackSet path.** `update-stack-set` has no change set. Specify instead: pre-check diff of the patched template against the StackSet's own deployed template (`describe-stack-set`), only policy lines may differ; `UsePreviousValue`, Copilot's existing `--administration-role-arn`/`--execution-role-name`, existing capabilities; wait for `SUCCEEDED` and run `verify-retain` on every instance stack. Step 5.4's re-patch is then redundant but harmless.
3. **P2 – §2.4, dynamic entries in the parent change set.** When a nested stack's `TemplateURL` changes, parent resources that read its outputs through `!GetAtt AddonsStack.Outputs.*` may be listed as `Modify` with `Evaluation: Dynamic`, `ChangeSource: ResourceAttribute` and `Replacement: Conditional` (task definition, IAM policies). Add a §6 e2e question; if it occurs, allow `Dynamic`/`ResourceAttribute` entries whose causing entity is a patched nested stack, provided that child's change set shows no output-affecting changes.
4. **P3 – §2.4, re-running an already-patched stack** yields "no changes", which the rule counts as failure. Skip any stack where `verify-retain` already passes. Name `SyncWithActual` in the reject list.
5. **P3 – §2.4, removing the imported task definition.** `aws_ecs_service.task_definition` must stop referencing `aws_ecs_task_definition.x` before the `removed` block. Emit a literal ARN or a data source.
6. **P3 – §2.2 wording.** Add `external-reference` as an allowed closure target.
7. **P3 – §2 command list.** Add `check --changeset` and `verify-retain`.
8. **P3 – §2.2, Aurora `AWS::SecretsManager::SecretTargetAttachment`** has no Terraform equivalent; fate it `manual-cleanup` (retained, then orphaned).

Sources: [ResourceChange API](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChange.html), [Metadata attribute](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-metadata.html).
