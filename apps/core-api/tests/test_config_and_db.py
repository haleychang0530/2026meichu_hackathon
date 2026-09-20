from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core_api.config import Settings
from core_api.db import Database
from core_api.models import Lesson
from tests.support import FIXTURE_PATH


class SettingsTests(unittest.TestCase):
    def test_demo_and_test_default_to_fixture(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env("development")
            self.assertEqual(settings.provider_mode, "real")
            self.assertFalse(settings.vlm_output_validation_enabled)
            self.assertEqual(Settings.from_env("demo").provider_mode, "fixture")
            self.assertEqual(Settings.from_env("test").provider_mode, "fixture")

    def test_environment_overrides_profile_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CORE_PROVIDER": "fixture",
                "CORE_PORT": "9000",
                "CORE_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
                "VLM_OUTPUT_VALIDATION_ENABLED": "false",
            },
            clear=True,
        ):
            settings = Settings.from_env("development")
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.provider_mode, "fixture")
        self.assertEqual(settings.allowed_origins, ("http://127.0.0.1:5173",))
        self.assertFalse(settings.vlm_output_validation_enabled)

    def test_manta_forwarding_origin_is_normalized(self) -> None:
        with patch.dict(
            os.environ,
            {"VLM_BASE_URL": "  http://210.61.209.139:46944/  "},
            clear=True,
        ):
            settings = Settings.from_env("development")
        self.assertEqual(settings.vlm_base_url, "http://210.61.209.139:46944")

    def test_vlm_base_url_rejects_endpoint_paths_and_credentials(self) -> None:
        invalid_values = (
            "210.61.209.139:46944",
            "http://user:secret@210.61.209.139:46944",
            "http://210.61.209.139:46944/internal/health",
            "http://210.61.209.139:46944?forward=8100",
        )
        for value in invalid_values:
            with self.subTest(value=value), patch.dict(
                os.environ, {"VLM_BASE_URL": value}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "VLM_BASE_URL"):
                    Settings.from_env("development")

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
            self.assertEqual(
                database.migrate(),
                [
                    "0001_runtime_metadata.sql",
                    "0002_lessons.sql",
                    "0003_sessions.sql",
                    "0004_turns.sql",
                    "0005_mastery.sql",
                    "0006_events.sql",
                    "0007_settings.sql",
                    "0008_stage08_source_read.sql",
                ],
            )
            self.assertEqual(database.migrate(), [])
            self.assertTrue(database.healthy())
            connection = database._connect()
            try:
                values = dict(connection.execute("SELECT key, value_json FROM settings"))
            finally:
                connection.close()
            self.assertEqual(json.loads(values["teaching_agent_version"]), "stage08-v2-source-read")
            self.assertEqual(json.loads(values["schema_version"]), "0.1.0")

    def test_lessons_are_structurally_persisted_and_reviewable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = Path(__file__).resolve().parents[1] / "migrations"
            database = Database(root / "db" / "app.sqlite3", migrations)
            database.migrate()
            lesson = Lesson.model_validate(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))

            database.save_lesson(lesson)
            stored = database.get_lesson(lesson.lesson_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.review_status, "pending")
            self.assertEqual(stored.source_text, lesson.source_text)
            self.assertEqual(stored.answer_evidence, lesson.answer_evidence)

            updated = database.update_lesson(lesson.lesson_id, {"review_status": "approved"})
            self.assertIsNotNone(updated)
            self.assertEqual(updated.review_status, "approved")
            self.assertEqual(database.get_lesson(lesson.lesson_id).review_status, "approved")
            self.assertIsNone(database.get_lesson("lesson_missing"))


if __name__ == "__main__":
    unittest.main()
