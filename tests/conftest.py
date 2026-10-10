import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEM_DB", str(tmp_path / "zem.db"))
