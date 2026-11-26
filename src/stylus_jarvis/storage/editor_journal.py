"""Durable dispatch fences and evidence-only editor recovery."""
import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4

from ..contracts.messages import Code, Failure, Scope
from ..editor.patch import DocumentBase, ReviewedPatch, now_ms
from .database import Database
from .repositories import _authorize


class EditorJournal:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def reserve(self, scope: Scope, root: Path, window: str, review: ReviewedPatch, expires: int) -> str:
        operation = uuid4().hex

        def write(conn: sqlite3.Connection) -> str:
            _authorize(conn, scope)
            if expires <= now_ms():
                raise Failure(Code.CONFLICT)
            if conn.execute("SELECT 1 FROM editor_patch_operations WHERE project=? AND digest=?",
                            (scope.project, review.digest)).fetchone():
                raise Failure(Code.CONFLICT)
            if conn.execute("SELECT 1 FROM editor_patch_operations WHERE project=? AND state='uncertain'",
                            (scope.project,)).fetchone():
                raise Failure(Code.BUSY)
            conn.execute("INSERT INTO editor_patch_operations VALUES(?,?,?,?,?,?,?,?,'uncertain')",
                         (operation, scope.project, scope.conversation, scope.grant, window, str(root),
                          review.digest, expires))
            conn.executemany("INSERT INTO editor_patch_targets VALUES(?,?,?,?,?,?,'unresolved')", (
                (operation, path, target.base.document_id, target.base.document_version, target.base.sha256,
                 hashlib.sha256(target.replacement.encode("utf-8")).hexdigest())
                for path, target in zip(review.paths, review.proposal.targets, strict=True)))
            return operation

        return await self.database.call(write, write=True)

    @staticmethod
    def _render(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        targets = conn.execute("SELECT path,outcome FROM editor_patch_targets WHERE operation=? ORDER BY rowid",
                               (row["id"],))
        return {"operation": row["id"], "digest": row["digest"], "state": row["state"],
                "workspace_uri": Path(row["workspace"]).as_uri(),
                "targets": [{"path": path, "outcome": outcome} for path, outcome in targets]}

    async def latest(self, scope: Scope, root: Path) -> dict | None:
        def read(conn: sqlite3.Connection) -> dict | None:
            _authorize(conn, scope)
            row = conn.execute("SELECT * FROM editor_patch_operations WHERE project=? AND workspace=? "
                               "ORDER BY (state='uncertain') DESC,rowid DESC LIMIT 1",
                               (scope.project, str(root))).fetchone()
            return self._render(conn, row) if row else None
        return await self.database.call(read)

    async def settle(self, scope: Scope, root: Path, operation: str, observed: dict[str, DocumentBase],
                     *, settled_dispatch: bool = False, acknowledge: bool = False) -> dict:
        def write(conn: sqlite3.Connection) -> dict:
            _authorize(conn, scope)
            row = conn.execute("SELECT * FROM editor_patch_operations WHERE id=? AND project=? AND workspace=?",
                               (operation, scope.project, str(root))).fetchone()
            if row is None:
                raise Failure(Code.SCOPE)
            targets = conn.execute("SELECT * FROM editor_patch_targets WHERE operation=?", (operation,)).fetchall()
            if not observed.keys() <= {target["path"] for target in targets}:
                raise Failure(Code.SCOPE)
            if row["state"] != "uncertain":
                return self._render(conn, row)
            if (acknowledge or not settled_dispatch) and now_ms() < row["permit_expires_ms"]:
                raise Failure(Code.BUSY)
            for target in targets:
                base = observed.get(target["path"])
                if base is None or target["outcome"] != "unresolved":
                    continue
                if base.sha256 == target["expected_digest"]:
                    outcome = "applied"
                elif settled_dispatch and (base.document_id, base.document_version, base.sha256) == (
                        target["document_id"], target["base_version"], target["base_digest"]):
                    outcome = "unchanged"
                else:
                    continue
                conn.execute("UPDATE editor_patch_targets SET outcome=? WHERE operation=? AND path=?",
                             (outcome, operation, target["path"]))
            unresolved = conn.execute("SELECT 1 FROM editor_patch_targets WHERE operation=? AND outcome='unresolved'",
                                      (operation,)).fetchone()
            state = ("acknowledged" if acknowledge else "uncertain") if unresolved else "settled"
            conn.execute("UPDATE editor_patch_operations SET state=? WHERE id=?", (state, operation))
            return self._render(conn, conn.execute("SELECT * FROM editor_patch_operations WHERE id=?",
                                                   (operation,)).fetchone())
        return await self.database.call(write, write=True)
