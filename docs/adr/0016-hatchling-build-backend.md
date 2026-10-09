# ADR-0016: Build with hatchling, not uv_build

- Status: accepted (amends ADR-0005)
- Date: 2026-10-08
- Deciders: maintainer

## Context
ADR-0005 chose uv_build as the build backend. Homebrew installs Python formulas from source,
including their build backends, and `uv_build` (and its `maturin` build dependency) are Rust: a
Homebrew formula for ecsodus would need `depends_on "rust" => :build`, which pulls in the Rust
and LLVM toolchains (several GB) for every user until the tap ships bottles (issue #9).

## Decision
Build with `hatchling` (pure Python). `[tool.hatch.build.targets.wheel]` packages `src/ecsodus`;
the sdist includes only `src/ecsodus`, `README.md`, `LICENSE` and `pyproject.toml`, as the uv_build
sdist did. uv remains the development tool (`uv sync`, `uv run`, `uv build`, `uv lock`).

## Consequences
The built wheel holds the same modules as 0.2.0, and the sdist the same files (plus
`.gitignore`, which hatchling always adds). The Homebrew formula needs no Rust. The next release
(0.2.1) carries the change; the tap points at it.
