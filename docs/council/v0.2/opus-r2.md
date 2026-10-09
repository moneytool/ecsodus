## Vote
APPROVE WITH NOTES: r2 addresses all 20 round-1 P1s, and the new mechanics I checked hold up against the provider source and AWS docs. The remaining items are P2/P3 build details, and none of them can drop traffic or run work twice.

## Round-1 items status
| Item | Status | Note |
|---|---|---|
| Astra 1 (Terraform-owned ≠ Copilot gone) | addressed | `verify-handoff` §4.1; inventory re-checks it with a 24 h freshness limit |
| Astra 2 (desired_count 0 not an interlock; Express) | addressed | §4.3 / §4.8 #3–5 scalable target at 0/0, then `start`; Express fails closed (§4.6) |
| Astra 3 (background double-run, rollback) | addressed | §4.10: App Runner off, deployment done, idle check or lock, then ECS on; reverse order on rollback; boot migrations blocked |
| Astra 4 (missing transitions, vacuous stage 0) | addressed | §4.8 lists every transition; `ready` requires counts > 0 |
| Astra 5 (unsafe DNS weight states) | addressed | §4.9 pair rules check the intermediate states too |
| Astra 6 (retire evidence) | addressed | §5.2 / §5.4 bound evidence that the gate consumes |
| Astra 7 (shared resources in retire set) | addressed | §5.3 deletes only three resources; the rest are forgotten or never touched |
| Astra 8 (tag ≠ deployed digest) | addressed | §4.1 accepts a digest or a synchronized deployment |
| Astra 9 (networking/authz) | addressed | §4.3 / §4.5 |
| Astra 10 (shared ALB vs create-only gate) | addressed | §4.7 dedicated ALB by default; shared is opt-in with a bounded `prepare` |
| Astra 11 (flag can't validate retirement) | addressed | §5.1 `generate --retire` refuses, with no flag to unlock it |
| Opus 1 (scalable target overrides 0) | addressed | §4.8 #3–5; live task definition read at #4 / #6. Provider updates min/max in place via `RegisterScalableTarget` ([target.go](https://github.com/hashicorp/terraform-provider-aws/blob/main/internal/service/appautoscaling/target.go)) |
| Opus 2 (TTL + 24 h unverifiable) | addressed | §5.2 CloudTrail + `GetChange`; fails closed |
| Opus 3 (validation-record collision; rollback gate) | addressed | §4.3, §4.11, §5.3; own root and state. See the P2 note on when the comparison can run |
| Opus 4 (retirement unverified / eligibility) | addressed | §4.12, §5.1, sentinel service in test accounts |
| Fable 1 (scaling bypasses worker gate) | addressed | as Opus 1 |
| Fable 2 (`Requests` service-wide) | addressed | §5.2 uses `2xxStatusResponses` + threshold + attested host sample |
| Fable 3 (ACM CNAME collision) | addressed | as Opus 3 |
| Fable 4 (cutover gate) | addressed | §4.9 |
| Fable 5 (`enable_www_subdomain`) | addressed | §3.3, §4.4 |

## Blocking issues (only if REJECT)
None.

## Notes (non-blocking)
- **P2, §4.3 validation-record comparison happens too early.** `generate` and `pre-create` cannot read the new certificate's `domain_validation_options`, because those exist only after `RequestCertificate`, at apply time.
  - **Fix:** as the read-only predictor, use `acm:ListCertificates` / `DescribeCertificate` on any certificate for the FQDN already in the account. ACM reuses one validation CNAME per FQDN per account, so its record is the one the new certificate will get.
  - Emit `allow_overwrite = false` explicitly and gate it. The provider then sends `CREATE`, which fails safely on an existing record. With `allow_overwrite = true` it sends `UPSERT` ([record.go](https://github.com/hashicorp/terraform-provider-aws/blob/main/internal/service/route53/record.go)).
- **P2, §4.9 7a step 5 / §7 `--forgotten`.** Step 5 puts the `removed` block and the imports in one plan under `check --phase import`. Today `src/ecsodus/check/plan.py` accepts `forget` only in the steady phase and only for `aws_ecs_task_definition`.
  - **Fix:** either extend the import phase to accept a `forget` of exactly the manifest's record addresses, or split it into an import plan followed by a steady plan with `--forgotten`. State which.
- **P2, §4.9 rollback waypoint.** Rollback from (0, 100) goes through (100, 100), but that pair is not "an earlier" manifest pair, so the `--rollback` rule as written rejects it. List the rollback waypoints in the manifest.
- **P2, drop two UNCONFIRMED tags (§4.9).** The provider source settles both:
  - For an existing record, the update goes through `UPSERT` (`DELETE` + `CREATE` in one transactional batch only when the type or `set_identifier` changes).
  - Create and update both call `waitChangeInsync` ([record.go](https://github.com/hashicorp/terraform-provider-aws/blob/main/internal/service/route53/record.go)).
  - Each weight step and the 7c switch is therefore atomic per record and INSYNC-waited. Still pin the provider version.
- **P3, §5.2 CloudTrail lookup limits.** `LookupEvents` takes one lookup attribute and allows 2 requests per second per account per region ([API](https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_LookupEvents.html)).
  - Filter on `EventName=ChangeResourceRecordSets` and match the zone ID and set identifier client-side from `CloudTrailEvent`.
  - Parse `DELETE`+`CREATE` pairs as well as `UPSERT`.
  - `GetChange` documents no retention period and can return `NoSuchChange`; treat that as fail-closed.
- **P3, §4.3 build ordering.** The ECS service with a `load_balancer` block, and an `ALBRequestCountPerTarget` policy, both need the target group attached to a listener first, so add `depends_on` on the listener and listener rule. Set `health_check_grace_period_seconds` and decide on the deployment circuit breaker.
- **P3, §4.11.** The `rollback-rebuild` destroy deletes the new log group. Consider `removed { destroy = false }` instead, to keep logs for forensics.
- **P3, §4.7.** The shared env ALB may live in the v0.1 env root, not the M5a root. Name the root that the `idle_timeout` `prepare` edits.
- **P3, checked against the repo.**
  - The RDWS fixture has exactly the 14 resources listed in §3.1.
  - The `TERRAFORM_CONSTRAINT = "~> 1.10"` constraint supports `removed` blocks.
  - ADR-0016 (hatchling) exists on `origin/build-hatchling`, so starting M5 at ADR-0017 is correct.
