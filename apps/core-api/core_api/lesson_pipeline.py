from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, SchemaError

from .errors import ProviderError
from .image_pipeline import PreparedImage
from .language import LanguageNormalizer
from .models import ErrorCode, EvidenceItem, Lesson, VocabularyItem
from .providers import StructuredGeneration
from .rag import HybridRetriever, RetrievalBundle


LOGGER = logging.getLogger("hear_our_language.lesson_pipeline")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class StructuredGenerator(Protocol):
    async def generate(
        self,
        image: PreparedImage,
        request_id: str,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
    ) -> StructuredGeneration: ...


class StageOutputError(ValueError):
    def __init__(self, stage: str, reasons: list[str], candidate: Any = None) -> None:
        super().__init__(f"{stage} output failed validation")
        self.stage = stage
        self.reasons = tuple(reasons)
        self.candidate = candidate


@dataclass(frozen=True, slots=True)
class GenerationTrace:
    stage: str
    attempts: int
    repair_attempted: bool
    model_revision: str


_SIGHTED_ONLY_HINTS = (
    "看圖",
    "看圖片",
    "觀看圖片",
    "觀察圖片",
    "觀察圖",
    "讀圖",
    "圈出",
    "指向",
    "指出圖",
    "圖片左",
    "圖片右",
    "圖片上",
    "圖片下",
    "顏色線索",
    "視覺線索",
)
_ANSWER_LEAK_PATTERNS = (
    re.compile(r"(?:正確)?答案(?:是|為|：|:)"),
    re.compile(r"正確的是"),
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def accessible_activity_issues(
    accessible_activity: str,
    answer_evidence: list[str] | tuple[str, ...],
    safety_checks: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return deterministic safety findings without exposing answer content.

    The returned reasons are safe metadata. They intentionally do not include
    the matched answer phrase or the full activity text in logs/errors.
    """

    activity = _compact(accessible_activity)
    folded = activity.casefold()
    reasons: list[str] = []
    checks = safety_checks or {}
    if checks.get("answer_leak_free") is not True:
        reasons.append("model_answer_leak_check_failed")
    if checks.get("no_sighted_only_clue") is not True:
        reasons.append("model_sighted_only_check_failed")

    if any(term.casefold() in folded for term in _SIGHTED_ONLY_HINTS):
        reasons.append("sighted_only_clue")
    if any(pattern.search(activity) for pattern in _ANSWER_LEAK_PATTERNS):
        reasons.append("answer_leak")

    for evidence in answer_evidence:
        phrase = _compact(str(evidence))
        # Short concepts such as 「買菜」 can be part of the learning goal,
        # so only reject copied answer-evidence sentences.
        if len(phrase) >= 8 and phrase.casefold() in folded:
            reasons.append("copied_answer_evidence")
            break
    return tuple(dict.fromkeys(reasons))


class LessonAnalysisPipeline:
    """Laptop orchestration for facts -> local RAG -> accessible activity."""

    def __init__(
        self,
        generator: StructuredGenerator | None,
        retriever: HybridRetriever,
        *,
        prompt_root: Path | None = None,
        language_normalizer: LanguageNormalizer | None = None,
    ) -> None:
        self.generator = generator
        self.retriever = retriever
        self.language_normalizer = language_normalizer
        self.prompt_root = prompt_root or (REPOSITORY_ROOT / "prompts" / "lesson-analysis")
        self.facts_prompt = (self.prompt_root / "facts.prompt.txt").read_text(encoding="utf-8")
        self.activity_prompt = (self.prompt_root / "activity.prompt.txt").read_text(encoding="utf-8")
        self.repair_prompt = (self.prompt_root / "repair.prompt.txt").read_text(encoding="utf-8")
        self.facts_schema = self._load_schema("facts.schema.json")
        self.activity_schema = self._load_schema("activity.schema.json")
        self.last_trace: tuple[GenerationTrace, ...] = ()

    def _load_schema(self, name: str) -> dict[str, Any]:
        payload = json.loads((self.prompt_root / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(payload)
        return payload

    @property
    def supports_two_step_generation(self) -> bool:
        return self.generator is not None

    async def analyze(self, image: PreparedImage, request_id: str) -> Lesson:
        if self.generator is None:
            raise ProviderError(
                ErrorCode.VLM_OFFLINE,
                "MI300 structured generator is not configured",
                status_code=503,
                retryable=True,
                fallback="fixture_mode",
            )

        traces: list[GenerationTrace] = []
        facts_generation = await self._generate_stage(
            image,
            request_id,
            stage="facts",
            prompt=self.facts_prompt,
            response_schema=self.facts_schema,
            evidence=None,
            semantic_validator=self._facts_issues,
            traces=traces,
        )
        facts = self._candidate(facts_generation)
        query = self._facts_query(facts)
        bundle = self.retriever.retrieve(query)
        compact_evidence = [citation.to_dict() for citation in bundle.evidence]
        activity_prompt = (
            f"{self.activity_prompt}\n\nFACTS (JSON):\n{self._bounded_json(facts)}\n\n"
            f"LOCAL RAG EVIDENCE (JSON):\n{self._bounded_json(compact_evidence)}"
        )
        activity_generation = await self._generate_stage(
            image,
            request_id,
            stage="activity",
            prompt=activity_prompt,
            response_schema=self.activity_schema,
            evidence=compact_evidence,
            semantic_validator=lambda candidate: self._activity_issues(candidate, facts),
            traces=traces,
        )
        activity = self._candidate(activity_generation)
        self.last_trace = tuple(traces)
        return self._assemble_lesson(
            facts,
            activity,
            bundle,
            model_revision=self._model_revision(activity_generation, facts_generation),
        )

    async def _generate_stage(
        self,
        image: PreparedImage,
        request_id: str,
        *,
        stage: str,
        prompt: str,
        response_schema: dict[str, Any],
        evidence: list[dict[str, Any]] | None,
        semantic_validator,
        traces: list[GenerationTrace],
    ) -> StructuredGeneration:
        assert self.generator is not None
        first_candidate: Any = None
        first_reasons: list[str] = []
        try:
            generation = await self.generator.generate(
                image,
                request_id,
                prompt=prompt,
                response_schema=response_schema,
                evidence=evidence,
            )
            first_candidate = self._candidate(generation)
            self._validate_schema(response_schema, first_candidate, stage)
            first_reasons = list(semantic_validator(first_candidate))
            if first_reasons:
                raise StageOutputError(stage, first_reasons, first_candidate)
            trace = GenerationTrace(stage, 1, False, self._model_revision_value(generation))
            traces.append(trace)
            self._log_trace(request_id, trace)
            return generation
        except ProviderError as error:
            if error.code != ErrorCode.VLM_INVALID_OUTPUT:
                raise
            first_reasons = ["structured_output_invalid"]
        except StageOutputError as error:
            first_reasons = list(error.reasons)

        repair_prompt = (
            f"{self.repair_prompt}\n\nSTAGE: {stage}\n"
            f"VALIDATION_REASONS: {json.dumps(first_reasons[:8], ensure_ascii=False)}\n"
            f"PREVIOUS_CANDIDATE_IF_PARSEABLE:\n{self._bounded_json(first_candidate)}"
        )
        try:
            repaired = await self.generator.generate(
                image,
                request_id,
                prompt=repair_prompt,
                response_schema=response_schema,
                evidence=evidence,
            )
            repaired_candidate = self._candidate(repaired)
            self._validate_schema(response_schema, repaired_candidate, stage)
            repaired_reasons = list(semantic_validator(repaired_candidate))
            if repaired_reasons:
                raise StageOutputError(stage, repaired_reasons, repaired_candidate)
        except ProviderError as error:
            if error.code != ErrorCode.VLM_INVALID_OUTPUT:
                raise
            raise self._repair_error(stage, first_reasons) from error
        except StageOutputError as error:
            raise self._repair_error(stage, list(error.reasons)) from error

        trace = GenerationTrace(stage, 2, True, self._model_revision_value(repaired))
        traces.append(trace)
        self._log_trace(request_id, trace)
        return repaired

    @staticmethod
    def _repair_error(stage: str, reasons: list[str]) -> ProviderError:
        return ProviderError(
            ErrorCode.VLM_INVALID_OUTPUT,
            f"{stage} output remained invalid after one repair attempt",
            status_code=503,
            retryable=False,
            fallback="manual_review",
            details={
                "stage": stage,
                "repair_attempted": True,
                "reasons": list(dict.fromkeys(reasons))[:8],
            },
        )

    @staticmethod
    def _validate_schema(schema: dict[str, Any], candidate: Any, stage: str) -> None:
        try:
            Draft202012Validator.check_schema(schema)
            errors = sorted(
                Draft202012Validator(schema).iter_errors(candidate),
                key=lambda error: list(error.path),
            )
        except SchemaError as error:
            raise StageOutputError(stage, ["pipeline_schema_invalid"]) from error
        if errors:
            reasons = [
                f"schema:{'.'.join(str(part) for part in error.path)[:120]}:{error.validator}"
                for error in errors[:8]
            ]
            raise StageOutputError(stage, reasons, candidate)

    @staticmethod
    def _facts_issues(facts: Any) -> tuple[str, ...]:
        if not isinstance(facts, dict):
            return ("facts_not_object",)
        reasons: list[str] = []
        source_text = facts.get("source_text")
        if not isinstance(source_text, str) or not source_text.strip():
            reasons.append("source_text_missing")
        reasons.extend(
            LessonAnalysisPipeline._language_segment_issues(
                facts.get("source_text"),
                facts.get("language_segments"),
                field="source_text",
            )
        )
        return tuple(reasons)

    @staticmethod
    def _activity_issues(activity: Any, facts: dict[str, Any]) -> tuple[str, ...]:
        if not isinstance(activity, dict):
            return ("activity_not_object",)
        reasons = list(
            accessible_activity_issues(
            str(activity.get("accessible_activity", "")),
            [str(item) for item in facts.get("answer_evidence", [])],
            activity.get("safety_checks") if isinstance(activity.get("safety_checks"), dict) else None,
            )
        )
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _language_segment_issues(
        text: Any,
        segments: Any,
        *,
        field: str,
    ) -> tuple[str, ...]:
        if not isinstance(text, str) or not text.strip():
            return (f"{field}_missing",)
        if not isinstance(segments, list) or not segments:
            return (f"{field}_language_segments_missing",)
        contents: list[str] = []
        reasons: list[str] = []
        for index, item in enumerate(segments):
            if not isinstance(item, dict):
                reasons.append(f"{field}_language_segment_{index}_invalid")
                continue
            if item.get("lang") not in {"zh-TW", "nan-TW"}:
                reasons.append(f"{field}_language_segment_{index}_lang_invalid")
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                reasons.append(f"{field}_language_segment_{index}_content_missing")
            else:
                contents.append(content)
        if _compact("".join(contents)) != _compact(text):
            reasons.append(f"{field}_language_segments_not_exact")
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _candidate(generation: StructuredGeneration) -> Any:
        return generation.candidate

    @staticmethod
    def _model_revision_value(generation: StructuredGeneration) -> str:
        return str(generation.model_revision or "unknown")

    def _model_revision(self, activity: StructuredGeneration, facts: StructuredGeneration) -> str:
        return self._model_revision_value(activity or facts)

    @staticmethod
    def _bounded_json(value: Any, limit: int = 12_000) -> str:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return serialized if len(serialized) <= limit else serialized[:limit] + "…"

    @staticmethod
    def _facts_query(facts: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("topic", "source_text", "scene", "original_activity"):
            value = facts.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        for item in facts.get("vocabulary", []):
            if not isinstance(item, dict):
                continue
            parts.extend(
                str(item.get(key)).strip()
                for key in ("hanji", "tailo", "meaning")
                if item.get(key)
            )
        for value in facts.get("visual_elements", []):
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        return " ".join(dict.fromkeys(parts))[:2400]

    @staticmethod
    def _bundle_evidence(bundle: RetrievalBundle) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                source_id=citation.source_id,
                title=citation.title,
                excerpt=citation.excerpt,
                locator=citation.locator,
            )
            for citation in bundle.evidence
        ]

    def _assemble_lesson(
        self,
        facts: dict[str, Any],
        activity: dict[str, Any],
        bundle: RetrievalBundle,
        *,
        model_revision: str,
    ) -> Lesson:
        vocabulary: list[VocabularyItem] = []
        for item in facts.get("vocabulary", []):
            if not isinstance(item, dict):
                continue
            hanji = str(item.get("hanji") or "").strip()
            meaning = str(item.get("meaning") or "").strip()
            tailo = str(item.get("tailo") or "").strip()
            if hanji and meaning and tailo:
                vocabulary.append(VocabularyItem(hanji=hanji, tailo=tailo, meaning=meaning, audio_key=None))

        quality_warnings = [
            str(item).strip()
            for item in facts.get("quality_warnings", [])
            if str(item).strip()
        ]
        if facts.get("source_text_complete") is not True:
            quality_warnings.append("教材原文完整性尚未確認，需教師審查。")
            quality_warnings = list(dict.fromkeys(quality_warnings))
        confidence = min(float(facts.get("confidence", 0.0)), float(activity.get("confidence", 0.0)))
        if quality_warnings:
            confidence *= 0.85
        answer_evidence = [
            str(item).strip()
            for item in facts.get("answer_evidence", [])
            if str(item).strip()
        ]
        source_text = facts["source_text"]
        if not isinstance(source_text, str) or not source_text.strip():
            raise StageOutputError("facts", ["source_text_missing"])
        lesson_id = f"lesson_{uuid.uuid4().hex[:16]}"
        source_utterance = None
        activity_utterance = None
        if self.language_normalizer is not None:
            try:
                source_utterance = self.language_normalizer.normalize_labeled_segments(
                    text=source_text,
                    segments=list(facts["language_segments"]),
                    utterance_id=f"utt_{lesson_id}_source",
                ).utterance
            except (TypeError, ValueError) as error:
                raise StageOutputError("language_normalization", ["language_segments_normalization_failed"]) from error
            try:
                activity_utterance = self.language_normalizer.normalize_labeled_segments(
                    text=str(activity["accessible_activity"]).strip(),
                    segments=list(activity["language_segments"]),
                    utterance_id=f"utt_{lesson_id}_activity",
                ).utterance
            except ValueError as error:
                # Activity language labels are advisory playback metadata. A
                # mismatch must not reject an otherwise safe activity; the
                # teaching agent falls back to conservative Chinese playback
                # when no validated activity utterance is available.
                if str(error) != "language_segments do not concatenate to the source text":
                    raise StageOutputError("language_normalization", ["language_segments_normalization_failed"]) from error
                activity_utterance = None
            except TypeError as error:
                raise StageOutputError("language_normalization", ["language_segments_normalization_failed"]) from error

        return Lesson(
            schema_version="0.1.0",
            lesson_id=lesson_id,
            topic=str(facts["topic"]).strip(),
            # Keep the validated facts text verbatim; strip only transport
            # whitespace around the JSON value, never internal line breaks or
            # lesson punctuation. The internal completeness flag is not a
            # public Lesson field; an unconfirmed value is retained as a
            # quality warning for teacher/parent review.
            source_text=source_text.strip(),
            vocabulary=vocabulary,
            scene=str(facts["scene"]).strip(),
            original_activity=str(facts["original_activity"]).strip(),
            learning_objective=str(activity["learning_objective"]).strip(),
            accessible_activity=str(activity["accessible_activity"]).strip(),
            source_utterance=source_utterance,
            accessible_activity_utterance=activity_utterance,
            answer_evidence=answer_evidence,
            evidence=self._bundle_evidence(bundle),
            confidence=max(0.0, min(confidence, 1.0)),
            review_status="pending",
            vlm_model_revision=model_revision,
            rag_index_revision=bundle.index_revision,
        )

    def bind_existing(self, lesson: Lesson) -> Lesson:
        """Replace model/fixture citations with citations replayed from laptop RAG."""

        query = self._lesson_query(lesson)
        bundle = self.retriever.retrieve(query)
        payload = lesson.model_dump(mode="json")
        payload["evidence"] = [item.model_dump(mode="json") for item in self._bundle_evidence(bundle)]
        payload["rag_index_revision"] = bundle.index_revision
        payload["review_status"] = "pending"
        payload.setdefault("answer_evidence", [])
        if self.language_normalizer is not None:
            if payload.get("source_utterance") is None:
                payload["source_utterance"] = self.language_normalizer.normalize_labeled_segments(
                    text=lesson.source_text,
                    segments=[{"lang": "nan-TW", "content": lesson.source_text}],
                    utterance_id=f"utt_{lesson.lesson_id}_source",
                ).utterance.model_dump(mode="json")
            if payload.get("accessible_activity_utterance") is None:
                payload["accessible_activity_utterance"] = self.language_normalizer.normalize_labeled_segments(
                    text=lesson.accessible_activity,
                    segments=[{"lang": "zh-TW", "content": lesson.accessible_activity}],
                    utterance_id=f"utt_{lesson.lesson_id}_activity",
                ).utterance.model_dump(mode="json")
        return Lesson.model_validate(payload)

    @classmethod
    def _lesson_query(cls, lesson: Lesson) -> str:
        parts = [lesson.topic, lesson.source_text, lesson.scene, lesson.original_activity]
        parts.extend(item.hanji for item in lesson.vocabulary)
        parts.extend(item.tailo for item in lesson.vocabulary)
        return " ".join(dict.fromkeys(part.strip() for part in parts if part.strip()))[:2400]

    @staticmethod
    def _log_trace(request_id: str, trace: GenerationTrace) -> None:
        LOGGER.info(
            "lesson generation stage complete",
            extra={
                "request_id": request_id,
                "stage": trace.stage,
                "attempts": trace.attempts,
                "repair_attempted": trace.repair_attempted,
                "model_revision": trace.model_revision,
            },
        )
