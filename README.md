# ecsodus

**Safely migrate AWS Copilot CLI apps to Terraform-managed ECS.**

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

ecsodus knows where these traps are. It reads your Copilot app and **adopts it in place**:
Terraform imports the resources exactly as they run today, and no traffic moves. It writes
**retain patches** so that no stack delete can remove anything, and a step-by-step runbook with a
machine check before every mutating step.

> **Status: v0.1.0rc1, private.** The tool is feature-complete for v0.1 and tested offline
> against real Copilot-generated templates. Teardown (runbook step 5) is gated behind a flag
> until a real AWS end-to-end run confirms two CloudFormation behaviours (see
> [docs/PLAN.md §6](docs/PLAN.md)).

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

## Scope (v0.1)

**Supported:**
- Load Balanced Web Services and Backend Services
- their environment (created or imported VPC)
- workload and environment addons: Aurora/RDS, DynamoDB, S3
- aliases and custom domains
- the app stack and StackSet

**Detected and reported as blocked:** Worker Services, Scheduled Jobs, Request-Driven Web
Services, Static Sites, NLB, CloudFront, sidecars, Service Connect, pipelines and multi-account
environments.

**Planned:**
- **v0.2:** App Runner, with a rebuild-in-parallel mode
- **v0.3:** more workload types

## Documentation

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

## License

Apache-2.0. Test fixtures under `tests/fixtures/copilot/` are copied verbatim from
[aws/copilot-cli](https://github.com/aws/copilot-cli) (Apache-2.0); see `SOURCE.md` there.
