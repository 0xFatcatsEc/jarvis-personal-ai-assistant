"""Measure the Windows Whisper → Qwen → Piper turn alongside scoped indexing."""
import argparse
import asyncio
import faulthandler
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from benchmarks.measurement import Sampler, latency

OUTPUT_TOKENS = 128


async def measure_turns(port: int, workspace: Path, count: int) -> dict:
    from PySide6.QtMultimedia import QAudioFormat
    from stylus_jarvis.bootstrap import user_identity
    from stylus_jarvis.contracts.messages import State
    from stylus_jarvis.inference.ollama import Ollama
    from stylus_jarvis.inference.router import Router
    from stylus_jarvis.runtime.coordinator import Coordinator
    from stylus_jarvis.runtime.diagnostics import Diagnostics
    from stylus_jarvis.runtime.scheduler import Scheduler
    from stylus_jarvis.settings import Settings, load, profile_path
    from stylus_jarvis.storage.database import Database
    from stylus_jarvis.storage.repositories import Repositories
    from stylus_jarvis.voice.capture import AudioClip
    from stylus_jarvis.voice.piper import Piper, ReplySpeech, play_pcm
    from stylus_jarvis.voice.piper_worker import SAMPLE_RATE
    from stylus_jarvis.voice.whisper import Whisper

    root = profile_path()
    _, manifest = load(root)
    settings = Settings(port=port, output=OUTPUT_TOKENS)
    model = Ollama(settings, manifest)
    log = Diagnostics(workspace / "logs")
    database = Database(workspace / "data/jarvis.sqlite3")
    store = Repositories(database)
    piper = Piper(root)
    whisper = Whisper(root)
    samples = await asyncio.to_thread(piper.synthesize, "Reply with the word hello and a period.", Event())
    clip = AudioClip(samples, SAMPLE_RATE, 1, QAudioFormat.SampleFormat.Int16)
    owner = await asyncio.to_thread(user_identity)
    rows = []
    await database.open()
    try:
        project = await store.register(owner, workspace)
        for number in range(count + 1):
            print(f"Starting mixed voice trial {number + 1}/{count + 1}", file=sys.stderr, flush=True)
            faulthandler.dump_traceback_later(120, repeat=True)
            scope = await store.select(owner, project, number)
            speech_status: list[str] = []
            played = 0

            async def play(pcm: bytes, cancellation: Event) -> None:
                nonlocal played
                await play_pcm(pcm, cancellation, volume=0.0)
                if not cancellation.is_set():
                    played += 1

            speech = ReplySpeech(piper, store.validate, speech_status.append, play)
            speech.begin(scope)
            playback: asyncio.Task[None] | None = None
            first_text: float | None = None
            sent = 0.0
            started = time.perf_counter()

            def deliver(event):
                nonlocal playback, first_text
                if event.kind == "fragment":
                    if first_text is None:
                        first_text = time.perf_counter() - sent
                    if speech.feed(event.text):
                        playback = asyncio.create_task(speech.drain())

            coordinator = Coordinator(store, Router(model, settings, manifest), Scheduler(), log, deliver)
            coordinator.select(scope)
            index_started = index_ended = 0.0

            async def index_fixture() -> int:
                nonlocal index_started, index_ended
                index_started = time.perf_counter()
                for index in range(8):
                    file = workspace / f"fixture-{number}-{index}.txt"
                    file.write_text(f"Fixture {number} {index}. Course indexing evidence.\n" * 8000,
                                    encoding="utf-8")
                    revision = await store.approve_source(scope, file)
                    await store.extract_locators(scope, revision.source_id, revision.revision_id)
                    await store.publish_revision(scope, revision.source_id, revision.revision_id)
                index_ended = time.perf_counter()
                return 8

            index_work = asyncio.create_task(index_fixture())
            try:
                transcript = await asyncio.to_thread(whisper.transcribe, clip, Event())
                if "hello" not in transcript.casefold():
                    raise RuntimeError("The synthetic voice fixture did not transcribe the expected term")
                sent = time.perf_counter()
                # Qwen's explicit short-answer mode keeps the timed fixture stable.
                result = await coordinator.submit(scope, uuid4(), transcript + "\n/no_think")
                print(f"Written reply settled as {result.state}", file=sys.stderr, flush=True)
                if speech.feed("", final=True):
                    playback = asyncio.create_task(speech.drain())
                if result.state not in (State.COMPLETED, State.TOKEN_LIMIT) or first_text is None or playback is None:
                    raise RuntimeError(f"The local model did not complete a speakable turn "
                                       f"(state={result.state}, text={first_text is not None}, "
                                       f"speech={playback is not None})")
                await playback
                voice_ended = time.perf_counter()
                indexed = await index_work
                if (speech.cancel.is_set() or not played
                        or not index_started < voice_ended or not started < index_ended):
                    raise RuntimeError(f"Mixed workload failed in trial {number} "
                                       f"(speech={speech_status[-1:]}, overlap="
                                       f"{index_started < voice_ended and started < index_ended})")
                rows.append({"warm": number > 0, "first_text_s": round(first_text, 4),
                             "voice_turn_s": round(voice_ended - started, 4),
                             "indexing_s": round(index_ended - index_started, 4), "published": indexed,
                             "state": result.state.value, "played_clips": played,
                             "speech_queue_limited": any("queue full" in status for status in speech_status)})
                print(f"Completed trial {number + 1}/{count + 1} in {voice_ended - started:.2f} s",
                      file=sys.stderr, flush=True)
            finally:
                speech.clear()
                if playback is not None:
                    await asyncio.gather(playback, return_exceptions=True)
                if not index_work.done():
                    index_work.cancel()
                await asyncio.gather(index_work, return_exceptions=True)
    finally:
        await model.close()
        await database.close()
        log.close()
    completed = [row["voice_turn_s"] for row in rows
                 if row["warm"] and row["state"] == State.COMPLETED and not row["speech_queue_limited"]]
    return {"model": manifest.model, "model_digest": manifest.digest, "output_tokens": OUTPUT_TOKENS, "trials": rows,
            "warm_first_text": latency([row["first_text_s"] for row in rows if row["warm"]]),
            "warm_voice_turn": latency([row["voice_turn_s"] for row in rows if row["warm"]]),
            "completed_warm_voice_turn": latency(completed) if completed else None}


def desktop(port: int, workspace: Path, count: int) -> None:
    from PySide6.QtWidgets import QApplication
    from qasync import QEventLoop
    from stylus_jarvis.runtime.offline import install_worker_policy, verify_application

    verify_application()
    install_worker_policy()
    app = QApplication([])

    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        with QEventLoop(app) as loop:
            asyncio.set_event_loop(loop)
            report = loop.run_until_complete(measure_turns(port, workspace, count))
    finally:
        faulthandler.cancel_dump_traceback_later()
    print(json.dumps(report))


def run(code: Path, count: int) -> dict:
    system = Path(os.environ["SystemRoot"]) / "System32"
    policy = Path(__file__).resolve().parents[2] / "src/stylus_jarvis/runtime/offline-policy.ps1"
    flags = subprocess.CREATE_NO_WINDOW
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="stylus-voice-", ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        profile = root / "code"
        (profile / "User").mkdir(parents=True)
        (profile / "User/settings.json").write_text(
            '{"telemetry.telemetryLevel":"off","update.mode":"none","extensions.autoCheckUpdates":false}',
            encoding="utf-8")
        processes = []
        try:
            for cmd in (
                [str(code), "--user-data-dir", str(profile), "--disable-extensions", "--new-window", str(workspace)],
                [str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "RemoteSigned", "-File", str(policy), "-Mode", "Serve",
                 "-PythonImage", sys.executable, "-Port", str(port)],
            ):
                processes.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                  creationflags=flags))
            deadline = time.monotonic() + 60
            while True:
                if any(process.poll() is not None for process in processes) or time.monotonic() >= deadline:
                    raise RuntimeError("Isolated VS Code or guarded Ollama failed to start")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.4):
                        break
                except OSError:
                    time.sleep(.25)
            with Sampler() as sampler:
                result = subprocess.run([sys.executable, "-B", "-P", "-s", __file__, "--desktop", str(port),
                                         str(workspace), str(count)], check=True, stdout=subprocess.PIPE,
                                        timeout=600, creationflags=flags)
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("VS Code or Ollama exited during measurement")
            report = json.loads(result.stdout)
            report.update({"platform": platform.platform(), "recorded_at_utc": datetime.now(UTC).isoformat(),
                           "vscode_open": True, "audio": "synthetic input, muted native playback",
                           "prompt_suffix": "/no_think",
                           "memory": sampler.summary(), "memory_samples": len(sampler.samples)})
            return report
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    subprocess.run([str(system / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=15, creationflags=flags)
                process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warm-turns", type=int, default=5, choices=range(3, 21))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh output path")
    report = run(args.code.resolve(strict=True), args.warm_turns)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--desktop"]:
        desktop(int(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
    else:
        main()
