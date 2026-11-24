"""Parent-side adapter for the isolated local Whisper worker."""
import json
import os
import struct
from pathlib import Path
from threading import Event

from ..runtime.offline import run_whisper_worker
from .capture import AudioClip


class Whisper:
    def __init__(self, root: Path) -> None:
        self.root = root

    def transcribe(self, clip: AudioClip, cancel: Event) -> str:
        formats = {"UInt8": 1, "Int16": 2, "Int32": 3, "Float": 4}
        protocol_format = formats.get(clip.sample_format.name)
        if cancel.is_set():
            return ""
        if protocol_format is None:
            raise ValueError("Unsupported audio format")
        payload = struct.pack("<IHH", clip.sample_rate, clip.channels, protocol_format) + clip.pcm
        result = run_whisper_worker(self.root, payload, cancel)
        if not result and not cancel.is_set():
            raise RuntimeError("Local Whisper worker did not return a result")
        if cancel.is_set():
            return ""
        if len(result) > 65536:
            raise RuntimeError("Local Whisper returned too much output")
        try:
            response = json.loads(result)
            transcript = response["text"]
            if not isinstance(transcript, str):
                raise ValueError("Invalid transcript")
            if os.environ.get("STYLUS_VOICE_DIAGNOSTICS") == "1":
                levels = response["levels"]
                peak = _level(levels["peak_dbfs"])
                rms = _level(levels["rms_dbfs"])
                print(f"[voice] Audio: {levels['seconds']:.2f} s, peak {peak}, RMS {rms}, "
                      f"near full scale {levels['near_full_scale_pct']:.2f}%", flush=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Invalid local Whisper response") from exc
        return transcript.strip()


def _level(dbfs: float | None) -> str:
    return "silent" if dbfs is None else f"{dbfs:.1f} dBFS"
