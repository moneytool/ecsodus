# Council review of the M5 App Runner plan

Three models reviewed the M5 plan (App Runner adopt-in-place and rebuild on ECS) independently
and read-only in every round:

- **gpt-6-astra** (Codex CLI, no network)
- **Claude Fable 5.1** (web access, checked against the Copilot source, the Terraform provider
  source and AWS docs)
- **Claude Opus 5.5** (web access, checked against the Copilot source, the Terraform provider
  source and AWS docs)

The final plan is [`../../PLAN-v0.2.md`](../../PLAN-v0.2.md) (r4, approved). Its §15, §16 and
§17 map every finding to the section that addresses it, and §18 lists the round-3 notes as
numbered build requirements.

## Outcome by round

| Round | Plan | gpt-6-astra | Fable 5.1 | Opus 5.5 | Brief |
|---|---|---|---|---|---|
| 1 (review) | `docs/council/v0.2/plan-r1.md` | [REVISE (11 P1)](astra.md) | [REVISE (5 P1)](fable.md) | [REVISE (4 P1)](opus.md) | [brief](brief.md) |
| 2 (vote) | `docs/council/v0.2/plan-r2.md` | [REJECT (2 P1)](astra-r2.md) | [APPROVE w/ notes](fable-r2.md) | [APPROVE w/ notes](opus-r2.md) | [brief](brief-r2.md) |
| 3 (vote) | `docs/council/v0.2/plan-r3.md` | [**APPROVE w/ notes**](astra-r3.md) | [**APPROVE w/ notes**](fable-r3.md) | [**APPROVE w/ notes**](opus-r3.md) | [brief](brief-r3.md) |
| final | r4 = [PLAN-v0.2.md](../../PLAN-v0.2.md) | — | — | — | — |

Every file is kept verbatim. The plan snapshots `plan-r1.md`, `plan-r2.md` and `plan-r3.md` are
excluded from the docs site (`exclude_docs` in `mkdocs.yml`), because their links are relative to
`docs/` and would break here; they are readable in the repository at the paths above.

## What the council changed

**Round 1.** All three asked for revision. The draft would have retired App Runner and run work
twice:
- Retirement moved out of release 0.4.0 into a separate artifact, M5c, which refuses to generate
  until it has run on real App Runner. No flag unlocks it.
- `desired_count = 0` is not an interlock once a scalable target exists. The target is created at
  `min = max = 0`, and a gated `start` phase raises it.
- A full phase table with exact allowed changes per transition, and weight-pair rules for the
  cutover: no (0, 0) pair on any path, exact before and after pairs, INSYNC waits.
- Retirement evidence comes from CloudTrail, `GetChange` and `2xxStatusResponses` metrics with
  fail-closed rules for missing data, not from the operator's word.
- Nothing that may be shared is ever deleted: not the VPC connector, roles or auto-scaling
  configurations, and never an ACM validation record.
- A dedicated new ALB by default; a shared env ALB is opt-in.
- `verify-handoff` proves Copilot is gone before any rebuild starts.
- The deployed image must be proven by digest (provenance), or a synchronized deployment comes
  first.

**Round 2.** Astra rejected with two P1s; Opus and Fable approved with notes.
- The certificate request is staged: a gated phase creates only the certificate, a read-only step
  reads its real validation record, and staged generation emits the next phase with that value
  as a literal. No gate depends on an unknown value.
- Background work moves to ECS through a separate `on` task-definition revision, registered and
  verified before App Runner workers go off.
- The VPC connector security groups were corrected: Copilot's connector carries both
  `ServiceSecurityGroup` and `EnvironmentSecurityGroup`, and an operator decision says whether
  the ECS tasks join the second.

**Round 3.** Unanimous approval. The P2 and P3 notes became 19 fail-closed build requirements
(plan §18): rollback forgets instead of deleting a created validation record, an off twin of the
live revision for rollback after hand-over, a gated `new_host` record for services without a
custom domain, an ownership decision before adopting a validation record, an import gate that
accepts the refreshed form of a `forget`, and smaller gate and wording fixes.

## Questions only the maintainer or a real run can settle

For the maintainer (plan §13):
1. **An eligible App Runner account.** An account that ran App Runner before 2026-04-30, or the
   design-partner path (plan §9).
2. **The e2e domain.** Register one cheap domain dedicated to ecsodus e2e; billable, needs a yes.
3. **The eligibility probe.** A `create-service` / `delete-service` attempt in the sandbox;
   near-zero cost, needs a yes.

For a real run (the items still marked UNCONFIRMED in the plan):
1. Whether a real import plan shows no diff for the default health-check block (§3.3).
2. Whether a `start-deployment` leaves the M5a plan empty (§3.5).
3. Whether `RegisterScalableTarget` accepts `MaxCapacity = 0` for ECS (§4.3).
4. Whether App Runner's managed certificate lives in the customer account (§4.3).
5. Whether `StartCommand` overrides ENTRYPOINT or CMD (§4.4).
6. Whether App Runner runs images only as amd64 (§4.4).
7. Whether deleting the last App Runner service ends "existing customer" status (§5.1).
8. How App Runner publishes metrics at zero traffic, and whether its health checks count (§5.2).
9. Which call blocks an ineligible account (§9).
10. Current prices for the e2e cost estimate (§9).
