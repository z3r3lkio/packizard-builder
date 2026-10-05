import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from gui.widgets import AnimatedButton, SectionCard


class SectionCardLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_line_edit_gets_row_stretch_instead_of_browse_button(self):
        card = SectionCard("Paths", label_width=140)
        edit = QLineEdit()
        button = AnimatedButton("Browse…", "secondary", icon="folder")
        card.add_row("Source", edit, button)
        self.assertEqual(card._rows.columnStretch(1), 1)
        self.assertEqual(card._rows.columnStretch(2), 0)
        self.assertGreater(button.sizeHint().width(), button.fontMetrics().horizontalAdvance(button.text()))

    def test_single_control_still_expands(self):
        card = SectionCard("Metadata", label_width=140)
        edit = QLineEdit()
        card.add_row("Title", edit)
        self.assertEqual(card._rows.columnStretch(1), 1)


if __name__ == "__main__":
    unittest.main()
