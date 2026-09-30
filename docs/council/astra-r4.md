## Vote

**APPROVE WITH NOTES** — r4 resolves the round-3 safety blockers sufficiently to build v0.1; the remaining mechanics and consistency fixes are P2/P3.

## Round-3 items status

Notes numbered by their order in each review.

| Condition (reviewer + number) | Status | Note |
|---|---|---|
| Astra B1 / Fable B1 / Opus N1 | partial | §2.4 fixes ordinary/nested change-set acceptance; Metadata fallback still rejects itself. |
| Astra B2 / Fable B2 | addressed | §§2.2/2.4 retain every resource, including destructive custom-resource handles. |
| Astra B3 | addressed | SecureStrings remain external; secret versions excluded; read contracts explicit. |
| Astra N1 / Opus N2 | addressed | §2.5 step 3 requires re-inventory and regeneration. |
| Fable N1 | partial | Re-inventory/regeneration added; regeneration stability assertion absent. |
| Astra N2 | addressed | §6 includes real partial migration and domain-enabled validation. |
| Astra N3 | addressed | §2.6 enforces zero-change steady plans. |
| Astra N4 | addressed | §2.2 extends permissions/ignore rules to sensitive outputs. |
| Fable N2 | partial | Earlier StackSet protection added, but its execution/checking mechanics need correction. |
| Fable N3 | addressed | §2.4 includes Lambda code-update cutoff. |
| Fable N4 | addressed | §2.5 explains protection drift and unchanged template properties. |
| Fable N5 | addressed | §2.3 includes Lambda-update baseline caveat. |
| Opus N3 | addressed | Artifact bucket included; closure follows ARN/name strings. |
| Opus N4 | addressed | §2.5 restricts Copilot operations after partial migration. |
| Opus N5 | addressed | §6 gates only step 5. |
| Opus N6 | addressed | Rotation schedules imported; Lambda ownership documented. |
| Opus N7 | addressed | Terraform 1.10 floor explicit. |
| Opus N8 | addressed | §2.4 specifies task-definition handoff through `removed`. |

## Notes (non-blocking)

- **P2 — §§2.4–2.5, StackSet execution:** `update-stack-set` starts an operation directly; it does not produce the change set described in step 3. Specify a separate path: validate the exact retention-only template diff, preserve parameters/overrides, wait for operation and individual-instance success, then verify every instance template before detachment. [AWS API](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_UpdateStackSet.html).

- **P2 — §§2.4/6, fallback and repeatability:** Allow the exact generated `ecsodus:retain` Metadata change in the checker; currently its attribute allowlist rejects it. Align §6’s invariants with unconditional retention and this exception. An empty change set should succeed only when template verification proves retention is already installed—particularly when step 5.4 repeats step 3’s patch. [AWS target attributes](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceTargetDefinition.html).

- **P2 — §2.2, closure:** Explicitly accept verified `external-reference` dependencies; the literal two-fate closure rule currently blocks supported imported VPCs and SecureStrings. Preserve ownership attribution: a parameter actually owned by a discovered stack cannot become ownerless merely by labeling it external.

- **P2 — §§2.1/2.6, post-teardown checks:** Define freshness after intentional stack deletion. The steady checker must use the verified handoff record plus live resource identity checks, rather than requiring deleted stacks to remain queryable.

- **P3 — §§2.4/2.6, Terraform representation:** Implement import detection using `change.importing` alongside `change.actions`; `import` is not an action-array value. During task-definition handoff, remove the corresponding resource/import configuration before applying `removed`, and update expected-state checks accordingly. [Terraform JSON format](https://developer.hashicorp.com/terraform/internals/json-format).