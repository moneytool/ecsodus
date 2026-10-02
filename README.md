# ecsodus

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23073590.svg)](https://doi.org/10.5281/zenodo.23073590)
[![PyPI](https://img.shields.io/pypi/v/ecsodus?label=PyPI&cacheSeconds=3600)](https://pypi.org/project/ecsodus/)
[![AWS ECS](https://img.shields.io/badge/AWS-ECS-FF9900?logo=amazonecs&logoColor=white)](https://aws.amazon.com/ecs/)
[![Terraform](https://img.shields.io/badge/Terraform-%E2%89%A5%201.10-7B42BC?logo=terraform&logoColor=white)](https://developer.hashicorp.com/terraform)
[![Docs](https://img.shields.io/badge/docs-moneytool.github.io%2Fecsodus-blue)](https://moneytool.github.io/ecsodus/)
[![CI](https://github.com/moneytool/ecsodus/actions/workflows/ci.yml/badge.svg)](https://github.com/moneytool/ecsodus/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/ecsodus)](https://pypi.org/project/ecsodus/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![AWS e2e](https://img.shields.io/badge/AWS%20e2e-44%2F44%20imports%2C%20zero%20data%20loss-brightgreen)](docs/e2e/2026-09-30-aws-e2e.md)

**Safely migrate AWS Copilot CLI apps to Terraform-managed ECS.**

![How ecsodus migrates an AWS Copilot app to Terraform in place: inventory, report, generate, retain-patch, import and teardown](https://raw.githubusercontent.com/moneytool/ecsodus/main/docs/assets/how-it-works.gif)

AWS ended support for the Copilot CLI on 2026-06-12 and archived its repository on 2026-06-22.
Your Copilot services keep running as CloudFormation stacks. Moving them to Terraform means
deleting those stacks without deleting what they manage, and done naively that destroys
production:

- **Custom-resource Delete handlers.** When a stack is deleted, Copilot's Lambda-backed custom
  resources delete ACM certificates, DNS alias and validation records, and the NS delegation, and
  they empty the ELB access-logs bucket.
- **The env-controller.** Deleting the last service stack makes the env-controller remove the
  shared ALB, the NAT gateways and the **EFS file system** from the environment stack.
- **Unprotected addons.** Addon databases (Aurora, DynamoDB) live in nested stacks with no
  `DeletionPolicy`.
- **`--retain-resources` doesn't help.** The obvious flag only works on stacks already in
  `DELETE_FAILED`.

![Deleting Copilot stacks as-is deletes the load balancer, NAT gateways, EFS, DynamoDB, certificates and the ECS service; after ecsodus retain patches every resource is kept and owned by Terraform](https://raw.githubusercontent.com/moneytool/ecsodus/main/docs/assets/retain-patch.gif)

ecsodus knows where these traps are. It reads your Copilot app and **adopts it in place**:
Terraform imports the resources exactly as they run today, and no traffic moves. It writes
**retain patches** so that no stack delete can remove anything, and a step-by-step runbook with a
machine check before every mutating step.

> **Status: v0.1.0, alpha.** It is tested offline against real Copilot-generated templates, and
> it passed a real AWS end-to-end run on 2026-09-30, including teardown
> ([report](docs/e2e/2026-09-30-aws-e2e.md)). Read the [verified scope](docs/STATUS.md) before
> running it against production.

## Install

```bash
pipx install ecsodus      # or run it without installing: uvx ecsodus --help
```

## What it does

```bash
ecsodus inventory --app myapp -o inventory.json    # read-only: stacks, templates, live state
ecsodus report    inventory.json                   # REPORT.md: readiness, fates, blockers
ecsodus generate  inventory.json --out infra/      # Terraform + retain patches + RUNBOOK.md
ecsodus check     plan.json --manifest infra/ecsodus-manifest.json --phase import
ecsodus verify-retain --app myapp                  # read-only: is every resource Retain?
```

- **Read-only by construction.** Every AWS client refuses any operation that isn't
  `Describe`/`List`/`Get`/`Lookup`, and secret values are never read. ecsodus never applies
  Terraform, deletes anything or moves traffic. You run the runbook.
- **Exact imports.** Imported resources become flat `aws_*` blocks built from literal deployed
  values, so the first plan is import-only. `check --phase import` rejects any update, create,
  delete or replacement.
- **Retain everything first.** Every resource in every handed-off stack gets
  `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`. The patch edits the deployed
  template line by line, so every other byte stays identical. It is applied through change sets,
  and `check --changeset` accepts only change sets that change policies and nothing else.
- **Never split a stack.** A stack is either handed off completely or kept on Copilot completely.
  If anything is unsupported, the stack and everything it depends on stay on Copilot, and the
  report says why. Nothing is ever dropped silently.
- **Honest baseline.** Every report starts with the zero-risk option: keep the CloudFormation.

![ecsodus terminal demo: report what a stack delete would destroy, then generate Terraform imports, retain patches and a gated runbook](https://raw.githubusercontent.com/moneytool/ecsodus/main/docs/assets/demo.gif)

### Safety gates

Every mutating step in the runbook runs only after an `ecsodus check` passes. An import that
would also change a resource fails, and so does a retain-patch change set that touches anything
except deletion policies:

![ecsodus check refusing an unsafe import plan and a non-policy change set, then passing the pure import and the policy-only change set](https://raw.githubusercontent.com/moneytool/ecsodus/main/docs/assets/gates.gif)

## How it compares

| Approach | Moves traffic? | Keeps your data? | Ends on Terraform? | Handles Copilot's Delete handlers? |
|---|---|---|---|---|
| **ecsodus** (adopt in place) | No | Yes, every resource is retained, then imported | Yes | Yes: retain patches, verified on AWS |
| Rebuild on ECS Express Mode or CDK (AWS's suggestion) | Yes, a cutover | You migrate stateful resources yourself | No (Express Mode / CDK) | Not applicable until you delete the old stacks |
| Convert templates with [cf2tf](https://github.com/DontShaveTheYak/cf2tf) | Depends | Only if you import and retain by hand | Yes | No |
| Keep the CloudFormation | No | Yes | No | Not triggered |

If you don't need Terraform, keeping the CloudFormation is the zero-risk choice, and every
ecsodus report says so first.

## Scope (v0.1)

**Supported:**
- Load Balanced Web Services, Backend Services and Worker Services (queues, SNS subscriptions
  and the backlog-based autoscaling they depend on)
- Copilot's default Service Connect, imported as deployed
- their environment (created or imported VPC)
- workload and environment addons: Aurora/RDS, DynamoDB, S3
- aliases and custom domains
- the app stack and StackSet

**Detected and reported as blocked:** Scheduled Jobs, Request-Driven Web Services, Static
Sites, NLB, CloudFront, sidecars, pipelines and multi-account environments.

**Planned:**
- **v0.2:** App Runner, with a rebuild-in-parallel mode
- **v0.3:** more workload types

## Documentation

**Docs site: https://moneytool.github.io/ecsodus/** — includes
[AWS Copilot CLI end of support: what to do](https://moneytool.github.io/ecsodus/copilot-end-of-support/),
[how to migrate AWS Copilot to Terraform](https://moneytool.github.io/ecsodus/migrate-copilot-to-terraform/)
and the [FAQ](https://moneytool.github.io/ecsodus/faq/).

- [Project status](docs/STATUS.md): what is done and what is pending
- [AWS end-to-end report](docs/e2e/2026-09-30-aws-e2e.md): the real run (passed)
- [Worked example](docs/examples/): REPORT.md and RUNBOOK.md for a real Copilot app
- [Quickstart](docs/guides/quickstart.md)
- [How it works](docs/guides/how-it-works.md): fates, hand-off, retain patches and the checks
- [Copilot custom resources and what their Delete handlers do](docs/knowledge/copilot-custom-resources.md)
- [Copilot stack layering](docs/knowledge/copilot-stacks.md)
- [The approved plan](docs/PLAN.md), the [council reviews](docs/council/README.md) behind it,
  and the [decision records](docs/adr/README.md)

## Development

```bash
uv sync
uv run pytest            # offline: fixtures, moto, and terraform validate if terraform is installed
uv run ruff check . && uv run mypy src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Citation

If you use ecsodus, please cite it: [doi:10.5281/zenodo.23073590](https://doi.org/10.5281/zenodo.23073590)
(all versions), or see [`CITATION.cff`](CITATION.cff). GitHub's "Cite this
repository" button reads it.

## License

Apache-2.0. Test fixtures under `tests/fixtures/copilot/` are copied verbatim from
[aws/copilot-cli](https://github.com/aws/copilot-cli) (Apache-2.0); see `SOURCE.md` there.
