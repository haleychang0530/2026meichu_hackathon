from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


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
