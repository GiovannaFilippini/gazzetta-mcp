# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `cerca_concorsi` and `cerca` now work from an empty cache: they load the table of contents
  of the most recent issues (last 30 days, bounded and rate limited) using the official
  "last 30 days" index, and state the coverage in every answer. `cerca_concorsi` gained
  `aperti`, `includi_altri_atti` and `limite`, classifies calls, extracts the number of posts
  and estimates the region; `cerca` gained `aggiorna`.

- Project documentation: README (English and Italian), usage guide, contributing guide, code of
  conduct, security policy, issue and pull request templates.
- Release workflow for PyPI trusted publishing (manual trigger only, not enabled).
