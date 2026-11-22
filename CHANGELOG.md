# Changelog

Notable project changes are recorded here. The package version is defined in
`pyproject.toml`. Before a release, move the relevant entries from **Unreleased**
to a heading matching that version and add the release date.

## 0.1.0a5 - 2026-11-22

### New Features

- Adds config templates for quick start.
- Adds auto LLM provider discovery, runs once automatically on the first launch, runnable on-demand.

## 0.1.0a4 - 2026-11-22

### Improved

- Updated README for better clarity.

## 0.1.0a3 - 2026-11-21

### Fixed

- In local use, if no SQLite DB URL is predefined a default DB will be created.
- DB table gets initialised automatically.

## 0.1.0a2 - 2026-11-21

### Fixed

- Support chat in Windows interactive terminal.
- Use async-compatible persistent checkpointers for assistant and bee chats,
  fixing failures when streaming with file-backed SQLite or PostgreSQL.

