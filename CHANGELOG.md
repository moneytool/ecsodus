# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-07

Two more Copilot workload types hand off: Worker Services and Scheduled Jobs. Both are checked
offline (synthetic full hand-off, `terraform validate`, and `terraform plan` against moto for
the new resource types) but not yet on a real AWS account; the import-only gate stops a
migration if a real account plans any change.

### Added
- Worker Services hand off (issue #4, ADR-0014). Their SQS queues, KMS key, SNS subscriptions
  (`aws_sns_topic_subscription`) and the backlog-per-task calculator that drives queue-depth
  autoscaling are imported. The calculator is imported, not deleted: `aws_lambda_function`
  with its code ignored after import, plus `aws_cloudwatch_event_rule`,
  `aws_cloudwatch_event_target` and `aws_lambda_permission`.
- One CloudFormation resource can now import several Terraform resources (an Events rule and
  its targets); each one is checked by the import-only gate.
- The inventory records exports of stacks outside the app that its templates import by a
  literal `Fn::ImportValue` name (for example an EFS file system mounted from another stack), so
  those imports resolve. No other export in the account is recorded.
- Read-only live reads for Events rules, Lambda tags and policy statement ids, and SNS
  subscription attributes. `lambda:GetFunction` stays forbidden.
- Scheduled Jobs hand off (issue #5, ADR-0015): the schedule (`aws_cloudwatch_event_rule` and a
  target that assumes a role), the Step Functions state machine that runs the task
  (`aws_sfn_state_machine`, its definition substituted exactly and checked against the live
  one), its roles, and the EFS access point on the environment's managed file system.
- Read-only live reads for Step Functions state machines (DescribeStateMachine, tags).
- A guide per Copilot workload type (issue #7): what ecsodus imports, what it cleans up, and what
  to watch for, for Load Balanced Web, Backend and Worker Services and Scheduled Jobs, and what
  to do with Request-Driven Web Services and Static Sites, which stay on Copilot.

### Changed
- The docs no longer list sidecars as blocked: task definitions with sidecar containers have
  always been imported as deployed.
- Network Load Balancers stay blocked (their stack is kept on Copilot), now pinned by a test and
  with a clearer reason in the report.

### Fixed
- An ECS service whose `ServiceRegistries`, `LoadBalancers` or `CapacityProviderStrategy` is
  `!Ref AWS::NoValue` no longer crashes the planner.
- An Events rule whose `Targets` is switched off with `Fn::If` / `AWS::NoValue` imports without
  targets instead of aborting the plan.

## [0.1.2] - 2026-09-30

Metadata and documentation only: no code changes since 0.1.1.

### Added
- A docs site at https://moneytool.github.io/ecsodus/ (MkDocs Material on GitHub Pages) with a
  sitemap, per-page descriptions, and pages on Copilot end of support, migrating Copilot to
  Terraform, and an FAQ.
- Zenodo DOI 10.5281/zenodo.23073590 (concept) in `CITATION.cff`, plus DOI, AWS ECS, Terraform
  and docs badges.
- README and docs animations: how it works, why retain patches matter, and the safety gates in
  action (`tools/visuals/` regenerates them).
- Search metadata on the docs site: Open Graph and Twitter cards, JSON-LD structured data, and
  Google Search Console verification, checked in CI by `tools/check_site_meta.py`.
- PyPI project links point to the docs site and the DOI, with search keywords.

## [0.1.1] - 2026-09-30

The first release archived on Zenodo.

### Added
- `CITATION.cff` with the author's ORCID and affiliation, plus README badges for PyPI and CI.

### Fixed
- The package metadata now gives the author's full surname, "Jannapu Reddy".

## [0.1.0] - 2026-09-30

First public release. It was verified end to end on real AWS against a Copilot v1.34.1 app
(`docs/e2e/2026-09-30-aws-e2e.md`).

### Changed
- The teardown gate is removed (ADR-0012). Runbook step 5 is always emitted, and the banner
  states the scope the AWS run verified. `--i-understand-teardown-is-unverified` is now a
  hidden no-op.

### Verified
- AWS end-to-end run on 2026-09-30 against a real Copilot v1.34.1 app: 44/44 pure imports, all
  Copilot stacks torn down with zero data loss, and PLAN §6 questions 1–3 answered
  (`docs/e2e/2026-09-30-aws-e2e.md`). The real-AWS defects it found are fixed.

### Added
- Approved plan (r4) after four rounds of three-model council review (`docs/PLAN.md`,
  `docs/council/`).
- ADRs 0001–0010.
- `ecsodus inventory`: a read-only Copilot discovery covering the app stack, StackSet
  instances, env and workload stacks, nested addons, SSM metadata, live state and out-of-band
  ACM certificates. Every client is wrapped in a read-only guard.
- `ecsodus report`: a readiness report. It gives each resource a fate, decides per stack
  whether it is handed off or kept (and why), lists what an unpatched delete would destroy,
  shows Express Mode fit, and starts from the keep-CloudFormation baseline.
- `ecsodus generate`:
  - flat root-module Terraform with `import` blocks
  - retain patches for every stack, applied to nested stacks through their parent's
    `TemplateURL`, plus one for the StackSet
  - the hand-off manifest, `REPORT.md` and `RUNBOOK.md`
- `ecsodus check`: gates for import- and steady-phase plans, state, the CloudFormation
  change-set acceptance rule, and a template diff.
- `ecsodus verify-retain`: a read-only check that every resource in every stack, nested stacks
  included, has both Retain policies.
- Copilot knowledge base: all 13 custom resources and what their Delete handlers do, the stack
  layering, and DeletionPolicy defaults.
- Terraform mappers for the network, compute, data, IAM and DNS resource types that Copilot's
  LBWS, Backend, env and addon templates use.
- `ecsodus verify-fresh`: a read-only check that the account, region and stacks still match the
  manifest before import.
- Offline tests:
  - real Copilot fixtures
  - a synthetic app
  - moto
  - golden snapshots
  - `terraform validate` on a full hand-off app

### Security
- Two independent code reviews and a verification review; every P0 and P1 finding is fixed
  (`docs/council/code-review-v0.1/`).

[Unreleased]: https://github.com/moneytool/ecsodus/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/moneytool/ecsodus/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/moneytool/ecsodus/releases/tag/v0.1.2
[0.1.1]: https://github.com/moneytool/ecsodus/releases/tag/v0.1.1
[0.1.0]: https://github.com/moneytool/ecsodus/releases/tag/v0.1.0
