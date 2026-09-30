# Round 4 vote: Claude Fable 5.1

(Verbatim; read-only; 2026-09-29.)

## Vote

**APPROVE WITH NOTES.** r4 closes both of my round-3 blockers, all three of Astra's, and every round-3 note, with the mechanics now stated correctly (I re-verified `ResourceTargetDefinition` attribute values, `RequiresRecreation` values and the `nodejs20.x` 2027-07-29 / 2027-08-31 dates against AWS docs today); the items r4 newly introduced that are wrong all fail closed and are P2/P3 fold-ins.

## Round-3 items status

| Condition | Status | Note |
|---|---|---|
| Astra B1 / Fable B1 / Opus N1: change-set acceptance rule | addressed | §2.4: `Modify` + `Replacement: False`, targets ∈ {`DeletionPolicy`, `UpdateReplacePolicy`} or `Properties/TemplateURL/Never` on `AWS::CloudFormation::Stack` with child SHA-256 match; `--include-nested-stacks`, recursive; `Replace` gone. Metadata fallback lacks a matching carve-out (note 2). |
| Astra B2 / Fable B2: no fate may re-enable destructive handlers | addressed | `drop-after-cutover` removed; `manual-cleanup` is still Retain-patched; §2.4 "no exceptions" names `Custom::*` and `EnvControllerAction`. |
| Astra B3: SecureString import reads values | addressed | §2.2 `external-reference`; Secrets Manager resource-only, never `secret_version`; ecsodus vs Terraform reads distinguished. |
| Astra N / Fable N / Opus N2: freshness vs step 3 | addressed | §2.5 step 3 ends with re-inventory and regenerate. |
| Astra N: steady gate machine-enforced | addressed | §2.6 `--phase steady` fails on any non-no-op. |
| Astra N: sensitive artifacts beyond inventory | addressed | §2.2 lists HCL, `plan.json`, `state.txt`, checkpoints as 0600 + gitignored. |
| Astra N: real partial-migration and domain e2e | addressed | §6 e2e scope, gated on approval. |
| Fable N: StackSet instances protected before detach | addressed, with a new gap | §2.5 step 3 `update-stack-set` first; but StackSets have no change set, so the §2.4 gate cannot run there (note 1). |
| Fable N: neutralizer / Lambda-update date | addressed | §2.3, §2.4 carry 2027-08-31. |
| Fable N: step-2 drift not reverted by step 3 | addressed | §2.5 step 2. |
| Fable N: baseline caveat | addressed | §2.3. |
| Opus N3: artifact bucket / ARN-string closure | addressed | §2.2 closure list + ARN rule. |
| Opus N4: coexistence after partial migration | addressed | §2.5 step 7. |
| Opus N5: gate only step 5 | addressed | §6: steps 6–7 always emitted. |
| Opus N6: rotation resources fated | addressed | §2.2. |
| Opus N7: Terraform ≥ 1.10 | addressed | §2.4, §5. |
| Opus N8: imported task-definition revision | addressed | §2.4 `removed` hand-off. |

## Blocking issues (only if REJECT)

None.

## Notes (non-blocking)

- **P2, §2.5 step 3 / §2.4: the StackSet path cannot use the change-set gate.** `update-stack-set` has no change-set preview. Substitute: (a) offline diff of the patched template against `describe-stack-set`'s template (policy attributes only), (b) `--operation-preferences FailureToleranceCount=0`, (c) `verify-retain` on each instance stack after the operation. The command must pass `--administration-role-arn` and `--execution-role-name` copied from `describe-stack-set` (UpdateStackSet requires re-specifying a customized admin role), plus `UsePreviousValue=true` parameters and existing capabilities.
- **P2, §2.4 acceptance rule vs. the Metadata fallback.** When the fallback is active, also accept `Attribute: Metadata` whose `AfterValue` contains only the `ecsodus:retain` key.
- **P2, §2.5 step 5.4 vs. "empty change set = failure".** After step 3's `update-stack-set`, detached instance stacks already carry Retain; replace re-patching with `verify-retain`, patch only if it fails.
- **P3, §6 invariants:** "every non-drop resource" is stale wording; say "every resource".
- **P3, §2 command list:** add `ecsodus check --changeset` and `ecsodus verify-retain`.
- **P3, §2.4 `removed` hand-off:** delete the `aws_ecs_task_definition` resource and its `import` block in the same commit as adding `removed`.
- **P3, §2.2:** `AWS::SecretsManager::SecretTargetAttachment` has no Terraform resource; fate it `manual-cleanup`.

Sources: [UpdateStackSet](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_UpdateStackSet.html), [ResourceTargetDefinition](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceTargetDefinition.html), [Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), [S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)
