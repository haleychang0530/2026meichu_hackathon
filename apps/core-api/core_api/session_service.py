from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from .db import (
    Database,
    SessionIdempotencyConflict,
    SessionRevisionConflict,
    SessionRow,
    StoredEvent,
)
from .errors import AppError
from .health import HealthAggregator
from .models import (
    ErrorCode,
    HealthResponse,
    Lesson,
    ObserverSessionSummary,
    SessionEvent,
    SessionView,
    StudentActionResult,
    TurnResult,
    TurnSubmission,
)
from .selectors import (
    select_event,
    select_observer_summary,
    select_student_action,
    select_student_session,
)
from .teaching_agent import ActionDecision, TeachingAgent


@dataclass(frozen=True, slots=True)
class ActionCommandResult:
    response: StudentActionResult
    event: StoredEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class SessionCommandResult:
    response: SessionView
    event: StoredEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class TurnCommandResult:
    response: TurnResult
    event: StoredEvent
    replayed: bool


class SessionService:
    def __init__(self, database: Database, teaching_agent: TeachingAgent, health: HealthAggregator) -> None:
        self.database = database
        self.teaching_agent = teaching_agent
        self.health = health

    async def create_session(
        self,
        lesson_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> SessionCommandResult:
        lesson = await asyncio.to_thread(self.database.get_lesson, lesson_id)
        if lesson is None:
            raise AppError(
                ErrorCode.LESSON_NOT_FOUND,
                "lesson was not found",
                status_code=404,
                fallback="manual_review",
            )
        initial = self.teaching_agent.start_session(lesson)
        session_id = f"session_{uuid.uuid4().hex[:16]}"
        view = SessionView(
            session_id=session_id,
            lesson_id=lesson_id,
            state=initial["state"],
            phase=initial["phase"],
            progress=initial["progress"],
            current_prompt=initial["current_prompt"],
            can_answer=False,
            revision=0,
            last_event_id=0,
        )
        try:
            row, event, _replayed = await asyncio.to_thread(
                self.database.create_session,
                session_id=session_id,
                lesson_id=lesson_id,
                schema_version="0.1.0",
                state=initial["state"],
                phase=initial["phase"],
                progress=initial["progress"],
                current_prompt=initial["current_prompt"],
                hint_level=initial["hint_level"],
                language_ratio_zh=initial["language_ratio_zh"],
                language_ratio_nan=initial["language_ratio_nan"],
                paused=initial["paused"],
                creation_idempotency_key=idempotency_key,
                request_id=request_id,
                payload=view.model_dump(mode="json"),
            )
        except SessionIdempotencyConflict as exc:
            raise AppError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "the idempotency key was already used for another session",
                status_code=409,
                retryable=False,
                fallback="retry_later",
                details={"event_type": exc.event_type},
            ) from exc
        return SessionCommandResult(
            response=select_student_session(row, event.event_id),
            event=event,
            replayed=_replayed,
        )

    async def get_student_session(self, session_id: str) -> SessionView:
        row, lesson = await self._session_and_lesson(session_id)
        last_event_id = await asyncio.to_thread(self.database.get_last_event_id, session_id)
        return select_student_session(
            row,
            last_event_id,
            current_prompt=self.teaching_agent.prompt_for_session(lesson, row),
        )

    async def submit_action(
        self,
        session_id: str,
        action: str,
        request_id: str,
        idempotency_key: str,
        expected_revision: int | None,
    ) -> ActionCommandResult:
        existing = await asyncio.to_thread(self.database.get_idempotent_event, session_id, idempotency_key)
        if existing is not None:
            if existing.event_type != "session.action":
                raise self._idempotency_error(existing.event_type)
            return ActionCommandResult(
                response=StudentActionResult.model_validate(existing.payload),
                event=existing,
                replayed=True,
            )

        row, lesson = await self._session_and_lesson(session_id)
        decision: ActionDecision = self.teaching_agent.apply_action(row, lesson, action)
        projected = self._project_row(row, decision.updates, row.revision + 1)
        provisional = select_student_action(
            projected,
            action,
            decision.feedback,
            decision.next_prompt,
            0,
        )
        try:
            updated, event, replayed = await asyncio.to_thread(
                self.database.commit_action,
                session_id=session_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                request_id=request_id,
                updates=decision.updates,
                payload=provisional.model_dump(mode="json"),
            )
        except SessionRevisionConflict as exc:
            raise self._revision_error(exc.current_revision) from exc
        except SessionIdempotencyConflict as exc:
            raise self._idempotency_error(exc.event_type) from exc
        response = StudentActionResult.model_validate(
            {
                **event.payload,
                "revision": updated.revision,
                "last_event_id": event.event_id,
            }
        )
        return ActionCommandResult(response=response, event=event, replayed=replayed)

    async def submit_turn(
        self,
        session_id: str,
        body: TurnSubmission,
        request_id: str,
        idempotency_key: str,
        expected_revision: int | None,
    ) -> TurnCommandResult:
        existing = await asyncio.to_thread(self.database.get_idempotent_event, session_id, idempotency_key)
        if existing is not None:
            if existing.event_type != "turn.completed":
                raise self._idempotency_error(existing.event_type)
            return TurnCommandResult(
                response=TurnResult.model_validate(existing.payload),
                event=existing,
                replayed=True,
            )

        row, lesson = await self._session_and_lesson(session_id)
        mastery_rows = await asyncio.to_thread(self.database.get_mastery, session_id)
        started = time.perf_counter()
        decision = await self.teaching_agent.evaluate_turn(
            row,
            lesson,
            body.transcript,
            request_id,
            mastery_rows,
        )
        asr_device = body.asr_device or "cpu"
        fallbacks = list(decision.fallbacks)
        if asr_device == "cpu" and "asr_cpu" not in fallbacks:
            fallbacks.append("asr_cpu")
        backend_ms = max(0, round((time.perf_counter() - started) * 1000))
        turn_id = f"turn_{uuid.uuid4().hex[:16]}"
        provisional = TurnResult(
            turn_id=turn_id,
            session_id=session_id,
            transcript_raw=body.transcript,
            transcript_normalized=decision.transcript_normalized,
            result=decision.result,  # type: ignore[arg-type]
            matched_concepts=decision.matched_concepts,
            feedback=decision.feedback,
            next_prompt=decision.next_prompt,
            progress=float(decision.updates["progress"]),
            latency_ms={
                "asr": None,
                "backend": backend_ms,
                "vlm": decision.semantic_latency_ms,
                "tts": None,
                "total": backend_ms,
            },
            asr_device=asr_device,  # type: ignore[arg-type]
            fallbacks=fallbacks,  # type: ignore[arg-type]
            phase=decision.updates["phase"],  # type: ignore[arg-type]
            revision=row.revision + 1,
            last_event_id=0,
        )
        try:
            updated, event, replayed = await asyncio.to_thread(
                self.database.commit_turn,
                session_id=session_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                request_id=request_id,
                turn_id=turn_id,
                transcript_raw=body.transcript,
                transcript_normalized=decision.transcript_normalized,
                result=decision.result,
                result_payload=provisional.model_dump(mode="json"),
                updates=decision.updates,
                mastery_updates=decision.mastery_updates,
            )
        except SessionRevisionConflict as exc:
            raise self._revision_error(exc.current_revision) from exc
        except SessionIdempotencyConflict as exc:
            raise self._idempotency_error(exc.event_type) from exc
        response = TurnResult.model_validate(
            {
                **event.payload,
                "revision": updated.revision,
                "last_event_id": event.event_id,
            }
        )
        return TurnCommandResult(response=response, event=event, replayed=replayed)

    async def get_summary(self, session_id: str, request_id: str) -> ObserverSessionSummary:
        row, lesson = await self._session_and_lesson(session_id)
        turn_payloads, mastery_rows, hints, last_event_id, health = await asyncio.gather(
            asyncio.to_thread(self.database.get_turn_payloads, session_id),
            asyncio.to_thread(self.database.get_mastery, session_id),
            asyncio.to_thread(self.database.get_hint_history, session_id),
            asyncio.to_thread(self.database.get_last_event_id, session_id),
            self.health.snapshot(request_id),
        )
        return select_observer_summary(
            row,
            lesson,
            turn_payloads,
            mastery_rows,
            hints,
            health,
            last_event_id,
        )

    async def get_events(self, session_id: str, after_event_id: int) -> list[SessionEvent]:
        await self._session_and_lesson(session_id)
        events = await asyncio.to_thread(self.database.get_events, session_id, after_event_id)
        return [select_event(event) for event in events]

    async def _session_and_lesson(self, session_id: str) -> tuple[SessionRow, Lesson]:
        row = await asyncio.to_thread(self.database.get_session, session_id)
        if row is None:
            raise AppError(
                ErrorCode.SESSION_NOT_FOUND,
                "session was not found",
                status_code=404,
                fallback="manual_review",
            )
        lesson = await asyncio.to_thread(self.database.get_lesson, row.lesson_id)
        if lesson is None:
            raise AppError(
                ErrorCode.LESSON_NOT_FOUND,
                "session lesson was not found",
                status_code=404,
                fallback="manual_review",
            )
        return row, lesson

    @staticmethod
    def _project_row(row: SessionRow, updates: dict[str, Any], revision: int) -> SessionRow:
        return replace(
            row,
            state=str(updates["state"]),
            phase=str(updates["phase"]),
            progress=float(updates["progress"]),
            current_prompt=updates["current_prompt"],
            revision=revision,
            hint_level=int(updates["hint_level"]),
            language_ratio_zh=float(updates["language_ratio_zh"]),
            language_ratio_nan=float(updates["language_ratio_nan"]),
            paused=bool(updates["paused"]),
        )

    @staticmethod
    def _revision_error(current_revision: int) -> AppError:
        return AppError(
            ErrorCode.SESSION_REVISION_CONFLICT,
            "session changed; refresh the snapshot and retry",
            status_code=409,
            retryable=True,
            fallback="retry_later",
            details={"current_revision": current_revision},
        )

    @staticmethod
    def _idempotency_error(event_type: str) -> AppError:
        return AppError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "the idempotency key was already used for a different session operation",
            status_code=409,
            retryable=False,
            fallback="retry_later",
            details={"event_type": event_type},
        )
