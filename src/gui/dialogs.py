"""The popups: frameless cards in the window's own skin, not the OS's frames.

`FramelessDialog` is the card: a header with the title and a ×, which is also
what moves it, then `body` for the content. The helpers below stand in for
Qt's stock QInputDialog, QMessageBox and QColorDialog, which would bring the
system titlebar back. The file pickers stay the OS's own, by choice: its
sidebar and recent places are worth more than the look.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLayout, QLineEdit, QVBoxLayout, QWidget)

from .frameless import Frameless
from .widgets import CloseButton

CLOSE_BTN = 26
# A word-wrapped label needs a pinned width, or Qt sizes it for a dozen lines.
WRAP_W = 400


class FramelessDialog(Frameless, QDialog):
    """`size`: a fixed (w, h). Without one the card is exactly as big as its
    content, and shrinks back when a line of it goes away."""

    def __init__(self, parent, title, size=None):
        super().__init__(parent)
        self._frameless()
        self.setObjectName("dialog")
        self.setWindowTitle(title)

        self.shell = QWidget(self)
        self.shell.setObjectName("dialogShell")
        self.shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)
        if size:
            self.setFixedSize(*size)
        else:
            outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(20, 12, 12, 2)
        name = QLabel(title)
        name.setObjectName("dialogTitle")
        close = CloseButton(CLOSE_BTN)
        close.setToolTip("Close")
        close.clicked.connect(self.reject)
        head.addWidget(name, 1)
        head.addWidget(close)

        lay = QVBoxLayout(self.shell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(20, 6, 20, 18)
        self.body.setSpacing(10)
        lay.addLayout(self.body, 1)

    def is_titlebar(self, pos):
        """The header stands in for the titlebar."""
        return self.header.geometry().contains(self.shell.mapFrom(self, pos))

    def add_buttons(self, ok_text="OK", cancel=True):
        """OK (the default, in the accent) and Cancel, in the platform's order."""
        box = QDialogButtonBox()
        ok = box.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setObjectName("primary")
        ok.setDefault(True)
        if cancel:
            box.addButton(QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.body.addWidget(box)
        return box, ok


def wrapped_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setFixedWidth(WRAP_W)
    return label


def ask_text(parent, title, prompt, text=""):
    """QInputDialog.getText in the skin: (text, accepted)."""
    dlg = FramelessDialog(parent, title)
    edit = QLineEdit(text)
    edit.selectAll()
    dlg.body.addWidget(wrapped_label(prompt))
    dlg.body.addWidget(edit)
    dlg.add_buttons()
    edit.setFocus()
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return edit.text(), ok


def inform(parent, text, title="ShortCutRadio"):
    """QMessageBox.information in the skin."""
    dlg = FramelessDialog(parent, title)
    dlg.body.addWidget(wrapped_label(text))
    dlg.add_buttons(cancel=False)
    dlg.exec()


class _EmbeddedColorDialog(QColorDialog):
    def keyPressEvent(self, event):
        # Esc and Enter belong to the popup around it: handled here, they
        # would close only the embedded picker and leave an empty card.
        event.ignore()


def pick_color(parent, color, title):
    """QColorDialog.getColor in the skin: Qt's own picker, embedded in the
    card as a plain widget. An invalid QColor when cancelled."""
    dlg = FramelessDialog(parent, title)
    picker = _EmbeddedColorDialog(QColor(color))
    picker.setOptions(QColorDialog.ColorDialogOption.DontUseNativeDialog
                      | QColorDialog.ColorDialogOption.NoButtons)
    picker.setWindowFlags(Qt.WindowType.Widget)
    dlg.body.addWidget(picker)
    dlg.add_buttons()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return picker.currentColor()
    return QColor()
