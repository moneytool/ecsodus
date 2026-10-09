## Vote
APPROVE WITH NOTES: r3 addresses both round-2 P1s using the staged-literal approach (cert-request then evidence then `generate --stage`; `on` revision registered before App Runner workers go off), and it also handles every round-2 note. What r3 introduced has one internal contradiction (rollback deleting a validation record) and a few gaps in the build spec. All of them are P2/P3, and none can drop traffic or run work twice.

## Round-2 items status
| Item | Status | Note |
|---|---|---|
| Astra P1-1 (cert collision before cert exists) | addressed | §4.3 predictor plus gated 2a, `cert-requested.json`, literal outcomes, `allow_overwrite = false`, listener on `aws_acm_certificate_validation`. Provider create waits for DVOs (`waitCertificateDomainValidationsAvailable`, 5 min) ([certificate.go](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/acm/certificate.go)) |
| Astra P1-2 (worker-on vs unknown ARN) | addressed | §4.8 8a→8b→8c: 8c gates on a literal ARN, and an unknown value fails. `skip_destroy` is read from state in Delete (`d.GetOk(skip_destroy)` then return), so revisions stay ACTIVE through the rollback destroy ([task_definition.go](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/ecs/task_definition.go)) |
| Astra P2 connector SGs | addressed | §3.1/§3.2/§4.3 use live membership and `env_sg: join\|omit`. Fixture and `vpc-connector.yml` agree |
| Astra P2 public-subnet path | addressed | §4.5 adds IGW plus `assign_public_ip` as a third path |
| Astra P2 no-custom-domain conditionals | addressed | §4.1 #3, §4.9; `new_host` needs refining (note) |
| Astra P2 rollback after hand-over | addressed | §4.11 re-freezes, refreshes, restores literal `task_definition`, and handles the off twin of a CI revision |
| Astra P3 provider UPSERT/INSYNC | addressed | §4.9 states it; version pinned; offline assertion |
| Astra P3 ADR-0016 | addressed | §14; `docs/adr/` on main still ends at 0015 |
| Opus P2 validation compare too early | addressed | as Astra P1-1; the predictor is advisory only |
| Opus P2 import-phase `forget` | addressed | §4.9/§7 accept exact manifest addresses only; `plan.py:77,103` confirms today's limits, so this is an explicit build item |
| Opus P2 rollback waypoint (100,100) | addressed | §4.9 lists the rollback path per pair; §8 has a negative test |
| Opus P2 drop UNCONFIRMED tags | addressed | §4.9, §15 |
| Opus P3 CloudTrail limits / `GetChange` | addressed | §5.2 |
| Opus P3 build ordering, grace, breaker | addressed | §4.3; `rollback = false` keeps state honest |
| Opus P3 log group on rollback | addressed | §4.11 `infra-rebuild-rollback/` with `removed { destroy = false }` |
| Opus P3 shared-ALB root | addressed | §4.7 `prepare-alb`; path and lineage in the manifest |
| Opus P3 repo facts | addressed | no change needed |
| Fable P2 connector SG error | addressed | the §15 sentence was deleted |
| Fable P2 worker-on | addressed | Astra's approach chosen; `skip_destroy` adopted |
| Fable P2 import `forget` | addressed | as Opus |
| Fable P3 UPSERT wording / 7c | addressed | 7c now rejects a replace for identity reasons |
| Fable P3 health-check defaults | addressed | §3.3 |
| Fable P3 `MaxCapacity = 0` | addressed | UNCONFIRMED; moto and stand-in checks in §8/§9 |
| Fable P3 synced deploy vs state | addressed | §4.1 check 4 |
| Fable P3 execution role perms | addressed | §4.3/§4.4 |
| Fable P3 `ROLLBACK_SUCCEEDED` | addressed | §4.1, §4.8 8b, §4.10 |
| Fable P3 ADR numbering | addressed | §14 |

## Blocking issues (only if REJECT)
None.

## Notes (non-blocking)
- **P2: §4.11 contradicts §4.3/§5.3 on validation records.** `rollback-rebuild` deletes every `infra-rebuild` address, which includes the validation record created in step 3 ("absent" outcome). §4.3 says "no gate may ever delete a record that matches a validation option of any certificate in either state", and at rollback time the infra-rebuild certificate still matches it. The deletion is also unsafe on its own terms. ACM reuses that CNAME for any later certificate on the FQDN in the account, and deleting it stops renewal ([ACM DNS validation](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html): "as long as the CNAME record remains in place"; "by deleting the CNAME record"). **Edit:** in `infra-rebuild-rollback/`, forget the created validation record (`removed { destroy = false }`) like the log group, list it in the report, allow that `forget` in `check --phase rollback-rebuild`, and add a negative test for a rollback plan that deletes it.
- **P2: §4.9 "No custom domain" / `new_host`.**
  - The §3.2 zone rules include "holding a CNAME whose value is the service's `DNSTarget`", which a new host can never meet. Name the subset: exact-name, public, delegated, in-account, plus the CAA check, and no existing record at `new_host`.
  - Say who creates the `new_host` → ALB record. Preferably make it a gated create in `infra-rebuild` (alias A, `allow_overwrite = false`), with `ready` checking TLS and SNI for `new_host`.
  - Nothing about the rollback in this branch protects clients already given the new URL. Have `rolled-back` print ALB `RequestCount` since start and require an explicit operator answer.
- **P3: §4.3/§4.8 2a timing.** ACM moves a certificate to `VALIDATION_TIMED_OUT` if it is not validated within 72 h of issuing the CNAME (same ACM page). For the "absent" outcome, step 3 must apply within 72 h of 2a. `generate --stage rebuild` and `verify-cutover --step created` should check `PENDING_VALIDATION` and the certificate's age. The recovery path is rollback-rebuild then re-run 2a, because rebuild forbids a replace. State this in the runbook.
- **P3: §4.8 2a gate "no SANs".** The provider's CustomizeDiff adds `domain_name` to `subject_alternative_names` at plan time ("Mimic ACM's behavior", certificate.go). Gate `subject_alternative_names == [domain_name]`, not empty; otherwise every valid 2a plan fails.
- **P3: §4.12 step 5 order for 2b.** The 2b import block and manifest entry depend on `cert-requested.json`. Run `generate --stage rebuild` (or a dedicated stage) before 2b, not after.
- **P3: §4.2/§4.8 8a artifact.** Name the file that carries `aws_ecs_task_definition.on` for 8a, and when it is added to `infra-rebuild`. If it is present at step 3, the step-3 gate must reject it, which it does as "a create outside the manifest". Say so.
- **P3: §4.3 "present, same value, in no state" (2b).** This means "in neither ecsodus state". Another IaC owner may still hold the record. Importing it with `prevent_destroy` is safe, but the report should warn that a foreign deletion breaks renewal for both owners.
- **P3: §8.** Add an offline test that `infra-rebuild-rollback/`'s `removed` block for the log group plans cleanly when only the 2a certificate is in state.
