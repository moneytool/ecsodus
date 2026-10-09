## Vote

**REJECT** — Most round-1 findings are addressed, but two computed-value sequencing gaps still prevent the certificate and worker-transfer gates from executing as specified.

## Round-1 items status

| Item | Status | Note |
|---|---|---|
| Astra 1 | addressed | §4.1 proves completed hand-off and excludes surviving env workloads. |
| Astra 2 | addressed | Zero-capacity creation, separate start gate; Express blocked. |
| Astra 3 | partial | Transfer order fixed; worker-on gate remains unexecutable as written (B2). |
| Astra 4 | partial | Explicit transitions and positive readiness checks; computed-value gaps remain (B1–B2). |
| Astra 5 | addressed | Exact weight pairs and safe intermediate states required. |
| Astra 6 | addressed | Bound evidence, history, pagination and missing-data rules; retirement unavailable pending verification. |
| Astra 7 | addressed | Ancillary and shared resources excluded from deletion. |
| Astra 8 | addressed | Digest required or synchronized deployment. |
| Astra 9 | addressed | Task ingress, connectivity checks, role reuse and limited-policy reporting added. |
| Astra 10 | addressed | Dedicated ALB default; bounded shared-ALB preparation. |
| Astra 11 | addressed | Untested retirement cannot be unlocked by acknowledgement. |
| Opus 1 | addressed | Scaling starts at 0/0; live counts and task definition checked. |
| Opus 2 | addressed | CloudTrail and INSYNC evidence establish timing. |
| Opus 3 | partial | Retirement preservation and rollback root fixed; certificate collision comparison occurs too early (B1). |
| Opus 4 | addressed | Separate retirement artifact, real-run requirement and sentinel service. |
| Fable 1 | addressed | Separate gated scaling activation. |
| Fable 2 | addressed | Residual-traffic wording, 2xx evidence and attested host sample. |
| Fable 3 | partial | Correct preservation policy; collision detection lacks an executable creation sequence (B1). |
| Fable 4 | addressed | Identity, TTL, direction and intermediate-weight checks specified. |
| Fable 5 | addressed | Live `EnableWWWSubdomain` read and explicit migration limitation. |

## Blocking issues (only if REJECT)

1. **P1 — §§4.3, 4.8, 4.12: certificate collision detection precedes certificate creation.** `generate` and `pre-create` cannot compare the new certificate’s validation record names and values: `domain_validation_options` is computed, and the certificate is created later in `rebuild`. Consequently, the exact manifest cannot yet decide which records to create versus reuse. **Edit:** introduce a gated certificate-request phase, then read its validation options, compare against live DNS and the imported records, and emit the remaining exact manifest. Create only absent records; reference matching owned records; reject conflicting values. Require issuance before listener activation. [Provider certificate schema](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/acm/certificate.go), [ACM validation reuse](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html).

2. **P1 — §§4.8–4.11: worker-on conflicts with the blanket rejection of unknown gated values.** Replacing the task definition makes its ARN/revision—and therefore the service’s new `task_definition` value—unknown until apply. Step 9 cannot satisfy an exact expected after-value under the stated rule, potentially stopping the transfer after App Runner workers have been disabled. **Edit:** register and verify the new revision in a separate gated phase before disabling App Runner workers, then gate service activation against its known literal ARN. Define the corresponding reverse phases for rollback. Alternatively, specify a narrowly validated dependency exception with equivalent enforcement; do not simply accept arbitrary unknown ARNs. [Provider task-definition schema](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/ecs/task_definition.go).

## Notes (non-blocking)

- **P2 — §§3.1, 4.3:** the checked-in RDWS fixture’s connector includes both `ServiceSecurityGroup` and `EnvironmentSecurityGroup`, contrary to “only `ServiceSecurityGroup`.” Preserve actual connector membership during adoption; distinguish the intended ECS membership explicitly.
- **P2 — §4.5:** add the supported public-subnet path: IGW route plus assigned public IP. The current NAT-or-endpoints predicate rejects a valid §4.4 decision.
- **P2 — §§4.1, 4.11:** make association/CNAME ownership and rollback DNS checks conditional for the explicitly supported no-custom-domain branch.
- **P2 — §§4.11–4.12:** rollback after hand-over must re-freeze deploys, refresh live configuration and restore Terraform deployment ownership before worker changes.
- **P3 — §4.9:** current provider source confirms UPSERT and INSYNC waits; verify these at the pinned version. [Route 53 provider implementation](https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/internal/service/route53/record.go).
- **P3 — §14:** ADR-0016 is absent from this checkout; reconcile the claimed reservation during the build.
