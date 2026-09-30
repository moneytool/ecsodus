# ADR-0003: Adopt in place is the default and the only v0.1 mode

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council rounds 1–2 (Opus proposed it; all three agreed)

## Context
A Copilot Load Balanced Web Service already is a plain ECS service with an ALB, target groups and
a VPC. Rebuilding it in parallel adds a DNS cutover, double-running workloads, a second ALB,
security-group rewiring and certificate churn, and gains nothing.

## Decision
ecsodus imports the existing resources into Terraform and moves no traffic. Rebuild-in-parallel,
which is needed for Express Mode or App Runner, ships in v0.2 with DNS pre-flight checks and
background-work controls.

## Consequences
The generated Terraform must match live state exactly, so the first plan is import-only
(`check --phase import`).
