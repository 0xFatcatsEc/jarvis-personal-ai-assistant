"""Windows system-wide memory telemetry and latency statistics."""
import ctypes
import math
import statistics
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in
        ("physical", "available", "page", "free_page", "virtual", "free_virtual", "extended")
    ]


def memory_mib() -> tuple[int, int]:
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    gpu = subprocess.check_output(
        ["nvidia-smi", "-i", "0", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return (status.physical - status.available) // (1024 ** 2), int(gpu.strip())


@dataclass
class Sampler:
    read: Callable[[], tuple[int, int]] = memory_mib
    samples: list[dict] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    error: Exception | None = None

    def sample(self) -> None:
        ram, vram = self.read()
        self.samples.append({"monotonic_s": time.monotonic(), "ram_mib": ram, "vram_mib": vram})

    def __enter__(self) -> "Sampler":
        self.sample()
        def poll() -> None:
            try:
                while not self._stop.wait(0.5):
                    self.sample()
            except Exception as exc:
                self.error = exc
        self._thread = threading.Thread(target=poll, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, typ, value, traceback) -> None:
        self._stop.set()
        self._thread.join()
        if typ is None:
            if self.error:
                raise RuntimeError("Memory sampler failed") from self.error
            self.sample()

    def summary(self) -> dict:
        return {metric: {"baseline": self.samples[0][metric],
                         "peak": max(s[metric] for s in self.samples),
                         "peak_above_baseline": max(s[metric] for s in self.samples) - self.samples[0][metric]}
                for metric in ("ram_mib", "vram_mib")}


def latency(values: list[float]) -> dict:
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Expected finite nonnegative latency observations")
    return {"n": len(values), "median_s": statistics.median(values),
            "p95_s": sorted(values)[math.ceil(.95 * len(values)) - 1]}
