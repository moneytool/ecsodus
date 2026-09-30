# ADR-0010: Repository layout and documentation standard

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer

## Decision

```
src/ecsodus/
  cli.py            argparse entry point (inventory, report, generate, check, verify-retain)
  cfn.py            template parsing: semantic view and source positions
  model.py          Inventory / Stack / Resource dataclasses (JSON round-trip, provenance)
  knowledge.py      facts from the Copilot source (custom resources, env conditions, tags)
  sources/          AWS readers (read-only boto3): copilot stack graph, live reads
  mappers/          fates, closure, blocker propagation, CFN -> Terraform mapping
  emit/             retain_patch, terraform, runbook, report
  check/            plan (Terraform JSON), changeset (CloudFormation), state
tests/
  unit/             pure-function tests
  golden/           snapshot tests over real Copilot fixtures
  fixtures/         copilot/ (verbatim from aws/copilot-cli, with licence), synthetic plans
docs/
  PLAN.md           the approved plan
  adr/              one decision per file (this directory)
  council/          every review and vote, verbatim
  knowledge/        Copilot internals the tool relies on (these double as SEO pages)
  guides/           user documentation
```

- Every decision gets an ADR, and superseded ADRs are kept.
- CHANGELOG follows Keep a Changelog.
- Every generated file carries a header naming its source and the ecsodus version.
