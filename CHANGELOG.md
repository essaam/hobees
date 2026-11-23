# Changelog

Notable project changes are recorded here. The package version is defined in
`pyproject.toml`. Before a release, move the relevant entries from **Unreleased**
to a heading matching that version and add the release date.

## Unreleased

### Fixed

- Web UI: the Workbench provider/target picker no longer resets to the first
  entry when switching views or the Assistant/Hive/Bee tabs. Pickers now live in
  the app context per scope and are persisted (localStorage), so the chosen
  provider is restored on return; it only falls back to the first entry when the
  remembered selection is missing or was deleted.
- Web UI: Command Palette arrow keys (↑/↓) now navigate the results from any
  focus position inside the palette, the highlight is clamped to the filtered
  list, and the active entry is scrolled into view.

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

