"""Tests for hobees.templates package and hobees init --template CLI command."""

from __future__ import annotations

import pytest

from hobees.templates import AVAILABLE_TEMPLATES, get_template_text


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------


def test_available_templates_not_empty():
    """AVAILABLE_TEMPLATES must list at least the five built-in blueprints."""
    expected = {"code-review", "research", "docs-writer", "local-ollama", "local-llamacpp"}
    assert expected.issubset(set(AVAILABLE_TEMPLATES))


def test_all_registered_templates_load():
    """Every template listed in AVAILABLE_TEMPLATES must load without error."""
    for name in AVAILABLE_TEMPLATES:
        text = get_template_text(name)
        assert text, f"Template {name!r} returned empty text"


def test_template_text_is_valid_yaml():
    """Every template must parse as valid YAML."""
    import yaml

    for name in AVAILABLE_TEMPLATES:
        text = get_template_text(name)
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict), f"Template {name!r} did not parse to a dict"


def test_template_contains_required_top_level_keys():
    """Each template must have at least 'providers', 'bees', and 'hives'."""
    import yaml

    required = {"providers", "bees", "hives"}
    for name in AVAILABLE_TEMPLATES:
        parsed = yaml.safe_load(get_template_text(name))
        missing = required - parsed.keys()
        assert not missing, f"Template {name!r} missing top-level keys: {missing}"


def test_template_providers_have_alias_and_type():
    """Every provider entry in every template must have 'alias' and 'provider_type'."""
    import yaml

    for name in AVAILABLE_TEMPLATES:
        parsed = yaml.safe_load(get_template_text(name))
        for p in parsed.get("providers", []):
            assert "alias" in p, f"Template {name!r}: provider missing 'alias'"
            assert "provider_type" in p, f"Template {name!r}: provider missing 'provider_type'"


def test_template_bees_reference_known_providers():
    """Every bee must reference a provider alias defined in the same template."""
    import yaml

    for name in AVAILABLE_TEMPLATES:
        parsed = yaml.safe_load(get_template_text(name))
        provider_aliases = {p["alias"] for p in parsed.get("providers", [])}
        for bee in parsed.get("bees", []):
            bee_provider = bee.get("provider")
            assert bee_provider in provider_aliases, (
                f"Template {name!r}: bee {bee.get('name')!r} references "
                f"unknown provider {bee_provider!r}"
            )


def test_template_hives_reference_known_bees():
    """Every hive member must reference a bee defined in the same template."""
    import yaml

    for name in AVAILABLE_TEMPLATES:
        parsed = yaml.safe_load(get_template_text(name))
        bee_names = {b["name"] for b in parsed.get("bees", [])}
        for hive in parsed.get("hives", []):
            for member in hive.get("bees", []):
                assert member in bee_names, (
                    f"Template {name!r}: hive {hive.get('name')!r} references "
                    f"unknown bee {member!r}"
                )


def test_local_templates_use_no_api_key():
    """Local templates must set api_key_env to 'NONE' for all providers."""
    import yaml

    for name in ("local-ollama", "local-llamacpp"):
        parsed = yaml.safe_load(get_template_text(name))
        for p in parsed.get("providers", []):
            assert p.get("api_key_env") == "NONE", (
                f"Template {name!r}: provider {p.get('alias')!r} should have api_key_env='NONE'"
            )


def test_unknown_template_raises_key_error():
    """get_template_text raises KeyError for unknown template names."""
    with pytest.raises(KeyError, match="Unknown template"):
        get_template_text("does-not-exist")


# ---------------------------------------------------------------------------
# CLI: hobees init --list-templates
# ---------------------------------------------------------------------------


def test_list_templates_command(monkeypatch, tmp_path):
    """hobees init --list-templates prints all template names and exits cleanly."""
    from typer.testing import CliRunner
    from hobees.cli.main import app

    # Point DB at an in-memory SQLite so the test is self-contained
    from hobees.config import settings
    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "config_path", None)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--list-templates"])

    assert result.exit_code == 0, result.output
    for name in AVAILABLE_TEMPLATES:
        assert name in result.output, f"Template name {name!r} missing from --list-templates output"


# ---------------------------------------------------------------------------
# CLI: hobees init --template <name>
# ---------------------------------------------------------------------------


def test_init_template_scaffolds_file(monkeypatch, tmp_path):
    """hobees init --template code-review writes hobees.yaml and imports it."""
    from typer.testing import CliRunner
    from hobees.cli.main import app
    from hobees.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "config_path", None)
    # Avoid actually importing the config (needs live DB), just check file creation
    monkeypatch.setattr("hobees.cli.main.import_config", lambda *a, **kw: None)
    # Suppress DB init for speed
    monkeypatch.setattr("hobees.cli.main._ensure_database_initialized", lambda e: None)
    monkeypatch.setattr("hobees.cli.main._run_migrations", lambda e: None)
    monkeypatch.setattr("hobees.cli.main._setup_postgres_checkpointer", lambda u: None)

    dest = tmp_path / "hobees.yaml"
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--template", "code-review", "--output", str(dest)])

    assert result.exit_code == 0, result.output
    assert dest.exists(), "Template file was not created"
    content = dest.read_text(encoding="utf-8")
    assert "code-review" in content or "dev-team" in content


def test_init_template_refuses_overwrite_without_force(monkeypatch, tmp_path):
    """hobees init --template refuses to overwrite an existing file without --force."""
    from typer.testing import CliRunner
    from hobees.cli.main import app
    from hobees.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "config_path", None)

    dest = tmp_path / "hobees.yaml"
    dest.write_text("existing content", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--template", "code-review", "--output", str(dest)])

    assert result.exit_code != 0
    assert dest.read_text(encoding="utf-8") == "existing content"


def test_init_unknown_template_exits_nonzero(monkeypatch, tmp_path):
    """hobees init --template bad-name exits with a non-zero code."""
    from typer.testing import CliRunner
    from hobees.cli.main import app
    from hobees.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "config_path", None)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--template", "bad-name"])

    assert result.exit_code != 0


def test_init_template_and_config_mutually_exclusive(monkeypatch, tmp_path):
    """hobees init --template X --config Y should exit with an error."""
    from typer.testing import CliRunner
    from hobees.cli.main import app
    from hobees.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "config_path", None)

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app, ["init", "--template", "code-review", "--config", str(cfg)]
    )

    assert result.exit_code != 0
