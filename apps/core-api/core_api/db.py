from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Lesson


@dataclass(frozen=True, slots=True)
class SessionRow:
    session_id: str
    lesson_id: str
    schema_version: str
    state: str
    phase: str
    progress: float
    current_prompt: str | None
    revision: int
    hint_level: int
    language_ratio_zh: float
    language_ratio_nan: float
    paused: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event_id: int
    session_id: str
    event_type: str
    request_id: str
    idempotency_key: str
    revision: int
    payload: dict[str, Any]
    created_at: str


class SessionRevisionConflict(Exception):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f"session revision is {current_revision}")
        self.current_revision = current_revision


class SessionIdempotencyConflict(Exception):
    def __init__(self, event_type: str) -> None:
        super().__init__(f"idempotency key already belongs to {event_type}")
        self.event_type = event_type


_SESSION_COLUMNS = (
    "session_id, lesson_id, schema_version, state, phase, progress, current_prompt, "
    "revision, hint_level, language_ratio_zh, language_ratio_nan, paused, created_at, updated_at"
)


class Database:
    def __init__(self, path: Path, migration_dir: Path) -> None:
        self.path = path
        self.migration_dir = migration_dir

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
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
                row = connection.execute("SELECT 1").fetchone()
                return row is not None and row[0] == 1
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

    @staticmethod
    def _session_from_row(row: sqlite3.Row | None) -> SessionRow | None:
        if row is None:
            return None
        return SessionRow(
            session_id=str(row["session_id"]),
            lesson_id=str(row["lesson_id"]),
            schema_version=str(row["schema_version"]),
            state=str(row["state"]),
            phase=str(row["phase"]),
            progress=float(row["progress"]),
            current_prompt=row["current_prompt"],
            revision=int(row["revision"]),
            hint_level=int(row["hint_level"]),
            language_ratio_zh=float(row["language_ratio_zh"]),
            language_ratio_nan=float(row["language_ratio_nan"]),
            paused=bool(row["paused"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row | None) -> StoredEvent | None:
        if row is None:
            return None
        return StoredEvent(
            event_id=int(row["event_id"]),
            session_id=str(row["session_id"]),
            event_type=str(row["event_type"]),
            request_id=str(row["request_id"]),
            idempotency_key=str(row["idempotency_key"]),
            revision=int(row["revision"]),
            payload=json.loads(row["payload_json"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _event_by_key(connection: sqlite3.Connection, session_id: str, idempotency_key: str) -> StoredEvent | None:
        row = connection.execute(
            "SELECT event_id, session_id, event_type, request_id, idempotency_key, revision, payload_json, created_at "
            "FROM events WHERE session_id = ? AND idempotency_key = ?",
            (session_id, idempotency_key),
        ).fetchone()
        return Database._event_from_row(row)

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        session_id: str,
        event_type: str,
        request_id: str,
        idempotency_key: str,
        revision: int,
        payload: dict[str, Any],
    ) -> StoredEvent:
        cursor = connection.execute(
            """
            INSERT INTO events(
                session_id, event_type, request_id, idempotency_key, revision, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                event_type,
                request_id,
                idempotency_key,
                revision,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        event_id = int(cursor.lastrowid)
        return StoredEvent(
            event_id=event_id,
            session_id=session_id,
            event_type=event_type,
            request_id=request_id,
            idempotency_key=idempotency_key,
            revision=revision,
            payload=payload,
            created_at="",
        )

    @staticmethod
    def _finalize_event_payload(
        connection: sqlite3.Connection,
        event: StoredEvent,
        payload: dict[str, Any],
    ) -> StoredEvent:
        finalized = dict(payload)
        finalized["last_event_id"] = event.event_id
        connection.execute(
            "UPDATE events SET payload_json = ? WHERE event_id = ?",
            (json.dumps(finalized, ensure_ascii=False, separators=(",", ":")), event.event_id),
        )
        return StoredEvent(
            event_id=event.event_id,
            session_id=event.session_id,
            event_type=event.event_type,
            request_id=event.request_id,
            idempotency_key=event.idempotency_key,
            revision=event.revision,
            payload=finalized,
            created_at=event.created_at,
        )

    def get_session(self, session_id: str) -> SessionRow | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_from_row(row)

    def get_idempotent_event(self, session_id: str, idempotency_key: str) -> StoredEvent | None:
        with closing(self._connect()) as connection:
            return self._event_by_key(connection, session_id, idempotency_key)

    def create_session(
        self,
        *,
        session_id: str,
        lesson_id: str,
        schema_version: str,
        state: str,
        phase: str,
        progress: float,
        current_prompt: str | None,
        hint_level: int,
        language_ratio_zh: float,
        language_ratio_nan: float,
        paused: bool,
        creation_idempotency_key: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> tuple[SessionRow, StoredEvent, bool]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE creation_idempotency_key = ?",
                    (creation_idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing = self._session_from_row(existing_row)
                    assert existing is not None
                    if existing.lesson_id != lesson_id:
                        raise SessionIdempotencyConflict("session.created")
                    event = self._event_by_key(connection, existing.session_id, creation_idempotency_key)
                    if event is None:
                        raise RuntimeError("session creation event is missing")
                    connection.commit()
                    return existing, event, True

                connection.execute(
                    """
                    INSERT INTO sessions(
                        session_id, lesson_id, schema_version, state, phase, progress,
                        current_prompt, revision, hint_level, language_ratio_zh,
                        language_ratio_nan, paused, creation_idempotency_key, created_request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        lesson_id,
                        schema_version,
                        state,
                        phase,
                        progress,
                        current_prompt,
                        hint_level,
                        language_ratio_zh,
                        language_ratio_nan,
                        int(paused),
                        creation_idempotency_key,
                        request_id,
                    ),
                )
                event = self._insert_event(
                    connection,
                    session_id=session_id,
                    event_type="session.created",
                    request_id=request_id,
                    idempotency_key=creation_idempotency_key,
                    revision=0,
                    payload=payload,
                )
                event = self._finalize_event_payload(connection, event, payload)
                row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                created = self._session_from_row(row)
                assert created is not None
                connection.commit()
                return created, event, False
            except Exception:
                connection.rollback()
                raise

    def commit_action(
        self,
        *,
        session_id: str,
        expected_revision: int | None,
        idempotency_key: str,
        request_id: str,
        updates: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[SessionRow, StoredEvent, bool]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._event_by_key(connection, session_id, idempotency_key)
                if existing is not None:
                    if existing.event_type != "session.action":
                        raise SessionIdempotencyConflict(existing.event_type)
                    row = connection.execute(
                        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    current = self._session_from_row(row)
                    if current is None:
                        raise KeyError(session_id)
                    connection.commit()
                    return current, existing, True

                row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                current = self._session_from_row(row)
                if current is None:
                    raise KeyError(session_id)
                if expected_revision is not None and current.revision != expected_revision:
                    raise SessionRevisionConflict(current.revision)

                new_revision = current.revision + 1
                connection.execute(
                    """
                    UPDATE sessions SET
                        state = ?, phase = ?, progress = ?, current_prompt = ?,
                        revision = ?, hint_level = ?, language_ratio_zh = ?,
                        language_ratio_nan = ?, paused = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = ? AND revision = ?
                    """,
                    (
                        updates["state"],
                        updates["phase"],
                        updates["progress"],
                        updates["current_prompt"],
                        new_revision,
                        updates["hint_level"],
                        updates["language_ratio_zh"],
                        updates["language_ratio_nan"],
                        int(updates["paused"]),
                        session_id,
                        current.revision,
                    ),
                )
                event = self._insert_event(
                    connection,
                    session_id=session_id,
                    event_type="session.action",
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    revision=new_revision,
                    payload=payload,
                )
                event = self._finalize_event_payload(connection, event, payload)
                row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                updated = self._session_from_row(row)
                assert updated is not None
                connection.commit()
                return updated, event, False
            except Exception:
                connection.rollback()
                raise

    def commit_turn(
        self,
        *,
        session_id: str,
        expected_revision: int | None,
        idempotency_key: str,
        request_id: str,
        turn_id: str,
        transcript_raw: str,
        transcript_normalized: str,
        result: str,
        result_payload: dict[str, Any],
        updates: dict[str, Any],
        mastery_updates: list[dict[str, Any]],
    ) -> tuple[SessionRow, StoredEvent, bool]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._event_by_key(connection, session_id, idempotency_key)
                if existing is not None:
                    if existing.event_type != "turn.completed":
                        raise SessionIdempotencyConflict(existing.event_type)
                    row = connection.execute(
                        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    current = self._session_from_row(row)
                    if current is None:
                        raise KeyError(session_id)
                    connection.commit()
                    return current, existing, True

                row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                current = self._session_from_row(row)
                if current is None:
                    raise KeyError(session_id)
                if expected_revision is not None and current.revision != expected_revision:
                    raise SessionRevisionConflict(current.revision)

                new_revision = current.revision + 1
                connection.execute(
                    """
                    UPDATE sessions SET
                        state = ?, phase = ?, progress = ?, current_prompt = ?,
                        revision = ?, hint_level = ?, language_ratio_zh = ?,
                        language_ratio_nan = ?, paused = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = ? AND revision = ?
                    """,
                    (
                        updates["state"],
                        updates["phase"],
                        updates["progress"],
                        updates["current_prompt"],
                        new_revision,
                        updates["hint_level"],
                        updates["language_ratio_zh"],
                        updates["language_ratio_nan"],
                        int(updates["paused"]),
                        session_id,
                        current.revision,
                    ),
                )
                event = self._insert_event(
                    connection,
                    session_id=session_id,
                    event_type="turn.completed",
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    revision=new_revision,
                    payload=result_payload,
                )
                event = self._finalize_event_payload(connection, event, result_payload)
                final_result = dict(result_payload)
                final_result["last_event_id"] = event.event_id
                connection.execute(
                    """
                    INSERT INTO turns(
                        turn_id, session_id, request_id, idempotency_key, revision,
                        transcript_raw, transcript_normalized, result, result_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        session_id,
                        request_id,
                        idempotency_key,
                        new_revision,
                        transcript_raw,
                        transcript_normalized,
                        result,
                        json.dumps(final_result, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                for mastery in mastery_updates:
                    connection.execute(
                        """
                        INSERT INTO mastery(
                            session_id, concept, status, attempts, correct_count,
                            partial_count, retry_count, hint_level,
                            language_ratio_zh, language_ratio_nan, last_result
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, concept) DO UPDATE SET
                            status = excluded.status,
                            attempts = excluded.attempts,
                            correct_count = excluded.correct_count,
                            partial_count = excluded.partial_count,
                            retry_count = excluded.retry_count,
                            hint_level = excluded.hint_level,
                            language_ratio_zh = excluded.language_ratio_zh,
                            language_ratio_nan = excluded.language_ratio_nan,
                            last_result = excluded.last_result,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            session_id,
                            mastery["concept"],
                            mastery["status"],
                            mastery["attempts"],
                            mastery["correct_count"],
                            mastery["partial_count"],
                            mastery["retry_count"],
                            mastery["hint_level"],
                            mastery["language_ratio_zh"],
                            mastery["language_ratio_nan"],
                            mastery["last_result"],
                        ),
                    )
                row = connection.execute(
                    f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                updated = self._session_from_row(row)
                assert updated is not None
                connection.commit()
                return updated, event, False
            except Exception:
                connection.rollback()
                raise

    def get_turn_payloads(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT result_json FROM turns WHERE session_id = ? ORDER BY revision, turn_id",
                (session_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_mastery(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT concept, status, attempts, correct_count, partial_count,
                       retry_count, hint_level, language_ratio_zh,
                       language_ratio_nan, last_result
                FROM mastery WHERE session_id = ? ORDER BY concept
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_hint_history(self, session_id: str) -> list[dict[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, payload_json FROM events
                WHERE session_id = ? AND event_type = 'session.action'
                ORDER BY event_id
                """,
                (session_id,),
            ).fetchall()
        history: list[dict[str, str]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("action") != "request_hint":
                continue
            history.append(
                {
                    "turn_id": f"turn_hint_{int(row['event_id'])}",
                    "prompt": str(payload.get("current_prompt") or payload.get("next_prompt") or "提示已準備完成。"),
                    "feedback": str(payload.get("feedback") or "提示已準備完成。"),
                }
            )
        return history

    def get_events(self, session_id: str, after_event_id: int = 0) -> list[StoredEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, session_id, event_type, request_id,
                       idempotency_key, revision, payload_json, created_at
                FROM events WHERE session_id = ? AND event_id > ?
                ORDER BY event_id
                """,
                (session_id, after_event_id),
            ).fetchall()
        return [event for row in rows if (event := self._event_from_row(row)) is not None]

    def get_last_event_id(self, session_id: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) FROM events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row[0] if row else 0)
