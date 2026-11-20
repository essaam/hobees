# Contributing

Contributions are welcome. For significant behavior or API changes, open an issue
before starting implementation.

## Development setup

Requirements: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/essaam/hobees.git
cd hobees
uv sync --group dev
```

## Running tests

Run the test suite with:

```bash
uv run pytest
```

PostgreSQL integration tests live in `tests/test_database_backends.py`. They
create and drop a uniquely named schema, so point them only at a disposable
database:

```bash
HOBEES_TEST_POSTGRES_URL=postgresql+psycopg://user:password@localhost:5432/hobees_test \
  uv run pytest tests/test_database_backends.py
```

## Pull requests

- Keep changes focused and add or update tests for behavior changes.
- Describe the motivation and testing performed in the pull request.
- Do not include secrets or generated database and artifact files.
- For repository conventions, see [AGENT.md](AGENT.md). AI coding agents should
  follow those instructions too.

Pull requests are reviewed for correctness, test coverage, maintainability,
security, and compatibility. Maintainer feedback may request revisions or a
narrower scope before merging.

## Release process

Releases are managed by the repository maintainer. Contributors should propose
feature changes without bumping the version in `pyproject.toml`. After the
contribution PRs are reviewed, approved, and merged, the maintainer prepares a
separate release PR with the next version. Once that PR is approved and merged,
only the maintainer creates a GitHub Release with a matching tag (for example,
`v0.2.0`). Publishing the release triggers
`.github/workflows/release.yml`, which runs the tests, builds the source and
wheel distributions, and publishes them to PyPI using trusted publishing.
