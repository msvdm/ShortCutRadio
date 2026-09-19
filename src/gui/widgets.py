"""The pieces a stylesheet cannot draw: art, switches, transport, meters.

Everything here reads `theme.tokens()` at paint time, so a theme change only
needs a repaint, not a rebuild.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QPainter,
                           QPainterPath, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFontComboBox,
                               QSizePolicy, QWidget)

from . import theme

MONO = None


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


def stripe_brush(band, a, b):
    """The 45° two-tone band fill the mock uses wherever station art will go."""
    size = band * 2
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor(a))
    p = QPainter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(b))
    p.translate(0, 0)
    p.rotate(-45)
    for i in range(-4, 8):
        p.drawRect(QRectF(i * size, -size * 4, band, size * 12))
    p.end()
    return QBrush(pm)


def draw_art(painter, rect, radius, band):
    t = theme.tokens()
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    painter.save()
    painter.setClipPath(path)
    painter.fillRect(QRectF(rect), stripe_brush(band, t["art_a"], t["art_b"]))
    painter.restore()


def draw_level_bars(painter, right, baseline, heights, color, width, gap):
    """A static level meter, right-aligned, sitting on `baseline`."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    x = right - (len(heights) * width + (len(heights) - 1) * gap)
    for h in heights:
        painter.drawRect(QRectF(x, baseline - h, width, h))
        x += width + gap
    painter.restore()


def level_bars_width(count, width, gap):
    return count * width + (count - 1) * gap


class ArtPlaceholder(QWidget):
    """Where station art would go, if the app had a source for it."""

    def __init__(self, size, radius, band, caption=""):
        super().__init__()
        self.setFixedSize(size, size)
        self.radius = radius
        self.band = band
        self.caption = caption

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_art(p, self.rect(), self.radius, self.band)
        if self.caption:
            p.setFont(mono_font(9))
            p.setPen(QColor(theme.tokens()["muted_small"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.caption)
        p.end()


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


def _paint_chevron(widget, painter):
    t = theme.tokens()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(t["muted"]))
    x = widget.width() - 16
    y = widget.height() / 2 - 1
    painter.drawPolygon(QPolygonF([QPointF(x - 4, y - 2), QPointF(x + 4, y - 2),
                                   QPointF(x, y + 3)]))


class ThemedComboBox(QComboBox):
    """A combo whose ▾ is painted, so the skin needs no image file."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        _paint_chevron(self, p)
        p.end()


class ThemedFontComboBox(QFontComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        _paint_chevron(self, p)
        p.end()


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
