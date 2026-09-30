## Vote

**REJECT** — R2 resolves the main architectural objections, but shared-stack teardown, nested retention, and secret/IAM preservation still need explicit safety rules before building.

## Round-1 findings status

“Partial” includes deferred requirements that do **not** block v0.1.

| Finding (reviewer + number) | Status | Note |
|---|---|---|
| Astra #1 P0 | partial | Retain patches replace the unsafe flag; nested application remains unspecified. |
| Astra #2 P0 | addressed | Retain all custom resources, discover external objects, document handlers, verify experimentally. |
| Astra #3 P0 | partial | Fates exist; no prohibition on deleting shared stacks with unmigrated consumers. |
| Astra #4 P1 | addressed | Explicit import-only apply, flat addresses, freeze, subsequent zero-change plan. |
| Astra #5 P1 | partial | Live reads, pagination and provenance added; disagreement/unavailable-value handling unspecified. |
| Astra #6 P1 | partial | Ordinary ECS adoption is default; concrete Express predicate deferred. |
| Astra #7 P1 | partial | Minimum versions and support matrix promised; “pins” remain open-ended ranges. |
| Astra #8 P1 | addressed | Operator-selected scaling replaces conversion. |
| Astra #9 P1 | partial | App Runner deferred; address family and endpoint SG preservation still unspecified. |
| Astra #10 P1 | addressed | Source services deferred; checkout and YAML required. |
| Astra #11 P1 | partial | TLS, atomic batches and waiting added; hostname/type/apex and rollback preconditions absent. Deferred. |
| Astra #12 P1 | partial | Question added; disabling consumers and draining absent. Deferred with rebuild. |
| Astra #13 P1 | partial | Disclosure controls added; secret ownership, rotation, policies and KMS dependencies unresolved. |
| Astra #14 P1 | partial | Image ignore rule added; task-definition deployment ownership remains unclear. |
| Astra #15 P1 | partial | Sentinel, interruption and rollback tests added; partial migration and update rejection absent. |
| Astra #16 P1 | addressed | Copilot-only v0.1, report first, substantial scope cuts. |
| Fable #1 P0 | partial | Nested templates included, but parent retention/application mechanics omitted. |
| Fable #2 P0 | addressed | External discovery and custom-resource retention; adopt-in-place avoids replacement TLS/DNS. |
| Fable #3 P0 | addressed | Env patched first; `EnvControllerAction` explicitly retained. |
| Fable #4 P1 | partial | Express deferred; explicit fit predicate still absent. |
| Fable #5 P1 | addressed | ADOT and rebuild deferred; sidecars blocked in v0.1. |
| Fable #6 P1 | partial | Express domains deferred; ownership/dependency contract still absent. |
| Fable #7 P1 | partial | StackSet inventoried; instance-stack patch/delete sequence ambiguous. |
| Fable #8 P1 | partial | Stateful protections added; addon secret fate and final-snapshot handling unspecified. |
| Fable #9 P1 | addressed | Flat imports; modules only for new compute. |
| Fable #10 P1 | addressed | Requested scope reductions adopted. |
| Opus #1 P0 | partial | Correct retention mechanism; nested deployment details missing. |
| Opus #2 P0 | addressed | Env-controller retention and deletion-side-effect reporting explicit. |
| Opus #3 P0 | addressed | All custom resources retained; cleanup list required. |
| Opus #4 P0 | partial | Recursive discovery added; parent `TemplateURL` update path missing. |
| Opus #5 P0 | partial | App resources included; app stack versus StackSet-instance lifecycle conflated. |
| Opus #6 P1 | partial | Plain ECS default adopted; Express predicate deferred. |
| Opus #7 P1 | addressed | Adopt-in-place is default. |
| Opus #8 P1 | partial | Atomic batches/TLS added; record-type/apex checks missing. Deferred. |
| Opus #9 P1 | partial | Double-work question and wait added; execution controls missing. Deferred. |
| Opus #10 P1 | partial | SGs imported; roles, policies, secret grants and KMS preservation not explicit. |
| Opus #11 P1 | addressed | Root resources, stateful protection and destroy/replace guard added. |
| Opus #12 P1 | addressed | Copilot freeze and import-only handoff explicit. |

## Conditions (if any)

1. **P0 — §2 report/runbook, §3:** Make blockers propagate through dependencies. Prohibit deleting workload, env, app or StackSet-instance stacks while any unmigrated consumer or `retain-under-existing-owner` resource depends on them. Cover other environments sharing app resources and externally owned VPCs. Add a mixed supported/blocked migration test in §6.

2. **P1 — §2 runbook steps 3–4, §5:** Specify nested-template publication and root-driven updates with changed `TemplateURL`s; explicitly retain nested-stack wrapper resources if using orphan-then-delete. Wait for successful updates and verify every deployed child template before deletion. Allow these reference changes in the “byte-stable otherwise” rule. [AWS nested-stack guidance](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-nested-stacks.html).

3. **P1 — §1, §2:** Separate the app stack from StackSet instance stacks. Specify patching and verification for each instance, detachment with `--retain-stacks`, then deletion of each retained instance stack when dependency-safe. Correct §1’s attribution of the hosted zone to the StackSet.

4. **P1 — §2–5:** Require explicit fates for addon secrets, SSM parameters, task/execution roles, attached policies, rotation resources and KMS dependencies. Preserve them without retrieving secret values; block teardown when unresolved. Define how redacted environment values are supplied without changing deployed configuration.

5. **P1 — §2 check/runbook, §6:** Add an adoption-phase guard rejecting attribute updates as well as deletes/replacements, and verify every expected import entered state. Defer enabling currently disabled `deletion_protection` until ownership transfer completes; otherwise generation contradicts the required import-only first apply.

6. **P2 — §2–3:** State unambiguously that rebuild generation is unavailable in v0.1. Before enabling it, require the missing Express predicate, DNS preconditions and background-work controls identified above.

## New issues in r2

- **P1:** Unconditional `deletion_protection` can require an update during the purported import-only apply; the current guard accepts that update.
- **P2:** §5 labels minimum-version ranges as “pins”; specify tested versions or bounded constraints.
- **P2:** Blanket environment redaction lacks a reconstruction contract for generating a zero-change configuration.