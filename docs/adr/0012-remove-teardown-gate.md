# ADR-0012: Remove the teardown gate

- Status: accepted (supersedes the gate part of ADR-0008)
- Date: 2026-09-30
- Deciders: maintainer

## Context
ADR-0008 put runbook step 5 (teardown) behind `--i-understand-teardown-is-unverified` until a
real AWS end-to-end run settled PLAN §6. The run on 2026-09-30 passed. Retain suppresses
custom-resource Delete handlers, policy-only change sets are applied, nested patches cause no
`Dynamic` entries, and a real Copilot app was torn down with no data or traffic loss
([report](../e2e/2026-09-30-aws-e2e.md)).

## Decision
- Step 5 is always emitted.
- The flag is still accepted as a hidden no-op, so existing scripts keep working.
- The runbook's banner now states what the AWS run verified, and lists what it did not cover:
  custom domains and ACM certificates, Aurora addons, private placement with NAT, and partial
  migrations. For those, the banner advises running on a non-production copy first.

## Consequences
The machine checks remain the safety mechanism: `verify-retain` before every delete, and the
change-set, plan and state gates. The banner should be revisited when those features are covered
by a real run.
