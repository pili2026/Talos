-- Future SQLite schema for alert state persistence

CREATE TABLE alert_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    alert_code TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('NORMAL', 'TRIGGERED', 'ACTIVE', 'RESOLVED')),
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    triggered_at TIMESTAMP,
    resolved_at TIMESTAMP,
    last_value REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_id, alert_code)
);

CREATE INDEX idx_device_alert ON alert_states(device_id, alert_code);
CREATE INDEX idx_state ON alert_states(state);

-- Migration note: AlertStateManager.states dict will map to this table
-- Key: (device_id, alert_code) → Primary key in DB