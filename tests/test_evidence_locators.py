import asyncio
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.knowledge.locators import extract
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows evidence acceptance")
class EvidenceLocators(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory()))
        self.root = self.base / "atlas"
        self.root.mkdir()
        await self.open_store()
        self.scope = await self.store.select("owner", await self.store.register("owner", self.root), 1)

    async def open_store(self):
        self.db = Database(self.base / "profile" / "store.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)

    async def test_pdf_pages_scan_and_reopen(self):
        fixture = Path(__file__).parent / "fixtures/m0-v1/atlas/handbook.pdf"
        writer = PdfWriter()
        writer.append(PdfReader(fixture))
        scan = writer.add_blank_page(100, 100)
        content = DecodedStreamObject()
        content.set_data(b"q 100 0 0 100 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID \x80 EI Q")
        scan[NameObject("/Contents")] = writer._add_object(content)
        path = self.root / "scan.pdf"
        writer.write(path)
        r = await self.store.approve_source(self.scope, path)
        args = self.scope, r.source_id, r.revision_id
        pages = await self.store.extract_locators(*args)
        self.assertEqual([p.page for p in pages], [1, 2, 3])
        self.assertIn("SQLite", pages[0].excerpt)
        self.assertEqual([p.ocr_needed for p in pages], [False, False, True])
        path.unlink()
        await self.db.close()
        await self.open_store()
        self.assertEqual(await self.store.extract_locators(*args), pages)
        self.assertEqual(await self.store.resolve_locator(*args, pages[1].id), pages[1])

    async def test_unicode_ranges_revision_binding_and_project_isolation(self):
        path = self.root / "notes.txt"
        original = "é" * 1022 + "\r\n🐈end"
        path.write_bytes(original.encode("utf-8-sig"))
        first = await self.store.approve_source(self.scope, path)
        args = self.scope, first.source_id, first.revision_id
        left, right = await asyncio.gather(self.store.extract_locators(*args), self.store.extract_locators(*args))
        self.assertEqual(left, right)
        self.assertEqual([(p.start, p.end) for p in left], [(0, 1024), (1024, len(original))])
        self.assertEqual(left[1].excerpt, "🐈end")
        path.write_bytes(b"different")
        second = await self.store.approve_source(self.scope, path)
        newer = await self.store.extract_locators(self.scope, second.source_id, second.revision_id)
        self.assertNotEqual(newer[0].id, left[0].id)
        await self.db.close()
        await self.open_store()
        self.assertEqual(await self.store.resolve_locator(*args, left[1].id), left[1])
        other = self.base / "birch"
        other.mkdir()
        foreign = await self.store.select("owner", await self.store.register("owner", other), 1)
        for scope, revision in ((foreign, first.revision_id), (self.scope, second.revision_id)):
            with self.assertRaises(Failure) as denied:
                await self.store.resolve_locator(scope, first.source_id, revision, left[0].id)
            self.assertEqual(denied.exception.code, Code.SCOPE)

    async def test_unapproved_replacement_and_revocation_publish_nothing(self):
        path = self.root / "a.txt"
        path.write_bytes(b"first")
        r = await self.store.approve_source(self.scope, path)
        args = self.scope, r.source_id, r.revision_id
        path.write_bytes(b"other")
        with self.assertRaises(Failure) as changed:
            await self.store.extract_locators(*args)
        self.assertEqual(changed.exception.code, Code.CONFLICT)
        path.write_bytes(b"first")

        def revoke(root, revision):
            result = extract(root, revision)
            with closing(sqlite3.connect(self.db.path)) as conn, conn:
                conn.execute("UPDATE projects SET grant=grant+1")
            return result

        with patch("stylus_jarvis.storage.repositories.extract", revoke), self.assertRaises(Failure) as denied:
            await self.store.extract_locators(*args)
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM evidence_locators").fetchone()[0]), 0)
