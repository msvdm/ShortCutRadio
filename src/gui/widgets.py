"""The pieces a stylesheet cannot draw: switches, transport, meters, labels.

Everything here reads `theme.tokens()` at paint time, so a theme change only
needs a repaint, not a rebuild. The art box's picture work is in art.py.
"""

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFontComboBox,
                               QSizePolicy, QWidget)

from ..core import levels
from . import theme
from .art import FittedArt, draw_art

METER_MS = 70           # ~14 frames a second: alive, but nearly free

MONO = None


def repolish(w):
    """Re-apply the stylesheet after a dynamic property changed."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def mono_font(px, spacing=0.0, bold=False):
    """The system fixed-width face at a pixel size; used for numbers and caps."""
    global MONO
    if MONO is None:
        MONO = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    f = QFont(MONO)
    f.setPixelSize(px)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing * 100)
    return f


def draw_level_bars(painter, right, baseline, values, color, width, gap, low, high):
    """The level meter, right-aligned, standing on `baseline`.

    `values` are 0..1 from core.levels; `low`..`high` is their range in pixels.
    """
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    x = right - level_bars_width(len(values), width, gap)
    for v in values:
        h = low + (high - low) * max(0.0, min(1.0, v))
        painter.drawRect(QRectF(x, baseline - h, width, h))
        x += width + gap
    painter.restore()


def level_bars_width(count, width, gap):
    return count * width + (count - 1) * gap


class Meter(QObject):
    """The clock behind the level bars -- see core/levels.py for the maths.

    It only runs while something is actually playing and the bars are on
    screen, so an idle or hidden ShortCutRadio costs nothing.
    """

    tick = Signal()

    def __init__(self, count, parent=None, interval=METER_MS):
        super().__init__(parent)
        self.values = levels.new_levels(count)
        self._targets = levels.new_targets(count)
        self._tick = 0
        self._timer = QTimer(self, interval=interval)
        self._timer.timeout.connect(self._advance)

    @property
    def running(self):
        return self._timer.isActive()

    def set_running(self, on):
        if on == self._timer.isActive():
            return
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            # One last tick: whatever drew the bars repaints without them,
            # instead of keeping its last frame frozen on screen.
            self.tick.emit()

    def _advance(self):
        self._tick += 1
        self.values, self._targets = levels.step(self.values, self._targets, self._tick)
        self.tick.emit()


class ArtView(QWidget):
    """The source's picture, or its tile. Fixed square, rounded corners."""

    def __init__(self, size, radius, dark=False):
        super().__init__()
        self.setFixedSize(size, size)
        self.radius = radius
        self.dark = dark            # True: stays dark whatever the theme is
        self._art = FittedArt(dark)
        self._name = ""

    def set_art(self, pixmap, name=""):
        fitted = self._art.fit(pixmap, self.width(), self.devicePixelRatioF())
        if fitted or name != self._name:
            self._name = name
            self.update()

    def apply_theme(self):
        self._art.refit(self.width(), self.devicePixelRatioF(), force=True)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        draw_art(p, self.rect(), self.radius, self._art.pixmap, self._name, self.dark)
        p.end()


class CloseButton(QAbstractButton):
    """The window's only chrome, now that it has no titlebar."""

    def __init__(self, size=26, parent=None):
        super().__init__(parent)
        self.d = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Close – ShortCutRadio keeps playing in the tray")

    def sizeHint(self):
        return QSize(self.d, self.d)

    def paintEvent(self, _event):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        glyph = t["muted"]
        if self.isDown():
            p.setBrush(QColor(t["accent"]))
            p.drawEllipse(QRectF(0, 0, self.d, self.d))
            glyph = t["on_accent"]
        elif self.underMouse():
            p.setBrush(QColor(t["hover_row"]))
            p.drawEllipse(QRectF(0, 0, self.d, self.d))
            glyph = t["text"]
        pen = QPen(QColor(glyph), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        a = self.d * 0.32
        c = self.d / 2
        p.drawLine(QPointF(c - a / 2, c - a / 2), QPointF(c + a / 2, c + a / 2))
        p.drawLine(QPointF(c + a / 2, c - a / 2), QPointF(c - a / 2, c + a / 2))
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class PillSwitch(QAbstractButton):
    """The 34x20 on/off switch from the mock."""

    W, H, KNOB = 34, 20, 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W, self.H)

    def sizeHint(self):
        return QSize(self.W, self.H)

    def paintEvent(self, _event):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        on = self.isChecked()
        p.setBrush(QColor(t["accent"] if on else t["slider_track"]))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2, self.H / 2)
        pad = (self.H - self.KNOB) / 2
        x = self.W - self.KNOB - pad if on else pad
        p.setBrush(QColor(t["on_accent"] if on else t["muted_small"]))
        p.drawEllipse(QRectF(x, pad, self.KNOB, self.KNOB))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(t["accent"]))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1),
                              self.H / 2, self.H / 2)
        p.end()


class RoundPlayButton(QAbstractButton):
    """The accent circle in the hero: play triangle or pause bars."""

    def __init__(self, diameter, parent=None):
        super().__init__(parent)
        self.d = diameter
        self.playing = False
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_playing(self, playing):
        if playing != self.playing:
            self.playing = playing
            self.update()

    def sizeHint(self):
        return QSize(self.d, self.d)

    def paintEvent(self, _event):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["accent_pressed"] if self.isDown() else t["accent"]))
        p.drawEllipse(QRectF(0, 0, self.d, self.d))
        p.setBrush(QColor(t["on_accent"]))
        c = self.d / 2
        if self.playing:                       # two bars
            bar, h, gap = self.d * 0.09, self.d * 0.36, self.d * 0.09
            for i in (-1, 1):
                x = c + i * (gap / 2) - (bar if i < 0 else 0)
                p.drawRect(QRectF(x, c - h / 2, bar, h))
        else:                                  # a triangle, optically centred
            s = self.d * 0.34
            p.drawPolygon(QPolygonF([QPointF(c - s * 0.45, c - s),
                                     QPointF(c - s * 0.45, c + s),
                                     QPointF(c + s * 0.9, c)]))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(t["text"]))
            p.drawEllipse(QRectF(1, 1, self.d - 2, self.d - 2))
        p.end()


class TriangleButton(QAbstractButton):
    """Previous / next, and the same glyph with a bar for the track skips."""

    def __init__(self, forward, bar=False, parent=None):
        super().__init__(parent)
        self.forward = forward
        self.bar = bar
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(28, 28)

    def paintEvent(self, _event):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if not self.isEnabled():
            color = t["disabled"]
        elif self.isDown():
            color = t["accent"]
        elif self.underMouse():
            color = t["text"]
        else:
            color = t["muted"]
        p.setBrush(QColor(color))
        cx, cy = self.width() / 2, self.height() / 2
        w, h = 10.0, 7.0
        if self.bar:
            cx -= 2
        d = 1 if self.forward else -1
        p.drawPolygon(QPolygonF([QPointF(cx - d * w / 2, cy - h),
                                 QPointF(cx - d * w / 2, cy + h),
                                 QPointF(cx + d * w / 2, cy)]))
        if self.bar:
            p.drawRect(QRectF(cx + d * w / 2 + 2, cy - h, 2.5, 2 * h))
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class _Chevron:
    """A combo whose ▾ is painted, so the skin needs no image file."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.tokens()["muted"]))
        x = self.width() - 16
        y = self.height() / 2 - 1
        p.drawPolygon(QPolygonF([QPointF(x - 4, y - 2), QPointF(x + 4, y - 2),
                                 QPointF(x, y + 3)]))
        p.end()


class ThemedComboBox(_Chevron, QComboBox):
    pass


class ThemedFontComboBox(_Chevron, QFontComboBox):
    pass


class ElidedLabel(QWidget):
    """A one-line label that shrinks by eliding, so long names never widen
    the window. QLabel would keep growing the layout instead."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(24)

    def setText(self, text):
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def text(self):
        return self._text

    def sizeHint(self):
        return QSize(24, self.fontMetrics().height())

    def minimumSizeHint(self):
        return QSize(24, self.fontMetrics().height())

    def paintEvent(self, _event):
        p = QPainter(self)
        fm = self.fontMetrics()
        p.setPen(self.palette().windowText().color())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   fm.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width()))
        p.end()
