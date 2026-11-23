"""Scoped project, conversation and turn operations. SQL never escapes this boundary."""
import asyncio
import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from ..contracts.messages import ChatMessage, Code, Failure, Scope, State, Turn
from .database import Database


def _authorize(conn: sqlite3.Connection, scope: Scope) -> None:
    row = conn.execute(
        "SELECT p.grant FROM projects p JOIN conversations c ON c.project=p.id "
        "WHERE p.owner=? AND p.id=? AND c.id=?", (scope.owner, scope.project, scope.conversation)
    ).fetchone()
    if row is None or row[0] != scope.grant or not scope.offline:
        raise Failure(Code.SCOPE)


def _turn(conn: sqlite3.Connection, scope: Scope, key: str) -> Turn:
    row = conn.execute(
        "SELECT t.id,u.content,a.content,t.state FROM turns t "
        "JOIN messages u ON u.turn=t.id AND u.role='user' "
        "JOIN messages a ON a.turn=t.id AND a.role='assistant' "
        "WHERE t.conversation=? AND t.id=?", (scope.conversation, key)
    ).fetchone()
    if not row:
        raise Failure(Code.SCOPE)
    return Turn(row[0], row[1], row[2], State(row[3]))


class Repositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def register(self, owner: str, root: Path) -> str:
        def resolve() -> Path:
            try:
                path = root.resolve(strict=True)
                if not path.is_dir() or str(path).startswith("\\\\"):
                    raise Failure(Code.SCOPE)
                return path
            except OSError as exc:
                raise Failure(Code.SCOPE) from exc
        path = await asyncio.to_thread(resolve)
        identity = os.path.normcase(str(path))

        def register(conn: sqlite3.Connection) -> str:
            conn.execute("INSERT INTO projects(id,owner,root,identity) VALUES(?,?,?,?) "
                         "ON CONFLICT(owner,identity) DO NOTHING", (uuid4().hex, owner, str(path), identity))
            return str(conn.execute("SELECT id FROM projects WHERE owner=? AND identity=?", (owner, identity)).fetchone()[0])
        return await self.db.call(register, write=True)

    async def projects(self, owner: str) -> list[tuple[str, str]]:
        return await self.db.call(lambda c: [(r[0], r[1]) for r in c.execute(
            "SELECT id,root FROM projects WHERE owner=? ORDER BY root", (owner,))])

    async def conversations(self, owner: str, project: str) -> list[tuple[str, str]]:
        return await self.db.call(lambda c: [(r[0], r[1]) for r in c.execute(
            "SELECT c.id,c.title FROM conversations c JOIN projects p ON p.id=c.project "
            "WHERE p.owner=? AND p.id=? ORDER BY c.rowid", (owner, project))])

    async def select(self, owner: str, project: str, generation: int, conversation: str | None = None) -> Scope:
        def select(conn: sqlite3.Connection) -> Scope:
            row = conn.execute("SELECT grant FROM projects WHERE id=? AND owner=?", (project, owner)).fetchone()
            if not row:
                raise Failure(Code.SCOPE)
            key = conversation or uuid4().hex
            if conversation is None:
                conn.execute("INSERT INTO conversations(id,project,title) VALUES(?,?,?)", (key, project, "New conversation"))
            scope = Scope(owner, project, key, row[0], generation)
            _authorize(conn, scope)
            return scope
        return await self.db.call(select, write=conversation is None)

    async def validate(self, scope: Scope, *, require_root: bool = False) -> None:
        def validate(conn: sqlite3.Connection) -> str:
            _authorize(conn, scope)
            return str(conn.execute("SELECT root FROM projects WHERE id=?", (scope.project,)).fetchone()[0])
        if require_root:
            path = Path(await self.db.call(validate))
            if not await asyncio.to_thread(path.is_dir):
                raise Failure(Code.SCOPE)
        # A grant can change while the filesystem check is in flight.
        await self.db.call(lambda conn: _authorize(conn, scope))

    async def begin(self, scope: Scope, request: UUID, text: str, digest: str) -> tuple[Turn, bool]:
        def begin(conn: sqlite3.Connection) -> tuple[Turn, bool]:
            _authorize(conn, scope)
            cid = scope.conversation
            existing = conn.execute("SELECT id FROM turns WHERE conversation=? AND submission=?", (cid, request.hex)).fetchone()
            if existing:
                turn = _turn(conn, scope, existing[0])
                if turn.question != text:
                    raise Failure(Code.CONFLICT)
                return turn, False
            turn_id = uuid4().hex
            seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM messages WHERE conversation=?", (cid,)).fetchone()[0]
            conn.execute("INSERT INTO turns(id,conversation,submission,digest,grant_revision,state) "
                         "VALUES(?,?,?,?,?,'active')", (turn_id, cid, request.hex, digest, scope.grant))
            conn.executemany("INSERT INTO messages VALUES(?,?,?,?,?,?)", [
                (uuid4().hex, cid, turn_id, seq, "user", text),
                (uuid4().hex, cid, turn_id, seq+1, "assistant", "")])
            if seq == 1:
                conn.execute("UPDATE conversations SET title=? WHERE id=?", (" ".join(text.split())[:60], cid))
            return _turn(conn, scope, turn_id), True
        return await self.db.call(begin, write=True)

    async def checkpoint(self, scope: Scope, key: str, ordinal: int, text: str) -> None:
        def update(conn: sqlite3.Connection) -> None:
            _authorize(conn, scope)
            changed = conn.execute("UPDATE turns SET ordinal=? WHERE id=? AND conversation=? AND grant_revision=? "
                                   "AND state='active' AND ordinal<?", (ordinal, key, scope.conversation, scope.grant, ordinal))
            if changed.rowcount:
                conn.execute("UPDATE messages SET content=? WHERE turn=? AND role='assistant'", (text, key))
        await self.db.call(update, write=True)

    async def finish(self, scope: Scope, key: str, state: State, text: str, error: Code | None) -> Turn:
        if state == State.ACTIVE:
            raise Failure(Code.CONFLICT)
        def finish(conn: sqlite3.Connection) -> Turn | None:
            row = conn.execute(
                "SELECT p.grant,t.grant_revision,t.state FROM projects p JOIN conversations c ON c.project=p.id "
                "JOIN turns t ON t.conversation=c.id WHERE p.owner=? AND p.id=? AND c.id=? AND t.id=?",
                (scope.owner, scope.project, scope.conversation, key)
            ).fetchone()
            if row is None or not scope.offline:
                raise Failure(Code.SCOPE)
            if row["grant_revision"] is None and row["state"] != State.ACTIVE and row["grant"] == scope.grant:
                # Historical terminal receipts predate admission revisions.
                return _turn(conn, scope, key)
            if row["grant_revision"] != scope.grant:
                raise Failure(Code.SCOPE)
            if row["grant"] != scope.grant:
                conn.execute("UPDATE turns SET state='failed',error=?,ended_at=CURRENT_TIMESTAMP "
                             "WHERE id=? AND state='active'", (Code.SCOPE.value, key))
                return None
            changed = conn.execute("UPDATE turns SET state=?,ended_at=CURRENT_TIMESTAMP,error=? "
                                   "WHERE conversation=? AND id=? AND state='active'",
                                   (state.value, error.value if error else None, scope.conversation, key))
            if changed.rowcount:
                conn.execute("UPDATE messages SET content=? WHERE turn=? AND role='assistant'", (text, key))
            return _turn(conn, scope, key)
        result = await self.db.call(finish, write=True)
        if result is None:
            # Raising inside the actor would roll back the status-only update.
            raise Failure(Code.SCOPE)
        return result

    async def history(self, scope: Scope, *, after: int = 0, limit: int = 100,
                      query: str = "") -> list[tuple[int, str, str, str]]:
        def fetch(conn: sqlite3.Connection) -> list[tuple[int, str, str, str]]:
            _authorize(conn, scope)
            return [tuple(r) for r in conn.execute(
                "SELECT m.seq,m.role,m.content,t.state FROM messages m JOIN turns t ON t.id=m.turn "
                "WHERE m.conversation=? AND m.seq>? AND instr(lower(m.content),lower(?))>0 ORDER BY m.seq LIMIT ?",
                (scope.conversation, after, query, min(max(1, limit), 500)))]
        return await self.db.call(fetch)

    async def context(self, scope: Scope, budget: int) -> list[ChatMessage]:
        def fetch(conn: sqlite3.Connection) -> list[ChatMessage]:
            _authorize(conn, scope)
            remaining = budget
            pairs: list[list[ChatMessage]] = []
            for r in conn.execute("SELECT u.content,a.content FROM turns t "
                                  "JOIN messages u ON u.turn=t.id AND u.role='user' "
                                  "JOIN messages a ON a.turn=t.id AND a.role='assistant' "
                                  "WHERE t.conversation=? AND t.state='completed' ORDER BY u.seq DESC", (scope.conversation,)):
                cost = len(r[0].encode()) + len(r[1].encode()) + 32
                if cost > remaining:
                    break
                remaining -= cost
                pairs.append([ChatMessage("user", r[0]), ChatMessage("assistant", r[1])])
            return [message for pair in reversed(pairs) for message in pair]
        return await self.db.call(fetch)

