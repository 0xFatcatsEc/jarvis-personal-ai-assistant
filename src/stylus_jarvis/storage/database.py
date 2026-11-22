"""Thread-affine SQLite owner. Every submitted operation observes a single transaction."""
import asyncio
import hashlib
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from ..contracts.messages import Code, Failure


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-sqlite")
        self._connection: sqlite3.Connection | None = None
        self._closing = False

    async def open(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._pool, self._initialize)

    def _initialize(self) -> None:
        if self._connection is not None:
            return
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=2, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            if conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise Failure(Code.STORE)
            conn.execute("PRAGMA synchronous=FULL")
            scripts = sorted(files(__package__).joinpath("migrations").iterdir(), key=lambda x: x.name)
            migrations = [(int(p.name.split("_")[0]), p.read_bytes()) for p in scripts if p.name.endswith(".sql")]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "migrations" not in tables:
                raise Failure(Code.SCHEMA)
            applied = dict(conn.execute("SELECT version,checksum FROM migrations")) if tables else {}
            if sorted(applied) != list(range(1, len(applied)+1)) or len(applied) > len(migrations):
                raise Failure(Code.SCHEMA)
            for expected, (version, raw) in enumerate(migrations, 1):
                checksum = hashlib.sha256(raw).hexdigest()
                if version != expected or applied.get(version, checksum) != checksum:
                    raise Failure(Code.SCHEMA)
                if version in applied:
                    continue
                if tables:
                    snapshot = self.path.with_suffix(f".pre-{version}-{uuid4().hex}.sqlite3")
                    backup = sqlite3.connect(snapshot)
                    try:
                        conn.backup(backup)
                    finally:
                        backup.close()
                conn.executescript("BEGIN IMMEDIATE;\n" + raw.decode("utf-8"))
                conn.execute("INSERT INTO migrations VALUES(?,?)", (version, checksum))
                conn.commit()
            if not migrations or conn.execute("PRAGMA quick_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
                raise Failure(Code.SCHEMA)
            conn.execute("UPDATE turns SET state='interrupted',ended_at=CURRENT_TIMESTAMP WHERE state='active'")
            self._connection = conn
        except (OSError, sqlite3.Error) as exc:
            raise Failure(Code.STORE) from exc
        finally:
            if conn is not None and self._connection is None:
                conn.close()

    async def call[T](self, operation: Callable[[sqlite3.Connection], T], *, write: bool = False) -> T:
        if self._closing:
            raise Failure(Code.STORE)

        def execute() -> T:
            conn = self._connection
            if conn is None:
                raise Failure(Code.STORE)
            try:
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                result = operation(conn)
                conn.commit()
                return result
            except sqlite3.Error as exc:
                conn.rollback()
                code = getattr(exc, "sqlite_errorcode", 0) & 255
                raise Failure(Code.BUSY if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else Code.STORE) from exc
            except BaseException:
                conn.rollback()
                raise

        return await asyncio.get_running_loop().run_in_executor(self._pool, execute)

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True

        def release() -> None:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

        try:
            await asyncio.get_running_loop().run_in_executor(self._pool, release)
        finally:
            self._pool.shutdown(wait=True)

