"""Metadata-only local tool receipts, separate from conversation content."""
import sqlite3
from uuid import UUID, uuid4

from ..contracts.messages import Code, Failure, Scope
from ..contracts.tools import LocalTool, ToolOutcome
from .database import Database

class ToolJournal:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def begin(self, scope: Scope, tool: LocalTool, request: UUID | None = None) -> UUID:
        operation = uuid4()

        def insert(conn: sqlite3.Connection) -> None:
            cursor = conn.execute(
                "INSERT INTO local_tool_runs(operation,request,project,conversation,grant_revision,selection_generation,"
                "tool,state) SELECT ?,?,p.id,c.id,?,?,?,'requested' FROM projects p "
                "JOIN conversations c ON c.project=p.id WHERE p.id=? AND c.id=? AND p.owner=?",
                (operation.hex, (request or operation).hex, scope.grant, scope.generation, tool.tool,
                 scope.project, scope.conversation, scope.owner),
            )
            if cursor.rowcount != 1:
                raise Failure(Code.SCOPE)

        await self.database.call(insert, write=True)
        return operation

    async def mark_dispatch(self, operation: UUID) -> None:
        def update(conn: sqlite3.Connection) -> None:
            cursor = conn.execute("UPDATE local_tool_runs SET state='dispatching',dispatch_at=CURRENT_TIMESTAMP "
                                  "WHERE operation=? AND state='requested'", (operation.hex,))
            if cursor.rowcount != 1:
                raise Failure(Code.CONFLICT)
        await self.database.call(update, write=True)

    async def finish(self, operation: UUID, outcome: ToolOutcome, code: Code | None = None) -> None:
        # Terminal bookkeeping belongs to the admitted operation even if its grant was revoked.
        def update(conn: sqlite3.Connection) -> None:
            allowed = ("dispatching",) if outcome == "succeeded" else ("requested", "dispatching")
            placeholders = ",".join("?" for _ in allowed)
            cursor = conn.execute("UPDATE local_tool_runs SET state=?,code=?,ended_at=CURRENT_TIMESTAMP "
                                  f"WHERE operation=? AND state IN ({placeholders})",
                                  (outcome, code, operation.hex, *allowed))
            if cursor.rowcount != 1:
                raise Failure(Code.CONFLICT)
        await self.database.call(update, write=True)
