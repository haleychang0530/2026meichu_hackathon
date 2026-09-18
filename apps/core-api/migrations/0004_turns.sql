CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    transcript_raw TEXT NOT NULL,
    transcript_normalized TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('correct', 'partial', 'retry')),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_turns_session_created ON turns(session_id, created_at, turn_id);
