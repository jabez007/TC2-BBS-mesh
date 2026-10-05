import database_core


def test_configured_db_path_wins_over_env_like_server_and_healthcheck(monkeypatch, tmp_path):
    # server.py applies [database] db_path via set_db_path, and the healthcheck
    # checks config before BBS_DB_PATH, so db_admin must resolve the same file.
    (tmp_path / "config.ini").write_text("[database]\ndb_path = from-config.db\n", encoding="utf-8")
    monkeypatch.setattr(database_core, "__file__", str(tmp_path / "database_core.py"))
    monkeypatch.setattr(database_core, "_custom_db_path", None)
    monkeypatch.setenv("BBS_DB_PATH", str(tmp_path / "from-env.db"))

    assert database_core.get_db_path() == str(tmp_path / "from-config.db")


def test_env_db_path_applies_when_config_has_none(monkeypatch, tmp_path):
    (tmp_path / "config.ini").write_text("[interface]\ntype = serial\n", encoding="utf-8")
    monkeypatch.setattr(database_core, "__file__", str(tmp_path / "database_core.py"))
    monkeypatch.setattr(database_core, "_custom_db_path", None)
    monkeypatch.setenv("BBS_DB_PATH", str(tmp_path / "from-env.db"))

    assert database_core.get_db_path() == str(tmp_path / "from-env.db")
