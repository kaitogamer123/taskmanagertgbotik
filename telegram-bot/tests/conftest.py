"""Общие фикстуры для тестов TaskMNGR."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Важно: config создаёт PlanesUser при импорте, поэтому подменяем путь заранее.
import config

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="taskmngr_tests_"))
config.PLANES_USER_DIR = _TMP_ROOT

import database.db_manager as dm  # noqa: E402

dm.PLANES_USER_DIR = _TMP_ROOT
dm.INDEX_FILE = _TMP_ROOT / "_index.json"


@pytest.fixture()
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированная папка PlanesUser и чистый индекс на каждый тест."""
    monkeypatch.setattr(config, "PLANES_USER_DIR", tmp_path)
    monkeypatch.setattr(dm, "PLANES_USER_DIR", tmp_path)
    monkeypatch.setattr(dm, "INDEX_FILE", tmp_path / "_index.json")
    dm._SCHEMA_READY.clear()
    dm._INDEX_CACHE = None
    dm._INDEX_MTIME = None
    return tmp_path
