-- Issue #49: durable ownership of an isolated Git workspace per Mission attempt.
--
-- Paths are executor-private operational data. They must never be returned by
-- Mission/MCP/public operator contracts. The gateway persists ownership and
-- immutable preparation facts so an executor can reconcile a worktree after a
-- restart without guessing which Mission owns it.

CREATE TABLE mission_workspaces (
    id VARCHAR(128) PRIMARY KEY,
    mission_id VARCHAR(128) NOT NULL,
    attempt_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    project_id VARCHAR(128) NOT NULL,
    node_id VARCHAR(128) NOT NULL,
    workspace_binding_id VARCHAR(128) NOT NULL,
    repository_root VARCHAR(2048) NOT NULL,
    worktree_path VARCHAR(2048) NOT NULL,
    base_branch VARCHAR(255) NOT NULL,
    base_commit VARCHAR(64) NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'reserved',
    cleanup_state VARCHAR(32) NOT NULL DEFAULT 'not_requested',
    last_error TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    released_at TIMESTAMP,
    CONSTRAINT fk_mission_workspaces_mission FOREIGN KEY (mission_id) REFERENCES missions(id),
    CONSTRAINT fk_mission_workspaces_attempt FOREIGN KEY (attempt_id) REFERENCES mission_attempts(id),
    CONSTRAINT fk_mission_workspaces_task FOREIGN KEY (task_id) REFERENCES tasks(id),
    CONSTRAINT fk_mission_workspaces_project FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT fk_mission_workspaces_node FOREIGN KEY (node_id) REFERENCES nodes(id),
    CONSTRAINT fk_mission_workspaces_binding FOREIGN KEY (workspace_binding_id) REFERENCES workspace_bindings(id),
    CONSTRAINT uq_mission_workspace_attempt UNIQUE (attempt_id),
    CONSTRAINT uq_mission_workspace_worktree UNIQUE (node_id, worktree_path),
    CONSTRAINT uq_mission_workspace_branch UNIQUE (workspace_binding_id, branch_name)
);

CREATE INDEX mission_workspaces_mission_idx
    ON mission_workspaces (mission_id, created_at);

CREATE INDEX mission_workspaces_owner_idx
    ON mission_workspaces (node_id, workspace_binding_id, state);
