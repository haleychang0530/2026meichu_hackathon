from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core_api.config import Settings
from core_api.db import Database


class SettingsTests(unittest.TestCase):
    def test_demo_and_test_default_to_fixture(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings.from_env("development").provider_mode, "real")
            self.assertEqual(Settings.from_env("demo").provider_mode, "fixture")
            self.assertEqual(Settings.from_env("test").provider_mode, "fixture")

    def test_environment_overrides_profile_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CORE_PROVIDER": "fixture",
                "CORE_PORT": "9000",
                "CORE_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
            },
            clear=True,
        ):
            settings = Settings.from_env("development")
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.provider_mode, "fixture")
        self.assertEqual(settings.allowed_origins, ("http://127.0.0.1:5173",))

    def test_rag_reliability_threshold_is_bounded(self) -> None:
        with patch.dict(os.environ, {"RAG_MIN_SCORE": "1.1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "RAG_MIN_SCORE"):
                Settings.from_env("test")


class DatabaseTests(unittest.TestCase):
    def test_migrations_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = Path(__file__).resolve().parents[1] / "migrations"
            database = Database(root / "db" / "app.sqlite3", migrations)
            self.assertEqual(database.migrate(), ["0001_runtime_metadata.sql"])
            self.assertEqual(database.migrate(), [])
            self.assertTrue(database.healthy())


if __name__ == "__main__":
    unittest.main()
