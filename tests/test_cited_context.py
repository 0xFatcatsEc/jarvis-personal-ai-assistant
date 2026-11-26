import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.knowledge.answers import extract_answer
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


FIXTURE = Path(__file__).parent / "fixtures" / "m0-v1"


@unittest.skipUnless(os.name == "nt", "Windows retrieval acceptance")
class CitedContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db = Database(self.root / "profile" / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)
        self.scopes = {}
        self.revisions = {}
        for project in ("atlas", "birch"):
            folder = self.root / project
            folder.mkdir()
            project_id = await self.store.register("owner", folder)
            scope = await self.store.select("owner", project_id, 1)
            self.scopes[project] = scope
            path = folder / "handbook.pdf"
            shutil.copyfile(FIXTURE / project / path.name, path)
            self.revisions[project] = await self.publish(scope, path)

    async def publish(self, scope, path, replaces=None):
        rev = await self.store.approve_source(scope, path)
        pair = rev.source_id, rev.revision_id
        await self.store.extract_locators(scope, *pair)
        await self.store.publish_revision(scope, *pair, replaces=replaces)
        return pair

    async def test_frozen_questions_and_citation_round_trip(self):
        for case in json.loads((FIXTURE / "cases.json").read_bytes())["cases"]:
            with self.subTest(case=case["id"]):
                scope = self.scopes[case["project"]]
                result = await self.store.cited_context(scope, case["question"])
                if case["expected"] == "abstain":
                    self.assertEqual((result.status, result.passages), ("insufficient_evidence", ()))
                    continue
                first = result.passages[0]
                self.assertIn(case["answer"].lower(), first.text.lower())
                for passage in result.passages:
                    for c in passage.citations:
                        self.assertEqual((c.source, c.revision), self.revisions[case["project"]])
                        loc = await self.store.resolve_locator(scope, c.source, c.revision, c.locator)
                        self.assertEqual(loc.excerpt, passage.text)
                self.assertEqual(first.citations[0].page, case["citation"]["page"])
                self.assertEqual(first.citations[0].relative_path, case["citation"]["file"])

    async def test_duplicates_conflict_budget_and_history(self):
        scope = self.scopes["atlas"]
        path = self.root / "atlas" / "copy.pdf"
        shutil.copyfile(FIXTURE / "atlas" / "handbook.pdf", path)
        old = await self.publish(scope, path)
        dedup = await self.store.cited_context(scope, "nightly export")
        self.assertEqual(len(dedup.passages), 1)
        self.assertEqual(len(dedup.passages[0].citations), 2)
        shutil.copyfile(FIXTURE / "birch" / "handbook.pdf", path)
        await self.publish(scope, path, replaces=old)
        conflict = await self.store.cited_context(scope, "nightly export")
        self.assertEqual(len(conflict.passages), 2)
        self.assertTrue(any("CSV" in p.text for p in conflict.passages))
        self.assertTrue(any("JSON" in p.text for p in conflict.passages))
        quotes = extract_answer("nightly export", conflict).passages
        self.assertEqual({p.text for p in quotes}, {"The nightly export is CSV.", "The nightly export is JSON."})
        self.assertEqual([p.citations for p in quotes], [p.citations for p in conflict.passages])
        bounded = await self.store.cited_context(scope, "nightly export", max_passages=1)
        self.assertEqual(bounded.passages, conflict.passages[:1])
        exact_bytes = len(conflict.payload().encode("utf-8"))
        self.assertEqual(await self.store.cited_context(scope, "nightly export", max_bytes=exact_bytes), conflict)
        smaller = await self.store.cited_context(scope, "nightly export", max_bytes=exact_bytes - 1)
        self.assertLess(len(smaller.payload().encode("utf-8")), exact_bytes)
        self.assertEqual(len(smaller.passages), 1)
        self.assertEqual((await self.store.cited_context(scope, "export", max_bytes=2)).status,
                         "insufficient_evidence")
        old_only = await self.store.cited_context(scope, "nightly export", revision=old[1])
        self.assertEqual(old_only.passages[0].citations[0].revision, old[1])
        self.assertIn("CSV", old_only.passages[0].text)
        foreign = await self.store.cited_context(self.scopes["birch"], "export", revision=old[1])
        self.assertEqual(foreign.status, "insufficient_evidence")

    async def test_overlapping_ranges_and_revoked_delivery(self):
        scope = self.scopes["atlas"]
        path = self.root / "atlas" / "range.txt"
        path.write_text("alpha shared omega", encoding="utf-8")
        rev = await self.store.approve_source(scope, path)
        # Insert two valid overlapping ranges as a future extractor could produce.
        await self.db.call(lambda c: c.executemany("INSERT INTO evidence_locators VALUES(?,?,?,NULL,?,?,?,0)",
            [("left", rev.revision_id, "range-v2", 0, 12, "alpha shared"),
             ("right", rev.revision_id, "range-v2", 6, 18, "shared omega")]), write=True)
        await self.store.publish_revision(scope, rev.source_id, rev.revision_id)
        result = await self.store.cited_context(scope, "shared")
        self.assertEqual([p.text for p in result.passages], ["alpha shared omega"])
        self.assertEqual({c.locator for c in result.passages[0].citations}, {"left", "right"})
        validate = self.store.validate

        async def revoke(current):
            await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?",
                                                   (current.project,)), write=True)
            await validate(current)

        with patch.object(self.store, "validate", revoke), self.assertRaises(Failure) as refused:
            await self.store.cited_context(scope, "shared")
        self.assertEqual(refused.exception.code, Code.SCOPE)
