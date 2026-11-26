"""Scheduled, authenticated SQLite backups for a separately provisioned destination."""
import argparse
import asyncio
import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..contracts.messages import Code, Failure, Scope
from ..settings import check_local_route, local_data_path, profile_path
from .database import Database


MAX_DATABASE_BYTES = 64 * 1024 * 1024
DAILY = timedelta(hours=24)
HEADER = b"STYLUS-JARVIS-SNAPSHOT\x01"


@dataclass(frozen=True, slots=True)
class SourceDependency:
    owner: str
    project: str
    root: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class RecoveryStatus:
    destination: str | None = None
    age: timedelta | None = None
    problem: str | None = None
    sources: tuple[tuple[str, bool], ...] = ()
    source_count: int | None = None
    previous_configuration: bool = False

    def display(self) -> str:
        lines = [f"Backup destination: {self.destination}" if self.destination else "Backup destination: Not configured"]
        if self.age is None:
            lines.append("Last verified backup: No recorded success")
        else:
            hours, minutes = divmod(int(self.age.total_seconds()) // 60, 60)
            age = f"{hours} h {minutes} min ago" if hours else f"{minutes} min ago"
            suffix = " (previous configuration)" if self.previous_configuration else ""
            lines.append(f"Last verified backup: {age}{suffix}")
        if self.problem:
            lines.append(self.problem)
        lines.append("Original source files are stored separately from the backup.")
        if self.source_count is None:
            lines.append("Source inventory: Select a project with a recorded snapshot inventory.")
        else:
            lines.append(f"Source dependencies in the selected project: {self.source_count}")
            lines.extend(f"{'Available' if available else 'Unavailable'} · {path}"
                         for path, available in self.sources)
            if self.source_count > len(self.sources):
                lines.append(f"Showing the first {len(self.sources)} dependencies.")
        return "\n".join(lines)


def _paths(root: Path, destination: Path, key: Path) -> tuple[Path, Path]:
    if not destination.is_absolute() or not key.is_absolute():
        raise Failure(Code.INPUT)
    # Reject Windows streams and device filenames before opening any user path.
    for path in (destination, key):
        if any(":" in part or Path(part).is_reserved() for part in path.parts[1:]):
            raise Failure(Code.INPUT)
    root, destination, key = (local_data_path(path) for path in (root, destination, key))
    if (destination.is_relative_to(root) or root.is_relative_to(destination)
            or key.is_relative_to(root) or key.is_relative_to(destination)):
        raise Failure(Code.SETTINGS, field="backup_paths")
    if not destination.is_dir():
        raise Failure(Code.STORE, field="backup_destination")
    if not key.parent.is_dir():
        raise Failure(Code.STORE, field="backup_key")
    return destination, key


def _write(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _key(path: Path) -> bytes:
    if not path.is_file():
        raise Failure(Code.STORE, field="backup_key")
    with path.open("rb") as stream:
        key = stream.read(33)
    if len(key) != 32:
        raise Failure(Code.SETTINGS, field="backup_key")
    return key


def configure(root: Path, destination: Path, key_path: Path) -> None:
    """First-time setup or reconfiguration with a new or existing recovery key."""
    destination, key_path = _paths(root, destination, key_path)
    if not key_path.exists():
        _write(key_path, secrets.token_bytes(32))
    _key(key_path)
    config = local_data_path(root / "config")
    config.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config) as staging:
        candidate = Path(staging) / "schedule.json"
        _write(candidate, json.dumps({"destination": str(destination), "key": str(key_path)}).encode("utf-8"))
        candidate.replace(config / "snapshots.json")


def _copy_snapshot(path: Path, stop: threading.Event) -> sqlite3.Connection:
    target = sqlite3.connect(":memory:")
    deadline = time.monotonic() + 60
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as source:
            page_size = source.execute("PRAGMA page_size").fetchone()[0]

            def progress(status: int, remaining: int, total: int) -> None:
                if stop.is_set() or time.monotonic() >= deadline:
                    raise Failure(Code.BUSY)
                if total * page_size > MAX_DATABASE_BYTES:
                    raise Failure(Code.STORE, field="backup_size")

            source.backup(target, pages=32, progress=progress, sleep=.025)
        if (target.execute("PRAGMA quick_check").fetchone() != ("ok",)
                or target.execute("PRAGMA foreign_key_check").fetchone() is not None):
            raise Failure(Code.STORE, field="backup_integrity")
        return target
    except BaseException:
        target.close()
        raise


def decrypt_snapshot(key: bytes, envelope: bytes, kind: str, snapshot_id: str) -> bytes:
    """Open and authenticate one artifact for a known set ID and purpose."""
    header = HEADER + bytes.fromhex(snapshot_id) + kind.encode("ascii")
    if not envelope.startswith(header):
        raise Failure(Code.STORE, field="backup_format")
    payload = envelope[len(header):]
    try:
        return AESGCM(key).decrypt(payload[:12], payload[12:], header)
    except (InvalidTag, ValueError) as exc:
        raise Failure(Code.STORE, field="backup_verification") from exc


def _seal(path: Path, snapshot: sqlite3.Connection, key: bytes, kind: str, snapshot_id: str) -> None:
    data = snapshot.serialize()
    header = HEADER + bytes.fromhex(snapshot_id) + kind.encode("ascii")
    nonce = secrets.token_bytes(12)
    _write(path, header + nonce + AESGCM(key).encrypt(nonce, data, header))
    if decrypt_snapshot(key, path.read_bytes(), kind, snapshot_id) != data:
        raise Failure(Code.STORE, field="backup_verification")


def snapshot(db: Database, root: Path, destination: Path, key_path: Path, stop: threading.Event,
             dependencies: list[SourceDependency] | None = None) -> str:
    destination, key_path = _paths(root, destination, key_path)
    key = _key(key_path)
    snapshot_id = uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".stylus-backup-", dir=destination) as workspace:
        stage = Path(workspace) / snapshot_id
        stage.mkdir()
        with closing(_copy_snapshot(db.path, stop)) as primary:
            binding = primary.execute("SELECT ledger_id,sequence FROM memory_ledger_binding").fetchone()
            if dependencies is not None:
                dependencies.extend(SourceDependency(*row) for row in primary.execute(
                    "SELECT p.owner,s.project,p.root,s.relative_path FROM sources s "
                    "JOIN projects p ON p.id=s.project ORDER BY s.project,s.relative_path"))
            _seal(stage / "primary.aesgcm", primary, key, "primary", snapshot_id)
        with closing(_copy_snapshot(db.deletion_path(), stop)) as ledger:
            ids = ledger.execute("SELECT id FROM identity").fetchall()
            watermark = ledger.execute("SELECT COALESCE(MAX(sequence),0) FROM deletions").fetchone()[0]
            if binding is None or ids != [(binding[0],)] or watermark < binding[1]:
                raise Failure(Code.STORE, field="backup_ledger")
            _seal(stage / "ledger.aesgcm", ledger, key, "ledger", snapshot_id)
        if stop.is_set():
            raise Failure(Code.BUSY)
        stage.rename(destination / snapshot_id)
    return snapshot_id


class SnapshotSchedule:
    def __init__(self, db: Database, root: Path, report: Callable[[Code], None],
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.db = db
        self.root = root
        self.report = report
        self.now = now
        self.stop = threading.Event()
        self._wake = asyncio.Event()
        self._problem: str | None = None

    def shutdown(self) -> None:
        self.stop.set()
        self._wake.set()

    def check(self) -> None:
        config = local_data_path(self.root / "config" / "snapshots.json")
        if not config.exists():
            return
        settings = json.loads(config.read_bytes())
        destination, key = (Path(settings[name]) for name in ("destination", "key"))
        _, resolved_key = _paths(self.root, destination, key)
        _key(resolved_key)
        receipt = local_data_path(config.with_name("snapshot-receipt.json"))
        if receipt.exists():
            last = json.loads(receipt.read_bytes())
            if (last["configuration"] == settings and self.now() - datetime.fromisoformat(last["at"]) < DAILY
                    and self.now() >= datetime.fromisoformat(last["at"])):
                return
        dependencies: list[SourceDependency] = []
        snapshot_id = snapshot(self.db, self.root, destination, key, self.stop, dependencies)
        with tempfile.TemporaryDirectory(dir=config.parent) as stage:
            candidate = Path(stage) / "receipt.json"
            _write(candidate, json.dumps({"at": self.now().isoformat(), "snapshot": snapshot_id,
                                          "configuration": settings,
                                          "sources": [asdict(source) for source in dependencies]}).encode("utf-8"))
            candidate.replace(receipt)

    def status(self, scope: Scope | None) -> RecoveryStatus:
        try:
            config = local_data_path(self.root / "config" / "snapshots.json")
            configured = json.loads(config.read_bytes()) if config.exists() else None
            receipt = local_data_path(config.with_name("snapshot-receipt.json"))
            last = json.loads(receipt.read_bytes()) if receipt.exists() else None
            age = max(timedelta(0), self.now() - datetime.fromisoformat(last["at"])) if last else None
            destination = configured["destination"] if configured else None
            problem = self._problem if configured else None
            if configured:
                try:
                    target, key = _paths(self.root, Path(destination), Path(configured["key"]))
                    _key(key)
                    if last and last["configuration"] == configured:
                        backup = target / UUID(last["snapshot"]).hex
                        for name in ("primary.aesgcm", "ledger.aesgcm"):
                            check_local_route(backup / name)
                            if not (backup / name).is_file():
                                problem = "Last verified backup files are unavailable at the destination."
                                break
                except Failure as exc:
                    problem = _backup_problem(exc)
                except OSError:
                    problem = "Backup destination or recovery key is unavailable."
            sources = ()
            count = None
            if scope is not None and last and "sources" in last:
                owned = [SourceDependency(**row) for row in last["sources"]
                         if row["owner"] == scope.owner and row["project"] == scope.project]
                count = len(owned)
                sources = tuple((item.relative_path, _source_available(item)) for item in owned[:100])
            return RecoveryStatus(destination, age, problem, sources, count,
                                  bool(last and last["configuration"] != configured))
        except (Failure, OSError, ValueError, TypeError, KeyError):
            return RecoveryStatus(problem="Backup configuration or receipt could not be read.")

    async def run(self) -> None:
        while not self.stop.is_set():
            try:
                await asyncio.to_thread(self.check)
                self._problem = None
            except Failure as exc:
                if not self.stop.is_set():
                    self._problem = _backup_problem(exc)
                    self.report(exc.code)
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
                self._problem = "Backup attempt failed. Check the destination and local storage."
                self.report(Code.STORE)
            try:
                await asyncio.wait_for(self._wake.wait(), 60)
            except TimeoutError:
                pass


def _backup_problem(failure: Failure) -> str:
    if failure.field == "backup_destination":
        return "Backup destination is unavailable."
    if failure.field == "backup_key":
        return "Recovery key is missing or invalid."
    if failure.field in ("data_directory", "backup_paths") or failure.code == Code.OFFLINE:
        return "Backup destination or recovery key location is unavailable or disallowed."
    return "Backup attempt failed. The previous verified receipt is retained."


def _source_available(item: SourceDependency) -> bool:
    root = Path(item.root)
    relative = Path(item.relative_path)
    if not root.is_absolute() or relative.anchor or ".." in relative.parts:
        return False
    path = root / relative
    try:
        check_local_route(path)
        return path.resolve(strict=True).is_relative_to(root) and path.is_file()
    except (Failure, OSError, RuntimeError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure STYLUS JARVIS daily snapshots.")
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    args = parser.parse_args()
    try:
        configure(profile_path(), args.destination, args.key)
    except (Failure, OSError) as exc:
        parser.exit(1, f"Snapshot configuration failed. {exc}\n")
    print("Daily snapshots configured. Keep a separate recovery copy of the key.")


if __name__ == "__main__":
    main()
