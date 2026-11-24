"""Bounded, ordered speech playback for the current desktop reply."""
import asyncio
import re
from math import gcd
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from ..contracts.messages import Failure, Scope
from ..runtime.offline import run_piper_worker
from .piper_worker import MAX_PCM, MAX_TEXT, SAMPLE_RATE

MAX_REPLY = 65536
MAX_PENDING = 24
# Open Markdown constructs hold back their tail until a later fragment closes them.
MARKUP = re.compile(r"`+|(?m:^ {0,3}~{3,})|!?\[|<?(?:https?://|www\.)", re.IGNORECASE)
SENTENCE_END = re.compile(r"""[.!?]+["'”’)]*(?=\s)""")
ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|e\.g|i\.e)\.$")


def _balanced_end(text: str, start: int, opening: str, closing: str) -> int | None:
    depth = 1
    for offset in range(start, len(text)):
        if text[offset] == closing:
            depth -= 1
            if not depth:
                return offset + 1
        elif text[offset] == opening:
            depth += 1
    return None


def _prose(text: str, final: bool) -> str:
    """Project Markdown to speech without editing the visible reply."""
    pieces: list[str] = []
    offset = 0
    while marker := MARKUP.search(text, offset):
        pieces.append(text[offset:marker.start()])
        token = marker[0]
        start = marker.end()
        if token.startswith("`") or token.lstrip().startswith("~"):
            fence = token.lstrip()
            prefix = text[text.rfind("\n", 0, marker.start()) + 1:marker.start()]
            if len(fence) >= 3 and len(prefix) <= 3 and not prefix.strip():
                closer = re.compile(r"(?m)^ {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*(?=\r?$)")
                match = closer.search(text, start)
                if match is None or (match.end() == len(text) and not final):
                    break
                offset = match.end()
            else:
                closer = re.compile(r"(?<!`)" + re.escape(fence) + r"(?!`)")
                match = closer.search(text, start)
                if match is None or (match.end() == len(text) and not final):
                    break
                offset = match.end()
        elif token.endswith("["):
            stop = _balanced_end(text, start, "[", "]")
            if stop is None or (stop == len(text) and not final):
                break
            offset = stop
            if text.startswith("(", offset):
                stop = _balanced_end(text, offset + 1, "(", ")")
                if stop is None:
                    break
                offset = stop
            elif text.startswith("[", offset):
                stop = _balanced_end(text, offset + 1, "[", "]")
                if stop is None:
                    break
                offset = stop
        else:
            end = re.search(r"[\s<>]", text[start:])
            if end is None and not final:
                break
            offset = start + end.start() if end else len(text)
            url = text[start:offset]
            pieces.append(url[len(url.rstrip(".!?")):])
            if token.startswith("<") and text.startswith(">", offset):
                offset += 1
        pieces.append(" ")
    else:
        pieces.append(text[offset:])
    return "".join(pieces)


class SentenceStream:
    def __init__(self) -> None:
        self.text = ""
        self.consumed = 0
        self.full = False

    def feed(self, fragment: str, *, final: bool = False) -> list[str]:
        if self.full:
            return []
        remaining = MAX_REPLY - len(self.text)
        self.text += fragment[:remaining]
        self.full = len(fragment) > remaining
        prose = _prose(self.text, final and not self.full)
        if final and not self.full:
            prose += " "
        sentences = []
        for end in SENTENCE_END.finditer(prose, self.consumed):
            candidate = prose[self.consumed:end.end()]
            if ABBREVIATION.search(candidate):
                continue
            self.consumed = end.end()
            sentence = " ".join(candidate.translate(str.maketrans("", "", "*_#")).split())
            sentence = re.sub(r"\s+([,.!?;:])", r"\1", sentence)
            if any(character.isalnum() for character in sentence) and len(sentence.encode("utf-8")) <= MAX_TEXT:
                sentences.append(sentence)
        return sentences


class Piper:
    def __init__(self, root: Path) -> None:
        self.root = root

    def synthesize(self, sentence: str, cancel: Event) -> bytes:
        pcm = run_piper_worker(self.root, sentence.encode("utf-8"), cancel)
        if not cancel.is_set() and (not pcm or len(pcm) > MAX_PCM or len(pcm) % 2):
            raise RuntimeError("Invalid local speech output")
        return pcm


def _convert_pcm(pcm: bytes, rate: int, channels: int, encoding: QAudioFormat.SampleFormat) -> bytes:
    import numpy as np
    from scipy.signal import resample_poly

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    if rate != SAMPLE_RATE:
        divisor = gcd(rate, SAMPLE_RATE)
        samples = resample_poly(samples, rate // divisor, SAMPLE_RATE // divisor)
    samples = np.repeat(np.clip(samples, -1, 1).astype(np.float64), channels)
    formats = {
        QAudioFormat.SampleFormat.UInt8: ("u1", 128, 128, 255),
        QAudioFormat.SampleFormat.Int16: ("<i2", 32768, 0, 32767),
        QAudioFormat.SampleFormat.Int32: ("<i4", 2147483648, 0, 2147483647),
        QAudioFormat.SampleFormat.Float: ("<f4", 1, 0, 1),
    }
    dtype, scale, offset, upper = formats[encoding]
    return np.minimum(samples * scale + offset, upper).astype(dtype).tobytes()


async def play_pcm(pcm: bytes, cancel: Event, *, volume: float = 1.0) -> None:
    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        raise RuntimeError("No speech playback device")
    fmt = QAudioFormat()
    fmt.setSampleRate(SAMPLE_RATE)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    if not device.isFormatSupported(fmt):
        fmt = device.preferredFormat()
        if not fmt.isValid():
            raise RuntimeError("Unsupported speech playback format")
        pcm = await asyncio.to_thread(_convert_pcm, pcm, fmt.sampleRate(), fmt.channelCount(), fmt.sampleFormat())
    if cancel.is_set():
        return
    data = QBuffer()
    data.setData(QByteArray(pcm))
    if not data.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Cannot open speech playback buffer")
    sink = QAudioSink(device, fmt)
    sink.setVolume(volume)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 35
    try:
        sink.start(data)
        while not cancel.is_set():
            current = sink.state()
            if current == QtAudio.State.IdleState and data.atEnd():
                return
            if (current == QtAudio.State.StoppedState or sink.error() != QtAudio.Error.NoError
                    or loop.time() >= deadline):
                raise RuntimeError("Speech playback failed")
            await asyncio.sleep(.03)
    finally:
        if cancel.is_set():
            sink.reset()
        else:
            sink.stop()
        data.close()


class ReplySpeech:
    def __init__(self, engine: Piper, validate: Callable[[Scope], Awaitable[None]],
                 status: Callable[[str], None],
                 play: Callable[[bytes, Event], Awaitable[None]] = play_pcm) -> None:
        self.engine = engine
        self.validate = validate
        self.status = status
        self.play = play
        self.scope: Scope | None = None
        self.stream = SentenceStream()
        self.pending: deque[str] = deque()
        self.cancel = Event()
        self.draining = False
        self.microphone_active: Callable[[], bool] = lambda: False
        self.playback_changed: Callable[[bool], None] = lambda _: None

    @property
    def busy(self) -> bool:
        return self.draining and not self.cancel.is_set()

    def clear(self) -> None:
        self.cancel.set()
        self.scope = None
        self.stream = SentenceStream()
        self.pending.clear()
        self.status("")

    def begin(self, scope: Scope) -> None:
        self.clear()
        self.scope = scope
        self.cancel = Event()

    def feed(self, text: str, *, final: bool = False) -> bool:
        if self.scope is None:
            return False
        sentences = self.stream.feed(text, final=final)
        available = MAX_PENDING - len(self.pending)
        self.pending.extend(sentences[:available])
        if len(sentences) > available:
            self.status("Speech queue full. Read the remaining reply on screen.")
            self.stream.full = True
        if self.pending and not self.draining:
            self.draining = True
            return True
        return False

    async def drain(self) -> None:
        try:
            while self.pending and (scope := self.scope) is not None:
                sentence = self.pending.popleft()
                cancel = self.cancel
                try:
                    pcm = await asyncio.to_thread(self.engine.synthesize, sentence, cancel)
                    while not cancel.is_set():
                        if self.microphone_active():
                            await asyncio.sleep(.03)
                            continue
                        await self.validate(scope)
                        if cancel.is_set() or self.microphone_active():
                            continue
                        self.playback_changed(True)
                        try:
                            await self.play(pcm, cancel)
                        finally:
                            self.playback_changed(False)
                        break
                except Failure:
                    if not cancel.is_set():
                        self.clear()
                except (OSError, ValueError, RuntimeError):
                    if not cancel.is_set():
                        self.clear()
                        self.status("Local speech unavailable. Read the reply on screen.")
        finally:
            self.draining = False
