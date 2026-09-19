from __future__ import annotations

from typing import Any

from .db import SessionRow, StoredEvent
from .models import (
    Familiarity,
    HealthResponse,
    Lesson,
    ObserverHint,
    ObserverSessionSummary,
    SessionEvent,
    SessionView,
    StudentActionResult,
    TurnResult,
    Utterance,
)


def select_student_session(
    row: SessionRow,
    last_event_id: int,
    *,
    current_prompt: str | None = None,
    current_utterance: Utterance | None = None,
) -> SessionView:
    """Return the strict student projection and nothing teacher-only."""

    return SessionView(
        session_id=row.session_id,
        lesson_id=row.lesson_id,
        state=row.state,  # type: ignore[arg-type]
        phase=row.phase,  # type: ignore[arg-type]
        progress=row.progress,
        current_prompt=row.current_prompt if current_prompt is None else current_prompt,
        current_utterance=current_utterance,
        can_answer=row.state == "LISTENING" and row.phase != "complete",
        revision=row.revision,
        last_event_id=last_event_id,
    )


def select_student_action(
    row: SessionRow,
    action: str,
    feedback: str | None,
    next_prompt: str | None,
    last_event_id: int,
    *,
    current_utterance: Utterance | None = None,
    feedback_utterance: Utterance | None = None,
    next_utterance: Utterance | None = None,
) -> StudentActionResult:
    """Keep answers, evidence, confidence, and review controls out of actions."""

    return StudentActionResult(
        session_id=row.session_id,
        lesson_id=row.lesson_id,
        state=row.state,  # type: ignore[arg-type]
        progress=row.progress,
        current_prompt=row.current_prompt,
        current_utterance=current_utterance,
        action=action,  # type: ignore[arg-type]
        feedback=feedback,
        next_prompt=next_prompt,
        feedback_utterance=feedback_utterance,
        next_utterance=next_utterance,
        can_answer=row.state == "LISTENING" and row.phase != "complete",
        phase=row.phase,  # type: ignore[arg-type]
        revision=row.revision,
        last_event_id=last_event_id,
    )


def select_turn(payload: dict[str, Any], last_event_id: int | None = None) -> TurnResult:
    data = dict(payload)
    if last_event_id is not None:
        data["last_event_id"] = last_event_id
    return TurnResult.model_validate(data)


def select_observer_summary(
    row: SessionRow,
    lesson: Lesson,
    turn_payloads: list[dict[str, Any]],
    mastery_rows: list[dict[str, Any]],
    hint_rows: list[dict[str, str]],
    health: HealthResponse,
    last_event_id: int,
) -> ObserverSessionSummary:
    turns = [select_turn(payload) for payload in turn_payloads]
    familiarity = [
        Familiarity(concept=str(item["concept"]), status=str(item["status"]))  # type: ignore[arg-type]
        for item in mastery_rows
    ]
    hints = [ObserverHint.model_validate(item) for item in hint_rows]
    return ObserverSessionSummary(
        session_id=row.session_id,
        lesson_id=row.lesson_id,
        state=row.state,  # type: ignore[arg-type]
        progress=row.progress,
        completed_turns=len(turns),
        turns=turns,
        concepts_to_review=[item.concept for item in familiarity if item.status != "familiar"],
        hint_history=hints,
        familiarity=familiarity,
        evidence=lesson.evidence,
        health=health.services,
        review_status=lesson.review_status,
        confidence=lesson.confidence,
        answer_evidence=list(lesson.answer_evidence),
        vlm_model_revision=lesson.vlm_model_revision,
        rag_index_revision=lesson.rag_index_revision,
        phase=row.phase,  # type: ignore[arg-type]
        revision=row.revision,
        last_event_id=last_event_id,
    )


def select_event(event: StoredEvent) -> SessionEvent:
    return SessionEvent(
        event_id=event.event_id,
        session_id=event.session_id,
        event=event.event_type,
        request_id=event.request_id,
        revision=event.revision,
        payload=event.payload,
    )
