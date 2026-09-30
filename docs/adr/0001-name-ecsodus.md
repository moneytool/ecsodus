# ADR-0001: Name the project "ecsodus"

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council round 1 (all three: keep)

## Context
Search results for "Copilot" are dominated by GitHub Copilot, so a tool with "copilot" in its
name would be hard to find and easy to confuse. The name must also be free on PyPI, npm and
GitHub.

## Decision
The name is `ecsodus` (ECS + exodus). On 2026-09-29 it was free on PyPI, npm and GitHub. Discovery
comes from the repo description, the PyPI summary and docs page titles that match the searches
people actually make: "migrate AWS Copilot CLI to Terraform", "Copilot custom resources
Terraform", and so on.

## Consequences
The name says nothing about Copilot, so the tagline has to: "Safely migrate AWS Copilot apps to
Terraform."

## Alternatives considered
`offramp`, which is taken on npm and has a 112-star GitHub namesake. `awsexit` and `sunsetkit`,
which are less specific. Any name containing "copilot".
