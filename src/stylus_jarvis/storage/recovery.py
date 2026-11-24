"""Local recovery records for terminal writes refused by the main SQLite store."""
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from ..contracts.messages import Code, Failure, PendingSave, State
from ..settings import local_data_path


_record = TypeAdapter(PendingSave)


def apply_final(conn: sqlite3.Connection, item: PendingSave) -> bool:
    """Settle inside the caller's transaction. False withholds the receipt after revocation."""
    if item.state == State.ACTIVE:
        raise Failure(Code.CONFLICT)
    scope = item.scope
    row = conn.execute(
        "SELECT p.grant,t.grant_revision,t.state FROM projects p JOIN conversations c ON c.project=p.id "
        "JOIN turns t ON t.conversation=c.id WHERE p.owner=? AND p.id=? AND c.id=? AND t.id=?",
        (scope.owner, scope.project, scope.conversation, item.key)
    ).fetchone()
    if row is None or not scope.offline:
        raise Failure(Code.SCOPE)
    if row["grant_revision"] is None and row["state"] != State.ACTIVE and row["grant"] == scope.grant:
        return True
    if row["grant_revision"] != scope.grant:
        raise Failure(Code.SCOPE)
    allowed = row["grant"] == scope.grant
    state, error = (item.state, item.error) if allowed else (State.FAILED, Code.SCOPE)
    if state == State.TOKEN_LIMIT:
        # Preserve the qualified schema-2 state constraint and completed-only context.
        state, error = State.FAILED, Code.TOKEN_LIMIT
    changed = conn.execute("UPDATE turns SET state=?,ended_at=CURRENT_TIMESTAMP,error=? "
                           "WHERE id=? AND state='active'", (state, error, item.key))
    if allowed and changed.rowcount:
        conn.execute("UPDATE messages SET content=? WHERE turn=? AND role='assistant'", (item.answer, item.key))
    return allowed


def record_path(database: Path, key: str) -> Path:
    if local_data_path(database.parent) != database.parent:
        raise Failure(Code.STORE)
    return database.with_name(f"{database.name}.{UUID(key).hex}.pending")


def preserve(database: Path, item: PendingSave) -> None:
    temporary: Path | None = None
    try:
        destination = record_path(database, item.key)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(_record.dump_json(item))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError as exc:
        raise Failure(Code.STORE) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def recover(conn: sqlite3.Connection, database: Path) -> None:
    for path in database.parent.glob(f"{database.name}.*.pending"):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise Failure(Code.STORE)
        try:
            item = _record.validate_json(path.read_bytes(), strict=True)
            if record_path(database, item.key) != path:
                raise Failure(Code.STORE)
        except ValueError as exc:
            raise Failure(Code.STORE) from exc
        conn.execute("BEGIN IMMEDIATE")
        apply_final(conn, item)
        conn.commit()
        path.unlink()
