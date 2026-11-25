"""Foreground push-to-talk controls and capture ownership."""
import os

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .capture import MAX_SECONDS, MicrophoneCapture


class VoiceControls(QWidget):
    capture_ready = Signal(object)
    capture_interrupted = Signal()
    capture_state_changed = Signal()
    KEYS = (Qt.Key.Key_F8, Qt.Key.Key_F9, Qt.Key.Key_F12)

    def __init__(self, parent: QWidget, capture: MicrophoneCapture | None = None) -> None:
        super().__init__(parent)
        self._capture = capture if capture is not None else MicrophoneCapture(self)
        self._trigger: str | None = None
        self.playing = False
        self._device_id: bytes | None = None
        self._fallback_message: str | None = None
        self._trace_enabled = os.environ.get("STYLUS_VOICE_DIAGNOSTICS") == "1"
        self.microphone = QComboBox()
        self.microphone.setAccessibleName("Microphone")
        self.microphone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.microphone.setMinimumContentsLength(16)
        self.hotkey = QComboBox()
        self.hotkey.setAccessibleName("Push-to-talk key")
        for key in self.KEYS:
            self.hotkey.addItem(key.name.removeprefix("Key_"), key.value)
        self.talk = QPushButton("Hold to record")
        self.recording = QLabel()
        self.recording.setAccessibleName("Microphone status")
        self.recording.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        devices = QHBoxLayout()
        microphone_label = QLabel("&Microphone")
        microphone_label.setBuddy(self.microphone)
        devices.addWidget(microphone_label)
        devices.addWidget(self.microphone, 1)
        key_label = QLabel("Push-to-&talk")
        key_label.setBuddy(self.hotkey)
        devices.addWidget(key_label)
        devices.addWidget(self.hotkey)
        layout.addLayout(devices)
        feedback = QHBoxLayout()
        feedback.addWidget(self.talk)
        feedback.addWidget(self.recording, 1)
        layout.addLayout(feedback)
        self.talk.pressed.connect(lambda: self._begin("button"))
        self.talk.released.connect(lambda: self._end("button"))
        self.hotkey.currentTextChanged.connect(self._show_hold_key)
        self._show_hold_key(self.hotkey.currentText())
        self._capture.failed.connect(self._failed)
        self._capture.inputs_changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._end(self._trigger, "Recording limit reached"))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.refresh()

    def _show_hold_key(self, key: str) -> None:
        self.talk.setText(f"Hold to record ({key})")
        self.talk.setAccessibleDescription(f"Hold {key} while JARVIS is focused to record, then release.")

    def refresh(self) -> None:
        if self._trigger is not None:
            if not self._device_present():
                self._interrupted("Microphone disconnected")
            return
        previous = self.microphone.currentData()
        self.microphone.clear()
        self._devices = self._capture.inputs()
        for index, device in enumerate(self._devices):
            self.microphone.addItem(device.description(), bytes(device.id()))
            if previous is not None and bytes(device.id()) == bytes(previous):
                self.microphone.setCurrentIndex(index)
        self.talk.setEnabled(bool(self._devices))
        self._status(self._fallback_message or ("Microphone ready" if self._devices else "No microphone available"))

    def _device_present(self) -> bool:
        return any(bytes(device.id()) == self._device_id for device in self._capture.inputs())

    def _trace(self, message: str) -> None:
        if self._trace_enabled:
            console_message = message.removeprefix("● ").replace("…", "...")
            print(f"[voice] {console_message}", flush=True)

    def _status(self, message: str) -> None:
        self.recording.setText(message)
        self._trace(message)

    def _begin(self, trigger: str) -> None:
        self._trace(f"{trigger} pressed")
        if self.playing:
            self._status("Playback active. Stop speech before recording.")
            return
        selected = self.microphone.currentIndex()
        if self._trigger is not None or selected < 0 or not self.isEnabled() or not self.isVisible():
            return
        if not self._capture.start(self._devices[selected]):
            self._status("Could not start microphone. Continue by typing.")
            return
        self._fallback_message = None
        self._trigger = trigger
        self._device_id = bytes(self._devices[selected].id())
        self.microphone.setEnabled(False)
        self.hotkey.setEnabled(False)
        self._status("● Recording…")
        self._timer.start(MAX_SECONDS * 1000)
        self.capture_state_changed.emit()

    def _end(self, trigger: str | None, status: str = "Recording stopped", *, discard: bool = False) -> None:
        if self._trigger is None or trigger != self._trigger:
            return
        if not discard and not self._device_present():
            self._interrupted("Microphone disconnected")
            return
        self._trigger = None
        self._device_id = None
        self._timer.stop()
        clip = self._capture.stop(discard=discard)
        self.microphone.setEnabled(True)
        self.hotkey.setEnabled(True)
        self.refresh()
        self._status(status)
        if clip is not None:
            self.capture_ready.emit(clip)
        self.capture_state_changed.emit()

    def _failed(self) -> None:
        if self._trigger is not None:
            reason = "Microphone stopped unexpectedly" if self._device_present() else "Microphone disconnected"
            self._interrupted(reason)

    def _interrupted(self, reason: str) -> None:
        if self._trigger is None:
            return
        self._fallback_message = f"{reason}. Continue by typing."
        self._end(self._trigger, self._fallback_message, discard=True)
        self.capture_interrupted.emit()

    def cancel(self) -> None:
        self._end(self._trigger, "Recording cancelled", discard=True)

    @property
    def capturing(self) -> bool:
        return self._trigger is not None

    def set_playback(self, playing: bool) -> None:
        self.playing = playing
        if not playing:
            self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        window = self.window()
        if kind in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
            if watched is QApplication.instance() or watched is window:
                self.cancel()
        if (kind == QEvent.Type.EnabledChange and watched is self and not self.isEnabled()):
            self.cancel()
        if (kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and isinstance(event, QKeyEvent)
                and isinstance(watched, QWidget) and watched.window() is window and window.isActiveWindow()
                and event.key() == self.hotkey.currentData() and self.isEnabled() and self.isVisible()):
            if event.isAutoRepeat():
                return True
            if kind == QEvent.Type.KeyRelease:
                self._end("key")
            elif event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self._begin("key")
            else:
                return False
            return True
        return False
