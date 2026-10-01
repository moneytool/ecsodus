# Architecture Decision Records

| ADR | Decision |
|---|---|
| [0001](0001-name-ecsodus.md) | Name the project "ecsodus" |
| [0002](0002-copilot-first.md) | Copilot first; App Runner in v0.2; no Proton tooling |
| [0003](0003-adopt-in-place.md) | Adopt in place is the default and only v0.1 mode |
| [0004](0004-retain-patches.md) | Retain-all patches via change sets, not `--retain-resources` |
| [0005](0005-python.md) | Python 3.11+, PyPI |
| [0006](0006-terraform-flat-imports.md) | Terraform only; flat root-module imports |
| [0007](0007-no-proton.md) | No Proton tooling |
| [0008](0008-offline-testing-aws-gate.md) | Offline testing; real AWS run gates release |
| [0009](0009-private-repo.md) | Private repo until AWS-tested |
| [0010](0010-repo-layout.md) | Repository layout and documentation standard |
| [0011](0011-service-connect-adopt-in-place.md) | Import Service Connect as deployed in adopt-in-place |
| [0012](0012-remove-teardown-gate.md) | Remove the teardown gate (supersedes part of 0008) |

To add one, copy [0000-template.md](0000-template.md).
