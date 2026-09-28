"""A top-level window with no titlebar, that is its own chrome.

The window is a fixed size -- no resizing, no maximising: the author's
choice, and one less thing a window manager can get wrong. Presses on
whatever the subclass calls its titlebar (`is_titlebar`) move it, asking
the window manager first (`startSystemMove`) and moving the window by hand
when it won't.

Only presses the children did not take arrive here, so a list keeps its
drag-to-reorder and every button keeps its click.

The behaviour is a mixin (`Frameless`) so the popups (dialogs.py) wear the
same chrome as the window.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget


def keep_on_screen(window, centre=False):
    """Move `window` wholly onto a screen's free area (not under a taskbar).

    `centre`: onto the middle of the screen under the mouse -- the first
    showing. Otherwise it stays where it was left, pulled back in if that
    spot is gone (a monitor unplugged, a resolution changed). A window
    bigger than the screen keeps its top left, and with it the part that
    moves it, in view.
    """
    screen = (QGuiApplication.screenAt(QCursor.pos()) if centre else
              QGuiApplication.screenAt(window.frameGeometry().center()))
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    geo = window.frameGeometry()
    if centre:
        geo.moveCenter(area.center())
    x = max(area.left(), min(geo.left(), area.right() + 1 - geo.width()))
    y = max(area.top(), min(geo.top(), area.bottom() + 1 - geo.height()))
    window.move(x, y)


class Frameless:
    """Mixed in before a QWidget or a QDialog; call `_frameless()` once."""

    def _frameless(self):
        self._drag_from = None
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def is_titlebar(self, pos):
        """Whether `pos` (in window coordinates) stands in for the titlebar."""
        return False

    def mousePressEvent(self, event):
        """Presses the children did not want: the titlebar's drag the window."""
        if (event.button() != Qt.MouseButton.LeftButton
                or not self.is_titlebar(event.position().toPoint())):
            return super().mousePressEvent(event)
        handle = self.windowHandle()
        if handle is None or not handle.startSystemMove():
            # No help from the window manager: carry it ourselves.
            self._drag_from = event.globalPosition().toPoint() - self.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        super().mouseReleaseEvent(event)


class FramelessWindow(Frameless, QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)
        self._frameless()
