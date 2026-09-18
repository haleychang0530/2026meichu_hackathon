CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('IDLE', 'SPEAKING', 'LISTENING', 'TRANSCRIBING', 'EVALUATING', 'RECOVERABLE_ERROR', 'COMPLETE')),
    phase TEXT NOT NULL CHECK (phase IN ('introduction', 'demonstration', 'read_aloud', 'comprehension', 'hint', 'review', 'complete')),
    progress REAL NOT NULL CHECK (progress >= 0 AND progress <= 1),
    current_prompt TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level >= 0 AND hint_level <= 3),
    language_ratio_zh REAL NOT NULL DEFAULT 0.7 CHECK (language_ratio_zh >= 0 AND language_ratio_zh <= 1),
    language_ratio_nan REAL NOT NULL DEFAULT 0.3 CHECK (language_ratio_nan >= 0 AND language_ratio_nan <= 1),
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    creation_idempotency_key TEXT NOT NULL UNIQUE,
    created_request_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_lesson_id ON sessions(lesson_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);
