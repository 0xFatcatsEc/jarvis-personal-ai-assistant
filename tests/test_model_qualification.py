import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from benchmarks import qualify as q
from benchmarks import measurement
from benchmarks.measurement import Sampler, latency


class QualificationTests(unittest.TestCase):
    def test_nvidia_path_with_spaces_outside_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe"
            exe.parent.mkdir(parents=True)
            exe.touch()
            with patch.object(measurement.shutil, "which", return_value=None), \
                 patch.dict(os.environ, {"ProgramFiles": str(Path(tmp) / "Program Files")}, clear=True), \
                 patch.object(subprocess, "check_output", return_value=b"245\r\n") as run:
                self.assertEqual(measurement._gpu_memory_mib(), 245)
                self.assertEqual(run.call_args.args[0][0], str(exe))
        with patch.object(measurement.shutil, "which", return_value=None), patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(measurement._gpu_memory_mib())

    def test_missing_gpu_readings_and_recovery(self):
        replies = [subprocess.CalledProcessError(255, "nvidia-smi"), b"N/A", b"0\r\n",
                   subprocess.TimeoutExpired("nvidia-smi", 8), FileNotFoundError(), b"380\r\n"]
        with patch.object(measurement.shutil, "which", return_value="nvidia-smi.exe"), \
             patch.object(subprocess, "check_output", side_effect=replies):
            sampler = Sampler(lambda: (1024, measurement._gpu_memory_mib()))
            with sampler:
                for _ in range(4):
                    sampler.sample()
        self.assertEqual([s["vram_mib"] for s in sampler.samples], [None, None, 0, None, None, 380])
        self.assertEqual(sampler.summary()["vram_mib"], {"baseline": None, "peak": 380, "peak_above_baseline": None})
        self.assertEqual(sampler.summary()["ram_mib"]["baseline"], 1024)

    def test_hardware_preflight_survives_nvidia_failure(self):
        snapshot = {"ac_line":"connected","model":"Thin A15","nvidia_gpus":None}
        with patch.object(subprocess, "check_output", side_effect=[
            subprocess.CalledProcessError(1,"powershell"), json.dumps(snapshot), "1"
        ]) as run:
            self.assertIsNone(q.environment()["nvidia_gpus"])
            self.assertIn("-SkipNvidiaQuery", run.call_args_list[1].args[0])

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
             patch.object(q,"Sampler",side_effect=lambda:Sampler(lambda:(120,None))):
            path = Path(tmp)/"run"
            q.run(path,11435,False)
            self.assertEqual([p for _,p in seen[:26]], [p for _,p in seen[26:]])
            self.assertEqual(q.read(path/"qwen3-4b"/"trials.json")[0]["answer"],"visible")
            self.assertFalse(resident)
            gpu = q.read(path/"qwen3-8b"/"metrics.json")["memory"]["vram_mib"]
            self.assertEqual(gpu, {"baseline": None, "peak": None, "peak_above_baseline": None})
            self.assertIsNone(q.read(path/"qwen3-4b"/"memory.json")[0]["vram_mib"])
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

            # A reviewed startup OOM excludes only the failed candidate.
            meta = q.read(path/"run.json")
            meta["status"] = "incomplete"
            q.write(path/"run.json", meta)
            eight = path/"qwen3-8b"
            q.write(eight/"environment.json", {"nvidia_gpus":[{"dedicated_mib":4096}]})
            exclusion = {"model":"qwen3:8b", "digest":q.PINS["qwen3:8b"],
                         "stage":"cold_model_load","reason":"cuda_out_of_memory",
                         "source":"test server log","excerpt":"CUDA error: out of memory"}
            q.write(path/"disqualified.json", exclusion)
            with self.assertRaisesRegex(ValueError, "before the first trial"):
                q.score(path)
            (eight/"trials.json").unlink()
            (eight/"metrics.json").unlink()
            rows[:] = [row for row in rows if row["model"] == "qwen3:4b"]
            save()
            self.assertIsNone(q.score(path)["candidate_for_owner_review"])  # disclosure still fails 4B
            rows[0]["disclosure"] = "0"
            save()
            adjudicated = q.score(path)
            self.assertEqual(adjudicated["candidate_for_owner_review"], "qwen3:4b")
            self.assertNotIn("coding_out_of_10", adjudicated["models"]["qwen3:8b"])
            exclusion["reason"] = "telemetry_timeout"
            q.write(path/"disqualified.json", exclusion)
            with self.assertRaises(ValueError):
                q.score(path)
