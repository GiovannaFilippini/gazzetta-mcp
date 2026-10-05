## What and why

## How it was tested

- [ ] `uv run pytest` passes (no network)
- [ ] `uv run ruff check .` passes
- [ ] New or changed behaviour has tests (fixtures instead of live requests)

## Checklist

- [ ] Commits follow Conventional Commits
- [ ] No bulk download; rate limit, cache and User-Agent are untouched
- [ ] Docs and CHANGELOG updated if needed
- [ ] Decision record added in `docs/decisioni` if the change is hard to reverse
