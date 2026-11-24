"""Produce a local synthetic course-vocabulary Whisper qualification record."""
import argparse
import json
import re
import subprocess
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from PySide6.QtMultimedia import QAudioFormat

from stylus_jarvis.runtime.offline import install_worker_policy, verify_application
from stylus_jarvis.settings import profile_path
from stylus_jarvis.voice.capture import AudioClip
from stylus_jarvis.voice.whisper import Whisper
from stylus_jarvis.voice.whisper_worker import MODEL_SHA256

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/voice-v1.json"
SYNTHESIS = r"""
param([string]$Root)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'en'
    } | Select-Object -First 1
    if (!$voice) { throw 'An installed English Windows speech voice is required.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($case in (Get-Content -LiteralPath (Join-Path $Root 'cases.json') -Raw | ConvertFrom-Json)) {
        $synth.SetOutputToWaveFile((Join-Path $Root ($case.id + '.wav')), $format)
        $synth.Speak($case.sentence)
        $synth.SetOutputToNull()
    }
    $voice.VoiceInfo.Name
} finally { $synth.Dispose() }
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args()
    fixture = args.fixture.read_bytes()
    cases = json.loads(fixture)
    with tempfile.TemporaryDirectory(prefix="stylus-whisper-") as directory:
        root = Path(directory)
        script = root / "speak.ps1"
        script.write_text(SYNTHESIS, encoding="ascii")
        (root / "cases.json").write_bytes(fixture)
        voice = subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive",
                                         "-File", str(script), "-Root", str(root)], timeout=60).decode().strip()
        verify_application()
        install_worker_policy()
        engine = Whisper(profile_path())
        results = []
        for case in cases:
            with wave.open(str(root / f"{case['id']}.wav"), "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                    raise ValueError("Unexpected synthetic fixture format")
                samples = wav.readframes(wav.getnframes())
            start = time.perf_counter()
            result = engine.transcribe(AudioClip(samples, 16000, 1, QAudioFormat.SampleFormat.Int16), Event())
            words = " ".join(re.findall(r"\w+", result.casefold()))
            matches = [term for term in case["terms"] if term in words]
            results.append({"id": case["id"], "reference": case["sentence"], "transcript": result,
                            "terms": case["terms"], "matched": matches,
                            "seconds": round(time.perf_counter() - start, 3)})
    report = {"fixture": args.fixture.stem, "recorded_at_utc": datetime.now(UTC).isoformat(),
              "model_sha256": MODEL_SHA256, "synthetic_voice": voice, "results": results,
              "matched_terms": sum(len(result["matched"]) for result in results),
              "total_terms": sum(len(result["terms"]) for result in results)}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
        out.write("\n")
    print(f"Whisper recognized {report['matched_terms']}/{report['total_terms']} fixture terms.")


if __name__ == "__main__":
    main()
