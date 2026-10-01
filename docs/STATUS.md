# Status: v0.1.0rc1 + AWS end-to-end passed (2026-09-30)

## Done

- **Plan.** [PLAN.md](PLAN.md) r4 was approved unanimously in council round 4 (gpt-6-astra,
  Claude Fable 5.1 and Claude Opus 5.5). All four rounds are kept verbatim in
  [council/](council/README.md), and the decisions are in [adr/](adr/README.md).
- **Commands.** All five plan commands are implemented: `inventory`, `report`, `generate`,
  `check` (`--phase import|steady`, `--state`, `--changeset`, `--template-diff`) and
  `verify-retain`. A sixth, `verify-fresh`, came out of the code review.
- **Mappers.** 61 CloudFormation resource types map to Terraform, covering the network, compute,
  data, IAM, DNS and out-of-band families. Unsupported shapes fail closed as `blocked`.
- **Knowledge base.** The [Copilot knowledge base](knowledge/) covers all 13 custom resources
  (9 of them have destructive Delete handlers), the stack layering, and the env conditions.
- **Tests.** 261 tests pass offline:
  - real Copilot-rendered fixtures
  - a synthetic app
  - moto
  - golden snapshots
  - a full hand-off app (env, LBWS, and an Aurora or S3/DynamoDB addon: 63–66 imports) whose
    generated Terraform passes `terraform validate` against the real AWS provider schema
  - a runbook block run under shell stubs, which proves a failed check stops the mutation
- **Code review.** Two independent reviews (gpt-6-astra and Claude Opus), then a verification
  review of the fixes. Every P0 and P1 finding is fixed; see
  [council/code-review-v0.1/](council/code-review-v0.1/README.md).
- **Checks.** `ruff`, `ruff format`, `mypy` and CI (GitHub Actions on Python 3.11–3.13) are all
  green.
- **Repository.** It is **private** at `github.com/moneytool/ecsodus`.

## AWS end-to-end: passed (2026-09-30)

A real Copilot v1.34.1 app (env + Load Balanced Web Service + DynamoDB and S3 addons, 5 stacks)
went through every runbook step in the sandbox account:

- 44/44 pure imports, then 44/44 no-op plans before and after teardown.
- All Copilot stacks and the StackSet were deleted.
- The service kept serving HTTP 200, and the sentinel data survived.
- Everything was removed afterwards.

Report: [e2e/2026-09-30-aws-e2e.md](e2e/2026-09-30-aws-e2e.md).

PLAN §6 questions 1–3 are answered: Retain stops custom-resource Delete handlers, policy-only
change sets are applied, and nested patches produce no Dynamic entries. Question 4 (a custom
domain and ACM certificate) was not covered.

## Open decisions for the maintainer

1. **Teardown gate.** Should step 5 stay behind `--i-understand-teardown-is-unverified`? The gate
   could be lifted now, or kept until a custom-domain run.
2. **Publishing.** Making the repo public and releasing to PyPI need the maintainer's decision
   (ADR-0009).

## Known limitations (fail-closed, documented)

- **Unsupported in v0.1:** Worker Services, Scheduled Jobs, RDWS, Static Sites, NLB, CloudFront,
  sidecars, pipelines, and Transform or `Fn::ForEach` templates. (Service Connect is imported
  as deployed, per ADR-0011.) Each is
  detected, reported, and kept on Copilot.
- **Partial imports:** some imports are generated with notes, where a sub-resource is a separate
  Terraform resource (S3 bucket sub-configurations, IAM managed-policy attachments, cluster
  capacity providers). `check --phase import` flags any difference.
- **JSON templates** are re-serialised rather than edited as text. The semantic check still
  applies.

## Next

1. Decide on the teardown gate and on publishing. Then tag `v0.1.0`, release to PyPI and
   write the launch posts.
2. v0.2: App Runner, with a rebuild-in-parallel mode.
