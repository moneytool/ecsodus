# ADR-0013: Public repository and PyPI release

- Status: accepted (supersedes ADR-0009)
- Date: 2026-09-30
- Deciders: maintainer

## Context
ADR-0009 kept the repository private until a real AWS end-to-end run passed and the maintainer
decided to publish. The run passed on 2026-09-30, and the maintainer asked for a public
repository and a PyPI release.

## Decision
- **Repository:** `github.com/moneytool/ecsodus` is public. Before switching, the full git history
  was scanned for credentials and account identifiers; only dummy test values were found.
- **Releases:**
  - published to PyPI as `ecsodus` by `.github/workflows/release.yml`, on `vX.Y.Z` tags
  - trusted publishing (OIDC), with no stored token
  - the tag must be on `main` and match the package version
  - the full suite runs before the build
- **Protection (mirroring aegis-devops):**
  - a "Prodbranch" ruleset on `main`: no deletion and no force-push; pull requests need 2
    approvals with code-owner review and resolved threads; the CI jobs are required with strict
    up-to-date
  - a "Release tags" ruleset: `v*.*.*` tags cannot be deleted or moved
  - admins can bypass, as in aegis-devops

## Consequences
The first release is 0.1.0, marked alpha. The README and STATUS state the verified scope and what
the AWS run did not cover.
