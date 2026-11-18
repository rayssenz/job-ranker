# job-ranker

A command-line program that collects new job postings from public company job feeds, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its own ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## Status

Milestone 0. The repository, the checks and the first decision record are being set up. Nothing ranks yet.

## Quick start

```bash
uv sync
uv run pytest
```

## Design

- [Technical design](docs/specs/2026-11-18-technical-design.md)
- Decision records live in `docs/decisions/`.

## How this was built

Built with AI assistance. Specs and tests come before code, and the design decisions are recorded in `docs/decisions/`.

## Licence

MIT. See [LICENSE](LICENSE).
