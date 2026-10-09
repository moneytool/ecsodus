---
title: Custom domains, offline gap analysis (issue #6)
description: >-
  What ecsodus does with every object a custom-domain Copilot app creates (hosted zones,
  delegation records, the ACM certificate, validation CNAMEs, alias records), what a retained
  teardown leaves behind, the gaps found offline and fixed, and what only a real AWS run can
  settle.
---

# Custom domains: offline gap analysis (issue #6)

*Offline only. Sources: `docs/knowledge/copilot-stacks.md`, `docs/knowledge/copilot-custom-resources.md`,
the Copilot renders under `tests/fixtures/copilot/`, the ecsodus code, and local experiments with
Terraform (AWS provider 6.68.0) against moto. No AWS account was used.*

PLAN §6 question 4 ("Does the shared ACM validation CNAME survive?") was not covered by the
2026-09-30 and 2026-10-07 runs. This page traces everything a custom domain adds, says what
ecsodus does with each object, and lists what the real run
([runbook draft](custom-domain-runbook-draft.md)) must measure.

## What a custom domain creates

`copilot app init <app> --domain <domain>` needs a public Route 53 hosted zone for `<domain>` in
the account (Copilot stores its ID as `domainHostedZoneID`). That zone is the customer's, not
Copilot's. Corrections to the issue's working assumptions, from the knowledge base and the
renders:

- The NS delegation of `<app>.<domain>` in the root zone is **not** out of band. The app stack
  owns it as `AppDomainDelegationRecordSet` (`AWS::Route53::RecordSet`, TTL 900, values
  `!GetAtt AppHostedZone.NameServers`).
- The NS delegation of `<env>.<app>.<domain>` in the **app** zone is out of band: the env stack's
  `DelegateDNSAction` (`dns-delegation.js`) writes it through the app's `DNSDelegationRole`.
- The certificate (`HTTPSCert`, `dns-cert-validator.js`) covers `<env>.<app>.<domain>`,
  `*.<env>.<app>.<domain>` **and every alias** in the env's `Aliases` parameter that falls in the
  env, app or root zone. Its validation CNAMEs go to the zone each name belongs to, so an alias in
  the root zone puts a CNAME into the customer's zone.
- Alias A records: an alias **without** `hosted_zone` gets its A record from the env's
  `CustomDomainAction` (`custom-domain.js`, out of band, in the env, app or root zone). An alias
  **with** `hosted_zone`, and the default `<svc>.<env>.<app>.<domain>` of an HTTPS service with no
  alias, are CloudFormation-owned `AWS::Route53::RecordSetGroup` resources (`LoadBalancerDNSAlias*`)
  in the workload stack.

## Object by object

Fates are from `build_plan`. "Teardown" assumes the retain patch: every resource, including every
`Custom::*` handle, has `DeletionPolicy: Retain`, so no Delete handler runs. That is confirmed on
AWS for the env-controller and rule-priority handlers (2026-09-30, 2026-10-07); it is CloudFormation
behaviour, not handler-specific, so the same is expected for the three DNS handlers, and the real
run measures it.

| # | Object | Created by | Discovered how | Fate | Terraform (import id) | Teardown | Status |
|---|---|---|---|---|---|---|---|
| 1 | App zone `<app>.<domain>` | app stack `AppHostedZone` | stack resource; live `GetHostedZone`, records, **tags** | import | `aws_route53_zone` (zone id), `prevent_destroy` | retained | OK. Tags were assumed from stack tags; now read live (fix 4) |
| 2 | NS `<app>.<domain>` in the root zone | app stack `AppDomainDelegationRecordSet` | stack resource; values = app zone's live `NameServers` | import | `aws_route53_record` (`<root zone>_<app>.<domain>_NS`) | retained | OK, one risk: R1 (trailing dots) |
| 3 | `<app>-DNSDelegationRole` | app stack | stack resource | import | `aws_iam_role` (name) | retained | OK |
| 4 | Root zone `<domain>` | customer | not inventoried | none | none | untouched | Correct: not a Copilot resource |
| 5 | Env zone `<env>.<app>.<domain>` | env stack `EnvironmentHostedZone` | stack resource; live read incl. tags | import | `aws_route53_zone` (zone id), `prevent_destroy` | retained | OK (fix 4) |
| 6 | NS `<env>.<app>.<domain>` in the app zone | `DelegateDNSAction` (out of band) | live records of the imported app zone | import (app stack) | `aws_route53_record` (`<app zone>_<env>.<app>.<domain>_NS`), live values verbatim | handler not invoked | OK |
| 7 | ACM certificate | `HTTPSCert` (out of band) | `ListCertificates` + `copilot-application` tag; `DescribeCertificate` | import (env stack) | `aws_acm_certificate` (ARN), `prevent_destroy` | handler not invoked | **Gap, fixed (1)**: tags were not written, so the import planned an update |
| 8 | Validation CNAME for the env name and its wildcard (one shared record) | `HTTPSCert` | live records of the env zone | import (env stack) | `aws_route53_record` (`<env zone>__<hash>.<env>.<app>.<domain>_CNAME`) | handler not invoked | OK |
| 9 | Validation CNAME of an env-zone or app-zone alias | `HTTPSCert` | live records of that imported zone | import | `aws_route53_record` | handler not invoked | OK |
| 10 | Validation CNAME of a root-zone alias (`www.<domain>`) | `HTTPSCert` (through `DNSDelegationRole`) | **not read** (zone not inventoried) | was: no fate at all | none | handler not invoked: survives | **Gap, fixed (3)**: now an `external-reference` row in the report |
| 11 | A alias in the env or app zone | `CustomDomainAction` (out of band) | live records of that imported zone | import | `aws_route53_record` (`<zone>_<alias>_A`) with the live `alias {}` | handler not invoked | OK |
| 12 | A alias in the root zone | `CustomDomainAction` | **not read** | was: no fate | none | survives | **Gap, fixed (3)**: `external-reference` |
| 13 | `LoadBalancerDNSAlias` A record in the env zone (HTTPS service without alias) | workload stack `RecordSetGroup` | stack resource **and** env zone records | import | `aws_route53_record` (`<env zone>_<svc>.<env>.<app>.<domain>_A`) | retained | **Gap, fixed (2)**: also imported a second time as an out-of-band record |
| 14 | `HTTPSCert`, `DelegateDNSAction`, `CustomDomainAction` handles | env stack | stack resources | manual-cleanup, retain-patched | none | Delete not invoked (to measure) | **Gap, fixed (5)**: the runbook told the operator to delete `HTTPSCert`'s physical ID, which is the certificate ARN |
| 15 | `CertificateValidationFunction`, `DNSDelegationFunction`, `CustomDomainFunction` | env stack | stack resources | manual-cleanup | none | retained, then deleted by hand | OK |
| 16 | `CustomResourceRole` (the three Lambdas' role) | env stack | stack resource | import | `aws_iam_role` | retained | Works; unused once the Lambdas are deleted (D4) |
| 17 | HTTPS listener (certificate ARN), host-header rules, HTTP-to-HTTPS redirect rules | env, workload stacks | stack resources + live | import | `aws_lb_listener`, `aws_lb_listener_rule` | retained | OK (covered by the full hand-off test) |
| 18 | `EnvControllerAction` with `Aliases` | workload stack | stack resource | manual-cleanup, retain-patched | none | Delete not invoked | OK. Its Delete would remove the alias from `Aliases`, which reissues `HTTPSCert` and fires `CustomDomainAction`'s Delete; retain stops it at the root |

**Would anything be deleted at teardown?** No, provided the retain patch holds for the three DNS
handles (rows 6 to 12 depend on it). Every CloudFormation-owned DNS object (rows 1, 2, 5, 13) is
retained by its own `DeletionPolicy`.

**Would anything be left unmanaged?** Only Copilot's records in the customer's root zone (rows 10
and 12). They survive, and they are now listed in REPORT.md under "External references". Before
this change they had no row at all. Also, the validation CNAMEs must stay for ACM's managed renewal;
they are now Terraform resources without `prevent_destroy` (D5).

## Gaps found and fixed

All five are offline fixes with tests. `uv run pytest -q`: 333 passed (325 before, 8 new).
`ruff check`, `ruff format --check` and `mypy src` are clean.

1. **The certificate's tags.** `plan_certificate` wrote no `tags`. A local `terraform plan` against
   moto, importing a certificate tagged like Copilot's, gave `1 to import, 1 to change`
   (`tags = {copilot-application, copilot-environment} -> null`). The import gate would refuse it.
   Inventory now records the certificate's tags (without `aws:` ones) and the mapper writes them;
   the same plan with tags is a pure import. An `inventory.json` from an older ecsodus has no
   certificate tags: the certificate is then **blocked** with "re-run ecsodus inventory" (exact
   or block, no guess). (`sources/copilot.py`, `mappers/tf_oob.py`)
2. **A RecordSetGroup's record imported twice.** The out-of-band pass skipped records owned by an
   `AWS::Route53::RecordSet`, but not those owned by an `AWS::Route53::RecordSetGroup`. Copilot's
   `LoadBalancerDNSAlias` is a group in the env zone, so its record was planned once from the
   workload stack and again as an out-of-band record of the env zone. Ownership now covers group
   records (zone from the record or the group), and only the identifying fields are resolved, so
   an alias target that cannot be resolved offline no longer hides ownership.
   (`mappers/fates.py`, `_record_key`)
3. **Records in a zone ecsodus does not read.** Validation CNAMEs (from the certificate's
   `DomainValidationOptions`) and alias records (from the env's `Aliases` parameter, when
   `CustomDomainAction` exists) that no imported zone and no stack record covers become
   `external-reference` rows naming the record, its writer, and that it must be kept. They do not
   block the hand-off: nothing deletes them. (`mappers/fates.py`, `_unmanaged_dns`)
4. **Hosted zone tags.** The zone mapper fell back to stack tags merged with `HostedZoneTags`
   because the live read had no tags. Whether CloudFormation copies stack tags onto a hosted zone
   was never checked (the same class of defect as the ELB and scalable-target tags found on AWS).
   The zone reader now calls `route53:ListTagsForResource`. (`sources/live.py`)
5. **The leftover list named custom-resource handles.** Step 6 of RUNBOOK.md listed every
   manual-cleanup row with its physical ID for deletion, including `Custom::*` handles. For
   `HTTPSCert` that ID is the certificate ARN, now owned by Terraform and in use by the HTTPS
   listener; for `DelegateDNSAction` it is the env subdomain. Handles are not AWS objects and
   vanish with their stack. They are no longer in the deletion list, and REPORT.md lists them
   separately with that warning. (`emit/runbook.py`, `emit/report.py`; `fixture-app-report.md`
   regenerated for this reason only.)

The full hand-off synthetic app now has a realistic certificate (tags, one validation option per
name, and a validation CNAME for its root-zone alias `example.com`), so it covers fixes 1 and 3.
The import snapshots are unchanged.

## Risks only a real run can settle

- **R1. NS record values and trailing dots.** `AppDomainDelegationRecordSet` is mapped with the app
  zone's `GetHostedZone` name servers, which have no trailing dot. CloudFormation submits those
  same strings, and Route 53 is expected to return them as stored. The provider does not normalise
  record values: against moto, a config without dots and a stored record with dots planned an
  update. If Route 53 returns dotted values, the dry-plan gate refuses the import, and the fix is
  to read the record live (D2). The out-of-band NS record (row 6) uses live values and is exact.
- **R2. Retain on the DNS handles.** Expected to suppress `CertificateValidationFunction`,
  `DNSDelegationFunction` and `CustomDomainFunction` exactly as it did the env-controller. Measured
  by invocation counts before and after teardown.
- **R3. Hosted zone tags and comments** are now read live; the first real import of both zones
  confirms the mapping (`comment` is always written, since the provider's default is "Managed by
  Terraform").
- **R4. Stale certificates.** Changing a service's aliases makes Copilot request a new certificate
  and delete the old one. If that Delete failed, a second tagged certificate exists and is imported
  too. The run counts tagged certificates before generating.
- **R5. Multi-account DNS** (app zone in another account) stays blocked with the rest of
  multi-account support.

## Decisions for the maintainer

- **D1. Root-zone records: report or import?** Implemented: report them as external references.
  Alternative: inventory reads the root zone (`AppDomainHostedZoneID`, a parameter of the app
  stack) and imports exactly the records Copilot wrote there (names from the certificate's
  validation options and the env's `Aliases`) as `aws_route53_record`s in a zone Terraform does not
  manage. That widens what ecsodus reads and manages into a customer zone.
- **D2. Read `AppDomainDelegationRecordSet` live.** Same root-zone read as D1. It would make the NS
  values exact and close R1 before the real run rather than through the gate.
- **D3. `docs/examples/copilot-lbws-aurora/` is stale** (66 imports, from before Worker Services
  and Scheduled Jobs) and still shows the hazardous leftover line
  `Custom::CertificateValidationFunction arn:aws:acm:...` (fix 5). Regenerating it changes its scope
  to the current synthetic app.
- **D4. `CustomResourceRole`** is imported, but its only users are the three Lambdas deleted by
  hand. It could become manual-cleanup with them.
- **D5. `prevent_destroy` on validation CNAMEs.** Deleting one stops ACM renewal of a certificate
  in use. Marking out-of-band validation records stateful would protect them like the certificate.
- **D6. Runbook scope banner.** After a successful real run, drop "custom domains and ACM
  certificates" from `VERIFIED_SCOPE` in `emit/runbook.py`.

## Not in scope

NLB custom domains (`wkld-cert-validator.js`, `wkld-custom-domain.js`), Static Site, Request-Driven
Web Service and CloudFront (`cert-replicator.js`) stay blocked, as before.
