from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import httpx

from core_api.app import create_app
from core_api.config import Settings
from core_api.models import SemanticJudgement
from core_api.providers import FixtureProvider
from tests.support import FIXTURE_PATH, REPOSITORY_ROOT, jpeg_bytes


FIXTURE_DIR = REPOSITORY_ROOT / "fixtures" / "session" / "stage08"
FORBIDDEN_STUDENT_KEYS = {
    "answer",
    "answers",
    "answer_key",
    "correct_answer",
    "expected_answer",
    "confidence",
    "evidence",
    "review_status",
    "teacher_controls",
    "teacher_notes",
    "source_text",
    "original_activity",
    "learning_objective",
    "accessible_activity",
    "answer_evidence",
    "vlm_model_revision",
    "rag_index_revision",
}


class SlowSemanticProvider(FixtureProvider):
    async def judge_answer(self, request_id: str, *, transcript: str, expected_concepts: list[str], lesson_context: dict[str, str]) -> SemanticJudgement:
        del request_id, transcript, expected_concepts, lesson_context
        await asyncio.sleep(0.2)
        return SemanticJudgement(decision="correct")


class Stage08SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = replace(
            Settings.from_env("test"),
            data_dir=Path(self.temporary.name),
            fixture_path=FIXTURE_PATH,
            speech_base_url=None,
            semantic_timeout_seconds=0.05,
        )
        self.app = create_app(self.settings)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )
        analyzed = await self.client.post(
            "/api/lessons/analyze",
            headers={"X-Request-ID": str(uuid.uuid4())},
            files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            data={"language": "nan-TW", "use_fixture_on_failure": "true"},
        )
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        self.lesson_id = analyzed.json()["lesson_id"]

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.temporary.cleanup()

    @staticmethod
    def request_id() -> str:
        return str(uuid.uuid4())

    def headers(self, key: str, revision: int | None = None) -> dict[str, str]:
        headers = {
            "X-Request-ID": self.request_id(),
            "Idempotency-Key": key,
        }
        if revision is not None:
            headers["X-Session-Revision"] = str(revision)
        return headers

    async def create_session(self, key: str) -> dict:
        response = await self.client.post(
            "/api/sessions",
            headers=self.headers(key),
            json={"schema_version": "0.1.0", "lesson_id": self.lesson_id},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["X-Session-Revision"], "0")
        return response.json()

    async def action(self, session_id: str, action: str, key: str, revision: int) -> httpx.Response:
        return await self.client.post(
            f"/api/sessions/{session_id}/actions",
            headers=self.headers(key, revision),
            json={"schema_version": "0.1.0", "action": action},
        )

    async def turn(self, session_id: str, transcript: str, key: str, revision: int) -> httpx.Response:
        return await self.client.post(
            f"/api/sessions/{session_id}/turns",
            headers=self.headers(key, revision),
            json={
                "schema_version": "0.1.0",
                "transcript": transcript,
                "input_mode": "keyboard",
                "asr_device": "cpu",
            },
        )

    async def run_fixture(self, fixture_name: str) -> tuple[dict, dict, dict]:
        fixture = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        session = await self.create_session(f"create-{fixture['fixture_id']}")
        session_id = session["session_id"]
        revision = session["revision"]
        turn_results: list[dict] = []
        for index, step in enumerate(fixture["steps"]):
            key = f"{fixture['fixture_id']}-{index}"
            if step["kind"] == "action":
                response = await self.action(session_id, step["action"], key, revision)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
            else:
                response = await self.turn(session_id, step["transcript"], key, revision)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["result"], step["expected_result"])
                turn_results.append(body)
            revision = body["revision"]
            self.assertEqual(body["last_event_id"], int(response.headers["X-Event-ID"]))

        snapshot = await self.client.get(
            f"/api/sessions/{session_id}/snapshot",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        snapshot_body = snapshot.json()
        self.assertEqual(snapshot_body["phase"], fixture["expected_final_phase"])
        self.assertEqual(snapshot_body["progress"], fixture["expected_final_progress"])

        summary = await self.client.get(
            f"/api/sessions/{session_id}/summary",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(summary.status_code, 200, summary.text)
        summary_body = summary.json()
        self.assertEqual(summary_body["completed_turns"], len(turn_results))
        self.assertEqual(summary_body["phase"], "complete")
        row = self.app.state.database.get_session(session_id)
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row.language_ratio_zh + row.language_ratio_nan, 1.0, places=3)
        self.assertNotEqual(row.language_ratio_zh, 0.7)
        mastery = self.app.state.database.get_mastery(session_id)
        self.assertTrue(mastery)
        self.assertTrue(all(0 <= int(item["hint_level"]) <= 3 for item in mastery))
        return snapshot_body, summary_body, {"session_id": session_id, "turns": turn_results}

    async def test_three_fixed_transcripts_complete_and_update_mastery(self) -> None:
        for fixture_name in ("all-correct.json", "partial-recovery.json", "retry-recovery.json"):
            snapshot, summary, details = await self.run_fixture(fixture_name)
            self.assertEqual(snapshot["state"], "COMPLETE")
            self.assertTrue(summary["familiarity"])
            self.assertEqual(summary["completed_turns"], len(details["turns"]))
            self.assertTrue(any(item["status"] in {"developing", "familiar"} for item in summary["familiarity"]))

    async def test_student_selector_boundary_observer_summary_and_revision_recovery(self) -> None:
        session = await self.create_session("create-selector-boundary")
        session_id = session["session_id"]
        duplicate_create = await self.client.post(
            "/api/sessions",
            headers=self.headers("create-selector-boundary"),
            json={"schema_version": "0.1.0", "lesson_id": self.lesson_id},
        )
        self.assertEqual(duplicate_create.status_code, 201, duplicate_create.text)
        self.assertEqual(duplicate_create.json()["session_id"], session_id)
        self.assertEqual(duplicate_create.headers["X-Idempotency-Replayed"], "true")

        student = await self.client.get(
            f"/api/sessions/{session_id}",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(student.status_code, 200)
        self.assertTrue(FORBIDDEN_STUDENT_KEYS.isdisjoint(student.json()))

        first = await self.action(session_id, "next", "selector-next", 0)
        self.assertEqual(first.status_code, 200, first.text)
        duplicate = await self.action(session_id, "next", "selector-next", 0)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json(), first.json())
        self.assertEqual(duplicate.headers["X-Idempotency-Replayed"], "true")

        stale = await self.action(session_id, "pause", "selector-stale", 0)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "SESSION_REVISION_CONFLICT")
        self.assertEqual(stale.json()["details"]["current_revision"], 1)

        snapshot = await self.client.get(
            f"/api/sessions/{session_id}/snapshot",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.json()["revision"], 1)

        observer = await self.client.get(
            f"/api/sessions/{session_id}/summary",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(observer.status_code, 200, observer.text)
        observer_body = observer.json()
        self.assertIn("evidence", observer_body)
        self.assertIn("health", observer_body)
        self.assertIn("review_status", observer_body)
        self.assertIn("confidence", observer_body)
        self.assertNotIn("source_text", student.json())

    async def test_sse_backlog_reconnect_deduplication_and_heartbeat(self) -> None:
        session = await self.create_session("create-sse")
        session_id = session["session_id"]
        action = await self.action(session_id, "next", "sse-next", 0)
        self.assertEqual(action.status_code, 200, action.text)

        backlog = await self.client.get(
            f"/api/sessions/{session_id}/events",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(backlog.status_code, 200, backlog.text)
        self.assertEqual(backlog.headers["content-type"].split(";", 1)[0], "text/event-stream")
        ids = [int(line.removeprefix("id: ")) for line in backlog.text.splitlines() if line.startswith("id: ")]
        self.assertEqual(ids, [1, 2])
        self.assertTrue(all("data:" in block for block in backlog.text.split("\n\n") if block.strip()))
        self.assertNotIn('"evidence"', backlog.text)
        self.assertNotIn('"confidence"', backlog.text)
        self.assertNotIn('"answer_evidence"', backlog.text)
        self.assertNotIn('"review_status"', backlog.text)

        reconnect = await self.client.get(
            f"/api/sessions/{session_id}/events",
            headers={"X-Request-ID": self.request_id(), "Last-Event-ID": "1"},
        )
        self.assertEqual(reconnect.status_code, 200, reconnect.text)
        reconnect_ids = [int(line.removeprefix("id: ")) for line in reconnect.text.splitlines() if line.startswith("id: ")]
        self.assertEqual(reconnect_ids, [2])
        self.assertNotIn("id: 1", reconnect.text)

        heartbeat = await self.client.get(
            f"/api/sessions/{session_id}/events?after=2",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertIn(": heartbeat", heartbeat.text)
        self.assertNotIn("id:", heartbeat.text)

    async def test_duplicate_turn_is_idempotent_and_only_one_history_entry_is_stored(self) -> None:
        session = await self.create_session("create-turn-idempotency")
        session_id = session["session_id"]
        first = await self.action(session_id, "next", "turn-next-1", 0)
        self.assertEqual(first.status_code, 200)
        second = await self.action(session_id, "next", "turn-next-2", 1)
        self.assertEqual(second.status_code, 200)
        listening = await self.action(session_id, "start_answer", "turn-start", 2)
        self.assertEqual(listening.status_code, 200)
        turn = await self.turn(session_id, "阿媽欲去市場買菜。", "turn-answer", 3)
        self.assertEqual(turn.status_code, 200, turn.text)
        replay = await self.turn(session_id, "完全不同的內容", "turn-answer", 0)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), turn.json())
        self.assertEqual(replay.headers["X-Idempotency-Replayed"], "true")
        summary = await self.client.get(
            f"/api/sessions/{session_id}/summary",
            headers={"X-Request-ID": self.request_id()},
        )
        self.assertEqual(summary.json()["completed_turns"], 1)

    async def test_semantic_judgement_timeout_is_bounded_and_falls_back(self) -> None:
        app = create_app(self.settings, provider=SlowSemanticProvider(FIXTURE_PATH))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                analyzed = await client.post(
                    "/api/lessons/analyze",
                    headers={"X-Request-ID": self.request_id()},
                    files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
                    data={"language": "nan-TW", "use_fixture_on_failure": "true"},
                )
                lesson_id = analyzed.json()["lesson_id"]
                created = await client.post(
                    "/api/sessions",
                    headers=self.headers("slow-create"),
                    json={"schema_version": "0.1.0", "lesson_id": lesson_id},
                )
                session_id = created.json()["session_id"]
                await client.post(
                    f"/api/sessions/{session_id}/actions",
                    headers=self.headers("slow-next-1", 0),
                    json={"schema_version": "0.1.0", "action": "next"},
                )
                await client.post(
                    f"/api/sessions/{session_id}/actions",
                    headers=self.headers("slow-next-2", 1),
                    json={"schema_version": "0.1.0", "action": "next"},
                )
                started = await client.post(
                    f"/api/sessions/{session_id}/actions",
                    headers=self.headers("slow-start", 2),
                    json={"schema_version": "0.1.0", "action": "start_answer"},
                )
                self.assertEqual(started.status_code, 200, started.text)
                result = await client.post(
                    f"/api/sessions/{session_id}/turns",
                    headers=self.headers("slow-turn", 3),
                    json={"schema_version": "0.1.0", "transcript": "我不確定。"},
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["result"], "retry")
                self.assertIn("mi300_offline", result.json()["fallbacks"])

    async def test_session_is_restored_after_app_restart(self) -> None:
        app = create_app(self.settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                analyzed = await client.post(
                    "/api/lessons/analyze",
                    headers={"X-Request-ID": self.request_id()},
                    files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
                    data={"language": "nan-TW", "use_fixture_on_failure": "true"},
                )
                created = await client.post(
                    "/api/sessions",
                    headers=self.headers("restart-create"),
                    json={"schema_version": "0.1.0", "lesson_id": analyzed.json()["lesson_id"]},
                )
                session_id = created.json()["session_id"]

        restarted = create_app(self.settings)
        async with restarted.router.lifespan_context(restarted):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://testserver",
            ) as client:
                restored = await client.get(
                    f"/api/sessions/{session_id}",
                    headers={"X-Request-ID": self.request_id()},
                )
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.json()["session_id"], session_id)
                self.assertEqual(restored.json()["last_event_id"], 1)


if __name__ == "__main__":
    unittest.main()
