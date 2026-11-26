import asyncio
import os
import platform
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, Mock, patch

from stylus_jarvis.contracts.messages import Code, Failure, Scope
from stylus_jarvis.settings import profile_path
from stylus_jarvis.voice.piper import MAX_PENDING, Piper, ReplySpeech, SentenceStream, play_pcm
from stylus_jarvis.voice.piper_worker import MAX_PCM, cache_windows_platform


class SentenceStreamTests(unittest.TestCase):
    def test_streams_complete_sentences_and_excludes_links_and_code(self) -> None:
        fragments = (
            "Dr. Reyes has a plan. Next, see [the",
            " docs](https://example.com/a(b)).\n``",
            "`python\nprint('Do not speak this!')\n`",
            "``\nOpen `private_id`. Visit https://example.com/p?q=1. ",
            "Done! Unfinished",
        )
        stream = SentenceStream()
        expected = [
            ["Dr. Reyes has a plan."], ["Next, see."], [],
            ["Open.", "Visit."], ["Done!"],
        ]
        for fragment, sentences in zip(fragments, expected, strict=True):
            self.assertEqual(stream.feed(fragment), sentences)
        self.assertEqual(stream.feed("", final=True), [])

    def test_last_punctuation_flushes_at_completion(self) -> None:
        stream = SentenceStream()
        self.assertEqual(stream.feed("Version 1.2 is ready."), [])
        self.assertEqual(stream.feed("", final=True), ["Version 1.2 is ready."])


class ReplySpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_microphone_holds_playback_and_stop_clears_an_active_queue(self) -> None:
        recording = True
        started = asyncio.Event()
        playing = Mock()
        engine = Mock(spec=Piper)
        engine.synthesize.return_value = b"\x01\x00"

        async def play(_pcm, cancel):
            started.set()
            while not cancel.is_set():
                await asyncio.sleep(.01)

        queue = ReplySpeech(engine, AsyncMock(), Mock(), play)
        queue.microphone_active = lambda: recording
        queue.playback_changed = playing
        queue.begin(Scope("owner", "project", "conversation", 1, 1))
        self.assertTrue(queue.feed("First. Second. "))
        task = asyncio.create_task(queue.drain())
        try:
            await asyncio.sleep(.06)
            self.assertFalse(started.is_set())
            recording = False
            await asyncio.wait_for(started.wait(), 1)
        finally:
            queue.clear()
            await asyncio.wait_for(task, 1)
        self.assertEqual([call.args for call in playing.call_args_list], [(True,), (False,)])
        engine.synthesize.assert_called_once()
        self.assertFalse(queue.pending)

    async def test_playback_is_ordered_and_revalidates_queued_content(self) -> None:
        engine = Mock(spec=Piper)
        engine.synthesize.side_effect = lambda sentence, _: sentence.encode()
        checked = AsyncMock(side_effect=(None, None, Failure(Code.SCOPE)))
        played = AsyncMock()
        queue = ReplySpeech(engine, checked, Mock(), played)
        scope = Scope("owner", "project", "conversation", 1, 1)
        queue.begin(scope)
        self.assertTrue(queue.feed("First. Second. "))
        self.assertFalse(queue.feed("Third.", final=True))
        await queue.drain()
        self.assertEqual([call.args[0] for call in played.await_args_list], [b"First.", b"Second."])
        self.assertEqual([call.args[0] for call in checked.await_args_list], [scope] * 3)
        self.assertFalse(queue.pending)

    async def test_queue_is_bounded_and_clear_suppresses_late_audio(self) -> None:
        engine = Mock(spec=Piper)
        started = Event()

        def synthesize(_sentence: str, cancel: Event) -> bytes:
            started.set()
            if not cancel.wait(2):
                raise AssertionError("Playback cancellation was not signalled")
            return b"\x01\x00"

        engine.synthesize.side_effect = synthesize
        played = AsyncMock()
        status = Mock()
        queue = ReplySpeech(engine, AsyncMock(), status, played)
        queue.begin(Scope("owner", "project", "conversation", 1, 1))
        self.assertTrue(queue.feed("Sentence. " * (MAX_PENDING + 2)))
        self.assertEqual(len(queue.pending), MAX_PENDING)
        self.assertIn("queue full", status.call_args.args[0])
        task = asyncio.create_task(queue.drain())
        try:
            async with asyncio.timeout(2):
                while not started.is_set():
                    await asyncio.sleep(.01)
        finally:
            queue.clear()
            await task
        played.assert_not_awaited()


@unittest.skipUnless(os.name == "nt", "Windows guarded worker")
class PiperWorkerTests(unittest.TestCase):
    def test_windows_version_fallback_needs_no_shell(self) -> None:
        with (patch.object(platform, "_uname_cache", None),
              patch.object(platform, "_wmi_query", side_effect=OSError("WMI unavailable"), create=True),
              patch("subprocess.check_output", side_effect=AssertionError("Unexpected shell call"))):
            cache_windows_platform()
            self.assertEqual(platform.system(), "Windows")
            self.assertTrue(platform.version())

    def test_missing_voice_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                Piper(root).synthesize("A local sentence.", Event())
            self.assertEqual(list(root.iterdir()), [])

    @unittest.skipUnless(os.environ.get("STYLUS_PIPER_NATIVE") == "1", "requires provisioned MSI voice")
    def test_pinned_voice_synthesizes_non_silent_pcm_offline(self) -> None:
        from stylus_jarvis.runtime.offline import install_worker_policy, verify_application

        verify_application()
        install_worker_policy()
        piper = Piper(profile_path())
        for sentence in ("The first sentence is ready.", "The second sentence follows."):
            pcm = piper.synthesize(sentence, Event())
            self.assertGreater(len(pcm), 22050)
            self.assertLessEqual(len(pcm), MAX_PCM)
            self.assertTrue(any(pcm))

    @unittest.skipUnless(os.environ.get("STYLUS_PIPER_NATIVE") == "1", "requires MSI audio output")
    def test_qt_plays_piper_audio_from_memory(self) -> None:
        from PySide6.QtWidgets import QApplication
        from qasync import QEventLoop
        from stylus_jarvis.runtime.offline import install_worker_policy, verify_application

        verify_application()
        install_worker_policy()
        app = QApplication.instance() or QApplication([])
        piper = Piper(profile_path())
        pcm = piper.synthesize("A short playback check.", Event())

        async def repeat_playback():
            for _ in range(3):
                await asyncio.wait_for(play_pcm(pcm, Event(), volume=0.0), timeout=10)

        with QEventLoop(app) as loop:
            loop.run_until_complete(repeat_playback())
