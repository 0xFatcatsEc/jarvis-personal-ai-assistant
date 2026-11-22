"""Run paired Qwen trials on a dedicated local Ollama server, then score reviewed answers."""
import argparse
import csv
import hashlib
import json
import subprocess
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .measurement import Sampler, latency

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks"
RECALL = ROOT / "tests/fixtures/m0-v1"
FOUR = tomllib.loads((ROOT / "src/stylus_jarvis/release-manifest.toml").read_text())["digest"]
PINS = {"qwen3:4b": FOUR, "qwen3:8b": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"}
OPTIONS = {"num_ctx": 4096, "num_predict": 512, "temperature": 0, "seed": 41}
COLD = "What is 13 plus 9? Reply only with the number."
FIELDS = ["model", "case", "check_1", "check_2", "disclosure", "note"]


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, obj: Any) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def suite() -> tuple[list[tuple[str, str]], dict]:
    hashes = read(RECALL / "checksums.json")
    for name, expected in hashes.items():
        raw = (RECALL / name).read_bytes()
        if name.endswith(".json"):
            raw = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Frozen recall fixture changed: {name}")
    passages = read(RECALL / "passages.json")
    prompts = []
    for case in read(RECALL / "cases.json")["cases"]:
        project = case["project"]
        excerpts = [f"{p['file']} page {p['page']}: {p['text']}" for p in passages if p["project"] == project]
        prompt = (f"Active project: {project}. Use only its supplied evidence. Give the answer and cite file and page. "
                  "If the evidence is missing, say so.\n" + "\n".join(excerpts) + "\nQuestion: " + case["question"])
        prompts.append((case["id"], prompt))
    coding = BENCH / "coding-v1.json"
    prompts.extend((c["id"], c["prompt"]) for c in read(coding)["cases"])
    hashes["coding-v1.json"] = hashlib.sha256(coding.read_bytes()).hexdigest()
    return prompts, hashes


def chat(client: httpx.Client, model: str, prompt: str) -> dict:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "stream": True, "think": False, "keep_alive": "10m", "options": OPTIONS}
    answer = ""
    first = None
    start = time.perf_counter()
    with client.stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.strip():
                continue
            frame = json.loads(line)
            if "error" in frame or frame.get("model") != model or type(frame.get("done")) is not bool:
                raise ValueError("Invalid model stream")
            answer += frame["message"]["content"]
            if first is None and answer.strip():
                first = time.perf_counter() - start
            if frame["done"]:
                if first is None:
                    raise ValueError("Terminal response contained no visible text")
                return {"answer": answer, "first_text_s": first, "complete_s": time.perf_counter()-start,
                        "load_s": frame["load_duration"]/1e9, "output_tokens": frame["eval_count"],
                        "done_reason": frame.get("done_reason")}
    raise ValueError("Model stream interrupted")


def loaded(client: httpx.Client) -> list[dict]:
    return client.get("/api/ps").raise_for_status().json()["models"]


def unload(client: httpx.Client, model: str) -> None:
    if any(m["name"] == model for m in loaded(client)):
        client.post("/api/generate", json={"model": model, "keep_alive": 0}).raise_for_status()
    deadline = time.monotonic() + 30
    while loaded(client):
        if time.monotonic() >= deadline:
            raise ValueError("Dedicated server must contain no other loaded model")
        time.sleep(.25)


def environment() -> dict:
    command = ["powershell.exe", "-NoProfile", "-NonInteractive"]
    hardware = json.loads(subprocess.check_output(
        [*command, "-File", str(ROOT / "packaging/windows/measure-foundation.ps1")], text=True, timeout=60))
    code_count = int(subprocess.check_output(
        [*command, "-Command", "@(Get-Process -Name Code -ErrorAction SilentlyContinue).Count"], text=True, timeout=15))
    if hardware["ac_line"] != "connected" or not code_count or "Thin A15" not in hardware["model"]:
        raise ValueError("Qualification requires the MSI Thin A15 on AC with VS Code open")
    return {**hardware, "vscode_process_count": code_count}


def collect(client: httpx.Client, model: str, prompts: list[tuple[str, str]], folder: Path) -> None:
    results: list[dict] = []
    samples = Sampler()
    try:
        with samples:
            for key, prompt in [("cold", COLD), *prompts]:
                resident = loaded(client)
                if key == "cold":
                    valid = not resident
                else:
                    valid = len(resident) == 1 and resident[0]["digest"].removeprefix("sha256:") == PINS[model]
                if not valid:
                    raise ValueError(f"Invalid model residency before {key}")
                result = chat(client, model, prompt)
                results.append({"case": key, **result})
                write(folder / "trials.json", results)
                print(model, key, f"{result['first_text_s']:.2f}s to first text", flush=True)
    finally:
        write(folder / "memory.json", samples.samples)
    final = loaded(client)
    if len(final) != 1 or final[0]["digest"].removeprefix("sha256:") != PINS[model]:
        raise ValueError("Candidate residency lost before final observation")
    write(folder / "metrics.json", {"cold": results[0], "memory": samples.summary(),
          "warm_recall": latency([r["first_text_s"] for r in results if r["case"].startswith("Q")]),
          "warm_coding": latency([r["first_text_s"] for r in results if r["case"].startswith("C")]),
          "residency_after": final})


def run(output: Path, port: int, reverse: bool) -> None:
    prompts, hashes = suite()
    models = list(reversed(PINS)) if reverse else list(PINS)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, follow_redirects=False,
                      timeout=httpx.Timeout(180, connect=5)) as client:
        tags = {v["name"]: v for v in client.get("/api/tags").raise_for_status().json()["models"]}
        for name, digest in PINS.items():
            if tags.get(name, {}).get("digest", "").removeprefix("sha256:") != digest:
                raise ValueError(f"Missing or wrong local digest: {name}")
        if loaded(client):
            raise ValueError("Start with an empty dedicated server")
        version = client.get("/api/version").raise_for_status().json()
        if version.get("version") != "0.40.17":
            raise ValueError("Qualification requires the provisioned Ollama 0.40.17 runtime")
        hardware = environment()
        output.mkdir(parents=True, exist_ok=False)
        meta = {"started": datetime.now(UTC).isoformat(), "status": "incomplete", "order": models,
                "fixtures": hashes, "options": OPTIONS, "think": False, "hardware": hardware,
                "server": version, "models": {m: tags[m] for m in models}}
        write(output / "run.json", meta)
        for model in models:
            folder = output / model.replace(":", "-")
            folder.mkdir()
            try:
                write(folder / "environment.json", environment())
                collect(client, model, prompts, folder)
            finally:
                unload(client, model)
        with (output / "review.csv").open("x", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            for model in models:
                writer.writerows({"model": model, "case": key} for key, _ in prompts)
        meta["status"] = "measured"
        write(output / "run.json", meta)


def score(folder: Path) -> dict:
    meta = read(folder / "run.json")
    prompts, hashes = suite()
    if meta["status"] != "measured" or meta["fixtures"] != hashes or meta["options"] != OPTIONS:
        raise ValueError("Incomplete run or changed comparison inputs")
    with (folder / "review.csv").open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    expected = {(m, k) for m in PINS for k, _ in prompts}
    if len(rows) != len(expected) or {(r["model"],r["case"]) for r in rows} != expected:
        raise ValueError("Missing, unknown or duplicated review rows")
    scores = {}
    for model in PINS:
        if meta["models"][model]["digest"].removeprefix("sha256:") != PINS[model]:
            raise ValueError("Candidate digest mismatch")
        path = folder / model.replace(":", "-")
        trials = read(path / "trials.json")
        if [r["case"] for r in trials] != ["cold", *[k for k, _ in prompts]]:
            raise ValueError("Missing or reordered trial evidence")
        recall = coding = leaks = 0
        for r in (r for r in rows if r["model"] == model):
            is_recall = r["case"].startswith("Q")
            if r["check_1"] not in ("0","1") or r["check_2"] not in ("0","1"):
                raise ValueError(f"Grade both checks for {model} {r['case']}")
            if is_recall:
                if r["disclosure"] not in ("0","1"):
                    raise ValueError("Review each recall answer for cross-project disclosure")
                leaks += int(r["disclosure"])
                recall += int(r["check_1"] == r["check_2"] == "1" and r["disclosure"] == "0")
            else:
                coding += int(r["check_1"]) + int(r["check_2"])
        warm = latency([r["first_text_s"] for r in trials if r["case"].startswith("Q")])
        metrics = read(path / "metrics.json")
        scores[model] = {"recall_out_of_20":recall,"disclosures":leaks,"coding_out_of_10":coding,
                         "cold_first_text_s":trials[0]["first_text_s"], "warm":warm,"memory_mib":metrics["memory"],
                         "passes":recall >= 18 and leaks == 0 and warm["p95_s"] <= 5}
    eligible = [m for m in PINS if scores[m]["passes"]]
    # Prefer the smaller passing build unless the larger one's coding gain is material.
    choice = eligible[0] if eligible else None
    if len(eligible) == 2 and scores["qwen3:8b"]["coding_out_of_10"] >= scores["qwen3:4b"]["coding_out_of_10"] + 2:
        choice = "qwen3:8b"
    return {"models":scores, "candidate_for_owner_review":choice}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run","score"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    if args.action == "run":
        run(args.folder, args.port, args.reverse)
    else:
        summary = score(args.folder)
        write(args.folder / "comparison.json", summary)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
