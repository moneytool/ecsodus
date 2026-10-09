## Verdict

**REVISE** — Adopt-first is the right sequence, but the rebuild and retirement gates do not yet enforce the safety guarantees claimed.

## Blocking issues (P0/P1)

1. **P1 — §§2.4, 4.1: “Terraform-owned” is not proof that Copilot is gone.** The existing manifest records intended handoff, not completed teardown; partial migrations can leave env-controller resources active. **Edit:** require a completion record plus fresh checks of Terraform resource identity, RDWS stack removal, and shared-stack ownership. Block rebuild when surviving Copilot controllers can mutate infrastructure it uses.

2. **P1 — §§4.2, 4.6: `desired_count = 0` is not a sufficient startup interlock.** The same apply creates scaling with App Runner’s positive minimum; scaling can change desired count. Express also lacks a demonstrated zero-task creation contract. **Edit:** defer scaling registration/policies until the start gate, verify zero running/pending tasks, and exclude Express until its startup interlock is demonstrated. [ECS scaling behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-auto-scaling.html).

3. **P1 — §§4.6–4.9: background-work transfer can double-run, and rollback is incomplete.** The proposed order enables ECS before confirming App Runner is disabled. An App Runner configuration deployment can also rerun boot migrations. DNS rollback does not restore background-work ownership. **Edit:** disable and drain the old worker first, verify deployment completion, then enable ECS; reverse that sequence on rollback. Require application-specific evidence or a distributed ownership lock, and block unsupported boot migrations.

4. **P1 — §§4.8–4.9: the gates omit necessary transitions.** Starting tasks, enabling scaling, changing background-work configuration, lowering TTL, and simple-switch cutover have no matching phase. Stage 0 requires healthy targets and a listener certificate before their creation; `healthy ≥ desired` passes vacuously at zero. **Edit:** define explicit pre-create, start, ready, cutover, worker-transfer, rollback, and retire transitions with exact allowed changes. Ready must require a positive task count, completed deployment, correct routing, and successful TLS/application probes.

5. **P1 — §§4.5, 4.8: “only weight changes” permits unsafe DNS states.** It permits both weights becoming zero, which routes equally to both destinations. Separate Terraform record updates also need an explicit ordering/atomicity policy. **Edit:** validate exact before/after weight pairs, both physical record identities and targets, TTL, and permitted stage transitions; reject unknown values and incomplete plans. Either apply each pair atomically or prove safe intermediate states. Wait for `INSYNC`. [Weighted routing](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-values-weighted.html), [change-batch semantics](https://docs.aws.amazon.com/Route53/latest/APIReference/API_ChangeResourceRecordSets.html).

6. **P1 — §§4.8, 4.9: retirement evidence is underspecified and disconnected from the deletion gate.** Current DNS does not establish 24 hours continuously at zero weight. Missing metrics or `INSUFFICIENT_DATA` must not mean safe; an operator threshold knowingly permits residual traffic. **Edit:** bind fresh retirement evidence to service ARN, account/region, final DNS configuration, observation interval, and saved plan. Require `check --phase retire` to consume it. Specify metric dimensions, `Sum`, pagination, delayed-data handling, missing-data behavior, and history/reset rules. Add separate evidence rules for simple-switch and default-URL migrations.

7. **P1 — §§4.8–4.9: the retirement allowlist includes potentially shared resources.** Connectors can serve multiple App Runner services; access roles, instance roles, and validation CNAMEs can also be shared. “No other principal references it” is not an implementable account-wide proof. **Edit:** initially retire only the explicitly selected service and association; retain ancillary resources unless exclusive ownership is positively established. Deduplicate DNS resources and preserve every validation record used by a surviving certificate. Remove unconditional manual validation-CNAME deletion. [Connector sharing](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html), [ACM validation reuse](https://docs.aws.amazon.com/en_en/acm/latest/userguide/dns-validation.html).

8. **P1 — §4.3: resolving today’s mutable image tag does not prove identical deployed bits.** App Runner may still run an older digest. `DescribeService` exposes the configured identifier, not a demonstrated running digest. `ECR_PUBLIC` also requires a separate resolution path. **Edit:** require deployment provenance establishing the deployed digest, or an explicit synchronized deployment and verification; block unverifiable mutable tags.

9. **P1 — §§4.2–4.3: networking and authorization translation is incomplete.** Connector SGs govern outbound traffic, so reusing them does not establish ALB-to-task ingress. ECS image pulls, logs, and secret retrieval newly depend on task-subnet connectivity. Grants naming the old role may need to authorize both the new task and execution roles. **Edit:** generate narrowly scoped ALB ingress rules; verify routes, endpoints/NAT, DNS, and secret/KMS authorization before startup. Report closure-limited findings without claiming exhaustive external-policy discovery. [App Runner networking distinctions](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html).

10. **P1 — §4.2: shared-ALB support does not fit the emitted resources or create-only gate.** The certificate must be attached with a listener-certificate resource; existing timeout, WAF, SG, and routing settings may require updates forbidden by `rebuild`. Associating the source WAF ACL can alter protection for other services. **Edit:** use a dedicated ALB initially, or introduce an explicitly reviewed shared-ALB preparation phase with conflict checks and bounded changes.

11. **P1 — §§7–9: an acknowledgement flag cannot validate irreversible retirement.** Stubber and a second ALB cannot establish App Runner disassociation, metric, provider-delete, or ancillary-resource behavior. ADR-0012 followed real testing and retained explicit coverage limitations. **Edit:** keep untested retirement unavailable; release rebuild through cutover with operator-managed retirement. Require real App Runner lifecycle evidence before emitting automated retirement instructions, and distinguish read-only partner-plan validation from full adoption E2E.

## Other findings

- **P2 — §3.2:** the custom-domain import format is confirmed: `domain,service-arn`. Pin the tested provider version and remove this uncertainty. [Provider documentation](https://registry.terraform.io/providers/hashicorp/aws/6.42.0/docs/resources/apprunner_custom_domain_association).
- **P2 — §4.3:** listed App Runner CPU/memory combinations fit Fargate; replace the uncertainty with explicit normalized lookup tables. ALB healthy-threshold minimum 2 is confirmed. [App Runner configurations](https://docs.aws.amazon.com/apprunner/latest/dg/architecture.html), [Fargate combinations](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html), [ALB health checks](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html).
- **P2 — §§4.2–4.3:** ALB idle timeout and App Runner’s total request timeout are different semantics; 120 seconds is not behavioral equivalence. Apply the timeout decision to reused ALBs too.
- **P2 — §§3.2, 4.5:** DNS discovery must verify exact zone name, public/private status, delegation, account/provider, and live target. Do not copy the handler’s unchecked first-zone lookup.
- **P2 — §§4.5, 4.7:** document resumable recovery after DNS mutation but before state imports, including state backup, configuration replacement, weighted import identifiers, and protection against reapplying the old simple record.
- **P2 — §4.4:** the private-subnet/internal-ALB Express claim is supported, but its provisioning creates infrastructure outside the Terraform address manifest. Document that gate limitation and narrowly allow required data sources; today’s checker rejects all data sources. [Express resource ownership](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html).
- **P3 — §8:** creating an autoscaling configuration is not proof of service-creation eligibility. Treat only the actual service attempt, or authoritative eligibility confirmation, as decisive.

## Answers to the open questions

1. Use **0.3.0 / 0.4.0**; rename the document “App Runner roadmap” to avoid package-version ambiguity.
2. Keep standalone services **report-only** initially.
3. Require completed adoption first, with fresh ownership checks; no still-Copilot path.
4. Plain ECS + **dedicated ALB** initially; Express opt-in after its safety contract is tested.
5. Flat resources.
6. Reference shared/external configurations; import demonstrably migration-owned custom revisions in v0.2a. Never automatically retire them.
7. Block private-ingress rebuild initially.
8. Allow explicit tracing-loss acknowledgement, with the lost capability clearly reported.
9. Unknown from repository evidence; maintainer must identify an eligible account.
10. Use a disposable subdomain of a maintainer-controlled domain; the repository does not establish which.
11. Stop at validated cutover initially. Add optional retirement only after a separate ADR, complete gates, and real lifecycle testing.
12. Read metrics and alarms; fail closed on unavailable/ambiguous evidence and retain operator application-health judgement.
13. Require an explicit command list when `StartCommand` is set. Permit explicitly selected shell invocation; preserve image defaults when absent.

## Unconfirmed claims

- **Identical deployed digest (§4.3):** confirm through deployment provenance or a synchronized, verified deployment; current tag resolution is insufficient.
- **Zero-task Express creation (§§4.4, 4.6):** confirm with the pinned provider and real AWS, including scaling behavior.
- **App Runner amd64-only (§4.2):** confirm with authoritative architecture documentation and image-manifest validation.
- **Deleting the last service loses eligibility (§4.7):** obtain AWS confirmation; published guidance says existing customers can create new services, without defining this edge case. [Availability guidance](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html).
- **Absent `Requests` datapoints establish zero traffic (§4.8):** validate publication behavior on an idle real service; AWS documents the metric, not this inference. [App Runner metrics](https://docs.aws.amazon.com/apprunner/latest/dg/monitor-cw.html).
- **App Runner and new ACM validation records are disjoint (§§4.2, 4.8–4.9):** compare live name/value sets and surviving certificate consumers before deletion.
- **Private/tracing rendered shapes and import-only fidelity (§§3.1–3.2):** archived-source fixtures plus pinned-provider import plans; schema validation alone cannot prove a no-op.
- **HTTP redirect behavior and timeout parity (§§4.3–4.4):** authoritative documentation plus endpoint tests.
- **App Runner domain/retirement lifecycle (§8):** real association, cutover, disassociation, deletion, and survivor assertions; a stand-in endpoint cannot confirm these.
