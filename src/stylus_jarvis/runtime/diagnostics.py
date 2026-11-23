"""Bounded local diagnostics. The event interface accepts no arbitrary message body."""
import json
import logging
import queue
import threading
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID

from ..contracts.messages import Code, Failure
from ..settings import local_data_path


class Event(StrEnum):
    START = "startup"
    PROBE = "model_probe"
    FIRST = "first_visible_text"
    FINISH = "turn_finish"
    ERROR = "operation_error"
    STOP = "shutdown"


class Sink(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        raise OSError("diagnostic sink unavailable")


class Diagnostics:
    def __init__(self, directory: Path) -> None:
        self._items: queue.Queue[str] = queue.Queue(256)
        self._stop = threading.Event()
        self.recent: deque[str] = deque(maxlen=32)
        self.dropped = 0
        self.degraded = False
        self._worker = threading.Thread(target=self._write, args=(directory,), daemon=True)
        self._worker.start()

    def emit(self, event: Event, *, run: UUID | None = None, code: Code | None = None,
             elapsed_ms: float | None = None, digest: str | None = None) -> None:
        fields = {"at": datetime.now(UTC).isoformat(), "event": event.value,
                  "severity": "error" if code else "info", "run": run.hex if run else None,
                  "code": code.value if code else None, "elapsed_ms": elapsed_ms}
        if digest and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            fields["model_digest"] = digest
        line = json.dumps(fields, separators=(",", ":"))
        self.recent.append(line)
        try:
            self._items.put_nowait(line)
        except queue.Full:
            self.dropped += 1

    def _write(self, directory: Path) -> None:
        sink = None
        try:
            destination = local_data_path(directory / "runtime.jsonl")
            destination.parent.mkdir(parents=True, exist_ok=True)
            sink = Sink(destination, maxBytes=2*1024*1024, backupCount=2, encoding="utf-8")
            while not self._stop.is_set() or not self._items.empty():
                try:
                    line = self._items.get(timeout=0.1)
                except queue.Empty:
                    continue
                sink.emit(logging.LogRecord("stylus", logging.INFO, "", 0, line, (), None))
        except (Failure, OSError):
            self.degraded = True
        finally:
            if sink:
                sink.close()

    def close(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2)

