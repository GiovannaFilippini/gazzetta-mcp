# Contributing

Thanks for your interest in gazzetta-mcp. By participating you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

This project queries public sites, so these rules are not negotiable:

- Requests only on user demand; **no bulk download**, no mirroring.
- Keep the rate limit, the local cache and the identifying User-Agent.
- Every output must carry the source, the official link and the notice that the text is
  unofficial and non-authentic (see [docs/fonti.md](docs/fonti.md)).

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<owner>/gazzetta-mcp
cd gazzetta-mcp
uv sync
uv run pytest
uv run ruff check .
```

## Tests

- Tests must run **without network**. Use the real samples in `tests/fixtures/real/`.
- Tests that call the real sites are marked `live` and only run with `uv run pytest --live`.
  Run them rarely and never in CI.
- New behaviour comes with a test; a parser fix comes with a fixture reproducing the problem.

## Branches and commits

- One branch per change, from `main`: `feat/...`, `fix/...`, `docs/...`, `ci/...`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/), in English:
  `feat: ...`, `fix: ...`, `docs: ...`, `test: ...`, `ci: ...`, `refactor: ...`, `chore: ...`.
- Keep commits small and atomic.
- Open a pull request against `main`; it is merged with a merge commit so a change can be undone
  with a single revert (see decision 006).
- CI (ruff + pytest on Python 3.10 and 3.12) must pass.

## Decision records

Choices that are hard to reverse (dependencies, data sources, formats, release process) are
recorded in `docs/decisioni/NNN-short-name.md`, with context, choice, discarded alternatives and
how to go back. Add a new numbered file instead of rewriting an old one.

## When the source site changes

If the Gazzetta Ufficiale changes its HTML or URLs, open a "source changed" issue with the
affected URL and what differs, and add a fixture if you send a fix.

## Reporting security problems

See [SECURITY.md](SECURITY.md).
