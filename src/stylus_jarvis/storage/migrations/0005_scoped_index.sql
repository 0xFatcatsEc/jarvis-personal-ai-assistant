-- Stable integer keys for the derived FTS postings, including across VACUUM.
CREATE TABLE indexed_locators (
    posting INTEGER PRIMARY KEY,
    locator TEXT NOT NULL UNIQUE REFERENCES evidence_locators(id)
);
CREATE VIRTUAL TABLE evidence_fts USING fts5(excerpt, content='', tokenize='unicode61');
CREATE TRIGGER index_excerpt AFTER INSERT ON indexed_locators
BEGIN
    INSERT INTO evidence_fts(rowid,excerpt)
    SELECT NEW.posting,excerpt FROM evidence_locators WHERE id=NEW.locator;
END;

CREATE UNIQUE INDEX source_revision_pair ON source_revisions(source,id);
CREATE TABLE active_evidence (
    source TEXT PRIMARY KEY NOT NULL,
    revision TEXT NOT NULL,
    FOREIGN KEY(source,revision) REFERENCES source_revisions(source,id)
);
