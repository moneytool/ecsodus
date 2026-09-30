# Status: v0.1.0rc1 (2026-09-30)

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

## Not done

**The real AWS end-to-end run** (PLAN §6). This is deliberate: the maintainer chose offline-only
testing on 2026-09-29. The run deploys a Copilot sample with an Aurora addon and a custom domain
into the sandbox account, runs the whole runbook, and checks that sentinel data survives. It
would cost about $1–3 and needs a fresh explicit yes.

Until it passes:
- The runbook's teardown (step 5) is gated behind `--i-understand-teardown-is-unverified`.
- Nothing is published: the repo stays private and nothing goes to PyPI (ADR-0008, ADR-0009).

The run answers these open questions:
1. Does `DeletionPolicy: Retain` on a `Custom::*` resource stop its Delete handler from running?
   If not, the runbook switches to the emitted neutralizer.
2. How is a policy-only change set reported? If it is treated as a no-op, the runbook switches to
   the Metadata fallback.
3. Does a patched nested stack produce `Dynamic` entries in its parent's change set? If so,
   `--allow-nested-dynamic` handles it.
4. Does the shared ACM validation CNAME survive?

## Known limitations (fail-closed, documented)

- **Unsupported in v0.1:** Worker Services, Scheduled Jobs, RDWS, Static Sites, NLB, CloudFront,
  sidecars, Service Connect, pipelines, and Transform or `Fn::ForEach` templates. Each is
  detected, reported, and kept on Copilot.
- **Partial imports:** some imports are generated with notes, where a sub-resource is a separate
  Terraform resource (S3 bucket sub-configurations, IAM managed-policy attachments, cluster
  capacity providers). `check --phase import` flags any difference.
- **JSON templates** are re-serialised rather than edited as text. The semantic check still
  applies.

## Next

1. The AWS end-to-end run, which needs approval. Then remove the teardown gate, tag `v0.1.0`,
   decide on publishing, release to PyPI and write the launch posts.
2. v0.2: App Runner, with a rebuild-in-parallel mode.
