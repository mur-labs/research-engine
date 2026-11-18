"""Unit tests for configuration loading."""

from pathlib import Path
import pytest
from research_engine.config import load_config, AppConfig


def test_load_config_defaults(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist.yaml"
    cfg = load_config(non_existent)
    assert isinstance(cfg, AppConfig)
    assert cfg.database.path == Path("data/research_engine.db")
    assert cfg.llm.model == "smart"
    assert cfg.apis.openalex.base_url == "https://api.openalex.org"


def test_load_config_yaml(tmp_path: Path):
    yaml_file = tmp_path / "test_config.yaml"
    yaml_file.write_text(
        """
database:
  path: "custom/db.sqlite"
llm:
  model: "custom-model"
"""
    )
    cfg = load_config(yaml_file)
    assert cfg.database.path == Path("custom/db.sqlite")
    assert cfg.llm.model == "custom-model"


def test_load_config_env_override(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "test_config.yaml"
    yaml_file.write_text('llm:\n  model: "from_yaml"\n')
    monkeypatch.setenv("RESEARCH_ENGINE_LLM__MODEL", "from_env")
    cfg = load_config(yaml_file)
    assert cfg.llm.model == "from_env"


def test_load_config_dotenv_and_tilde_expansion(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "RESEARCH_ENGINE_LLM__API_KEY=from_dotenv\n"
        "RESEARCH_ENGINE_ZOTERO__DATA_DIR=~/custom_zotero\n",
        encoding="utf-8",
    )
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text('llm:\n  api_key: "from_yaml"\n', encoding="utf-8")

    cfg = load_config(yaml_file)
    assert cfg.llm.api_key == "from_dotenv"
    assert cfg.zotero.data_dir == Path("~/custom_zotero").expanduser()
