CREATE TABLE memory_ledger_binding (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    ledger_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 0)
);
