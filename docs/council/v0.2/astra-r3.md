## Vote

APPROVE WITH NOTES — r3 resolves both round-2 P1s; the remaining issues are bounded P2/P3 build corrections, with no remaining P0/P1.

## Round-2 items status

Note numbers below follow bullet order in each reviewer’s round-2 vote.

| Item (reviewer + number) | Status | Note |
|---|---|---|
| Astra P1-1; Opus N1 | addressed | 2a requests the certificate before the binding comparison; staged generation emits literal validation records. Listener waits for issuance. |
| Astra P1-2; Fable N2 | addressed | 8a registers and verifies `on` before 8b disables App Runner work; 8c uses its known ARN. `skip_destroy` preserves revisions. |
| Astra N1; Fable N1 | addressed | Actual connector membership retained; extra task SG membership requires a decision and exposure report. |
| Astra N2 | addressed | §4.5 accepts IGW routing with assigned public IP. |
| Astra N3 | partial | Association checks are conditional; `new_host` still inherits an incompatible zone predicate. |
| Astra N4 | partial | Freeze, refresh and deployment ownership restored; the new revision’s rollback-off gate needs clarification. |
| Astra N5; Opus N4; Fable N4 | addressed | UPSERT/transactional update and INSYNC behavior stated, with pinned-version verification required. [Provider source](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/route53/record.go). |
| Astra N6; Fable N9 | addressed | §14 explicitly reserves 0016 conditionally and requires renumbering if necessary. |
| Opus N2; Fable N3 | addressed | Import-phase `forget` restricted to manifest record addresses, including reverse conversion. |
| Opus N3 | addressed | Explicit rollback waypoint `(100,100)` added. |
| Opus N5 | addressed | Lookup limits, pagination, client-side matching, DELETE+CREATE parsing and `NoSuchChange` handling specified. |
| Opus N6 | addressed | Listener dependencies, grace-period decision and circuit-breaker behavior specified. |
| Opus N7 | addressed | Rollback forgets the log group and preserves logs. |
| Opus N8 | addressed | ALB root path and lineage recorded; separate `prepare-alb`. |
| Opus N9 | addressed | Fixture/resource count and Terraform constraint agree with the checkout; ADR reservation is conditional. |
| Fable N5 | addressed | Defaults corrected; real import-plan behavior remains explicitly unconfirmed. |
| Fable N6 | addressed | `MaxCapacity = 0` explicitly unconfirmed and assigned offline/real stand-in checks. |
| Fable N7 | addressed | §4.1 checks state image identifier against live. |
| Fable N8 | addressed | Execution-role permissions distinguish SSM, Secrets Manager and customer-managed KMS keys. |
| Fable N10 | addressed | Confirmed facts retained; `ROLLBACK_SUCCEEDED` explicitly rejected. |

The staged ARN and revision-preservation mechanics agree with the [task-definition provider source](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/ecs/task_definition.go); validation reuse and issuance gating agree with [ACM documentation](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html) and the [validation provider source](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/acm/certificate_validation.go).

## Notes (non-blocking)

- **P2 — §§4.3, 4.11:** reconcile the unconditional “never delete any certificate-validation record” rule with rollback’s “delete every address except logs.” Newly created validation records also match the new certificate. Preserve them with manifest-bound `forget`, or explicitly narrow the rule to records needed by surviving/shared certificates.

- **P2 — §§4.8, 4.11:** give post-hand-over rollback an explicit `taskdef-off` variant. The current 8a gate permits creating `on` with the **on** value; it cannot literally register the promised **off** twin of a CI-deployed revision. Bind the fresh rollback manifest/evidence to the current live revision before worker mutations.

- **P2 — §§3.2, 4.9:** separate `new_host` zone validation from adoption discovery. A new hostname cannot satisfy the requirement for an existing CNAME to App Runner’s `DNSTarget`. Specify a gated creation of its traffic record to the ALB and its rollback ownership; certificate validation alone does not make the new URL resolve.

- **P2 — §4.3, step 2b:** “in no state” needs an ownership boundary. Absence from the two supplied states does not establish absence from another Terraform state or CloudFormation stack. Require owner confirmation/provenance before adoption; matching DNS values alone establish compatibility, not ownership.

- **P3 — §§4.9, 7:** waypoint plans leave one weight unchanged; explicitly permit its manifest-bound no-op. Extend the `--forgotten` validation in `src/ecsodus/cli.py` as well as `check/plan.py`, while retaining exact forget-set coverage checks.

- **P3 — §8:** ADR-0014/0015 document worker/job moto evidence, not dedicated moto architecture decisions; tighten that reference. Archived Copilot raw-source URLs were unavailable during this review; connector membership was verified against the checked-in fixture.
