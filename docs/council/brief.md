You are one member of an independent review council for a new open-source project plan. Other reviewers (different models) review the same plan separately; do not assume anyone else will catch what you skip. Today is 2026-09-29.

THE PLAN UNDER REVIEW: docs/PLAN.md in this directory — "ecsodus", a read-only CLI that migrates AWS Copilot CLI apps and AWS App Runner services (both retired/closed by AWS in 2026) to ECS (Express Mode where it fits) managed by Terraform, emitting import blocks, a readiness report and a cutover runbook. Read it in full.

Context from the maintainer: single developer, Python background, free AWS sandbox account (every billable test needs approval), ships side projects in ~6 weeks of evenings. The idea was scored 6.5/10: moderate reach (Copilot's audience is small, App Runner has no hard deadline, Cloud Run and platforms like Encore compete), doable because building blocks exist (extract-cf2tf, terraform-aws-modules/ecs express-service submodule, ecspresso for deploys).

Review for, in this order:
1. FACTUAL / TECHNICAL CORRECTNESS: Copilot's generated CloudFormation (custom resources, env/service stacks, addons, overrides), App Runner features and their ECS equivalents, ECS Express Mode (what it provisions, what it cannot do, Terraform/provider support), Terraform import semantics (import blocks, config generation, `terraform plan -generate-config-out`), CloudFormation stack teardown with retained resources. Say exactly what is wrong, with confidence; mark anything unsure (UNSURE).
2. SAFETY: any path where following the generated output destroys or orphans a stateful resource, breaks DNS/TLS, loses secrets, or double-runs workloads (e.g. Worker/Scheduled jobs during parallel run).
3. PRODUCT / SCOPE: is the wedge right, is v1 too big or too small for 6 weeks, what to cut, what the real differentiator is versus AWS's own guides, Kiro+MCP, Encore, fortem.dev, extract-cf2tf + manual work.
4. The five OPEN QUESTIONS in §10.

Output format (markdown), concrete and terse:
## Verdict
(one paragraph: build as-is / revise / rethink, and the single most important change)
## Findings
Numbered. Each: **[P0|P1|P2|P3] Title** — section — what is wrong — why it matters — concrete fix. P0 = plan is wrong or unsafe; P1 = must fix before building; P2 = should fix; P3 = nice to have.
## Open questions (§10)
1-5, each: recommendation + one-line reason.
## Missing from the plan
Bullets.

Do not modify any files. Read-only review.
