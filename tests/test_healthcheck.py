import configparser
import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest


healthcheck = importlib.import_module("docker.healthcheck")


@contextmanager
def pushd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def build_config(*, heartbeat_interval=None, low_power=None, db_path=None):
    config = configparser.ConfigParser()
    if heartbeat_interval is not None or low_power is not None:
        config.add_section("healthcheck")
        if heartbeat_interval is not None:
            config.set("healthcheck", "heartbeat_interval", str(heartbeat_interval))
        if low_power is not None:
            config.set("healthcheck", "low_power", str(low_power))
    if db_path is not None:
        config.add_section("database")
        config.set("database", "db_path", db_path)
    return config


class HealthcheckDatabasePathTests(unittest.TestCase):
    def test_check_files_uses_relative_db_path_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_root = root / "app"
            config_dir = app_root / "config"
            runtime_dir = root / "runtime"
            config_dir.mkdir(parents=True)
            runtime_dir.mkdir()
            db_path = app_root / "data" / "mesh.db"
            db_path.parent.mkdir()
            db_path.touch()

            config = build_config(db_path="data/mesh.db")
            config_path = config_dir / "config.ini"
            config_path.write_text("[database]\ndb_path = data/mesh.db\n", encoding="utf-8")

            with pushd(runtime_dir):
                self.assertTrue(healthcheck.check_files(config, str(config_path)))
                candidates, source = healthcheck.get_database_candidates(config, str(config_path))
                self.assertEqual(source, "[database] db_path")
                self.assertEqual(candidates, [str(db_path.resolve())])

    def test_check_files_uses_absolute_db_path_from_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            config_dir.mkdir()
            db_path = root / "persistent" / "mesh.db"
            db_path.parent.mkdir()
            db_path.touch()

            config = build_config(db_path=str(db_path))
            config_path = config_dir / "config.ini"
            config_path.write_text(
                f"[database]\ndb_path = {db_path}\n",
                encoding="utf-8",
            )

            with pushd(root):
                self.assertTrue(healthcheck.check_files(config, str(config_path)))

    def test_check_files_does_not_fallback_to_default_when_custom_path_is_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            config_dir.mkdir()
            (root / healthcheck.DEFAULT_DB_NAME).touch()

            config = build_config(db_path="missing/mesh.db")
            config_path = config_dir / "config.ini"
            config_path.write_text("[database]\ndb_path = missing/mesh.db\n", encoding="utf-8")

            with pushd(root), patch.dict(os.environ, {}, clear=False):
                self.assertFalse(healthcheck.check_files(config, str(config_path)))

    def test_configured_db_path_takes_precedence_over_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            config_dir.mkdir()
            configured_db = root / "configured" / "mesh.db"
            configured_db.parent.mkdir()
            configured_db.touch()
            env_db = root / "env" / "mesh.db"
            env_db.parent.mkdir()
            env_db.touch()

            config = build_config(db_path="configured/mesh.db")
            config_path = config_dir / "config.ini"
            config_path.write_text("[database]\ndb_path = configured/mesh.db\n", encoding="utf-8")

            with pushd(root), patch.dict(os.environ, {"BBS_DB_PATH": str(env_db)}, clear=False):
                self.assertTrue(healthcheck.check_files(config, str(config_path)))
                candidates, source = healthcheck.get_database_candidates(config, str(config_path))
                self.assertEqual(source, "[database] db_path")
                self.assertEqual(candidates[0], str(configured_db.resolve()))

    def test_relative_env_db_path_without_config_uses_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_db = root / "env" / "mesh.db"
            env_db.parent.mkdir()
            env_db.touch()

            with pushd(root), patch.dict(os.environ, {"BBS_DB_PATH": "env/mesh.db"}, clear=False):
                candidates, source = healthcheck.get_database_candidates(None, None)
                self.assertEqual(source, "BBS_DB_PATH")
                self.assertEqual(candidates, [str(env_db.resolve())])

    def test_default_db_path_without_config_uses_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            expected = root / healthcheck.DEFAULT_DB_NAME

            with pushd(root), patch.dict(os.environ, {}, clear=False):
                candidates, source = healthcheck.get_database_candidates(None, None)
                self.assertEqual(source, f"default {healthcheck.DEFAULT_DB_NAME}")
                self.assertEqual(candidates, [str(expected.resolve())])


def test_heartbeat_max_age_defaults_to_base_threshold_without_config():
    assert healthcheck.get_effective_heartbeat_interval(None) == 10
    assert healthcheck.get_heartbeat_max_age(None) == 60


def test_heartbeat_max_age_matches_low_power_server_override():
    config = build_config(heartbeat_interval=15, low_power=True)

    assert healthcheck.get_effective_heartbeat_interval(config) == 120
    assert healthcheck.get_heartbeat_max_age(config) == 120


def test_heartbeat_max_age_respects_non_low_power_custom_interval_above_default():
    config = build_config(heartbeat_interval=90, low_power=False)

    assert healthcheck.get_effective_heartbeat_interval(config) == 90
    assert healthcheck.get_heartbeat_max_age(config) == 90


def test_heartbeat_config_falls_back_cleanly_on_invalid_values():
    config = configparser.ConfigParser()
    config.add_section("healthcheck")
    config.set("healthcheck", "heartbeat_interval", "0")
    config.set("healthcheck", "low_power", "definitely-not-bool")

    assert healthcheck.get_effective_heartbeat_interval(config) == 10
    assert healthcheck.get_heartbeat_max_age(config) == 60


def test_main_passes_computed_heartbeat_max_age_to_check(monkeypatch, capsys):
    config = build_config(heartbeat_interval=15, low_power=True)
    observed = {}

    monkeypatch.setattr(healthcheck, "get_config", lambda: (config, "config.ini"))
    monkeypatch.setattr(healthcheck, "check_files", lambda config, config_path: True)
    monkeypatch.setattr(healthcheck, "check_process_health", lambda: (True, "123"))

    def fake_check_heartbeat(server_pid, max_age=60):
        observed["call"] = (server_pid, max_age)
        return True

    monkeypatch.setattr(healthcheck, "check_heartbeat", fake_check_heartbeat)
    monkeypatch.setattr(
        healthcheck,
        "check_meshtastic_connection",
        lambda host="localhost", port=4403: (True, "ok"),
    )

    with pytest.raises(SystemExit) as exc_info:
        healthcheck.main()

    assert exc_info.value.code == 0
    assert observed["call"] == ("123", 120)
    assert "Running heartbeat health check (max age 120s)..." in capsys.readouterr().out


if __name__ == "__main__":
    unittest.main()
