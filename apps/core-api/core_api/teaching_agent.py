from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from .db import SessionRow
from .models import Lesson, SemanticJudgement


class SemanticJudge(Protocol):
    async def judge_answer(
        self,
        request_id: str,
        *,
        transcript: str,
        expected_concepts: list[str],
        lesson_context: dict[str, str],
    ) -> SemanticJudgement: ...


@dataclass(frozen=True, slots=True)
class ActionDecision:
    updates: dict[str, Any]
    feedback: str | None
    next_prompt: str | None
    can_answer: bool


@dataclass(frozen=True, slots=True)
class TurnDecision:
    updates: dict[str, Any]
    result: str
    matched_concepts: list[str]
    feedback: str
    next_prompt: str
    transcript_normalized: str
    fallbacks: list[str]
    mastery_updates: list[dict[str, Any]]
    semantic_latency_ms: int | None


_NON_WORD = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_transcript(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold().strip()
    return _NON_WORD.sub("", folded)


class TeachingAgent:
    """Laptop-owned deterministic teaching state machine.

    The agent only asks a semantic judge after local concept matching cannot
    decide a sufficiently long response. The judge is optional so fixture and
    MI300-offline sessions remain usable without a remote dependency.
    """

    def __init__(self, semantic_judge: SemanticJudge | None = None, *, semantic_timeout_seconds: float = 4.0) -> None:
        self.semantic_judge = semantic_judge
        self.semantic_timeout_seconds = semantic_timeout_seconds

    def start_session(self, lesson: Lesson) -> dict[str, Any]:
        return {
            "state": "SPEAKING",
            "phase": "introduction",
            "progress": 0.0,
            "current_prompt": self.prompt_for(lesson, "introduction", 0, 0.7, {}),
            "hint_level": 0,
            "language_ratio_zh": 0.7,
            "language_ratio_nan": 0.3,
            "paused": False,
        }

    def prompt_for(
        self,
        lesson: Lesson,
        phase: str,
        hint_level: int,
        language_ratio_zh: float,
        mastery: dict[str, dict[str, Any]],
        *,
        hinted_phase: str | None = None,
    ) -> str:
        vocabulary = lesson.vocabulary
        first = vocabulary[0] if vocabulary else None
        concepts = [item.hanji for item in vocabulary[:3]]
        if phase == "introduction":
            return f"今天我們來學習「{lesson.topic}」。{lesson.scene}"
        if phase == "demonstration":
            if first is None:
                return "先聽一次示範，等一下請跟著說。"
            return f"先聽示範：「{first.tailo}」，意思是「{first.meaning}」。請準備跟讀。"
        if phase == "read_aloud":
            return f"請跟讀這句：{lesson.source_text}"
        if phase == "comprehension":
            return f"請回答活動：{lesson.accessible_activity}"
        if phase == "hint":
            hint = self._hint_text(lesson, hint_level)
            if hinted_phase in {"demonstration", "read_aloud", "comprehension", "review"}:
                activity_prompt = self.prompt_for(
                    lesson,
                    hinted_phase,
                    0,
                    language_ratio_zh,
                    mastery,
                )
                return f"目前題目：{activity_prompt} {hint}"
            return hint

        if phase == "review":
            weak = self._weakest_concept(lesson, mastery)
            if weak is None:
                return "我們來複習剛才的重點，請說出一個關鍵詞。"
            return f"來複習「{weak}」：請說出它的台語或意思。"
        return "本課完成。"

    def _hint_text(self, lesson: Lesson, hint_level: int) -> str:
        concepts = [item.hanji for item in lesson.vocabulary[:3]]
        if hint_level <= 1:
            return "提示：先想想這一課的情境，再用一句話回答。"
        if hint_level == 2:
            joined = "、".join(concepts) or "課文詞語"
            return f"再提示：課文裡有「{joined}」，請說出和活動有關的詞語。"
        first = lesson.vocabulary[0] if lesson.vocabulary else None
        if first is not None:
            return f"最後提示：可以從「{first.meaning}」這個意思開始回答。"
        return "最後提示：請用你聽到的關鍵詞再回答一次。"

    def prompt_for_session(self, lesson: Lesson, row: SessionRow) -> str | None:
        """Return a student prompt that can repair older persisted hint states."""

        if row.phase != "hint":
            return row.current_prompt
        return self.prompt_for(
            lesson,
            "hint",
            row.hint_level,
            row.language_ratio_zh,
            {},
            hinted_phase=self.effective_phase(row),
        )

    @staticmethod
    def _weakest_concept(lesson: Lesson, mastery: dict[str, dict[str, Any]]) -> str | None:
        if not lesson.vocabulary:
            return None
        ranked = sorted(
            lesson.vocabulary,
            key=lambda item: (
                {"new": 0, "developing": 1, "familiar": 2}.get(
                    str(mastery.get(item.hanji, {}).get("status", "new")), 0
                ),
                int(mastery.get(item.hanji, {}).get("correct_count", 0)),
            ),
        )
        return ranked[0].hanji

    @staticmethod
    def effective_phase(row: SessionRow) -> str:
        if row.phase != "hint":
            return row.phase
        if row.progress < 0.34:
            return "read_aloud"
        if row.progress < 0.67:
            return "comprehension"
        return "review"

    def apply_action(self, row: SessionRow, lesson: Lesson, action: str) -> ActionDecision:
        phase = row.phase
        state = row.state
        progress = row.progress
        hint_level = row.hint_level
        paused = row.paused
        feedback: str | None = None
        hinted_phase = self.effective_phase(row) if action == "request_hint" or row.phase == "hint" else None

        if action == "pause":
            paused = True
            state = "IDLE"
            feedback = "已暫停，回來時可以繼續目前活動。"
        elif action == "resume":
            paused = False
            state = "COMPLETE" if phase == "complete" else "SPEAKING"
            feedback = "已繼續目前活動。"
        elif action == "replay_prompt":
            paused = False
            state = "COMPLETE" if phase == "complete" else "SPEAKING"
            feedback = "現在重播目前提示。"
        elif action == "start_answer":
            if phase == "complete":
                state = "COMPLETE"
                feedback = "這一課已完成。"
            else:
                paused = False
                state = "LISTENING"
                feedback = "可以開始回答。"
        elif action == "request_hint":
            if phase == "complete":
                state = "COMPLETE"
                feedback = "這一課已完成。"
            else:
                hint_level = min(3, row.hint_level + 1)
                phase = "hint"
                paused = False
                state = "SPEAKING"
                feedback = f"已提供第 {hint_level} 層提示。"
        elif action == "next":
            phase = self._next_phase(row)
            paused = False
            hint_level = 0 if phase != "hint" else row.hint_level
            state = "COMPLETE" if phase == "complete" else "SPEAKING"
            if phase == "complete":
                progress = 1.0
                feedback = "本課完成，做得很好。"
            else:
                feedback = "已進入下一個活動。"

        prompt = self.prompt_for(
            lesson,
            phase,
            hint_level,
            row.language_ratio_zh,
            {},
            hinted_phase=hinted_phase if phase == "hint" else None,
        )
        updates = {
            "state": state,
            "phase": phase,
            "progress": progress,
            "current_prompt": prompt,
            "hint_level": hint_level,
            "language_ratio_zh": row.language_ratio_zh,
            "language_ratio_nan": row.language_ratio_nan,
            "paused": paused,
        }
        return ActionDecision(
            updates=updates,
            feedback=feedback,
            next_prompt=prompt,
            can_answer=state == "LISTENING" and phase != "complete",
        )

    @staticmethod
    def _next_phase(row: SessionRow) -> str:
        phase = row.phase
        if phase == "introduction":
            return "demonstration"
        if phase == "demonstration":
            return "read_aloud"
        if phase == "hint":
            return TeachingAgent.effective_phase(row)
        if phase == "read_aloud":
            return "comprehension"
        if phase == "comprehension":
            return "review"
        if phase == "review":
            return "complete"
        return "complete"

    @staticmethod
    def _concepts(lesson: Lesson) -> list[tuple[str, tuple[str, ...]]]:
        concepts: list[tuple[str, tuple[str, ...]]] = []
        for item in lesson.vocabulary:
            variants = tuple(
                dict.fromkeys(
                    normalize_transcript(value)
                    for value in (item.hanji, item.tailo, item.meaning)
                    if value and normalize_transcript(value)
                )
            )
            if variants:
                concepts.append((item.hanji, variants))
        return concepts

    @staticmethod
    def _matched_concepts(lesson: Lesson, normalized: str) -> list[str]:
        return [
            display
            for display, variants in TeachingAgent._concepts(lesson)
            if any(variant in normalized for variant in variants)
        ]

    async def evaluate_turn(
        self,
        row: SessionRow,
        lesson: Lesson,
        transcript: str,
        request_id: str,
        mastery_rows: list[dict[str, Any]],
    ) -> TurnDecision:
        normalized = normalize_transcript(transcript)
        active_phase = self.effective_phase(row)
        concepts = self._matched_concepts(lesson, normalized)
        outcome: str | None = None
        semantic_latency_ms: int | None = None
        fallbacks: list[str] = []

        if active_phase == "read_aloud":
            source = normalize_transcript(lesson.source_text)
            if source and source in normalized:
                outcome = "correct"
            elif concepts:
                outcome = "partial"
        elif active_phase in {"comprehension", "review"} and concepts:
            outcome = "correct"

        if outcome is None and normalized and len(normalized) >= 3 and self.semantic_judge is not None:
            context = {
                "topic": lesson.topic,
                "scene": lesson.scene,
                "activity": lesson.accessible_activity,
            }
            expected = [display for display, _variants in self._concepts(lesson)]
            started = perf_counter()
            try:
                judged = await asyncio.wait_for(
                    self.semantic_judge.judge_answer(
                        request_id,
                        transcript=transcript,
                        expected_concepts=expected,
                        lesson_context=context,
                    ),
                    timeout=self.semantic_timeout_seconds,
                )
                semantic_latency_ms = judged.latency_ms or round((perf_counter() - started) * 1000)
                outcome = judged.decision
                concepts = [concept for concept in judged.matched_concepts if concept in expected]
            except asyncio.TimeoutError:
                fallbacks.append("mi300_offline")
            except Exception:
                # The detailed upstream error is deliberately not copied into
                # logs or student data; the safe fallback is enough.
                fallbacks.append("mi300_offline")
        elif outcome is None and not concepts:
            fallbacks.append("fixture_mode") if self.semantic_judge is None else None

        outcome = outcome or "retry"
        if outcome not in {"correct", "partial", "retry"}:
            outcome = "retry"
        mastery_by_concept = {str(item["concept"]): item for item in mastery_rows}
        zh_ratio, nan_ratio = self._language_ratios(row, outcome)
        updates: dict[str, Any]
        if outcome == "correct":
            next_phase, progress = self._after_correct(active_phase, row.progress)
            next_hint_level = 0
            state = "COMPLETE" if next_phase == "complete" else "SPEAKING"
            next_prompt = self.prompt_for(lesson, next_phase, next_hint_level, zh_ratio, mastery_by_concept)
            feedback = "答對了，繼續下一個活動。" if next_phase != "complete" else "本課完成，做得很好。"
        else:
            next_phase = "hint"
            progress = row.progress
            next_hint_level = min(3, row.hint_level + 1)
            state = "SPEAKING"
            next_prompt = self.prompt_for(
                lesson,
                next_phase,
                next_hint_level,
                zh_ratio,
                mastery_by_concept,
                hinted_phase=active_phase,
            )
            feedback = (
                "有抓到部分重點，我給你一個提示。"
                if outcome == "partial"
                else "我們再試一次，我先提供提示。"
            )
        updates = {
            "state": state,
            "phase": next_phase,
            "progress": progress,
            "current_prompt": next_prompt,
            "hint_level": next_hint_level,
            "language_ratio_zh": zh_ratio,
            "language_ratio_nan": nan_ratio,
            "paused": False,
        }
        return TurnDecision(
            updates=updates,
            result=outcome,
            matched_concepts=concepts,
            feedback=feedback,
            next_prompt=next_prompt,
            transcript_normalized=normalized,
            fallbacks=fallbacks,
            mastery_updates=self._mastery_updates(
                lesson,
                mastery_by_concept,
                concepts,
                outcome,
                next_hint_level,
                zh_ratio,
                nan_ratio,
            ),
            semantic_latency_ms=semantic_latency_ms,
        )

    @staticmethod
    def _after_correct(active_phase: str, progress: float) -> tuple[str, float]:
        if active_phase == "read_aloud":
            return "comprehension", max(progress, 0.34)
        if active_phase == "comprehension":
            return "review", max(progress, 0.67)
        if active_phase == "review":
            return "complete", 1.0
        return "comprehension", max(progress, 0.34)

    @staticmethod
    def _language_ratios(row: SessionRow, outcome: str) -> tuple[float, float]:
        if outcome == "correct":
            zh = max(0.2, row.language_ratio_zh - 0.1)
        elif outcome == "partial":
            zh = min(0.8, row.language_ratio_zh + 0.05)
        else:
            zh = min(0.85, row.language_ratio_zh + 0.15)
        return round(zh, 3), round(1.0 - zh, 3)

    @staticmethod
    def _mastery_updates(
        lesson: Lesson,
        current: dict[str, dict[str, Any]],
        matched: list[str],
        outcome: str,
        hint_level: int,
        zh_ratio: float,
        nan_ratio: float,
    ) -> list[dict[str, Any]]:
        targets = list(matched)
        if not targets and lesson.vocabulary:
            targets = [lesson.vocabulary[0].hanji]
        updates: list[dict[str, Any]] = []
        for concept in dict.fromkeys(targets):
            old = current.get(concept, {})
            attempts = int(old.get("attempts", 0)) + 1
            correct = int(old.get("correct_count", 0)) + (1 if outcome == "correct" else 0)
            partial = int(old.get("partial_count", 0)) + (1 if outcome == "partial" else 0)
            retry = int(old.get("retry_count", 0)) + (1 if outcome == "retry" else 0)
            status = "familiar" if correct >= 2 else "developing"
            updates.append(
                {
                    "concept": concept,
                    "status": status,
                    "attempts": attempts,
                    "correct_count": correct,
                    "partial_count": partial,
                    "retry_count": retry,
                    "hint_level": hint_level,
                    "language_ratio_zh": zh_ratio,
                    "language_ratio_nan": nan_ratio,
                    "last_result": outcome,
                }
            )
        return updates
