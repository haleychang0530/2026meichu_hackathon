# Laptop storage and data deletion policy v0.1

Runtime root: `%LOCALAPPDATA%\HearOurLanguage` on the Ryzen AI 9 laptop.

| Data | Location | Default retention | Clear operation |
| --- | --- | --- | --- |
| SQLite structured lessons/sessions/turns | `db/app.sqlite3` | demo data auto-purged after 7 days; teacher reset clears immediately | transactional demo reset |
| RAG corpus metadata/index | `rag/corpus`, `rag/indexes/<revision>` | persistent while source/license record is valid | admin reindex/reset; retain active revision until replacement succeeds |
| Generated TTS audio | `cache/audio` | LRU, max 30 days or 2 GiB | cache clear or demo reset |
| Parsed lesson cache | `cache/lessons` | max 7 days | cache clear or demo reset |
| Uploaded textbook image | `tmp/uploads` | delete after analysis; hard maximum 15 minutes | request-finalizer plus startup janitor |
| Student recording | memory or `tmp/audio` | delete after transcription; hard maximum 15 minutes | request-finalizer plus startup janitor |
| Operational logs | `logs` | 7 days, metadata only | log rotation or demo reset |
| Explicit debug media | `debug/media` | disabled by default; maximum 24 hours | debug expiry job and visible teacher clear action |

Raw student recordings and textbook images are never retained by default. Debug capture requires an explicit teacher/parent toggle, an on-screen notice, and automatic expiry. MI300 never persists images, prompts, evidence, outputs, or request history.

Deletion should be idempotent and recorded only as metadata (`request_id`, category, count, timestamp). A deletion log must not reproduce deleted content. SQLite, RAG, and cache paths are laptop-only and must be excluded from Git and backups used for demos.
