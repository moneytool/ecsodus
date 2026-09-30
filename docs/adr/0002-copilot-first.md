# ADR-0002: Copilot first; App Runner in v0.2; no Proton tooling

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council round 1 (Opus and Fable for Copilot first, gpt-6-astra for App
  Runner first; all three against Proton tooling)

## Context
AWS retired three container front ends in 2026. Moving from App Runner to Express Mode is a single
Terraform resource, and AWS documents it end to end. Leaving Copilot means tearing down
CloudFormation stacks whose custom resources delete certificates, DNS records and bucket contents,
and whose env-controller removes the shared ALB, NAT gateways and EFS. Nothing covers that. Proton
reaches end of support on 2026-10-07, eight days after this decision.

## Decision
v0.1 covers Copilot Load Balanced Web Services and Backend Services. App Runner image-based
services come in v0.2. There is no Proton tooling, only one docs page pointing to generic
CloudFormation adoption.

## Consequences
The differentiator is safe Copilot teardown, which is also the riskiest part. It needs the retain
patches (ADR-0004) and a real AWS run before release (ADR-0008).
