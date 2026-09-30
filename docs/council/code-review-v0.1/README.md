# Code review of v0.1.0rc1

Two independent, read-only reviews of the implementation, both against commit `66f3245`:

- **gpt-6-astra** (Codex CLI): [astra.md](astra.md), from the [brief](brief.md).
- **Claude Opus 5.5**: [opus.md](opus.md), with the same scope. Its brief included the task of
  trying adversarial inputs against the retain patcher.

Both verdicts were **fix first**. Every P0 and P1 finding was fixed in the commit
`fix: code-review findings`, and so were most P2 and P3 findings. The table below maps each one to
its fix.

| Finding | Fix |
|---|---|
| verify_patch compares `1 == True` and lets the Metadata key through without the flag (astra 1, opus 10) | Canonical-JSON comparison, a text-skeleton check, and the Metadata exemption only when the flag is set |
| Nested change sets and hashes are not verified; in-progress change sets pass (astra 2–3, opus 3) | The check requires `CREATE_COMPLETE`/`AVAILABLE` status, every referenced nested change set, a single root, and a `TemplateURL` equal to the manifest's child URL |
| The import gate ignores physical IDs; the steady gate passes vacuously; data sources pass (astra 4–6, opus 5) | Import IDs are checked, every expected address must be covered, and data sources and errored plans fail |
| Freshness is not enforced (astra 7) | New `verify-fresh` command, and the import phase refuses a manifest older than 24h |
| `verify-retain` passes when it finds nothing (astra 8, opus 9) | Zero stacks is a failure, and `--manifest` requires full coverage and matching hashes |
| `--env` hides consumers; environments elsewhere are invisible (astra 9, opus 2) | Every environment is discovered, and environments or StackSet instances in other accounts or regions keep the app layer |
| A teardown cutoff can cause dual ownership (astra 10) | No truncation: stack hand-off already implies there are no consumers |
| Closure ignores kept stacks (astra 11) | Closure scans imported arguments and the templates of kept stacks |
| Out-of-band certificates and DNS records get no fate (astra 12) | New `tf_oob` module: certificates follow their creating stack, and unowned records in imported zones are imported |
| The paginator bypasses the secret guard (astra 13, opus 11) | Guarded paginators, SSM parameter history, and forbidden `s3:GetObject` and `lambda:GetFunction` |
| Sensitive files are exposed (astra 14, opus 12) | Patches are written 0600, a broader generated `.gitignore`, `umask 077` in the runbook, and a warning about env values in `.tf` files |
| Regeneration drops the selection (astra 15, opus 1) | The inventory saves the selection, and the runbook replays it along with the patch bucket and teardown flag |
| Pasted blocks keep going after a failure (astra 16, opus 4) | Fail-fast subshells, with each mutating command chained to its check using `&&` |
| `--include-property-values` is on the wrong command (astra 17) | Moved to `describe-change-set`, for the root and nested change sets |
| StackSet ordering and waits (astra 18, opus 8) | Operations are polled to `SUCCEEDED`, instances are scoped to this account and region, and the app stack is deleted last |
| Cleanup is listed without teardown (astra 19) | Cleanup is only listed together with step 5 |
| Every Lambda is treated as manual-cleanup (opus 6) | Only custom-resource handlers are manual-cleanup; user Lambdas are blocked |
| Transform, ForEach and Include templates (opus 7) | Blocked in v0.1 |
| Unknown `--keep-on-copilot` name, and stack statuses (opus 13–14) | Unknown names are an error; all statuses are discovered, and nested stacks are processed parents first |
| Step 2 gaps (opus 15) | Instance snapshots, snapshot waits, and Aurora members protected through their cluster |
| The steady gate conflicts with the `removed` hand-off (opus 18) | `--forgotten ADDRESS` |
| HCL map keys are not escaped (opus 18) | Keys are escaped |
| Kept stacks are patched (opus 16) | Only handed-off stacks are patched |

## Verification rounds

- [astra-verify.md](astra-verify.md): 4 new P1 findings plus partial fixes. All were fixed in
  `fix: verification-review findings`.
- [astra-verify-2.md](astra-verify-2.md): 1 new P1 (the StackSet coverage test sat on the left of
  `&&`). Fixed, together with these partials:
  - the exact provider string
  - the resource type must match the address
  - steady-phase identity against the manifest ID
  - the nested change-set parent and `StackId` binding
  - an unknown certificate owner as a closure error
  - `SetIdentifier` in DNS ownership
  - deleted stacks fail `verify-fresh`
  - `--forgotten` limited to the manifest's task definitions

Open and accepted for v0.1, fail-closed:

- **The patched template's bytes in S3 are not re-hashed before `execute-change-set`.** They are
  uploaded in the same block, and after the update `verify-retain --manifest` compares the
  deployed template's SHA-256 with the manifest, failing on any mismatch.
- **The generated `*.tf` files are deliberately not gitignored,** because they are the
  deliverable. They contain plaintext task-definition environment values, which the runbook and
  the generated `.gitignore` header warn about. Secrets remain `valueFrom` references.
- **The offline `check --phase import` does not itself prove that the live verification ran.**
  The runbook runs `verify-fresh` in the same fail-fast block, immediately before the plan.
- **The zone-name fallback in DNS ownership can conflate two private and public zones with the
  same name** when a RecordSet names its zone by name. Rare in Copilot, which uses zone IDs.


- JSON templates are re-serialised rather than edited as text (opus 16). The semantic check
  still applies.
- Line separators and lone-CR files make the patcher refuse the template (opus 16).
- The `NextToken` in change-set documents (opus 17). The CLI paginates automatically.
