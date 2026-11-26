import os
import tempfile
import unittest
from pathlib import Path
from struct import pack
from threading import Event
from unittest.mock import patch

from PySide6.QtMultimedia import QAudioFormat

from stylus_jarvis.voice.capture import AudioClip
from stylus_jarvis.voice.whisper import Whisper
from stylus_jarvis.voice.whisper_worker import normalize, signal_levels


class WhisperTests(unittest.TestCase):
    def test_levels_distinguish_silence_quiet_and_full_scale(self) -> None:
        header = pack("<IHH", 16000, 1, 2)
        for amplitude, expected, near_full in ((0, None, 0.0), (328, -40.0, 0.0), (-32768, 0.0, 100.0)):
            with self.subTest(amplitude=amplitude):
                levels = signal_levels(normalize(header + pack("<h", amplitude) * 16000))
                self.assertEqual(levels["seconds"], 1.0)
                self.assertEqual(levels["peak_dbfs"], expected)
                self.assertEqual(levels["rms_dbfs"], expected)
                self.assertEqual(levels["near_full_scale_pct"], near_full)

    def test_opt_in_trace_contains_levels_without_transcript(self) -> None:
        clip = AudioClip(b"\x01\x00", 16000, 1, QAudioFormat.SampleFormat.Int16)
        result = b'{"text":"private text","levels":{"seconds":2,"peak_dbfs":-15,"rms_dbfs":-25,"near_full_scale_pct":0}}'
        with (patch.dict(os.environ, {"STYLUS_VOICE_DIAGNOSTICS": "1"}),
              patch("stylus_jarvis.voice.whisper.run_whisper_worker", return_value=result),
              patch("builtins.print") as trace):
            self.assertEqual(Whisper(Path("fixture")).transcribe(clip, Event()), "private text")
        trace.assert_called_once_with("[voice] Audio: 2.00 s, peak -15.0 dBFS, RMS -25.0 dBFS, near full scale 0.00%",
                                     flush=True)

    def test_resamples_stereo_and_rejects_nonfinite_or_partial_frames(self) -> None:
        stereo = pack("<IHH", 48000, 2, 2) + pack("<hh", 8192, 0) * 4800
        output = normalize(stereo)
        self.assertEqual(output.shape, (1600,))
        self.assertEqual(output.dtype.name, "float32")
        self.assertAlmostEqual(float(output[800]), .125, places=3)
        with self.assertRaises(ValueError):
            normalize(stereo[:-1])
        with self.assertRaises(ValueError):
            normalize(pack("<IHHf", 16000, 1, 4, float("nan")))

    def test_cancellation_and_failed_worker_have_distinct_results(self) -> None:
        clip = AudioClip(b"\x01\x00", 16000, 1, QAudioFormat.SampleFormat.Int16)
        cancel = Event()
        with patch("stylus_jarvis.voice.whisper.run_whisper_worker", return_value=b"") as run:
            worker = Whisper(Path("fixture"))
            cancel.set()
            self.assertEqual(worker.transcribe(clip, cancel), "")
            run.assert_not_called()
            cancel.clear()
            with self.assertRaises(RuntimeError):
                worker.transcribe(clip, cancel)

    @unittest.skipUnless(os.name == "nt", "Windows pipe worker")
    def test_worker_round_trips_silence_and_refuses_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = Whisper(root)
            clip = AudioClip(b"\0\0" * 1600, 16000, 1, QAudioFormat.SampleFormat.Int16)
            self.assertEqual(worker.transcribe(clip, Event()), "")
            self.assertEqual(list(root.iterdir()), [])
            voiced = AudioClip(b"\x71\x10" * 1600, 16000, 1, QAudioFormat.SampleFormat.Int16)
            with self.assertRaises(RuntimeError):
                worker.transcribe(voiced, Event())
            self.assertEqual(list(root.iterdir()), [])
