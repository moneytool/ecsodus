# Round 3 vote: Claude Fable 5.1

(Verbatim; read-only; 2026-09-29.)

## Vote

**REJECT** (narrowly): r3 closes every round-2 condition and P1, but two mechanics it introduced in §2.2/§2.4 are stated wrongly and one of them re-opens the env-controller P0 if built as written; both are one-line edits, no redesign.

## Blocking issues

1. **P1, §2.4 "Update commands" and §2.5 step 3 (and §6 question 2): the change-set acceptance rule is wrong and would abort every retain patch.** A `DeletionPolicy`/`UpdateReplacePolicy`-only change is reported by CloudFormation as a `ResourceChange` with `Action: Modify`, `Replacement: False` and `Scope`/`Details[].Target.Attribute` = `DeletionPolicy` | `UpdateReplacePolicy` (the API reference lists both as valid `Attribute` values; `ResourceChange` also carries `PolicyAction: Retain`). The nested-stack `TemplateURL` change appears as `Modify` with `Attribute: Properties`, `Name: TemplateURL`. So "abort on any Modify" and "must contain no resource changes" cannot both hold and step 3 can never execute; an always-failing gate invites the operator to bypass it. Edit: replace with "abort unless every change is `Action: Modify`, `Replacement: False`, and every `Details[].Target` is `Attribute ∈ {DeletionPolicy, UpdateReplacePolicy}`, or `Attribute: Properties, Name: TemplateURL, RequiresRecreation: Never` on an `AWS::CloudFormation::Stack` resource; abort on any `Add`, `Remove`, `Import`, `Dynamic`, any other `Properties` target, or `Replacement ≠ False`. Create the change set with `IncludeNestedStacks` and apply the same rule to each nested change set." Rephrase §6 question 2 accordingly: "does a policy-only change set produce `Modify`/`Scope: DeletionPolicy` entries and apply them, rather than being treated as a no-op?" (coverage-roadmap issue #1543 reported the no-op behaviour in 2023; if it still occurs, the documented fallback is to add a `Metadata` key per resource, which needs a carve-out in the "byte-stable otherwise" rule).

2. **P1, §2.2 `drop-after-cutover`: `EnvControllerAction`-style handles must not be fated `drop`.** §2.2 lists them as `drop-after-cutover`, but §2.4 says Retain goes on "every resource not fated `drop-after-cutover`" and then names `EnvControllerAction` as retained, and §11 claims it is "explicitly retained". A mapper built from §2.2 omits Retain, the workload-stack delete sends `Delete` to env-controller, and it removes the ALB/NAT/EFS from the env stack when the last workload leaves, the original round-1 P0. Edit §2.2: `drop-after-cutover` = the custom-resource **Lambda functions**, their roles and log groups, and the pipeline bucket only; every `Custom::*` resource, including `EnvControllerAction`, is fated `retain-under-existing-owner` (Retain-patched, then left orphaned when its stack is deleted; listed for manual cleanup in step 6).

## Notes (non-blocking)

- **P2, §2.1/§2.5:** the freshness rule is triggered by the runbook itself: steps 2 and 3 both change `LastUpdatedTime`. Re-run `inventory` and `generate` after step 3 and assert the regenerated HCL and patches are byte-identical, or make freshness tolerate a policy-only/TemplateURL diff.
- **P2, §2.5 step 5.4:** StackSet-instance resources (ECR repos, KMS key, pipeline bucket) carry no Retain until step 5.4. Consider `update-stack-set` with the patched template in step 3 (same change-set rule), so the instances are protected before detach.
- **P3, §2.4 neutralizer:** swapping a `nodejs20.x` function's code is a function update, blocked from 2027-08-31. Add that date, or prefer repointing `ServiceToken` in the patch.
- **P3, §2.5 step 2:** out-of-band `DeletionProtection`/versioning creates CloudFormation drift; state that the step-3 change set will not revert it because the template property is unchanged.
- **P3, §2.3 baseline:** the "keep CloudFormation" caveat should also say a stack update that changes a custom-resource Lambda's code fails after 2027-08-31.

(The full round-2-conditions table in this vote marked every condition addressed except Astra C2/Opus C5/Fable C4, partial because of Blocking 1. Facts re-verified: copilot-cli archived 2026-06-22, EoS 2026-06-12; env-controller Delete calls `controlEnv(EnvStack, Workload, [])`.)

Sources: [ResourceTargetDefinition](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceTargetDefinition.html), [ResourceChange](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChange.html), [DeletionPolicy attribute](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-attribute-deletionpolicy.html), [coverage-roadmap #1543](https://github.com/aws-cloudformation/cloudformation-coverage-roadmap/issues/1543), [Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), [env-controller.js](https://raw.githubusercontent.com/aws/copilot-cli/mainline/cf-custom-resources/lib/env-controller.js)
