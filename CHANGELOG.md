# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One-click install for Claude Desktop: the `mcpb/` folder builds a `.mcpb` Desktop Extension that
  installs the published `gazzetta-mcp` package from PyPI.
- README: PyPI downloads badge and an animated demo.
- README: "Sources and attribution" section, including the CC BY 4.0 credit for Normattiva Open
  Data results.

### Changed

- README: the English text now matches the Italian one and the code (`cerca` with the Normattiva
  archive, `solo_vigenti` and `periodo`; the archive and advanced-search environment variables).
- README (Italian): proper accented letters; series codes added.
- README: `uv` is the recommended install and fetches Python by itself; "from source" renamed
  "development version".
- LICENSE: copyright holder is now Giovanna Filippini (as in `pyproject.toml`).

## [0.1.0] - 2026-10-16

### Changed

- README and CONTRIBUTING: replaced the `<owner>` placeholder with the repository owner, removed
  the note saying the repository is private, and explained how to install `uv`.

### Fixed

- `leggi_atto` returned only the first article of acts with several articles (the GU text page
  shows one article at a time). It now uses the site's export form to get every article and
  annex in one request. Acts already read are cached with the partial text: clear the cache
  with `gazzetta-mcp --svuota-cache --si`.

### Added

- `cerca_concorsi` and `cerca` now work from an empty cache: they load the table of contents
  of the most recent issues (last 30 days, bounded and rate limited) using the official
  "last 30 days" index, and state the coverage in every answer. `cerca_concorsi` gained
  `aperti`, `includi_altri_atti` and `limite`, classifies calls, extracts the number of posts
  and estimates the region; `cerca` gained `aggiorna`.

- Project documentation: README (English and Italian), usage guide, contributing guide, code of
  conduct, security policy, issue and pull request templates.
- Release workflow for PyPI trusted publishing (manual trigger only, not enabled).

[Unreleased]: https://github.com/GiovannaFilippini/gazzetta-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GiovannaFilippini/gazzetta-mcp/releases/tag/v0.1.0
