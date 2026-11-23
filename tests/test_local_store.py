"""Windows acceptance for 1.2.2.1, using isolated on-disk databases."""
import ctypes
import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.settings import profile_path
from stylus_jarvis.storage.database import Database


@unittest.skipUnless(os.name == "nt", "Windows local-store qualification")
class LocalStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(strict=True)
        self.sync = self.root / "Synced company documents"
        self.sync.mkdir()
        self.enterContext(patch.dict(os.environ, {
            "LOCALAPPDATA": str(self.root / "Local"), "OneDriveCommercial": str(self.sync),
        }))
        self.data = profile_path() / "data"
        self.path = self.data / "jarvis.sqlite3"

    def database(self, path: Path) -> Database:
        db = Database(path)
        self.addAsyncCleanup(db.close)
        return db

    def junction(self, link: Path, target: Path) -> None:
        from _winapi import CreateJunction
        link.parent.mkdir(parents=True, exist_ok=True)
        CreateJunction(str(target), str(link))
        self.assertTrue(link.is_junction())

    async def test_live_database_and_wal_use_resolved_local_directory(self) -> None:
        target = self.root / "Local database files"
        target.mkdir()
        self.junction(self.data, target)
        db = self.database(self.path)
        await db.open()
        filename, mode, fk = await db.call(lambda c: (
            c.execute("PRAGMA database_list").fetchone()["file"],
            c.execute("PRAGMA journal_mode").fetchone()[0],
            c.execute("PRAGMA foreign_keys").fetchone()[0],
        ))
        expected = target / self.path.name
        self.assertEqual(Path(filename), expected)
        self.assertEqual(db.path, expected)
        self.assertEqual((mode, fk), ("wal", 1))
        for suffix in ("", "-wal", "-shm"):
            actual = Path(filename + suffix).resolve(strict=True)
            self.assertEqual(actual.parent, target)
            self.assertFalse(actual.is_relative_to(self.sync))

        def insert_invalid(c: sqlite3.Connection) -> None:
            c.execute("INSERT INTO projects(id,owner,root,identity) VALUES('p','owner','root','root')")
            c.execute("INSERT INTO conversations(id,project,title) VALUES('c','missing','title')")
        with self.assertRaises(Failure) as failure:
            await db.call(insert_invalid, write=True)
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(await db.call(lambda c: c.execute("SELECT count(*) FROM projects").fetchone()[0]), 0)

    async def test_junction_into_onedrive_denied_before_any_write(self) -> None:
        self.junction(self.data, self.sync)
        db = self.database(self.data / "new subdirectory" / self.path.name)
        with self.assertRaises(Failure):
            await db.open()
        self.assertEqual(list(self.sync.iterdir()), [])

    async def test_remote_volume_behind_junction_denied(self) -> None:
        target = self.root / "Mounted volume"
        target.mkdir()
        self.junction(self.data, target)
        # Exercise a real reparse point; emulate Windows' network-volume result
        # without requiring a mapped share or sending traffic off the laptop.
        kernel = ctypes.windll.kernel32
        with (patch.object(kernel, "GetVolumePathNameW", wraps=kernel.GetVolumePathNameW) as volume_path,
              patch.object(kernel, "GetDriveTypeW", return_value=4) as drive_type):
            with self.assertRaises(Failure):
                await self.database(self.path).open()
            self.assertEqual(Path(volume_path.call_args.args[0]), target)
            drive_type.assert_called()
        self.assertEqual(list(target.iterdir()), [])

    async def test_unc_location_rejected_before_filesystem_access(self) -> None:
        path = Path(r"\\unreachable.invalid\share\jarvis.sqlite3")
        with patch.object(Path, "lstat", side_effect=AssertionError("UNC path accessed")):
            with self.assertRaises(Failure) as failure:
                await self.database(path).open()
        self.assertEqual(failure.exception.code, Code.SETTINGS)

    async def test_dangling_junction_is_rejected(self) -> None:
        target = self.root / "retired volume"
        target.mkdir()
        self.junction(self.data, target)
        target.rmdir()
        with self.assertRaises(Failure):
            await self.database(self.path).open()
        self.assertFalse(target.exists())

    async def test_linked_database_or_sidecar_cannot_write_into_sync_root(self) -> None:
        self.data.mkdir(parents=True)
        for suffix in ("", "-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                source = self.sync / ("db" + suffix)
                source.touch()
                linked = self.path.with_name(self.path.name + suffix)
                linked.hardlink_to(source)
                db = self.database(self.path)
                try:
                    with self.assertRaises(Failure) as failure:
                        await db.open()
                    self.assertEqual(failure.exception.code, Code.SETTINGS)
                    self.assertEqual(source.read_bytes(), b"")
                finally:
                    await db.close()
                    linked.unlink(missing_ok=True)

    async def test_fts5_on_the_application_connection(self) -> None:
        db = self.database(self.path)
        await db.open()

        def exercise(conn: sqlite3.Connection) -> list[int]:
            conn.execute("CREATE VIRTUAL TABLE temp.store_fts_check USING fts5(body)")
            conn.executemany("INSERT INTO store_fts_check(body) VALUES(?)",
                             [("local conversation history",), ("unrelated record",)])
            return [r[0] for r in conn.execute(
                "SELECT rowid FROM store_fts_check WHERE store_fts_check MATCH ?", ('"conversation history"',)
            )]
        self.assertEqual(await db.call(exercise, write=True), [1], sqlite3.sqlite_version)

    def seed_v1(self) -> None:
        self.data.mkdir(parents=True)
        migration = files("stylus_jarvis.storage").joinpath("migrations/0001_initial.sql").read_bytes()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(migration.decode())
            conn.execute("INSERT INTO migrations VALUES(1,?)", (hashlib.sha256(migration).hexdigest(),))
            conn.execute("INSERT INTO projects(id,owner,root,identity) VALUES('p','owner','root','root')")
            conn.execute("INSERT INTO conversations(id,project,title) VALUES('c','p','original thread')")

    def assert_v1_data(self, path: Path) -> None:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            self.assertEqual(conn.execute("SELECT version FROM migrations").fetchall(), [(1,)])
            self.assertNotIn("grant_revision", [r[1] for r in conn.execute("PRAGMA table_info(turns)")])
            self.assertEqual(conn.execute("SELECT project,title FROM conversations").fetchall(), [("p", "original thread")])
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchall(), [("ok",)])
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_upgrade_and_restore_pre_upgrade_snapshot(self) -> None:
        self.seed_v1()
        db = self.database(self.path)
        await db.open()
        self.assertEqual(await db.call(lambda c: [r[0] for r in c.execute("SELECT version FROM migrations ORDER BY version")]), [1, 2])
        await db.call(lambda c: c.execute("UPDATE conversations SET title='after upgrade'").rowcount, write=True)
        await db.close()
        snapshot, = self.data.glob("*.pre-2-*.sqlite3")
        # Stage rollback in a clean directory so no newer WAL/SHM is reused.
        restored = self.root / "restore" / self.path.name
        restored.parent.mkdir()
        shutil.copyfile(snapshot, restored)
        self.assert_v1_data(restored)
        earlier_package = self.root / "v1-package"
        earlier_sql = earlier_package / "migrations" / "0001_initial.sql"
        earlier_sql.parent.mkdir(parents=True)
        earlier_sql.write_bytes(files("stylus_jarvis.storage").joinpath("migrations", earlier_sql.name).read_bytes())
        rollback = self.database(restored)
        with patch("stylus_jarvis.storage.database.files", return_value=earlier_package):
            await rollback.open()
        title = await rollback.call(lambda c: c.execute("SELECT title FROM conversations WHERE id='c'").fetchone()[0])
        self.assertEqual(title, "original thread")
        await rollback.close()
        self.assert_v1_data(restored)
        await self.database(self.path).open()
        self.assertEqual(list(self.data.glob("*.pre-2-*.sqlite3")), [snapshot])

    async def test_failed_upgrade_rolls_back_schema_data_and_ledger(self) -> None:
        self.seed_v1()
        resources = self.root / "package"
        migrations = resources / "migrations"
        migrations.mkdir(parents=True)
        original = files("stylus_jarvis.storage").joinpath("migrations/0001_initial.sql")
        (migrations / original.name).write_bytes(original.read_bytes())
        candidate = migrations / "0002_candidate.sql"
        for fault, statements in (
            ("SQL error", "SELECT * FROM missing_table;"),
            ("integrity check", "PRAGMA ignore_check_constraints=ON; INSERT INTO candidate VALUES(-1); "
                                "PRAGMA ignore_check_constraints=OFF;"),
        ):
            with self.subTest(fault=fault):
                candidate.write_text("UPDATE conversations SET title='uncommitted'; "
                                     "CREATE TABLE candidate(n INTEGER CHECK(n>0)); " + statements, encoding="utf-8")
                db = self.database(self.path)
                with patch("stylus_jarvis.storage.database.files", return_value=resources), self.assertRaises(Failure):
                    await db.open()
                with self.assertRaises(Failure) as blocked:
                    await db.call(lambda c: c.execute("SELECT 1").fetchone()[0])
                self.assertEqual(blocked.exception.code, Code.STORE)
                self.assert_v1_data(self.path)
                with closing(sqlite3.connect(self.path)) as conn:
                    self.assertIsNone(conn.execute("SELECT name FROM sqlite_schema WHERE name='candidate'").fetchone())
                await db.close()
