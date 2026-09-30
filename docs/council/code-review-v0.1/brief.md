Read-only security and correctness code review of this repository (ecsodus). Do not modify files.

ecsodus is a read-only CLI that migrates AWS Copilot CloudFormation apps to Terraform: it imports resources in place, generates "retain patches" (DeletionPolicy/UpdateReplacePolicy: Retain on every resource of every stack, applied via change sets) so Copilot stacks can be deleted without deleting infrastructure, and writes a runbook with machine checks before every mutating step. The approved design is docs/PLAN.md (§2.2 fates and closure, §2.4 generate and the change-set acceptance rule, §2.5 runbook, §2.6 check, §13 build requirements). Read it first.

Review src/ecsodus/ for defects that could cause data loss, an outage, secret leakage, or a safety gate that passes when it should fail. Focus in this order:
1. emit/retain_patch.py and cfn.py (line-based YAML patching + verify_patch): adversarial templates (comments, anchors/aliases, block scalars, CRLF, quoted keys, duplicate keys, Fn::If policies, flow mappings) that yield a patched template that differs beyond the permitted edits yet passes verification, or silently misses a resource.
2. check/changeset.py and check/plan.py: any unsafe change set or Terraform plan (terraform show -json format) that passes.
3. mappers/fates.py: dual ownership (resource imported while its stack is kept), a stack with a remaining consumer reaching the teardown list, closure gaps.
4. sources/aws.py and sources/*: any mutating or secret-reading AWS call possible; secret values reaching output files.
5. emit/runbook.py: wrong or dangerous commands or ordering versus PLAN §2.5/§13.
6. mappers/tf_*.py: arguments that force replacement (ForceNew) of an imported stateful resource, or emitted secrets.

Output markdown:
## Verdict
(ship v0.1.0rc1 / fix first, one paragraph)
## Findings
Numbered. Each: **[P0|P1|P2|P3] title** — file:line — concrete failure scenario (input → wrong outcome) — fix. P0 = data loss, secret leak or unsafe gate pass; P1 = must fix before release. Mark unverified items (UNSURE). Be concrete and terse.
