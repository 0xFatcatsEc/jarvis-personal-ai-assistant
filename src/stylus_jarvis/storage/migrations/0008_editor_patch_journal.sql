CREATE TABLE editor_patch_operations (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL REFERENCES projects(id),
    conversation TEXT NOT NULL,
    grant_revision INTEGER NOT NULL,
    window_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    digest TEXT NOT NULL CHECK(length(digest)=64),
    permit_expires_ms INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('uncertain','settled','acknowledged')),
    UNIQUE(project,digest)
);
CREATE UNIQUE INDEX editor_one_uncertain_patch ON editor_patch_operations(project) WHERE state='uncertain';

CREATE TABLE editor_patch_targets (
    operation TEXT NOT NULL REFERENCES editor_patch_operations(id),
    path TEXT NOT NULL,
    document_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    base_digest TEXT NOT NULL CHECK(length(base_digest)=64),
    expected_digest TEXT NOT NULL CHECK(length(expected_digest)=64),
    outcome TEXT NOT NULL CHECK(outcome IN ('unresolved','applied','unchanged')),
    PRIMARY KEY(operation,path)
);
