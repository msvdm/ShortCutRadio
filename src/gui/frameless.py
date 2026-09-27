"""A top-level window with no titlebar, that is its own chrome.

The window is a transparent carrier: its layout keeps a RESIZE_MARGIN around
the card it holds, and presses in that margin resize the window. Presses on
whatever the subclass calls its titlebar (`is_titlebar`) move it, and a
double-click there maximises. Both ask the window manager first
(`startSystemResize` / `startSystemMove`) and fall back to moving the window
by hand.

Only presses the children did not take arrive here, so a list keeps its
drag-to-reorder and every button keeps its click.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

RESIZE_MARGIN = 6           # the transparent grip around the card

CURSORS = {
    (Qt.Edge.LeftEdge).value: Qt.CursorShape.SizeHorCursor,
    (Qt.Edge.RightEdge).value: Qt.CursorShape.SizeHorCursor,
    (Qt.Edge.TopEdge).value: Qt.CursorShape.SizeVerCursor,
    (Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeVerCursor,
    (Qt.Edge.LeftEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeFDiagCursor,
    (Qt.Edge.RightEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeFDiagCursor,
    (Qt.Edge.RightEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeBDiagCursor,
    (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeBDiagCursor,
}


class FramelessWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._drag_from = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def is_titlebar(self, pos):
        """Whether `pos` (in window coordinates) stands in for the titlebar."""
        return False

    def _edges(self, pos):
        """Which window edges `pos` sits on, inside the resize margin."""
        edges = Qt.Edge(0)
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event):
        """Presses the children did not want: the edges resize, the top drags."""
        pos = event.position().toPoint()
        if event.button() != Qt.MouseButton.LeftButton or self.isMaximized():
            return super().mousePressEvent(event)
        handle = self.windowHandle()
        edges = self._edges(pos)
        if edges and handle is not None:
            handle.startSystemResize(edges)
        elif not edges and not self.is_titlebar(pos):
            return super().mousePressEvent(event)
        elif handle is None or not handle.startSystemMove():
            # No help from the window manager: carry it ourselves.
            self._drag_from = event.globalPosition().toPoint() - self.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            return
        shape = CURSORS.get(self._edges(event.position().toPoint()).value,
                            Qt.CursorShape.ArrowCursor)
        self.setCursor(shape)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.isMaximized():
            self.showNormal()
        elif self.is_titlebar(event.position().toPoint()):
            self.showMaximized()

    def changeEvent(self, event):
        # Maximised there is nothing to grip, and the margin would show as a
        # transparent frame around the card.
        if event.type() == event.Type.WindowStateChange and self.layout():
            m = 0 if self.isMaximized() else RESIZE_MARGIN
            self.layout().setContentsMargins(m, m, m, m)
        super().changeEvent(event)
