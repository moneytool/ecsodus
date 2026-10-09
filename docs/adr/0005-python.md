# ADR-0005: Python 3.11+, distributed via PyPI (uvx/pipx)

- Status: accepted
- Date: 2026-09-29
- Deciders: maintainer; council round 1 (all three: Python)

## Context
The work is text code generation plus AWS API reads. Nothing is CPU-bound. The maintainer works in
Python.

## Decision
Python ≥ 3.11 with boto3, ruamel.yaml and Jinja2. The build backend is uv_build (since 0.2.1: hatchling, ADR-0016). The tool is
published to PyPI only after the real AWS run passes.

## Alternatives considered
Go. It gives a single binary and matches Copilot's own language, but adds delivery friction and
solves none of the hard problems.
