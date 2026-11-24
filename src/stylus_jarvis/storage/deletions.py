"""Independent append-only memory deletion ledger. Called on the SQLite worker."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from ..contracts.messages import Code, Failure


class DeletionLedger:
    def __init__(self, conn: sqlite3.Connection, key: bytes) -> None:
        self.conn = conn
        self.key = key

    def token(self, kind: str, owner: str, project: str | None, value: str = "") -> bytes:
        payload = json.dumps((kind, owner, project, value), ensure_ascii=True).encode("ascii")
        return hmac.digest(self.key, payload, hashlib.sha256)

    def text_token(self, owner: str, project: str | None, text: str) -> bytes:
        normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
        return self.token("text", owner, project, normalized)

    def forgotten(self, fact: str, owner: str, project: str | None) -> bool:
        return self.conn.execute("SELECT 1 FROM deletions WHERE fact=? AND scope=?",
                                 (fact, self.token("scope", owner, project))).fetchone() is not None

    def blocks(self, tokens: list[bytes]) -> bool:
        return any(self.conn.execute("SELECT 1 FROM suppression WHERE fingerprint=?", (token,)).fetchone()
                   for token in tokens)

    def record(self, fact: str, scope: bytes, version: int, tokens: set[bytes]) -> None:
        with self.conn:
            row = self.conn.execute("INSERT INTO deletions(fact,scope,version) VALUES(?,?,?)",
                                    (fact, scope, version))
            self.conn.executemany("INSERT INTO suppression VALUES(?,?)",
                                  ((token, row.lastrowid) for token in tokens))


def _purge(primary: sqlite3.Connection, fact: str) -> None:
    primary.execute("DELETE FROM fact_versions WHERE fact=?", (fact,))
    primary.execute("DELETE FROM facts WHERE id=?", (fact,))


def reconcile(primary: sqlite3.Connection, ledger: DeletionLedger) -> None:
    sequence = primary.execute("SELECT sequence FROM memory_ledger_binding").fetchone()[0]
    for number, fact, scope in ledger.conn.execute(
        "SELECT sequence,fact,scope FROM deletions WHERE sequence>? ORDER BY sequence", (sequence,)
    ):
        row = primary.execute("SELECT owner,project FROM facts WHERE id=?", (fact,)).fetchone()
        if row is not None:
            if scope != ledger.token("scope", *row):
                raise Failure(Code.STORE)
            _purge(primary, fact)
        sequence = number
    primary.execute("UPDATE memory_ledger_binding SET sequence=?", (sequence,))


@contextmanager
def open_ledger(primary: sqlite3.Connection, path: Path, *, initialize: bool = False) -> Iterator[DeletionLedger]:
    binding = primary.execute("SELECT ledger_id,sequence FROM memory_ledger_binding").fetchone()
    mode = "rwc" if initialize and binding is None else "rw"
    with closing(sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=2)) as conn:
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        if initialize and binding is None:
            conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS identity(id TEXT PRIMARY KEY, key BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS deletions(
                    sequence INTEGER PRIMARY KEY, fact TEXT UNIQUE NOT NULL,
                    scope BLOB NOT NULL, version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS suppression(
                    fingerprint BLOB NOT NULL, deletion INTEGER NOT NULL REFERENCES deletions(sequence),
                    PRIMARY KEY(fingerprint,deletion)
                );
                CREATE TRIGGER IF NOT EXISTS immutable_deletion BEFORE UPDATE ON deletions
                BEGIN SELECT RAISE(ABORT, 'immutable deletion'); END;
                CREATE TRIGGER IF NOT EXISTS no_deletion_removal BEFORE DELETE ON deletions
                BEGIN SELECT RAISE(ABORT, 'immutable deletion'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_suppression BEFORE UPDATE ON suppression
                BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
                CREATE TRIGGER IF NOT EXISTS no_suppression_removal BEFORE DELETE ON suppression
                BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
                COMMIT;
            """)
            with conn:
                conn.execute("INSERT INTO identity SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM identity)",
                             (uuid4().hex, secrets.token_bytes(32)))
        if initialize and conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise Failure(Code.STORE)
        identities = conn.execute("SELECT id,key FROM identity").fetchall()
        if len(identities) != 1 or not isinstance(identities[0][1], bytes) or len(identities[0][1]) != 32:
            raise Failure(Code.STORE)
        ledger_id, key = identities[0]
        head = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM deletions").fetchone()[0]
        if binding is None and initialize:
            primary.execute("INSERT INTO memory_ledger_binding VALUES(1,?,0)", (ledger_id,))
        elif binding is None or binding[0] != ledger_id or binding[1] > head:
            raise Failure(Code.STORE)
        yield DeletionLedger(conn, key)
