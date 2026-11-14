-- EARTHSCOPE NASA POWER daily archive and durable model records.
-- Safe to execute repeatedly; HistoryStore applies this schema on initialization.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    location_name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS variables (
    variable_code TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    canonical_unit TEXT NOT NULL,
    raw_unit TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL,
    resolution TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_code, resolution)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'dry_run')),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    location_count INTEGER NOT NULL DEFAULT 0,
    parameters_json TEXT NOT NULL DEFAULT '[]',
    request_count INTEGER NOT NULL DEFAULT 0,
    observation_rows INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    variable_code TEXT NOT NULL REFERENCES variables(variable_code),
    observed_on TEXT NOT NULL,
    resolution TEXT NOT NULL,
    raw_value REAL,
    raw_unit TEXT NOT NULL,
    normalized_value REAL,
    canonical_unit TEXT NOT NULL,
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    raw_response_path TEXT,
    raw_sha256 TEXT,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (location_id, dataset_id, variable_code, observed_on, resolution)
);

CREATE INDEX IF NOT EXISTS idx_observations_location_variable_resolution_date
    ON observations (location_id, variable_code, resolution, observed_on);
CREATE INDEX IF NOT EXISTS idx_observations_dataset_date
    ON observations (dataset_id, observed_on);
CREATE INDEX IF NOT EXISTS idx_observations_date
    ON observations (observed_on);

CREATE TABLE IF NOT EXISTS model_versions (
    model_version_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    training_start TEXT,
    training_end TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (model_name, version)
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    model_version_id TEXT NOT NULL REFERENCES model_versions(model_version_id),
    evaluation_name TEXT NOT NULL DEFAULT 'default',
    evaluated_at TEXT NOT NULL,
    dataset_id TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (model_version_id, evaluation_name, evaluated_at, dataset_id)
);
CREATE INDEX IF NOT EXISTS idx_model_evaluations_version_date
    ON model_evaluations (model_version_id, evaluated_at);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    model_version_id TEXT NOT NULL REFERENCES model_versions(model_version_id),
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    variable_code TEXT NOT NULL REFERENCES variables(variable_code),
    target_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    horizon_days INTEGER NOT NULL DEFAULT 0,
    predicted_value REAL NOT NULL,
    unit TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (model_version_id, location_id, variable_code, target_date, horizon_days)
);
CREATE INDEX IF NOT EXISTS idx_predictions_location_variable_target
    ON predictions (location_id, variable_code, target_date);
