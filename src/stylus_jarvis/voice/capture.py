"""Bounded microphone capture over Qt Multimedia."""
from dataclasses import dataclass

from PySide6.QtCore import QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices, QtAudio

MAX_SECONDS = 30
MAX_PCM_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AudioClip:
    pcm: bytes
    sample_rate: int
    channels: int
    sample_format: QAudioFormat.SampleFormat


class MicrophoneCapture(QObject):
    failed = Signal()
    inputs_changed = Signal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._media = QMediaDevices(self)
        self._media.audioInputsChanged.connect(self.inputs_changed)
        self._source: QAudioSource | None = None
        self._stream: QIODevice | None = None
        self._pcm = bytearray()
        self._limit = 0
        self._monitor = QTimer(self)
        self._monitor.setInterval(100)
        self._monitor.timeout.connect(self._check_state)

    @staticmethod
    def inputs() -> list[QAudioDevice]:
        return sorted(QMediaDevices.audioInputs(), key=lambda device: not device.isDefault())

    def start(self, device: QAudioDevice) -> bool:
        if self._source is not None:
            return False
        requested = QAudioFormat()
        requested.setSampleRate(16000)
        requested.setChannelCount(1)
        requested.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        fmt = requested if device.isFormatSupported(requested) else device.preferredFormat()
        if not fmt.isValid():
            return False
        limit = fmt.bytesPerFrame() * fmt.sampleRate() * MAX_SECONDS
        if not 0 < limit <= MAX_PCM_BYTES:
            return False
        source = QAudioSource(device, fmt, self)
        stream = source.start()
        if stream is None or not self._running(source):
            source.stop()
            source.deleteLater()
            return False
        self._source, self._stream = source, stream
        self._limit = limit
        stream.readyRead.connect(self._drain)
        # Some PySide6 builds cannot marshal the native QAudio::State signal
        # argument. Read state directly on the owning Qt thread instead.
        self._monitor.start()
        return True

    def _check_state(self) -> None:
        source = self._source
        if source is not None and not self._running(source):
            self._fail()

    def _fail(self) -> None:
        self.stop(discard=True)
        self.failed.emit()

    @staticmethod
    def _running(source: QAudioSource) -> bool:
        return source.error() == QtAudio.Error.NoError and source.state() != QtAudio.State.StoppedState

    def _drain(self) -> None:
        if self._source is not None and not self._read():
            self._fail()

    def _read(self) -> bool:
        if self._stream is None:
            return False
        try:
            self._pcm.extend(self._stream.read(self._limit - len(self._pcm)))
        except RuntimeError:
            # Qt can dispose of its internal device as the endpoint is removed.
            return False
        return True

    def stop(self, *, discard: bool = False) -> AudioClip | None:
        source = self._source
        if source is None:
            return None
        self._monitor.stop()
        discard = discard or not self._running(source)
        if not discard:
            discard = not self._read()
        self._stream = None
        self._source = None
        fmt = source.format()
        source.stop()
        source.deleteLater()
        frame = fmt.bytesPerFrame()
        size = len(self._pcm) // frame * frame
        clip = (AudioClip(bytes(memoryview(self._pcm)[:size]), fmt.sampleRate(), fmt.channelCount(), fmt.sampleFormat())
                if size and not discard else None)
        self._pcm.clear()
        return clip
