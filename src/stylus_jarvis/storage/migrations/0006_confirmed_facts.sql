CREATE TABLE facts (
    id TEXT PRIMARY KEY NOT NULL,
    owner TEXT NOT NULL,
    project TEXT REFERENCES projects(id)
);
CREATE INDEX facts_destination ON facts(owner, project);
CREATE TABLE fact_versions (
    fact TEXT NOT NULL REFERENCES facts(id),
    version INTEGER NOT NULL CHECK(version >= 1),
    text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 8192),
    origin TEXT NOT NULL CHECK(origin IN ('user','inferred')),
    conversation TEXT NOT NULL REFERENCES conversations(id),
    grant_revision INTEGER NOT NULL,
    locator TEXT REFERENCES evidence_locators(id),
    confirmed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(fact, version)
);
CREATE TRIGGER immutable_fact_version BEFORE UPDATE ON fact_versions
BEGIN
    SELECT RAISE(ABORT, 'immutable fact version');
END;
