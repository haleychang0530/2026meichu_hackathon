# Agent A Stage 07 fixture review

Command:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py
```

Result on 2026-09-19: **5/5 passed**. All facts and activity objects validate
against the versioned Stage 07 schemas; all five fixtures explicitly confirm
that the original `source_text` is complete; all activities pass the
deterministic answer-leak, position-hint, and sighted-only checks; every
expected Lesson is `pending`; and every fixture includes at least one
teacher-only `answer_evidence` item.

| Fixture | Representative page | Source text complete | Warnings | Review status |
| --- | --- | :---: | ---: | --- |
| `stage07-market-picture` | market visual question | yes | 0 | pending |
| `stage07-family-greeting` | family greeting dialogue | yes | 0 | pending |
| `stage07-weather-clothing` | weather/clothing matching | yes | 1 | pending |
| `stage07-classroom-dialogue` | classroom object dialogue | yes | 0 | pending |
| `stage07-food-order` | food-order role play | yes | 1 | pending |

The fixtures are metadata-only. No textbook photograph, student recording,
generated media, runtime index, database, or model weight is committed.

The error cases cover invalid facts JSON, incomplete source text, direct answer
leakage, position language, and empty Local RAG results. The expected policy is
one repair at most; an unresolved result returns explicit
`VLM_INVALID_OUTPUT`/manual-review handling, and empty retrieval produces no
fabricated citation.
