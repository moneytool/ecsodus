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

## Releasing
1. Open a release PR: the version in `pyproject.toml`, `src/ecsodus/__init__.py`,
   `CITATION.cff` (`version`, `date-released`) and `mkdocs.yml` (`extra.version`); the
   CHANGELOG section and compare links; regenerate the golden snapshots
   (`ECSODUS_UPDATE_GOLDEN=1 uv run pytest -q tests/golden`) and `docs/examples/`; `uv lock`.
2. After it merges, tag `vX.Y.Z` on `main` and push the tag. `.github/workflows/release.yml`
   checks the tag and version, runs the suite, publishes to PyPI (trusted publishing) and
   creates the GitHub Release. Zenodo archives the release and issues a DOI; add it to
   `CITATION.cff` in a follow-up PR.
3. Once the version is live on PyPI, bump the Homebrew tap: in a checkout of
   `moneytool/homebrew-tap`, run `scripts/bump.sh X.Y.Z`, check with `brew style`,
   `brew audit` and a local `brew install --build-from-source` + `brew test` (see the tap
   README), and open a PR titled `ecsodus X.Y.Z`; merge once its `test` workflow passes.

## Commits
Use conventional prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). Keep the subject line
under 72 characters.
