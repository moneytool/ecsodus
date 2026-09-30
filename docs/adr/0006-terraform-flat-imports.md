# ADR-0006: Terraform only; imported resources as flat root-module resources

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council rounds 1–2 (all three)

## Context
Importing into terraform-aws-modules internals means matching each module's exact arguments.
Otherwise plans show replacements, for example on an ALB's `name` or `subnets`.
`-generate-config-out` is experimental and cannot target module or `count`/`for_each` resources.
Express Mode's Terraform resource has no task definition, sidecars, volumes or custom domain.

## Decision
- Imported resources become plain `aws_*` blocks in the root module, built from the deployed
  template plus live reads, with an `import` block each.
- Modules are used only for newly created compute (v0.2).
- No CloudFormation or CDK output. Keeping the CloudFormation is presented honestly as the
  zero-risk baseline.
- Terraform ≥ 1.10 (`use_lockfile`, `removed`). Version constraints are bounded.
