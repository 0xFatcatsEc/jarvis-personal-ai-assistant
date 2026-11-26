"""Qt presentation for the dashboard's event-driven Core."""
import os
from enum import Enum
from math import cos, tau

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QHideEvent, QPaintEvent, QPainter, QPen, QShowEvent
from PySide6.QtWidgets import QApplication, QBoxLayout, QLabel, QStyle, QWidget

BLUE = "#8BAFFF"
CYAN = "#62D9F5"
YELLOW = "#F7CC79"
RED = "#FF7C86"
ARCS = ((30, 62), (151, 58), (259, 65))
STEADY = (0.88, 0.88, 0.88)
FRAME_MS = 42
TRANSITION_MS = 240
IDLE_CYCLE_MS = 3600
GENERATION_CYCLE_MS = 1800


class CoreState(Enum):
    STARTING = ("Starting offline…", "…", YELLOW)
    CHECKING = ("Checking local model…", "…", YELLOW)
    READY = ("Ready", "✓", BLUE)
    GENERATING = ("Generating locally…", "•••", CYAN)
    STOPPING = ("Stopping…", "■", YELLOW)
    RECORDING = ("Recording…", "●", YELLOW)
    TRANSCRIBING = ("Transcribing locally…", "≡", YELLOW)
    SPEAKING = ("Speaking…", "♪", YELLOW)
    SAVE = ("Reply needs saving", "!", YELLOW)
    UNAVAILABLE = ("Local model unavailable", "!", RED)


class CoreDisplay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.state = CoreState.STARTING
        self.diameter = 0
        self._host: QWidget | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._phase_ms = 0
        self._transition_ms = TRANSITION_MS
        self._target = QColor(self.state.value[2])
        self._color = self._target
        self._from_color = self._target
        self._levels = STEADY
        self._from_levels = STEADY
        self.title = QLabel("JARVIS CORE")
        self.title.setObjectName("coreTitle")
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setText(self.state.value[0])
        self.contents = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        for label in (self.title, self.label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.contents.addWidget(label)
        # Keep the style-hints wrapper alive for its accessibility child.
        self._style_hints = QGuiApplication.styleHints()
        self._accessibility = getattr(self._style_hints, "accessibility", lambda: None)()
        changed = getattr(self._accessibility, "motionPreferenceChanged", None)
        if changed is not None:
            changed.connect(self._refresh_motion)
        self.set_diameter(24)

    def set_state(self, state: CoreState) -> None:
        if self.state == state:
            return
        self._from_color = self._color
        self._from_levels = self._levels
        self.state = state
        self._target = QColor(state.value[2])
        self._transition_ms = 0
        self.label.setText(state.value[0])
        self._sync_motion()
        self.update()

    def set_diameter(self, diameter: int) -> None:
        if diameter == self.diameter:
            return
        self.diameter = diameter
        circular = diameter >= 144
        self.contents.setDirection(QBoxLayout.Direction.TopToBottom if circular
                                   else QBoxLayout.Direction.LeftToRight)
        self.contents.setContentsMargins(20 if circular else 34, 12 if circular else 0,
                                         20 if circular else 0, 12 if circular else 0)
        self.contents.setSpacing(4 if circular else 12)
        self.contents.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(diameter if circular else 300, diameter if circular else 34)
        self._sync_motion()
        self.update()

    def _motion_allowed(self) -> bool:
        if os.getenv("STYLUS_REDUCED_MOTION") == "1":
            return False
        if self.style().styleHint(QStyle.StyleHint.SH_Widget_Animation_Duration, None, self) <= 0:
            return False
        preference = getattr(self._accessibility, "motionPreference", None)
        if preference is not None:
            return preference() != Qt.MotionPreference.ReducedMotion
        return QGuiApplication.platformName() != "windows" or QApplication.isEffectEnabled(Qt.UIEffect.UI_General)

    def _sync_motion(self) -> None:
        if (self.diameter < 144 or not self.isVisible() or self.window().isMinimized()
                or not self._motion_allowed()):
            self._timer.stop()
            self._transition_ms = TRANSITION_MS
            self._color = self._target
            self._levels = STEADY
            return
        if self.state in (CoreState.READY, CoreState.GENERATING) or self._transition_ms < TRANSITION_MS:
            if not self._timer.isActive():
                self._clock.start()
                self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        elapsed = self._clock.restart()
        self._phase_ms = (self._phase_ms + elapsed) % IDLE_CYCLE_MS
        self._transition_ms = min(TRANSITION_MS, self._transition_ms + elapsed)
        fraction = self._transition_ms / TRANSITION_MS
        mix = fraction * fraction * (3 - 2 * fraction)
        if self.state == CoreState.READY:
            pulse = 0.08 * (1 - cos(tau * self._phase_ms / IDLE_CYCLE_MS))
            levels = (0.76 + pulse,) * len(ARCS)
        elif self.state == CoreState.GENERATING:
            phase = tau * self._phase_ms / GENERATION_CYCLE_MS
            levels = tuple(0.83 + 0.15 * cos(phase - index * tau / len(ARCS))
                           for index in range(len(ARCS)))
        else:
            levels = STEADY
        self._levels = tuple(start + (end - start) * mix for start, end in zip(self._from_levels, levels))
        if fraction < 1:
            self._color = QColor.fromRgbF(*(start + (end - start) * mix
                                           for start, end in zip(self._from_color.getRgbF(), self._target.getRgbF())))
        else:
            self._color = self._target
            if self.state not in (CoreState.READY, CoreState.GENERATING):
                self._timer.stop()
        self.update()

    def _refresh_motion(self) -> None:
        self._sync_motion()
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        host = self.window()
        if host is not self._host:
            if self._host is not None:
                self._host.removeEventFilter(self)
            self._host = host
            host.installEventFilter(self)
        self._refresh_motion()

    def hideEvent(self, event: QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() in (
            QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate, QEvent.Type.StyleChange,
            QEvent.Type.ThemeChange,
        ):
            self._refresh_motion()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _, glyph, color = self.state.value
        if self.diameter < 144:
            painter.setPen(QColor(color))
            painter.drawText(QRectF(0, 0, 28, self.height()), Qt.AlignmentFlag.AlignCenter, glyph)
            return
        bounds = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor("#304357"), 1))
        painter.drawEllipse(bounds)
        painter.drawEllipse(bounds.adjusted(13, 13, -13, -13))
        arc = bounds.adjusted(6, 6, -6, -6)
        for glow, width in ((True, 7), (False, 3)):
            for (start, length), level in zip(ARCS, self._levels):
                ink = QColor(self._color)
                ink.setAlphaF(level * (0.13 if glow else 1))
                painter.setPen(QPen(ink, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(arc, start * 16, length * 16)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(0, self.height() * .76, self.width(), 20), Qt.AlignmentFlag.AlignCenter, glyph)


DASHBOARD_STYLE = """
QMainWindow, QWidget#dashboard, QWidget#railContent, QStackedWidget, QScrollArea {
    background: #0B1118; color: #E4EDF6;
}
QWidget { color: #E4EDF6; font-family: "Segoe UI"; font-size: 13px; }
QFrame[dashCard="true"], QMenu, QDialog, QMenuBar { background: #111C27; }
QFrame[dashCard="true"] { border: 1px solid #304357; border-radius: 7px; }
QLabel { background: transparent; }
QLabel[heading="true"] { color: #A9BDD0; font-weight: 600; font-size: 15px; }
QLabel#coreTitle { color: #BCEBF7; font-weight: 700; }
QLabel#offlineMode { color: #62D9F5; }
QPushButton, QToolButton, QComboBox, QLineEdit, QPlainTextEdit {
    background: #111C27; color: #E4EDF6; border: 1px solid #435B72; border-radius: 5px; padding: 5px 8px;
}
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border: 2px solid #62D9F5;
}
QPushButton:hover, QToolButton:hover, QMenu::item:selected, QMenuBar::item:selected {
    background: #233B51;
}
QPushButton:checked, QToolButton:checked { color: #62D9F5; background: #193246; }
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled, QCheckBox:disabled {
    color: #8BA0B5; background: #121B24;
}
QPushButton#sendMessage:enabled { background: #62D9F5; color: #0B1118; font-weight: 600; }
QPushButton#sendMessage:focus { border-color: #E4EDF6; }
QPlainTextEdit, QListView { selection-background-color: #17607A; selection-color: white; }
QComboBox QAbstractItemView { background: #111C27; color: #E4EDF6; selection-background-color: #17607A; }
QScrollBar:vertical { background: #0B1118; width: 12px; }
QScrollBar::handle:vertical { background: #435B72; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QStatusBar { background: #0B1118; color: #A9BDD0; }
"""
