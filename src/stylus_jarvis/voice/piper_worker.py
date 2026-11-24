"""Synthesize one bounded sentence from pinned, local Piper assets."""
import hashlib
import platform
import sys
from pathlib import Path
from unittest.mock import patch

from ..runtime.offline import install_worker_policy
from ..settings import local_data_path

SAMPLE_RATE = 22050
MAX_TEXT = 2048
MAX_PCM = SAMPLE_RATE * 2 * 30
MODEL = "en_US-ljspeech-medium.onnx"
VOICE_ASSETS = {
    MODEL: "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    MODEL + ".json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
    "MODEL_CARD": "fbee1529c89d36b3fe76d7e9f3f832dce17f44900a52d76a9bda735654766b4d",
}


def cache_windows_platform() -> None:
    if sys.platform == "win32":
        # ONNX calls platform.system(). CPython can fall back from the native
        # version query to a shell command, which the worker policy denies.
        version = ".".join(map(str, sys.getwindowsversion().platform_version))
        with patch.object(platform, "_syscmd_ver", return_value=("Microsoft Windows", "", version)):
            platform.uname()


def synthesize(root: Path, text: str) -> bytes:
    paths = {}
    for name, expected in VOICE_ASSETS.items():
        path = local_data_path(root / "assets/m0-v1/piper" / name)
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise ValueError("Piper asset digest mismatch")
        paths[name] = path

    cache_windows_platform()
    from piper import PiperVoice

    voice = PiperVoice.load(paths[MODEL], config_path=paths[MODEL + ".json"], use_cuda=False)
    pcm = bytearray()
    for chunk in voice.synthesize(text):
        audio = chunk.audio_int16_bytes
        if ((chunk.sample_rate, chunk.sample_width, chunk.sample_channels) != (SAMPLE_RATE, 2, 1)
                or len(audio) % 2 or len(pcm) + len(audio) > MAX_PCM):
            raise ValueError("Invalid Piper audio")
        pcm.extend(audio)
    return bytes(pcm)


if __name__ == "__main__":
    install_worker_policy()
    payload = sys.stdin.buffer.read(MAX_TEXT + 1)
    if not 0 < len(payload) <= MAX_TEXT:
        sys.exit(1)
    sys.stdout.buffer.write(synthesize(Path(sys.argv[1]), payload.decode("utf-8")))
