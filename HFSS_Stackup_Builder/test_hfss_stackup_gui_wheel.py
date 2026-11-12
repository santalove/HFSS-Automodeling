"""Offscreen checks: the mouse wheel scrolls the page instead of changing combo values."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox

from hfss_stackup_gui import MainWindow, NoWheelComboBox


def _wheel_event(combo: QComboBox) -> QWheelEvent:
    center = combo.rect().center()
    return QWheelEvent(
        QPointF(center),
        QPointF(combo.mapToGlobal(center)),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


class ComboWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def test_every_combo_uses_no_wheel_class(self) -> None:
        combos = self.window.findChildren(QComboBox)
        self.assertTrue(combos)
        for combo in combos:
            with self.subTest(combo=combo.objectName() or combo.currentText()):
                self.assertIsInstance(combo, NoWheelComboBox)

    def test_wheel_does_not_change_reference_layer(self) -> None:
        combo = self.window.stackup_upper_reference
        before = combo.currentText()
        event = _wheel_event(combo)
        QApplication.sendEvent(combo, event)
        self.assertEqual(before, combo.currentText())
        # 事件保持未接受状态，才能继续传播给外层 QScrollArea 滚动页面。
        self.assertFalse(event.isAccepted())


if __name__ == "__main__":
    unittest.main()
