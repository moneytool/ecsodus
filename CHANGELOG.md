# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
