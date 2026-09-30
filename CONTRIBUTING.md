# Contributing

## Setup
```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
The Terraform-marked tests need `terraform` ≥ 1.10 on `PATH`. Without it they are skipped.

## Ground rules
- **Read-only.** No code path may call a mutating AWS API. `tests/unit/test_readonly.py` enforces
  this by allowing only boto3 operations that start with `Describe`, `List`, `Get` or `Lookup`.
- **Fail closed.** Anything ecsodus does not fully understand becomes `blocked` with a reason in
  the report. It is never guessed and never dropped silently.
- **Every decision gets an ADR** (`docs/adr/`). A change to the approved plan needs an ADR, and
  for safety mechanics a council review.
- **Fixtures** under `tests/fixtures/copilot/` are verbatim from aws/copilot-cli. Keep
  `SOURCE.md` and the licence files next to them.

## Commits
Use conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). Keep the subject line
under 72 characters.
