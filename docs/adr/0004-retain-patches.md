# ADR-0004: Retain-all patches via change sets, not `--retain-resources`

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council rounds 1–4 (unanimous)

## Context
`DeleteStack --retain-resources` only applies to stacks already in `DELETE_FAILED`. On a healthy
stack, a normal delete removes every resource that lacks `DeletionPolicy: Retain`. Copilot's
templates set Retain almost nowhere, and its custom resources have destructive Delete handlers.

## Decision
For every stack, ecsodus emits the deployed template with `DeletionPolicy: Retain` and
`UpdateReplacePolicy: Retain` on every resource, with no exceptions. It edits the original YAML
text line by line, so every other byte is unchanged. `verify_patch` proves semantic equality
apart from the permitted edits.
- **Permitted edits:** the two policies, a nested stack's `TemplateURL` (pointing at the patched
  child), and the optional `ecsodus:retain` Metadata fallback.
- **How patches are applied:** plain stacks through change sets, gated by `check --changeset`.
  The StackSet through `update-stack-set`, after an offline diff (PLAN §13.1).
- **Order:** retain patches go on before any Terraform import.

## Consequences
Two behaviours are unverified until the real AWS run: whether Retain suppresses custom-resource
Delete invocations, and how a policy-only change set is reported. Each has a fallback: the
neutralizer, and the Metadata key.
