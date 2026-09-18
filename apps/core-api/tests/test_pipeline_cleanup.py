from __future__ import annotations

import asyncio
import io
import os
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from starlette.datastructures import Headers, UploadFile

from core_api.analyzer import LessonAnalyzer
from core_api.config import Settings
from core_api.image_pipeline import ImagePreparer
from core_api.providers import FixtureProvider
from tests.support import FIXTURE_PATH, jpeg_bytes


class BlockingProvider:
    mode = "real"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def analyze(self, image, request_id):
        self.started.set()
        await asyncio.Future()

    async def health(self, request_id):
        raise AssertionError("not used")

    async def close(self):
        return None


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_janitor_only_removes_expired_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings.from_env("test"), data_dir=Path(directory), upload_ttl_seconds=60)
            preparer = ImagePreparer(settings)
            settings.upload_dir.mkdir(parents=True)
            stale = settings.upload_dir / "lesson-stale.jpg"
            recent = settings.upload_dir / "lesson-recent.jpg"
            stale.write_bytes(b"old")
            recent.write_bytes(b"new")
            old = time.time() - 120
            os.utime(stale, (old, old))
            self.assertEqual(preparer.cleanup_stale(), 1)
            self.assertFalse(stale.exists())
            self.assertTrue(recent.exists())

    async def test_cancelled_analysis_removes_normalized_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                Settings.from_env("test"),
                data_dir=Path(directory),
                fixture_path=FIXTURE_PATH,
                speech_base_url=None,
            )
            provider = BlockingProvider()
            analyzer = LessonAnalyzer(
                ImagePreparer(settings),
                provider,
                FixtureProvider(FIXTURE_PATH),
            )
            upload = UploadFile(
                io.BytesIO(jpeg_bytes()),
                filename="page.jpg",
                headers=Headers({"content-type": "image/jpeg"}),
            )
            task = asyncio.create_task(
                analyzer.analyze(upload, str(uuid.uuid4()), use_fixture_on_failure=False)
            )
            await provider.started.wait()
            self.assertEqual(len(list(settings.upload_dir.glob("lesson-*.jpg"))), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(list(settings.upload_dir.glob("lesson-*")), [])
            await upload.close()


if __name__ == "__main__":
    unittest.main()
