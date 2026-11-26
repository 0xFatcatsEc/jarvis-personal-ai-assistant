"""Windows system-wide memory telemetry and latency statistics."""
import ctypes
import math
import os
import shutil
import statistics
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in
        ("physical", "available", "page", "free_page", "virtual", "free_virtual", "extended")
    ]


def _find_nvidia_smi() -> str | None:
    executable = shutil.which("nvidia-smi.exe")
    if executable:
        return executable
    for variable, directory in (("SystemRoot", "System32"),
                                ("ProgramW6432", "NVIDIA Corporation/NVSMI"),
                                ("ProgramFiles", "NVIDIA Corporation/NVSMI")):
        root = os.environ.get(variable)
        if root:
            candidate = Path(root) / directory / "nvidia-smi.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def _gpu_memory_mib() -> int | None:
    """A failed poll is a missing observation. The next poll tries again."""
    try:
        executable = _find_nvidia_smi()
        if executable is None:
            return None
        output = subprocess.check_output(
            [executable, "-i", "0", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        return int(output) if output.isdigit() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def memory_mib() -> tuple[int, int | None]:
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return (status.physical - status.available) // (1024 ** 2), _gpu_memory_mib()


@dataclass
class Sampler:
    read: Callable[[], tuple[int, int | None]] = memory_mib
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
        summary = {}
        for metric in ("ram_mib", "vram_mib"):
            baseline = self.samples[0][metric]
            peak = max((s[metric] for s in self.samples if s[metric] is not None), default=None)
            summary[metric] = {"baseline": baseline, "peak": peak,
                               "peak_above_baseline": peak - baseline if baseline is not None else None}
        return summary


def latency(values: list[float]) -> dict:
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Expected finite nonnegative latency observations")
    return {"n": len(values), "median_s": statistics.median(values),
            "p95_s": sorted(values)[math.ceil(.95 * len(values)) - 1]}
