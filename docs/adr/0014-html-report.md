# ADR-0014: Render reports as HTML from Markdown

- Status: proposed
- Date: 2026-10-01
- Deciders: maintainer

## Context

`ecsodus report` writes Markdown, which is convenient in GitHub but less convenient to share
with reviewers who are not working in a repository. The HTML output should not become a second
report implementation that can drift from `REPORT.md`.

## Decision

Keep Markdown as the report source and add an optional `--html` output mode that renders the
same report into a standalone HTML document.

Use Python-Markdown for conversion, with the tables extension enabled for the report's existing
tables. The HTML wrapper is local and self-contained so the file can be opened or shared without
external assets.

## Consequences

- Markdown and HTML contain the same report content because both come from `report.render()`.
- `ecsodus report --html` defaults to `REPORT.html`; Markdown remains the default format.
- The runtime gains one Markdown-rendering dependency.
- Generated HTML remains a report artifact only; this does not change AWS access or migration
  safety behavior.

## Alternatives considered

- Maintain a separate HTML report renderer: rejected because two renderers can drift.
- Require users to convert Markdown themselves: rejected because the requested workflow is a
  directly shareable report.
