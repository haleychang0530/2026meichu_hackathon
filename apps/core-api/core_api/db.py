from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Lesson


class Database:
    def __init__(self, path: Path, migration_dir: Path) -> None:
        self.path = path
        self.migration_dir = migration_dir

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self) -> list[str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        applied: list[str] = []
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
                known = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
                for script in sorted(self.migration_dir.glob("*.sql")):
                    if script.name in known:
                        continue
                    connection.executescript(script.read_text(encoding="utf-8"))
                    connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (script.name,))
                    applied.append(script.name)
        return applied

    def healthy(self) -> bool:
        try:
            with closing(self._connect()) as connection:
                return connection.execute("SELECT 1").fetchone() == (1,)
        except sqlite3.Error:
            return False

    def save_lesson(self, lesson: Lesson) -> None:
        """Persist only the structured lesson; source media never enters SQLite."""

        payload = json.dumps(lesson.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO lessons(
                        lesson_id, schema_version, review_status, payload_json
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(lesson_id) DO UPDATE SET
                        schema_version = excluded.schema_version,
                        review_status = excluded.review_status,
                        payload_json = excluded.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (lesson.lesson_id, lesson.schema_version, lesson.review_status, payload),
                )

    def get_lesson(self, lesson_id: str) -> Lesson | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM lessons WHERE lesson_id = ?",
                (lesson_id,),
            ).fetchone()
        if row is None:
            return None
        return Lesson.model_validate(json.loads(row[0]))

    def update_lesson(self, lesson_id: str, patch: dict[str, object]) -> Lesson | None:
        current = self.get_lesson(lesson_id)
        if current is None:
            return None
        payload = current.model_dump(mode="json")
        for field, value in patch.items():
            if value is not None:
                payload[field] = value
        updated = Lesson.model_validate(payload)
        self.save_lesson(updated)
        return updated
