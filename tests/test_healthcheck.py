import configparser
import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

healthcheck = importlib.import_module("docker.healthcheck")


@contextmanager
def pushd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


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

            config = configparser.ConfigParser()
            config.read_dict({"database": {"db_path": "data/mesh.db"}})
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

            config = configparser.ConfigParser()
            config.read_dict({"database": {"db_path": str(db_path)}})
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

            config = configparser.ConfigParser()
            config.read_dict({"database": {"db_path": "missing/mesh.db"}})
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

            config = configparser.ConfigParser()
            config.read_dict({"database": {"db_path": "configured/mesh.db"}})
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


if __name__ == "__main__":
    unittest.main()
