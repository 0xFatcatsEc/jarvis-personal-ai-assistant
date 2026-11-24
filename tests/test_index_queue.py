import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from stylus_jarvis.contracts.messages import Code, Failure, Scope
from stylus_jarvis.runtime.index_queue import MAX_PENDING, IndexQueue
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


class IndexQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_queue_accepts_replacement_and_clear_discards_pending(self) -> None:
        queue = IndexQueue(Mock(spec=Repositories), Mock())
        scope = Scope("owner", "project", "conversation", 1, 1)
        for number in range(MAX_PENDING):
            self.assertEqual(queue.put(scope, Path(f"fixture-{number}")), number == 0)
        self.assertFalse(queue.put(scope, Path("fixture-0")))
        with self.assertRaises(Failure) as raised:
            queue.put(scope, Path("overflow"))
        self.assertEqual(raised.exception.code, Code.BUSY)
        queue.clear()
        await queue.drain()
        self.assertFalse(queue.pending)
        self.assertFalse(queue.running)

    async def test_foreground_yields_and_latest_requested_bytes_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            source = project / "notes.txt"
            source.write_text("original searchable", encoding="utf-8")
            database = Database(root / "store.db")
            await database.open()
            try:
                store = Repositories(database)
                project_id = await store.register("owner", project)
                scope = await store.select("owner", project_id, 1)
                reports = []
                queue = IndexQueue(store, lambda reported_scope, text: reports.append((reported_scope, text)))
                self.assertTrue(queue.put(scope, source))
                await queue.drain()
                first = (await store.search_evidence(scope, "original searchable"))[0]
                queue.set_foreground(True)
                source.write_text("superseded while live", encoding="utf-8")
                self.assertTrue(queue.put(scope, source))
                worker = asyncio.create_task(queue.drain())
                try:
                    async with asyncio.timeout(2):
                        while queue.active is None:
                            await asyncio.sleep(.01)
                    source.write_text("latest version is searchable", encoding="utf-8")
                    self.assertFalse(queue.put(scope, source))
                    self.assertEqual(await store.search_evidence(scope, "latest version"), [])
                    self.assertEqual(len(reports), 1)
                    self.assertFalse(worker.done())
                    self.assertEqual(await store.active_revision(scope, first.source), first.revision)
                finally:
                    queue.set_foreground(False)
                    await asyncio.wait_for(worker, 3)
                latest = (await store.search_evidence(scope, "latest version"))[0]
                self.assertEqual(latest.source, first.source)
                self.assertNotEqual(latest.revision, first.revision)
                self.assertEqual(await store.search_evidence(scope, "superseded while live"), [])
                self.assertEqual((await store.search_evidence(scope, "original searchable",
                                                             revision=first.revision))[0], first)
                self.assertEqual(len(reports), 2)
            finally:
                await database.close()
