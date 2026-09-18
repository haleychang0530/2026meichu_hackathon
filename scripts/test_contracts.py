"""Validate Stage 01 JSON Schema, OpenAPI, fixtures, and student-data policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker, RefResolver
except ModuleNotFoundError as exc:  # pragma: no cover - provides an actionable local error
    raise SystemExit(
        "Missing contract test dependency. Run: "
        "python -m pip install -r packages/contracts/requirements-contracts.txt"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "packages" / "contracts" / "schemas" / "v0.1"
OPENAPI_DIR = ROOT / "packages" / "contracts" / "openapi" / "v0.1"
FIXTURE_DIR = ROOT / "fixtures" / "contracts" / "v0.1"

EXPECTED_SCHEMAS = {
    "lesson.schema.json",
    "utterance.schema.json",
    "turn-result.schema.json",
    "observer-session-summary.schema.json",
    "student-action.schema.json",
    "service-health.schema.json",
    "error.schema.json",
}

EXPECTED_PATHS = {
    "core-api.openapi.json": {
        "/api/health",
        "/api/lessons/analyze",
        "/api/lessons/{lesson_id}",
        "/api/utterances/normalize",
        "/api/sessions",
        "/api/sessions/{session_id}",
        "/api/sessions/{session_id}/turns",
        "/api/sessions/{session_id}/actions",
        "/api/sessions/{session_id}/events",
        "/api/sessions/{session_id}/summary",
        "/api/admin/rag/reindex",
    },
    "vlm-mi300.openapi.json": {"/internal/health", "/internal/vlm/generate"},
    "speech-gateway.openapi.json": {
        "/local/health",
        "/local/warmup",
        "/local/cancel",
        "/v1/audio/transcriptions",
        "/v1/audio/speech",
    },
}

STUDENT_FORBIDDEN_KEYS = {
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
    "vlm_model_revision",
    "rag_index_revision",
}

REQUIRED_SCENARIOS = {
    "success",
    "partial_success",
    "mi300_offline",
    "rag_no_result",
    "asr_failure",
    "tts_failure",
}

EXPECTED_OBSERVER_SUMMARIES = {
    "observer/no-turn.observer-session-summary.json",
    "observer/success.observer-session-summary.json",
    "observer/partial-success.observer-session-summary.json",
    "observer/fallback.observer-session-summary.json",
}

EXPECTED_STUDENT_ACTION_FIXTURES = {
    "student/action-request-hint.json",
    "student/action-response-hint.json",
    "student/answer-submission.request.json",
    "student/answer-submission.response.json",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(f"Cannot parse {path.relative_to(ROOT)}: {exc}") from exc


def walk_refs(value: Any):
    if isinstance(value, dict):
        if isinstance(value.get("$ref"), str):
            yield value["$ref"]
        for child in value.values():
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def walk_keys(value: Any, location: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield location, key
            yield from walk_keys(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, f"{location}[{index}]")


def response_object(document: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    ref = response.get("$ref")
    if not ref:
        return response
    prefix = "#/components/responses/"
    assert ref.startswith(prefix), f"Unsupported response ref: {ref}"
    return document["components"]["responses"][ref.removeprefix(prefix)]


def validate_schemas() -> dict[str, dict[str, Any]]:
    actual = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert actual == EXPECTED_SCHEMAS, f"Schema set differs: {actual ^ EXPECTED_SCHEMAS}"
    schemas: dict[str, dict[str, Any]] = {}
    for name in sorted(actual):
        schema = load_json(SCHEMA_DIR / name)
        Draft202012Validator.check_schema(schema)
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"
        schemas[name] = schema
    action = schemas["student-action.schema.json"]
    expected_actions = {
        "replay_prompt",
        "start_answer",
        "pause",
        "resume",
        "request_hint",
        "next",
    }
    assert set(action["$defs"]["action"]["enum"]) == expected_actions
    assert "transcript" in action["$defs"]["answer_submission"]["required"]
    assert "submit_answer" not in expected_actions
    return schemas


def validate_openapi() -> int:
    operation_ids: set[str] = set()
    response_count = 0
    for name, expected_paths in EXPECTED_PATHS.items():
        path = OPENAPI_DIR / name
        document = load_json(path)
        assert document["openapi"] == "3.1.0"
        assert document["info"]["version"] == "0.1.0"
        assert set(document["paths"]) == expected_paths, f"Unexpected paths in {name}"

        for ref in walk_refs(document):
            if ref.startswith("#"):
                continue
            target = (path.parent / ref.split("#", 1)[0]).resolve()
            assert target.is_file(), f"Missing external ref {ref} in {name}"

        for api_path, path_item in document["paths"].items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation_id = operation.get("operationId")
                assert operation_id, f"Missing operationId: {name} {method} {api_path}"
                assert operation_id not in operation_ids, f"Duplicate operationId: {operation_id}"
                operation_ids.add(operation_id)
                for status, response in operation["responses"].items():
                    resolved = response_object(document, response)
                    headers = resolved.get("headers", {})
                    assert "X-Request-ID" in headers, (
                        f"Missing X-Request-ID response header: {name} {method} {api_path} {status}"
                    )
                    response_count += 1

    vlm = load_json(OPENAPI_DIR / "vlm-mi300.openapi.json")
    assert set(vlm["paths"]) == {"/internal/health", "/internal/vlm/generate"}
    assert all(path.startswith("/internal/") for path in vlm["paths"])

    core = load_json(OPENAPI_DIR / "core-api.openapi.json")
    turns_body = core["paths"]["/api/sessions/{session_id}/turns"]["post"]["requestBody"]
    assert turns_body["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/TurnSubmission"
    )
    actions_body = core["paths"]["/api/sessions/{session_id}/actions"]["post"]["requestBody"]
    assert actions_body["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/StudentActionRequest"
    )
    assert core["paths"]["/api/sessions/{session_id}/actions"]["post"]["responses"]["200"]["$ref"] == (
        "#/components/responses/StudentAction"
    )
    summary_response = core["paths"]["/api/sessions/{session_id}/summary"]["get"]["responses"]["200"]
    assert summary_response["$ref"] == "#/components/responses/ObserverSessionSummary"
    component_schemas = core["components"]["schemas"]
    assert component_schemas["StudentActionRequest"]["$ref"].endswith(
        "student-action.schema.json#/$defs/control_request"
    )
    assert component_schemas["TurnSubmission"]["$ref"].endswith(
        "student-action.schema.json#/$defs/answer_submission"
    )
    assert component_schemas["ObserverSessionSummary"]["$ref"].endswith(
        "observer-session-summary.schema.json"
    )
    normalize = core["paths"]["/api/utterances/normalize"]["post"]
    normalize_request = normalize["requestBody"]["content"]["application/json"]["schema"]
    assert set(normalize_request["required"]) == {"schema_version", "text", "lang"}
    assert normalize["responses"]["200"]["$ref"] == "#/components/responses/Utterance"
    return response_count


def validate_fixtures(schemas: dict[str, dict[str, Any]]) -> tuple[int, int]:
    manifest = load_json(FIXTURE_DIR / "manifest.json")
    assert manifest["schema_version"] == "0.1.0"
    assert manifest["contract_status"] == "draft_pending_agent_b_walkthrough"

    validated = 0
    student_count = 0
    student_scenarios: set[str] = set()
    manifest_paths: set[str] = set()
    schema_store: dict[str, dict[str, Any]] = {}
    for schema_name, schema_document in schemas.items():
        schema_store[schema_document["$id"]] = schema_document
        schema_store[(SCHEMA_DIR / schema_name).as_uri()] = schema_document

    for entry in manifest["fixtures"]:
        relative = entry["path"]
        assert relative not in manifest_paths, f"Duplicate fixture in manifest: {relative}"
        manifest_paths.add(relative)
        fixture_path = FIXTURE_DIR / relative
        assert fixture_path.is_file(), f"Missing fixture: {relative}"
        fixture = load_json(fixture_path)
        assert fixture.get("schema_version") == "0.1.0", f"Missing version: {relative}"

        schema_reference = entry.get("schema")
        if schema_reference:
            schema_name, separator, fragment = schema_reference.partition("#")
            schema = schemas[schema_name]
            validation_schema = schema
            if separator:
                validation_schema = {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$ref": f"{schema['$id']}#{fragment}",
                }
            resolver = RefResolver(
                base_uri=(SCHEMA_DIR / schema_name).as_uri(),
                referrer=validation_schema,
                store=schema_store,
            )
            errors = sorted(
                Draft202012Validator(
                    validation_schema,
                    resolver=resolver,
                    format_checker=FormatChecker(),
                ).iter_errors(fixture),
                key=lambda error: list(error.path),
            )
            assert not errors, f"{relative}: {errors[0].message if errors else ''}"
            validated += 1

        if entry["audience"] == "student":
            student_count += 1
            student_scenarios.add(entry["scenario"])
            for location, key in walk_keys(fixture):
                assert key not in STUDENT_FORBIDDEN_KEYS, (
                    f"Student fixture {relative} leaks forbidden field {location}.{key}"
                )

    actual_json = {
        path.relative_to(FIXTURE_DIR).as_posix()
        for path in FIXTURE_DIR.rglob("*.json")
        if path.name != "manifest.json"
    }
    assert actual_json == manifest_paths, "Fixture manifest and filesystem differ"
    assert EXPECTED_OBSERVER_SUMMARIES <= manifest_paths, "Observer summary fixture set is incomplete"
    assert EXPECTED_STUDENT_ACTION_FIXTURES <= manifest_paths, "Student action fixture set is incomplete"
    tts_ready = load_json(FIXTURE_DIR / "observer/success.utterance.json")
    tts_segment = next(item for item in tts_ready["segments"] if item["lang"] == "nan-TW")
    assert "ⁿ" not in tts_segment["poj_citation"], "MMS fixture contains unsupported superscript nasal"
    needs_review = load_json(FIXTURE_DIR / "observer/needs-review.utterance.json")
    assert needs_review["segments"][0]["pronunciation_status"] == "needs_review"
    assert needs_review["segments"][0]["poj_citation"] is None
    assert needs_review["tts_provider"] is None
    assert student_scenarios == REQUIRED_SCENARIOS, (
        f"Student scenarios differ: {student_scenarios ^ REQUIRED_SCENARIOS}"
    )
    return validated, student_count


def main() -> int:
    schemas = validate_schemas()
    response_count = validate_openapi()
    validated_fixtures, student_count = validate_fixtures(schemas)
    print(
        "PASS: "
        f"{len(schemas)} schemas; "
        f"{len(EXPECTED_PATHS)} OpenAPI documents/{response_count} responses; "
        f"{validated_fixtures} schema fixtures; "
        f"{student_count} student-safe fixtures"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
