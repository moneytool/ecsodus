# Examples

[`copilot-lbws-aurora/`](copilot-lbws-aurora/REPORT.md) is the output of ecsodus for a real
Copilot-rendered app:
- an environment built from `template-with-basic-manifest`, with a public ALB, HTTPS, NAT and
  delegated DNS
- a Load Balanced Web Service (`svc-staging`)
- an Aurora Serverless v2 addon

The live state is synthetic but consistent: this is the app from `tests/golden/test_full_handoff.py`.
All runbook steps are shown, including teardown, which has been verified on real AWS.

- [REPORT.md](copilot-lbws-aurora/REPORT.md): readiness report (66 imports, 12 manual-cleanup)
- [RUNBOOK.md](copilot-lbws-aurora/RUNBOOK.md): the exact operator commands, steps 1–7

Account IDs, bucket names and hashes are fixture values.
