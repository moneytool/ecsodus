## Vote
APPROVE WITH NOTES — r3 addresses both round-2 P1s with gates that only ever act on known literals (2a/2b, 8a/8b/8c), every round-2 note is folded in, and the new steps I checked against the provider source and AWS docs are safe; the one mechanical gap I found (the 7a `forget` can never appear in a refreshed plan) stalls the cutover in a safe state rather than endangering traffic, so it is a P2 build fix, not a blocker.

## Round-2 items status
| Item | Status | Note |
|---|---|---|
| Astra P1-1 (cert collision detected before cert exists) | addressed | §4.3 two-stage: read-only predictor, then gated `cert-request` (2a) creating only `aws_acm_certificate`, `cert-requested.json`, `generate --stage rebuild` emits literals; `allow_overwrite = false` gated (provider sends `CREATE` unless `allow_overwrite` or `!IsNewResource()`, https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/route53/record.go); ACM reuse per FQDN confirmed ("request additional ACM certificates for your FQDN for as long as the CNAME record remains in place", https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html) |
| Astra P1-2 (worker-on vs unknown task_definition) | addressed | §4.8 #8a–8c: `on` revision is its own address created and verified first; 8c updates `task_definition` literal→literal; `skip_destroy = true` keeps both revisions ACTIVE for `--rollback`; 8a before 8b so App Runner is untouched on failure |
| Astra P2 (connector carries both SGs) / Fable P2 | addressed | §3.1, §3.2, §4.3, §4.4, §4.5; live `DescribeVpcConnector.SecurityGroups`, `env_sg: join | omit`; fixture lines 377–379 confirm both SGs |
| Astra P2 (IGW + public IP path) | addressed | §4.5 second route path |
| Astra P2 (no-custom-domain branch) | addressed | §4.1 check 3, §4.8 #1, §4.9 "No custom domain", §4.11; see P2 note on `new_host` |
| Astra P2 (rollback after hand-over) | addressed | §4.11 row: re-freeze, refresh, restore literal `task_definition`, off-twin via 8a gate |
| Astra P3 (pin provider for UPSERT/INSYNC) | addressed | §4.9, §7, §8 offline assertion at pinned version |
| Astra/Opus/Fable P3 (ADR-0016) | addressed | §14 |
| Opus P2 (validation compare too early) | addressed | as Astra P1-1 |
| Opus P2 / Fable P2 (`forget` in import phase) | addressed | §4.9 step 5, §7: import phase extended; split rejected with reason. `plan.py:74,103` confirm today's restriction. See P2 note on refresh |
| Opus P2 (rollback waypoint) | addressed | §4.9 manifest lists rollback path per pair; direct (0,100)→(100,0) fails |
| Opus P2 (drop UNCONFIRMED UPSERT/INSYNC) | addressed | §4.9, §15 |
| Opus P3 (CloudTrail limits) | addressed | §5.2 item 1 |
| Opus P3 (build ordering) | addressed | §4.3 `depends_on`, grace period, circuit breaker |
| Opus P3 (log group on rollback) | addressed | §4.11 `infra-rebuild-rollback/` with `removed { destroy = false }` |
| Opus P3 (which root for `idle_timeout`) | addressed | §4.2, §4.7 `prepare-alb` |
| Fable P3 (health-check defaults) | addressed | §3.3; provider docs confirm TCP/5/2/1/5 |
| Fable P3 (`MaxCapacity = 0`) | addressed | §4.3 UNCONFIRMED, §8 stand-in; API doc still only documents `MinCapacity` 0 for ECS (https://docs.aws.amazon.com/autoscaling/application/APIReference/API_RegisterScalableTarget.html) |
| Fable P3 (sync deploy vs state==live) | addressed | §4.1 check 4 |
| Fable P3 (execution role SSM/KMS) | addressed | §4.3, §4.4 |
| Fable P3 (`ROLLBACK_SUCCEEDED`) | addressed | §4.1, §4.8 #8b, §4.10 |

## Blocking issues (only if REJECT)
None.

## Notes (non-blocking)
- **P2 — §4.9 step 5 and §4.11 "Weighted pair at (100, 0)": the `removed` block will produce no `forget` action, so a gate that requires one cannot pass.** After the batch, the simple record's refresh calls `findResourceRecordSetByFourPartKey` whose filter requires `recordSetID == SetIdentifier`; `""` ≠ `"apprunner"`, so the record is not found and the Read does `d.SetId("")` (https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/route53/record.go). Terraform's `planForget` then returns `NoOp` when the prior object is null (https://raw.githubusercontent.com/hashicorp/terraform/main/internal/terraform/node_resource_abstract_instance.go). The same holds for the two weighted records in the reverse. Consequence: `check --phase import --forgotten …` fails with "does not forget it", the runbook forbids any M5a apply until it passes, and 7b (an M5a-root plan) is stuck at (100, 0): safe, all traffic on App Runner, DNS revert batch still available. Edit: the extended import gate accepts, for exactly the manifest-named addresses, either `forget` or a `no-op` with null before/after together with a `resource_drift` delete entry, and asserts the address is absent from state after apply (`check --state`); keep the `removed` block for the `-refresh=false` case. Add it to the §8 must-fail/must-pass list.
- **P2 — §4.9 "No custom domain" / `new_host`: the record for `new_host` is never generated.** §4.3 and §4.8 #3 create a certificate and listener for `new_host` but no `aws_route53_record` pointing it at the ALB, so "give clients the new URL" has no URL. Edit: `infra-rebuild` creates an alias A (or CNAME) for `new_host` in step 3 with `allow_overwrite = false`, gated on name/type/target; `pre-create` requires no record of any type at that name; and reword "a zone that passes the §3.2 zone rules" since the §3.2 rule "holding a CNAME to `DNSTarget`" cannot apply here (exact-name, public, delegated, same account is the applicable subset).
- **P3 — §4.3 step 2b (adopt an unowned matching record).** "In no state" means in neither ecsodus state; the record may be owned by another IaC in the account (the App Runner case is already in the M5a state via `CertificateValidationRecords`). The import is harmless (`prevent_destroy`, M5c forgets it) but the report should say ownership is unknown and that the alternative is referencing the literal FQDN without importing.
- **P3 — §4.3 "Certificate", step 3.** `aws_acm_certificate_validation` takes literal `validation_record_fqdns`, so there is no implicit edge to the created validation record; add `depends_on` on it (the resource otherwise polls in parallel until ISSUED, create timeout 75 min, https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/acm_certificate_validation.html.markdown).
- **P3 — §4.8 #3 wording.** After 2a the certificate (and after 2b, the M5a record) appear in the `rebuild` plan as `no-op`; say the gate allows no-ops of exactly those addresses, since the preamble says "exactly its addresses".
- **P3 — §4.8 #8a.** Compare `container_definitions` after parsing the JSON (the provider normalizes it); a string compare of `off` vs `on` can fail spuriously.
- **P3 — §3.2 drop an UNCONFIRMED.** `aws_apprunner_vpc_connector` has `ForceNew: true` on `security_groups`, `subnets`, `vpc_connector_name` and a tags-only Update (https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/apprunner/vpc_connector.go), so any mismatch plans a replace; `check` rejects it as stated.
- **P3 — §3.5 `ignore_changes` path.** `image_identifier` sits directly under `image_repository` in the provider schema, so `source_configuration[0].image_repository[0].image_identifier` is correct; `auto_deployments_enabled` defaults to `true` as §3.3 says; only `service_name` and `encryption_configuration` are ForceNew, so `worker-off` is in place (https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/apprunner_service.html.markdown).
- **P3 — §4.9 recovery vs §4.11.** "the old simple-record block is never applied again" is contradicted by the rollback, which re-adds and imports it; say "never applied again unless rolling back".
- **P3 — checked, no change:** `TERRAFORM_CONSTRAINT = "~> 1.10"` (`src/ecsodus/emit/terraform.py:25`) supports `removed` blocks; `handoff_stacks` exists in the manifest (`terraform.py:208`, `cli.py:228`); `docs/adr/` on this checkout ends at 0015 and `build-hatchling` exists as a branch; `aws_ecs_service.task_definition` accepts a full revision ARN and the provider keeps the ARN form in state when configured as one.
