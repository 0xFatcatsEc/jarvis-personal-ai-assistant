import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtMultimedia import QAudioFormat, QtAudio
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from stylus_jarvis.voice.capture import AudioClip, MicrophoneCapture
from stylus_jarvis.voice.controller import VoiceControls


class Device:
    def __init__(self, name):
        self.name = name

    def description(self):
        return self.name

    def id(self):
        return self.name.encode("ascii")


class MicrophoneFixture(QObject):
    failed = Signal()
    inputs_changed = Signal()

    def __init__(self):
        super().__init__()
        self.starts = []
        self.stops = []
        self.available = True

    def inputs(self):
        return [Device("Default fixture"), Device("Second fixture")] if self.available else []

    def start(self, device):
        self.starts.append(device.description())
        return True

    def stop(self, *, discard=False):
        self.stops.append(discard)
        return None if discard else AudioClip(b"\0\0", 16000, 1, QAudioFormat.SampleFormat.Int16)


@unittest.skipUnless(os.name == "nt", "Windows push-to-talk acceptance")
class VoiceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.window = QWidget()
        self.addCleanup(self.window.close)
        self.capture = MicrophoneFixture()
        self.voice = VoiceControls(self.window, self.capture)
        self.editor = QLineEdit()
        layout = QVBoxLayout(self.window)
        layout.addWidget(self.editor)
        layout.addWidget(self.voice)
        self.window.show()
        self.window.activateWindow()
        self.editor.setFocus()
        self.app.processEvents()
        self.assertTrue(self.window.isActiveWindow())

    def test_selected_microphone_and_key_hold_with_repeat(self):
        key = Qt.Key.Key_F9
        self.voice.hotkey.setCurrentIndex(self.voice.hotkey.findData(key.value))
        self.voice.microphone.setCurrentIndex(1)
        clips = []
        self.voice.capture_ready.connect(clips.append)
        QTest.keyClick(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.starts, [])
        QTest.keyPress(self.editor, key)
        for kind in (QEvent.Type.KeyRelease, QEvent.Type.KeyPress):
            self.app.sendEvent(self.editor, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier, "", True))
            self.assertIn("Recording…", self.voice.recording.text())
        self.assertEqual(self.capture.starts, ["Second fixture"])
        self.assertEqual(self.capture.stops, [])
        QTest.keyRelease(self.editor, key)
        self.assertEqual(self.capture.stops, [False])
        self.assertEqual(self.voice.recording.text(), "Recording stopped")
        self.assertEqual(len(clips), 1)

    def test_mouse_hold_and_window_deactivation(self):
        QTest.mousePress(self.voice.talk, Qt.MouseButton.LeftButton)
        self.assertIn("Recording…", self.voice.recording.text())
        QTest.mouseRelease(self.voice.talk, Qt.MouseButton.LeftButton)
        self.assertEqual(self.capture.stops, [False])
        QTest.keyPress(self.editor, Qt.Key.Key_F8)
        self.app.sendEvent(self.window, QEvent(QEvent.Type.WindowDeactivate))
        self.assertEqual(self.capture.stops, [False, True])
        self.assertEqual(self.voice.recording.text(), "Recording cancelled")
        QTest.keyRelease(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.stops, [False, True])

    def test_empty_device_list_preserves_typing(self):
        self.capture.available = False
        self.capture.inputs_changed.emit()
        self.assertFalse(self.voice.talk.isEnabled())
        QTest.keyClicks(self.editor, "ordinary text")
        QTest.keyClick(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.editor.text(), "ordinary text")
        self.assertEqual(self.capture.starts, [])

    def test_unplug_discards_partial_capture_and_requires_a_fresh_press(self):
        clips = []
        self.voice.capture_ready.connect(clips.append)
        QTest.keyPress(self.editor, Qt.Key.Key_F8)
        with patch.object(self.capture, "inputs", return_value=[Device("Second fixture")]):
            self.capture.inputs_changed.emit()
            self.assertEqual(self.capture.stops, [True])
            self.assertIn("Microphone disconnected. Continue by typing.", self.voice.recording.text())
            self.assertEqual(self.voice.microphone.currentText(), "Second fixture")
        self.capture.inputs_changed.emit()
        QTest.keyRelease(self.editor, Qt.Key.Key_F8)
        self.assertIn("Continue by typing", self.voice.recording.text())
        self.assertEqual(self.capture.starts, ["Default fixture"])
        self.assertEqual(clips, [])
        QTest.keyClick(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.starts, ["Default fixture", "Second fixture"])
        self.assertEqual(len(clips), 1)

    def test_release_before_topology_notification_discards_capture(self):
        QTest.mousePress(self.voice.talk, Qt.MouseButton.LeftButton)
        self.capture.available = False
        QTest.mouseRelease(self.voice.talk, Qt.MouseButton.LeftButton)
        self.assertEqual(self.capture.stops, [True])
        self.assertFalse(self.voice.talk.isEnabled())
        self.assertIn("Continue by typing", self.voice.recording.text())

    def test_unexpected_backend_stop_allows_typed_fallback(self):
        QTest.keyPress(self.editor, Qt.Key.Key_F8)
        self.capture.failed.emit()
        QTest.keyRelease(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.stops, [True])
        self.assertIn("Microphone stopped unexpectedly", self.voice.recording.text())
        QTest.keyClicks(self.editor, "fallback")
        self.assertEqual(self.editor.text(), "fallback")

    def test_long_device_name_leaves_recording_feedback_visible(self):
        with patch.object(self.capture, "inputs", return_value=[Device("Microphone " * 40)]):
            self.voice.refresh()
        self.window.resize(640, 360)
        self.app.processEvents()
        self.assertEqual(self.window.width(), 640)
        QTest.mousePress(self.voice.talk, Qt.MouseButton.LeftButton)
        self.assertIn("Recording…", self.voice.recording.text())
        self.assertTrue(self.voice.recording.isVisible())
        self.assertGreaterEqual(self.voice.recording.width(), self.voice.recording.sizeHint().width())
        QTest.mouseRelease(self.voice.talk, Qt.MouseButton.LeftButton)

    def test_capture_backend_drains_frames_and_discards_on_cancel(self):
        class Source(QObject):
            def __init__(self, device, fmt, parent):
                super().__init__(parent)
                self._format = fmt
                self.status = QtAudio.State.ActiveState
                self.buffer = QBuffer(self)
                self.buffer.setData(b"\x01\x00\x02\x00\x03")
                self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)

            def start(self):
                return self.buffer

            def stop(self):
                self.status = QtAudio.State.StoppedState

            def error(self):
                return QtAudio.Error.NoError

            def state(self):
                return self.status

            def format(self):
                return self._format

        microphone = Mock()
        microphone.isFormatSupported.return_value = True
        backend = MicrophoneCapture(self.window)
        failures = []
        backend.failed.connect(lambda: failures.append(True))
        with patch("stylus_jarvis.voice.capture.QAudioSource", side_effect=Source) as audio_source:
            self.assertTrue(backend.start(microphone))
            self.assertFalse(backend.start(microphone))
            self.assertEqual(backend.stop(), AudioClip(b"\x01\x00\x02\x00", 16000, 1,
                                                       QAudioFormat.SampleFormat.Int16))
            self.assertFalse(backend._pcm)
            self.assertTrue(backend.start(microphone))
            self.assertIsNone(backend.stop(discard=True))
            self.assertFalse(backend._pcm)
            self.assertTrue(backend.start(microphone))
            backend._source.stop()
            backend._monitor.timeout.emit()
            backend._monitor.timeout.emit()
            self.assertEqual(failures, [True])
            self.assertFalse(backend._monitor.isActive())
            self.assertIsNone(backend.stop())
            self.assertEqual(audio_source.call_count, 3)

    def test_playback_blocks_button_and_hotkey_capture(self):
        self.voice.set_playback(True)
        QTest.mouseClick(self.voice.talk, Qt.MouseButton.LeftButton)
        QTest.keyClick(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.starts, [])
        self.assertIn("Playback active", self.voice.recording.text())
        self.voice.set_playback(False)
        QTest.keyClick(self.editor, Qt.Key.Key_F8)
        self.assertEqual(self.capture.starts, ["Default fixture"])

    def test_windows_native_device_enumeration(self):
        for device in MicrophoneCapture.inputs():
            self.assertFalse(device.isNull())
            self.assertTrue(device.id())
            self.assertTrue(device.preferredFormat().isValid())
