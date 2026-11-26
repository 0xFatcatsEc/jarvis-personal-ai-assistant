"""Prepare and report a restore in a fresh directory, without activating it."""
import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass
from importlib.resources import files
from itertools import zip_longest
from pathlib import Path
from uuid import UUID

from ..contracts.messages import Code, Failure
from ..settings import local_data_path, profile_path
from .database import _check_integrity
from .deletions import open_ledger, reconcile
from .snapshots import MAX_DATABASE_BYTES, _key, _write, decrypt_snapshot


@dataclass(frozen=True, slots=True)
class RestoreReport:
    status: str
    reason: str | None
    snapshot: str
    primary_sequence: int
    required_sequence: int | None
    ledger_sequence: int | None = None
    removed_facts: int = 0


def _artifact(folder: Path, key: bytes, kind: str) -> bytes:
    try:
        identity = UUID(folder.name).hex
    except ValueError as exc:
        raise Failure(Code.INPUT, field="snapshot_directory") from exc
    path = local_data_path(folder / f"{kind}.aesgcm")
    with path.open("rb") as stream:
        data = stream.read(MAX_DATABASE_BYTES + 257)
    if len(data) > MAX_DATABASE_BYTES + 256:
        raise Failure(Code.STORE, field="restore_size")
    return decrypt_snapshot(key, data, kind, identity)


def _primary_binding(conn: sqlite3.Connection) -> tuple[str, int]:
    _check_integrity(conn)
    migrations = {int(path.name.split("_")[0]): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in files(__package__).joinpath("migrations").iterdir()
                  if path.name.endswith(".sql")}
    if dict(conn.execute("SELECT version,checksum FROM migrations")) != migrations:
        raise Failure(Code.SCHEMA)
    binding = conn.execute("SELECT ledger_id,sequence FROM memory_ledger_binding WHERE singleton=1").fetchone()
    if binding is None:
        raise Failure(Code.SCHEMA)
    return binding


def _ledger_head(conn: sqlite3.Connection) -> int:
    _check_integrity(conn)
    count, first, last = conn.execute(
        "SELECT count(*),COALESCE(min(sequence),1),COALESCE(max(sequence),0) FROM deletions"
    ).fetchone()
    if first != 1 or count != last:
        raise Failure(Code.STORE, field="ledger_gap")
    return last


def _replay(primary: sqlite3.Connection, archived_path: Path, latest_path: Path,
            minimum: int, watermark: int) -> tuple[int, int]:
    with open_ledger(primary, archived_path) as archived, open_ledger(primary, latest_path) as latest:
        previous = _ledger_head(archived.conn)
        head = _ledger_head(latest.conn)
        if latest.key != archived.key or head < max(watermark, previous, minimum):
            raise Failure(Code.STORE, field="ledger_coverage")
        for table, cutoff, order in (
            ("deletions", "sequence", "sequence"),
            ("suppression", "deletion", "deletion,fingerprint"),
        ):
            query = f"SELECT * FROM {table} WHERE {cutoff}<=? ORDER BY {order}"
            original = archived.conn.execute(query, (previous,))
            candidate = latest.conn.execute(query, (previous,))
            if any(left != right for left, right in zip_longest(original, candidate)):
                raise Failure(Code.STORE, field="ledger_prefix")
        before = primary.execute("SELECT count(*) FROM facts").fetchone()[0]
        with primary:
            reconcile(primary, latest)
            _check_integrity(primary)
        after = primary.execute("SELECT count(*) FROM facts").fetchone()[0]
        return head, before - after


def stage_restore(snapshot: Path, key_path: Path, target: Path, *, latest_ledger_set: Path | None = None,
                  expected_sequence: int | None = None, protected_profile: Path | None = None) -> RestoreReport:
    """Stage an authenticated pair or a quarantine report. Never replace existing data."""
    if expected_sequence is not None and (type(expected_sequence) is not int or expected_sequence < 0):
        raise Failure(Code.INPUT, field="expected_sequence")
    if (not target.is_absolute() or any(":" in p or Path(p).is_reserved() for p in target.parts[1:])):
        raise Failure(Code.INPUT, field="staging_destination")
    snapshot = local_data_path(snapshot)
    latest = None
    if latest_ledger_set is not None:
        try:
            latest = local_data_path(latest_ledger_set)
        except Failure:
            pass
    target = local_data_path(target.parent) / target.name
    protected = [snapshot.parent]
    if latest is not None:
        protected.append(latest.parent)
    if protected_profile is not None:
        protected.append(local_data_path(protected_profile))
    if os.path.lexists(target) or any(target.is_relative_to(path) or path.is_relative_to(target) for path in protected):
        raise Failure(Code.CONFLICT, field="staging_destination")
    key = _key(local_data_path(key_path))
    identity = snapshot.name
    with tempfile.TemporaryDirectory(prefix=".stylus-restore-", dir=target.parent) as staging:
        work = Path(staging)
        shipment = work / "delivery"
        shipment.mkdir()
        primary_path = work / "jarvis.sqlite3"
        archived_path = work / "archived.sqlite3"
        latest_path = work / "jarvis.sqlite3.deletions.sqlite3"
        _write(primary_path, _artifact(snapshot, key, "primary"))
        with closing(sqlite3.connect(primary_path)) as primary:
            primary.execute("PRAGMA foreign_keys=ON")
            _, watermark = _primary_binding(primary)
            report = RestoreReport("quarantined", "independent_coverage_required", identity, watermark,
                                   expected_sequence)
            if latest is not None and latest != snapshot and expected_sequence is not None:
                try:
                    _write(archived_path, _artifact(snapshot, key, "ledger"))
                    _write(latest_path, _artifact(latest, key, "ledger"))
                    head, removed = _replay(primary, archived_path, latest_path, expected_sequence, watermark)
                except (OSError, sqlite3.Error, Failure):
                    report = RestoreReport("quarantined", "ledger_coverage_unverified", identity, watermark,
                                           expected_sequence)
                else:
                    report = RestoreReport("ready_for_review", None, identity, watermark, expected_sequence,
                                           head, removed)
                    primary.execute("PRAGMA journal_mode=DELETE")
        if report.status == "ready_for_review":
            with closing(sqlite3.connect(latest_path)) as ledger:
                ledger.execute("PRAGMA journal_mode=DELETE")
            data = shipment / "data"
            data.mkdir()
            primary_path.rename(data / primary_path.name)
            latest_path.rename(data / latest_path.name)
        _write(shipment / "restore-report.json", json.dumps(asdict(report), indent=2).encode("utf-8"))
        shipment.rename(target)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage a STYLUS JARVIS backup for review.")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--latest-ledger-set", type=Path)
    parser.add_argument("--expected-sequence", type=int)
    args = parser.parse_args()
    try:
        report = stage_restore(args.snapshot, args.key, args.target, latest_ledger_set=args.latest_ledger_set,
                               expected_sequence=args.expected_sequence, protected_profile=profile_path())
    except (Failure, OSError, sqlite3.Error):
        parser.exit(1, "Could not stage the backup. Check the snapshot, key, and unused local destination.\n")
    print(f"Restore status: {report.status}. See restore-report.json in the staging directory.")
    if report.status == "quarantined":
        parser.exit(2)


if __name__ == "__main__":
    main()
