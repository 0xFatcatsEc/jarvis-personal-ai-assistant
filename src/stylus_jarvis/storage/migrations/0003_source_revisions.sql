CREATE TABLE sources (
    id TEXT PRIMARY KEY NOT NULL,
    project TEXT NOT NULL REFERENCES projects(id),
    relative_path TEXT NOT NULL,
    UNIQUE(project, relative_path)
);
CREATE TABLE source_revisions (
    id TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL REFERENCES sources(id),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    byte_count INTEGER NOT NULL CHECK(byte_count >= 0),
    UNIQUE(source, sha256)
);
CREATE TRIGGER immutable_source_revision BEFORE UPDATE ON source_revisions
BEGIN
    SELECT RAISE(ABORT, 'immutable source revision');
END;
