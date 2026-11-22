CREATE TABLE migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL);
CREATE TABLE projects(
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, root TEXT NOT NULL, identity TEXT NOT NULL,
    grant INTEGER NOT NULL DEFAULT 1, UNIQUE(owner,identity)
);
CREATE TABLE conversations(
    id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX conversations_project ON conversations(project);
CREATE TABLE turns(
    id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES conversations(id),
    submission TEXT NOT NULL, digest TEXT NOT NULL, ordinal INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN ('active','completed','cancelled','failed','interrupted')),
    error TEXT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TEXT,
    UNIQUE(conversation,submission), UNIQUE(conversation,id)
);
CREATE TABLE messages(
    id TEXT PRIMARY KEY, conversation TEXT NOT NULL, turn TEXT NOT NULL,
    seq INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
    UNIQUE(conversation,seq), UNIQUE(turn,role),
    FOREIGN KEY(conversation,turn) REFERENCES turns(conversation,id)
);

