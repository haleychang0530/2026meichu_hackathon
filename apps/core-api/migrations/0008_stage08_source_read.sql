UPDATE settings
SET value_json = '"stage08-v2-source-read"',
    updated_at = CURRENT_TIMESTAMP
WHERE key = 'teaching_agent_version';

INSERT OR IGNORE INTO settings(key, value_json)
VALUES ('teaching_agent_version', '"stage08-v2-source-read"');
