CREATE TABLE evidence_locators (
    id TEXT PRIMARY KEY NOT NULL,
    revision TEXT NOT NULL REFERENCES source_revisions(id),
    extractor TEXT NOT NULL,
    page INTEGER,
    start INTEGER,
    end INTEGER,
    excerpt TEXT NOT NULL,
    ocr_needed INTEGER NOT NULL CHECK(ocr_needed IN (0,1)),
    CHECK ((page IS NOT NULL AND page >= 1 AND start IS NULL AND end IS NULL)
        OR (page IS NULL AND start IS NOT NULL AND end IS NOT NULL AND
            start >= 0 AND end >= start AND ocr_needed = 0)),
    UNIQUE(revision,page),
    UNIQUE(revision,start)
);
CREATE TRIGGER immutable_locator BEFORE UPDATE ON evidence_locators
BEGIN
    SELECT RAISE(ABORT, 'immutable evidence locator');
END;
