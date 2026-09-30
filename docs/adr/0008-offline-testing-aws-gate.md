# ADR-0008: Offline testing during development; a real AWS run gates public release

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer (the maintainer chose "offline only for now" when asked on 2026-09-29)

## Context
A real end-to-end run means deploying a Copilot sample with an Aurora addon, running the whole
runbook and checking that sentinel data survives. It costs about $1–3 in the sandbox account. The
account's rule is no billable use without explicit approval.

## Decision
- **Offline development testing:** golden fixtures from real Copilot-rendered templates, moto
  for inventory, synthetic Terraform plan and change-set JSON, and `terraform validate`.
- **Release gate:** the real AWS run needs separate approval, and it must pass before any public
  release or PyPI publish.
- **Until then:** the runbook's teardown step carries an UNVERIFIED banner, and `generate` needs
  `--i-understand-teardown-is-unverified` to emit step 5.

## Consequences
v0.1.0rc1 is feature-complete and safe by construction, but the questions only real AWS can
answer stay open (PLAN §6).
