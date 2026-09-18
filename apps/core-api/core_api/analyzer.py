from __future__ import annotations

from dataclasses import dataclass

from fastapi import UploadFile

from .errors import ProviderError
from .image_pipeline import ImagePreparer, PreparedImage
from .models import Lesson
from .providers import FixtureProvider, LessonProvider


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    lesson: Lesson
    provider_mode: str


class LessonAnalyzer:
    def __init__(
        self,
        preparer: ImagePreparer,
        primary: LessonProvider,
        fixture: FixtureProvider,
    ) -> None:
        self.preparer = preparer
        self.primary = primary
        self.fixture = fixture

    async def analyze(
        self,
        upload: UploadFile,
        request_id: str,
        *,
        use_fixture_on_failure: bool,
    ) -> AnalysisResult:
        prepared: PreparedImage | None = None
        try:
            prepared = await self.preparer.prepare(upload)
            try:
                lesson = await self.primary.analyze(prepared, request_id)
                return AnalysisResult(lesson=lesson, provider_mode=self.primary.mode)
            except ProviderError:
                if not use_fixture_on_failure or self.primary.mode == "fixture":
                    raise
                lesson = await self.fixture.analyze(prepared, request_id)
                return AnalysisResult(lesson=lesson, provider_mode="fixture-fallback")
        finally:
            if prepared is not None:
                prepared.path.unlink(missing_ok=True)
