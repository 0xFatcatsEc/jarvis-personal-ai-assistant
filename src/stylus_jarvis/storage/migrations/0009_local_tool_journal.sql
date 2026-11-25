CREATE TABLE local_tool_runs (
    operation TEXT PRIMARY KEY CHECK(length(operation)=32),
    request TEXT NOT NULL CHECK(length(request)=32),
    project TEXT NOT NULL REFERENCES projects(id),
    conversation TEXT NOT NULL REFERENCES conversations(id),
    grant_revision INTEGER NOT NULL,
    selection_generation INTEGER NOT NULL,
    tool TEXT NOT NULL CHECK(tool IN ('coding.read_saved_code','system.open_approved_project',
        'files.search_evidence','files.inspect_citation','memory.recall_facts')),
    state TEXT NOT NULL CHECK(state IN ('requested','dispatching','succeeded','denied','failed',
        'cancelled','interrupted','uncertain')),
    code TEXT,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dispatch_at TEXT,
    ended_at TEXT
);
CREATE INDEX local_tool_runs_by_project ON local_tool_runs(project, conversation, requested_at);
