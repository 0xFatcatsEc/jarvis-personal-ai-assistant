"""Protect the qualification inputs from accidental drift between model runs."""
import hashlib
import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "m0-v1"


class QualificationFixtureTests(unittest.TestCase):
    def test_frozen_inputs(self) -> None:
        manifest = json.loads((FIXTURE / "checksums.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), {"atlas/handbook.pdf", "birch/handbook.pdf", "cases.json", "passages.json"})
        for name, digest in manifest.items():
            with self.subTest(name=name):
                content = (FIXTURE / name).read_bytes()
                if name.endswith(".json"):
                    content = json.dumps(json.loads(content), sort_keys=True, separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(content).hexdigest(), digest)

    def test_answer_key_has_scoped_evidence(self) -> None:
        fixture = json.loads((FIXTURE / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["revision"], "m0-v1")
        cases = fixture["cases"]
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), 20)
        passages = json.loads((FIXTURE / "passages.json").read_text(encoding="utf-8"))
        evidence = {(p["project"], p["file"], p["page"]): p["text"] for p in passages}
        for project in ("atlas", "birch"):
            scoped = [c for c in cases if c["project"] == project]
            self.assertEqual(len(scoped), 10)
            self.assertEqual(sum(c["expected"] == "abstain" for c in scoped), 2)
            for case in scoped:
                with self.subTest(question=case["id"]):
                    if case["expected"] == "abstain":
                        self.assertIsNone(case["citation"])
                        self.assertIsNone(case["answer"])
                    else:
                        citation = case["citation"]
                        self.assertIn(case["answer"].lower(), evidence[project, citation["file"], citation["page"]].lower())

