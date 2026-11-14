-- Normalize metadata shared by every variable/date in one NASA POWER response.
-- HistoryStore applies this once after migration 001 and vacuums the database.
PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE source_responses (
    source_response_id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    raw_sha256 TEXT UNIQUE,
    raw_response_path TEXT,
    source_metadata_json TEXT NOT NULL DEFAULT '{}'
);

INSERT INTO source_responses(source_key, raw_sha256, raw_response_path, source_metadata_json)
SELECT 'sha256:' || raw_sha256, raw_sha256, MAX(raw_response_path), MAX(source_metadata_json)
FROM observations
WHERE raw_sha256 IS NOT NULL
GROUP BY raw_sha256;

INSERT INTO source_responses(source_key, raw_sha256, raw_response_path, source_metadata_json)
SELECT 'legacy:' || observation_id, NULL, raw_response_path, source_metadata_json
FROM observations
WHERE raw_sha256 IS NULL;

CREATE TABLE observations_v2 (
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
    source_response_id INTEGER REFERENCES source_responses(source_response_id),
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (location_id, dataset_id, variable_code, observed_on, resolution)
);

INSERT INTO observations_v2(
    observation_id, location_id, dataset_id, variable_code, observed_on, resolution,
    raw_value, raw_unit, normalized_value, canonical_unit, source_response_id, ingested_at
)
SELECT o.observation_id, o.location_id, o.dataset_id, o.variable_code, o.observed_on, o.resolution,
       o.raw_value, o.raw_unit, o.normalized_value, o.canonical_unit,
       (SELECT s.source_response_id FROM source_responses s WHERE s.source_key =
           CASE WHEN o.raw_sha256 IS NULL THEN 'legacy:' || o.observation_id
                ELSE 'sha256:' || o.raw_sha256 END),
       o.ingested_at
FROM observations o;

DROP TABLE observations;
ALTER TABLE observations_v2 RENAME TO observations;

CREATE INDEX idx_observations_location_variable_resolution_date
    ON observations (location_id, variable_code, resolution, observed_on);
CREATE INDEX idx_observations_dataset_date
    ON observations (dataset_id, observed_on);
CREATE INDEX idx_observations_date
    ON observations (observed_on);

PRAGMA user_version = 2;
COMMIT;
PRAGMA foreign_keys = ON;
