"""One-shot offline Whisper subprocess. Input and output are pipes only."""
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

from ..runtime.offline import install_worker_policy
from ..settings import local_data_path

HEADER = struct.Struct("<IHH")
MAX_INPUT = 32 * 1024 * 1024
MODEL_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"


def normalize(payload: bytes):
    import numpy as np
    from scipy.signal import resample_poly

    rate, channels, encoding = HEADER.unpack_from(payload)
    if not 8000 <= rate <= 192000 or not 1 <= channels <= 16 or encoding not in (1, 2, 3, 4):
        raise ValueError("Invalid audio format")
    dtype, scale, offset = {1: ("u1", 128, 128), 2: ("<i2", 32768, 0),
                            3: ("<i4", 2**31, 0), 4: ("<f4", 1, 0)}[encoding]
    values = np.frombuffer(payload, dtype=dtype, offset=HEADER.size).reshape(-1, channels)
    if not 0 < len(values) <= rate * 30:
        raise ValueError("Invalid recording duration")
    mono = (values.mean(axis=1, dtype=np.float32) - offset) / scale
    if not np.isfinite(mono).all():
        raise ValueError("Non-finite audio")
    if rate != 16000:
        divisor = math.gcd(rate, 16000)
        mono = resample_poly(mono, 16000 // divisor, rate // divisor)
    return np.ascontiguousarray(np.clip(mono, -1, 1), dtype=np.float32)


def signal_levels(samples) -> dict[str, float | None]:
    """Measure the mono signal actually passed to the decoder."""
    import numpy as np

    magnitude = np.abs(samples)
    peak = float(magnitude.max())
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return {
        "seconds": round(len(samples) / 16000, 2),
        "peak_dbfs": round(20 * math.log10(peak), 1) if peak else None,
        "rms_dbfs": round(20 * math.log10(rms), 1) if rms else None,
        "near_full_scale_pct": round(100 * float(np.mean(magnitude >= 0.999)), 2),
    }


def transcribe(root: Path, samples) -> str:
    if not samples.any():
        return ""
    # Open the exact pinned local file. Use native initialization directly so
    # the binding's model-name resolver cannot download a missing model.
    path = local_data_path(root / "assets/m0-v1/whisper/ggml-base.bin")
    with path.open("rb") as model:
        if hashlib.file_digest(model, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("Whisper model digest mismatch")
    import _pywhispercpp as native

    context_options = native.whisper_context_default_params()
    context_options.use_gpu = False
    context = native.whisper_init_from_file_with_params(str(path), context_options)
    if context is None:
        raise RuntimeError("Could not initialize Whisper")
    try:
        options = native.whisper_full_default_params(native.whisper_sampling_strategy.WHISPER_SAMPLING_GREEDY)
        options.language = "en"
        if os.environ.get("STYLUS_WHISPER_NAME_HINT") == "1":
            options.initial_prompt = "Jarvis."
        options.n_threads = 4
        options.no_context = True
        options.print_progress = options.print_realtime = options.print_timestamps = False
        if native.whisper_full(context, options, samples, len(samples)) != 0:
            raise RuntimeError("Could not transcribe recording")
        return " ".join(native.whisper_full_get_segment_text(context, i).decode("utf-8", errors="replace").strip()
                        for i in range(native.whisper_full_n_segments(context))).strip()
    finally:
        native.whisper_free(context)


if __name__ == "__main__":
    install_worker_policy()
    data = sys.stdin.buffer.read(MAX_INPUT + HEADER.size + 1)
    if not HEADER.size < len(data) <= MAX_INPUT + HEADER.size:
        sys.exit(1)
    pcm = normalize(data)
    result = {"text": transcribe(Path(sys.argv[1]), pcm), "levels": signal_levels(pcm)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
