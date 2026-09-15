-- Issue #44: immutable source-issue snapshots for durable Missions.
--
-- A Mission must keep the issue state it was planned from even when the
-- provider/local issue changes later.  This table is append-only by design:
-- drift creates Mission events / replanning decisions; it never rewrites the
-- planning basis stored here.

CREATE TABLE mission_issue_snapshots (
    id VARCHAR(128) PRIMARY KEY,
    mission_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    issue_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    external_id VARCHAR(255),
    issue_revision INTEGER NOT NULL,
    canonical_hash VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL,
    labels_json TEXT NOT NULL DEFAULT '[]',
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    snapshot_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT fk_mission_issue_snapshots_mission FOREIGN KEY (mission_id) REFERENCES missions(id),
    CONSTRAINT fk_mission_issue_snapshots_project FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT fk_mission_issue_snapshots_issue FOREIGN KEY (issue_id) REFERENCES issues(id),
    CONSTRAINT uq_mission_issue_snapshot_mission UNIQUE (mission_id)
);

CREATE INDEX mission_issue_snapshots_source_idx
    ON mission_issue_snapshots (project_id, provider, issue_id, issue_revision);

CREATE INDEX mission_issue_snapshots_hash_idx
    ON mission_issue_snapshots (canonical_hash);
