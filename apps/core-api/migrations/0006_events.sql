CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id, event_id);
