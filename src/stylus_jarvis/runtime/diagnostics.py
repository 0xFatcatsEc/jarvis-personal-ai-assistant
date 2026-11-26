"""Bounded local diagnostics. The event interface accepts no arbitrary message body."""
import json
import logging
import math
import queue
import re
import threading
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID

from ..contracts.messages import Code, Failure, State
from ..settings import local_data_path


class Event(StrEnum):
    START = "startup"
    PROBE = "model_probe"
    FIRST = "first_visible_text"
    FINISH = "turn_finish"
    ERROR = "operation_error"
    STOP = "shutdown"
    WRITER = "sqlite_writer"


QUEUE_LIMIT = 256
RECENT_LIMIT = 32
FILE_BYTES = 2 * 1024 * 1024
BACKUPS = 2
COMPONENT = {Event.START: "runtime", Event.STOP: "runtime", Event.ERROR: "runtime",
             Event.PROBE: "inference", Event.FIRST: "inference", Event.FINISH: "inference",
             Event.WRITER: "storage"}


class Sink(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        raise OSError("diagnostic sink unavailable")


class Diagnostics:
    def __init__(self, directory: Path) -> None:
        self._items: queue.Queue[str] = queue.Queue(QUEUE_LIMIT)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.recent: deque[str] = deque(maxlen=RECENT_LIMIT)
        self._build = "unknown"
        self.dropped = 0
        self.degraded = False
        self._worker = threading.Thread(target=self._write, args=(directory,), daemon=True)
        self._worker.start()

    def identify(self, build: str) -> None:
        if re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,8}){2}", build):
            with self._lock:
                self._build = build

    def snapshot(self) -> tuple[str, tuple[str, ...]]:
        with self._lock:
            health = (f"Diagnostics {'degraded' if self.degraded else 'local'} · "
                      f"queued {self._items.qsize()}/{QUEUE_LIMIT} · dropped {self.dropped}")
            return health, tuple(self.recent)

    def writer(self, wait_ms: float, elapsed_ms: float) -> None:
        self.emit(Event.WRITER, wait_ms=wait_ms, elapsed_ms=elapsed_ms)

    def emit(self, event: Event, *, run: UUID | None = None, code: Code | None = None,
             elapsed_ms: float | None = None, digest: str | None = None,
             outcome: State | None = None, wait_ms: float | None = None) -> None:
        if not isinstance(event, Event):
            raise TypeError("invalid diagnostic event")
        fields = {"at": datetime.now(UTC).isoformat(), "event": event.value,
                  "component": COMPONENT[event],
                  "severity": "warning" if code == Code.TOKEN_LIMIT else "error" if code else "info",
                  "run": run.hex if isinstance(run, UUID) else None,
                  "code": code.value if isinstance(code, Code) else None}
        for key, value in (("elapsed_ms", elapsed_ms), ("wait_ms", wait_ms)):
            if type(value) in (int, float) and 0 <= value <= 1e18 and math.isfinite(value):
                fields[key] = round(value, 3)
        if isinstance(outcome, State):
            fields["outcome"] = outcome.value
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            fields["model_digest"] = digest
        with self._lock:
            fields["build"] = self._build
            line = json.dumps(fields, separators=(",", ":"))
            self.recent.append(line)
            if not self.degraded and not self._stop.is_set():
                try:
                    self._items.put_nowait(line)
                    return
                except queue.Full:
                    pass
            self.dropped += 1

    def _write(self, directory: Path) -> None:
        sink = None
        writing = False
        try:
            destination = local_data_path(directory / "runtime.jsonl")
            destination.parent.mkdir(parents=True, exist_ok=True)
            sink = Sink(destination, maxBytes=FILE_BYTES, backupCount=BACKUPS, encoding="utf-8")
            while not self._stop.is_set() or not self._items.empty():
                try:
                    line = self._items.get(timeout=0.1)
                except queue.Empty:
                    continue
                writing = True
                sink.emit(logging.LogRecord("stylus", logging.INFO, "", 0, line, (), None))
                writing = False
        except (Failure, OSError):
            with self._lock:
                self.degraded = True
                self.dropped += int(writing)
                while not self._items.empty():
                    self._items.get_nowait()
                    self.dropped += 1
        finally:
            if sink:
                try:
                    sink.close()
                except OSError:
                    with self._lock:
                        self.degraded = True

    def close(self) -> None:
        with self._lock:
            self._stop.set()
        self._worker.join(timeout=2)

