CREATE TABLE IF NOT EXISTS mastery (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    concept TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('new', 'developing', 'familiar')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    correct_count INTEGER NOT NULL DEFAULT 0 CHECK (correct_count >= 0),
    partial_count INTEGER NOT NULL DEFAULT 0 CHECK (partial_count >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level >= 0 AND hint_level <= 3),
    language_ratio_zh REAL NOT NULL DEFAULT 0.7 CHECK (language_ratio_zh >= 0 AND language_ratio_zh <= 1),
    language_ratio_nan REAL NOT NULL DEFAULT 0.3 CHECK (language_ratio_nan >= 0 AND language_ratio_nan <= 1),
    last_result TEXT CHECK (last_result IN ('correct', 'partial', 'retry')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(session_id, concept)
);
