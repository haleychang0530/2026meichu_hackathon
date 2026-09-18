CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO settings(key, value_json)
VALUES ('teaching_agent_version', '"stage08-v1"');

INSERT OR IGNORE INTO settings(key, value_json)
VALUES ('schema_version', '"0.1.0"');
