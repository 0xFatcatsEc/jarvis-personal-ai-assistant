import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from benchmarks import qualify as q
from benchmarks.measurement import Sampler, latency


class QualificationTests(unittest.TestCase):
    def test_scoped_prompts_and_hidden_keys(self):
        prompts = dict(q.suite()[0])
        self.assertEqual(len(prompts), 25)
        self.assertIn("SQLite", prompts["Q01"])
        self.assertNotIn("PostgreSQL", prompts["Q01"])
        self.assertNotIn("SQLite", prompts["Q11"])
        for case in q.read(q.BENCH / "coding-v1.json")["cases"]:
            self.assertTrue(all(check not in prompts[case["id"]] for check in case["rubric"]))

    def test_nearest_rank_and_memory_headroom(self):
        self.assertEqual(latency(list(range(1,21)))["p95_s"],19)
        values = iter([(100,2),(127,8),(110,4)])
        sampler = Sampler(lambda: next(values))
        with sampler:
            sampler.sample()
        self.assertEqual(sampler.summary()["ram_mib"]["peak_above_baseline"],27)
        self.assertEqual(sampler.summary()["vram_mib"]["peak"],8)

    def test_incomplete_stream_rejected(self):
        def handler(req):
            return httpx.Response(200, text='{"model":"qwen3:4b","done":false,"message":{"content":"partial"}}\n')
        with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(ValueError,"interrupted"):
                q.chat(client,"qwen3:4b","question")

    def test_full_pair_and_grading_gates(self):
        resident = []
        seen = []
        def handler(req):
            path = req.url.path
            if path == "/api/tags":
                return httpx.Response(200,json={"models":[{"name":k,"digest":v} for k,v in q.PINS.items()]})
            if path == "/api/version":
                return httpx.Response(200,json={"version":"0.40.17"})
            if path == "/api/ps":
                return httpx.Response(200,json={"models":resident})
            data = json.loads(req.content)
            if path == "/api/generate":
                self.assertEqual(data["keep_alive"],0)
                resident.clear()
                return httpx.Response(200,json={})
            model = data["model"]
            self.assertFalse(data["think"])
            self.assertEqual(len(data["messages"]),1)
            self.assertEqual(data["options"],q.OPTIONS)
            seen.append((model,data["messages"][0]["content"]))
            resident[:] = [{"name":model,"digest":q.PINS[model]}]
            stream = [{"model":model,"done":False,"message":{"thinking":"private","content":""}},
                      {"model":model,"done":True,"load_duration":12,"eval_count":1,"message":{"content":"visible"}}]
            return httpx.Response(200,text="\n".join(map(json.dumps,stream)))
        client = httpx.Client(base_url="http://test",transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as tmp, patch.object(q.httpx,"Client",return_value=client), \
             patch.object(q,"environment",return_value={"fixture":True}), \
             patch.object(q,"Sampler",side_effect=lambda:Sampler(lambda:(120,10))):
            path = Path(tmp)/"run"
            q.run(path,11435,False)
            self.assertEqual([p for _,p in seen[:26]], [p for _,p in seen[26:]])
            self.assertEqual(q.read(path/"qwen3-4b"/"trials.json")[0]["answer"],"visible")
            self.assertFalse(resident)
            with self.assertRaises(ValueError):
                q.score(path)
            with (path/"review.csv").open() as file:
                rows = list(csv.DictReader(file))
            for row in rows:
                row.update(check_1="1",check_2="1",disclosure="0")
            def save():
                with (path/"review.csv").open("w",newline="") as file:
                    writer=csv.DictWriter(file,fieldnames=q.FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
            save()
            self.assertEqual(q.score(path)["candidate_for_owner_review"],"qwen3:4b")
            rows[0]["disclosure"]="1"
            save()
            self.assertEqual(q.score(path)["candidate_for_owner_review"],"qwen3:8b")
            rows.pop()
            save()
            with self.assertRaises(ValueError):
                q.score(path)
