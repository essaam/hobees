# Changelog

Notable project changes are recorded here. The package version is defined in
`pyproject.toml`. Before a release, move the relevant entries from **Unreleased**
to a heading matching that version and add the release date.

## 0.1.0a2 - 2026-11-21

### Fixed

- Support chat in Windows interactive terminal.
- Use async-compatible persistent checkpointers for assistant and bee chats,
  fixing failures when streaming with file-backed SQLite or PostgreSQL.

