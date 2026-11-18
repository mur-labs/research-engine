"""Unit tests for Typer CLI commands."""

from typer.testing import CliRunner
from research_engine.cli import app
from research_engine import __version__

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "System Diagnostics" in result.stdout
    assert "Python" in result.stdout


def test_cli_works_list_uninitialized_db(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    db_file = tmp_path / "missing.db"
    cfg_file.write_text(f'database:\n  path: "{db_file}"\n', encoding="utf-8")

    result = runner.invoke(app, ["works", "list", "--config", str(cfg_file)])
    assert result.exit_code == 1
    assert "research-engine init" in result.stdout
    assert not db_file.exists()
