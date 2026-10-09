You are one member of a three-model review council (Codex / gpt-6-astra, Claude Fable 5.1, Claude Opus 5.5). Today is 2026-10-08. This is ROUND 1 of the review of the ecsodus v0.2 plan.

ecsodus is a read-only Python CLI that migrates AWS Copilot CLI applications to Terraform-managed ECS "in place" (adopt-in-place): it inventories the Copilot CloudFormation stacks, generates Terraform import blocks from literal deployed values, retain-patches every stack via change sets, and writes a fail-fast RUNBOOK with gates (`ecsodus check`). v0.1 and 0.2.0 shipped (Load Balanced Web, Backend, Worker Services, Scheduled Jobs; verified on real AWS twice). The approved v0.1 plan is docs/PLAN.md; decisions are in docs/adr/ (0001–0015); the v0.1 council record is docs/council/.

The plan under review is docs/PLAN-v0.2.md (DRAFT): App Runner support for Copilot Request-Driven Web Services, in two parts — v0.2a adopt the App Runner service in place into Terraform, and v0.2b a new "rebuild in parallel" mode onto ECS Fargate with a DNS cutover and, for the first time, a destructive retirement step.

Facts: AWS App Runner closed to new customers on 2026-04-30 (existing customers keep their services). AWS Copilot CLI reached end of support on 2026-06-12. The test sandbox account was never an App Runner customer.

Your job: read docs/PLAN-v0.2.md in full, plus whatever of docs/PLAN.md, docs/adr/, docs/knowledge/, src/ecsodus/ and tests/fixtures/copilot/ you need to check its claims. Review for:
1. Safety: anything that could destroy data, drop traffic, or let a Copilot custom resource / env-controller fire; whether the new gates (`check --phase rebuild|cutover|retire`, `--retire`, `verify-cutover`) actually enforce what they claim; whether the retirement step is justified and safely gated.
2. Correctness of AWS/Terraform/CloudFormation mechanics stated in the plan (App Runner resources and import IDs, custom-domain association behaviour, Route 53 weighted-record changes, ALB vs App Runner limits, ECS Express Mode), flagging anything UNCONFIRMED that the plan treats as fact.
3. Scope and sequencing: is v0.2a → v0.2b the right order? Should standalone App Runner services be covered? Is the plan's answer to the testability problem (the sandbox likely cannot create App Runner services) honest and sufficient?
4. Answer the plan's open questions (§11) with your recommendation for each.

Do not re-litigate stated maintainer decisions (Copilot first, Python, Terraform only, read-only CLI with mutations only in the runbook, no Proton) unless unsafe.

Output format (markdown), terse:
## Verdict
APPROVE | REVISE | REJECT, plus one sentence.
## Blocking issues (P0/P1)
Numbered; each with the plan section and a concrete edit.
## Other findings
Bullets with P-level (P2/P3).
## Answers to the open questions
Numbered to match §11.
## Unconfirmed claims
Bullets: claim, section, what would confirm it.

Do not modify any files. Read-only review.
