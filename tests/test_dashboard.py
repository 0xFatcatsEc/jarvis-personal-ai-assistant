"""Exercise the native Qt shell without a model or an audio device."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stylus_jarvis.ui.dashboard import BLUE, CYAN, RED, YELLOW, CoreDisplay, CoreState, TRANSITION_MS
from stylus_jarvis.ui.main_window import MainWindow


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.centralWidget().setEnabled(True)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.hide)

    def test_keyboard_navigation_preserves_the_conversation_draft(self) -> None:
        window = self.window
        window.draft.setPlainText("keep this draft")
        window.draft.setFocus()
        QTest.keyClick(window.draft, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(window.approve_source.isVisible())
        self.assertFalse(window.voice.isVisible())
        self.assertTrue(window._dock["Evidence"].isChecked())
        QTest.keyClick(window.approve_source, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(window.capture_fact.isVisible())
        QTest.keyClick(window.capture_fact, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(window.draft.hasFocus())
        self.assertEqual(window.draft.toPlainText(), "keep this draft")
        QTest.keyClick(window.draft, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(window.search.hasFocus())
        self.assertTrue(all(button.width() > 50 for button in window._dock.values()))

    def test_operations_and_coding_move_without_recreating_controls(self) -> None:
        window = self.window
        self.assertEqual(window.core_display.diameter, 256)
        self.assertTrue(window.probe.isVisible())
        self.assertTrue(window.open_editor.isVisible())
        window.resize(1160, 700)
        self.app.processEvents()
        self.assertFalse(window.probe.isVisible())
        self.assertFalse(window.open_editor.isVisible())
        window._dock["Coding"].click()
        self.assertTrue(window.open_editor.isVisible())
        self.assertTrue(window.history.isVisible())
        window.resize(800, 630)
        self.app.processEvents()
        self.assertTrue(window.open_editor.isVisible())
        self.assertFalse(window.history.isVisible())
        window._dock["System"].click()
        self.assertTrue(window.probe.isVisible())
        self.assertTrue(window.diagnostic_view.isVisible())
        self.assertEqual(window.core_display.diameter, 24)

    def test_core_shrinks_for_voice_review_and_stop_remains_reachable(self) -> None:
        window = self.window
        window.core_display.set_state(CoreState.GENERATING)
        window.stop.setEnabled(True)
        window.show_task_actions()
        self.assertEqual(window.core_display.label.text(), CoreState.GENERATING.value[0])
        window.show_voice_review("Review transcript", "hello")
        self.assertLess(window.core_display.diameter, 256)
        self.assertTrue(window.stop.isVisible())
        window.resize(800, 630)
        self.app.processEvents()
        self.assertTrue(window.voice_transcript.isVisible())
        window.voice.hotkey.setCurrentIndex(1)
        self.assertIn("F9", window.voice.talk.text())
        window.voice_transcript.setFocus()
        QTest.keyClick(window.voice_transcript, Qt.Key.Key_Tab)
        self.assertTrue(window.use_transcript.hasFocus())
        window._dock["Memory"].click()
        self.assertTrue(window.stop.isVisible())
        window._dock["Conversation"].click()
        self.assertEqual(window.voice_transcript.toPlainText(), "hello")

    def test_system_details_switch_from_operations_and_keyboard(self) -> None:
        window = self.window
        window.recovery_toggle.click()
        self.assertTrue(window.recovery_view.isVisible())
        self.assertTrue(window.recovery_toggle.isChecked())
        self.assertFalse(window.diagnostic_toggle.isChecked())
        QTest.keyClick(window.system_tabs.tabBar(), Qt.Key.Key_Left)
        self.assertTrue(window.diagnostic_view.isVisible())
        self.assertTrue(window.diagnostic_toggle.isChecked())
        self.assertFalse(window.recovery_toggle.isChecked())
        window._dock["Conversation"].click()
        self.assertFalse(window.diagnostic_toggle.isChecked())

    def test_core_animates_ready_and_generation_and_settles_at_error(self) -> None:
        core = self.window.core_display
        with patch.object(CoreDisplay, "_motion_allowed", return_value=True):
            core.set_state(CoreState.READY)
            QTest.qWait(TRANSITION_MS + 80)
            self.assertEqual(core._color, QColor(BLUE))
            self.assertTrue(core._timer.isActive())
            levels = core._levels
            QTest.qWait(140)
            self.assertNotEqual(core._levels, levels)
            self.assertEqual(len(set(core._levels)), 1)

            core.set_state(CoreState.GENERATING)
            self.assertEqual(core.label.text(), CoreState.GENERATING.value[0])
            self.assertEqual(core._color, QColor(BLUE))
            QTest.qWait(TRANSITION_MS + 80)
            self.assertEqual(core._color, QColor(CYAN))
            self.assertGreater(len(set(core._levels)), 1)

            core.set_state(CoreState.CHECKING)
            QTest.qWait(TRANSITION_MS + 80)
            self.assertEqual(core._color, QColor(YELLOW))
            self.assertFalse(core._timer.isActive())
            core.set_state(CoreState.UNAVAILABLE)
            QTest.qWait(TRANSITION_MS + 80)
            self.assertEqual(core._color, QColor(RED))
            self.assertFalse(core._timer.isActive())

    def test_core_suspends_motion_when_hidden_minimized_or_compact(self) -> None:
        window = self.window
        core = window.core_display
        with patch.object(CoreDisplay, "_motion_allowed", return_value=True):
            core.set_state(CoreState.GENERATING)
            self.assertTrue(core._timer.isActive())
            window.hide()
            self.assertFalse(core._timer.isActive())
            phase = core._phase_ms
            QTest.qWait(100)
            self.assertEqual(core._phase_ms, phase)
            window.show()
            self.assertTrue(core._timer.isActive())
            window.showMinimized()
            self.app.processEvents()
            self.assertFalse(core._timer.isActive())
            window.showNormal()
            self.app.processEvents()
            self.assertTrue(core._timer.isActive())
            window._dock["Memory"].click()
            self.assertFalse(core._timer.isActive())
            self.assertEqual(core.label.text(), CoreState.GENERATING.value[0])

    def test_core_uses_static_state_when_reduced_motion_is_requested(self) -> None:
        core = self.window.core_display
        with patch.object(CoreDisplay, "_motion_allowed", return_value=True):
            core.set_state(CoreState.READY)
            self.assertTrue(core._timer.isActive())
        with patch.dict(os.environ, {"STYLUS_REDUCED_MOTION": "1"}):
            self.app.sendEvent(self.window, QEvent(QEvent.Type.WindowActivate))
            self.assertFalse(core._timer.isActive())
            core.set_state(CoreState.GENERATING)
            self.assertEqual(core._color, QColor(CYAN))
            self.assertEqual(core.label.text(), CoreState.GENERATING.value[0])
            self.assertFalse(core._timer.isActive())
