"""Review the five metadata-only Stage 07 representative lesson fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CORE_APP = ROOT / "apps" / "core-api"
if str(CORE_APP) not in sys.path:
    sys.path.insert(0, str(CORE_APP))

from core_api.lesson_pipeline import accessible_activity_issues  # noqa: E402


FIXTURE_ROOT = ROOT / "fixtures" / "lesson-analysis" / "stage07"
PROMPT_ROOT = ROOT / "prompts" / "lesson-analysis"


def main() -> int:
    facts_schema = json.loads((PROMPT_ROOT / "facts.schema.json").read_text(encoding="utf-8"))
    activity_schema = json.loads((PROMPT_ROOT / "activity.schema.json").read_text(encoding="utf-8"))
    facts_validator = Draft202012Validator(facts_schema)
    activity_validator = Draft202012Validator(activity_schema)
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    fixtures = sorted(FIXTURE_ROOT.glob("0*.json"))
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fixture_id = str(payload.get("fixture_id", path.stem))
        facts = payload.get("facts")
        activity = payload.get("activity")
        errors = [
            *facts_validator.iter_errors(facts),
            *activity_validator.iter_errors(activity),
        ]
        safety = accessible_activity_issues(
            str(activity.get("accessible_activity", "")) if isinstance(activity, dict) else "",
            [str(item) for item in facts.get("answer_evidence", [])] if isinstance(facts, dict) else [],
            activity.get("safety_checks") if isinstance(activity, dict) else None,
        )
        source_text = facts.get("source_text") if isinstance(facts, dict) else None
        source_text_complete = facts.get("source_text_complete") is True if isinstance(facts, dict) else False
        row = {
            "fixture_id": fixture_id,
            "file": path.relative_to(ROOT).as_posix(),
            "schema_valid": not errors,
            "safety_reasons": list(safety),
            "review_status": payload.get("expected", {}).get("review_status"),
            "answer_evidence_count": len(facts.get("answer_evidence", [])) if isinstance(facts, dict) else 0,
            "quality_warning_count": len(facts.get("quality_warnings", [])) if isinstance(facts, dict) else 0,
            "source_text_complete": source_text_complete,
            "source_text_length": len(source_text) if isinstance(source_text, str) else 0,
        }
        rows.append(row)
        if (
            errors
            or safety
            or row["review_status"] != "pending"
            or row["answer_evidence_count"] < 1
            or not source_text_complete
            or not isinstance(source_text, str)
            or not source_text.strip()
        ):
            failures.append({
                "fixture_id": fixture_id,
                "schema_errors": [error.validator for error in errors[:8]],
                "safety_reasons": list(safety),
            })
    report = {
        "schema_version": "stage07-review.v1",
        "fixture_count": len(fixtures),
        "passed": len(fixtures) >= 5 and not failures,
        "failures": failures,
        "rows": rows,
        "privacy": {
            "media_committed": False,
            "raw_textbook_photos_committed": False,
            "student_recordings_committed": False,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
