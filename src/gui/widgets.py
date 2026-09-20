"""The pieces a stylesheet cannot draw: art, switches, transport, meters.

Everything here reads `theme.tokens()` at paint time, so a theme change only
needs a repaint, not a rebuild.
"""

import hashlib
import re

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFontComboBox,
                               QSizePolicy, QWidget)

from ..core import levels
from . import theme

METER_MS = 70           # ~14 frames a second: alive, but nearly free
PROBE = 96              # art is measured on a copy this big, not full size
TRIM_TOL = 14           # how near the corner's colour still counts as border
TRIM_MAX = 0.42         # never trim more than this much off one side

# The overlay and the tray menu are drawn dark whatever the theme is.
DARK_TILE = {"tile_sat": 120, "tile_val": 96, "tile_text": "#f1f3f6",
             "art_dark": "#1b1f26", "art_light": "#e8eaee"}

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


def monogram(name):
    """One or two letters to stand for a source that has no picture."""
    words = [w for w in re.split(r"[\s\-–—_/|:.]+", name or "")
             if w and not w.isdigit()]
    # Filter first, then take two, or "Drum & Bass" spends one of them on "&".
    letters = [w[0] for w in words if w[0].isalnum()][:2]
    if len(letters) < 2 and words:
        # One word: two of its letters read better than a lone initial.
        pair = [c for c in words[0] if c.isalnum()][:2]
        letters = pair if len(pair) == 2 else letters
    return ("".join(letters) or (name or "?")[:1]).upper()


def tile_color(name, sat, val):
    """A stable colour per source: one station is always the same tile."""
    digest = hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:8]
    return QColor.fromHsv(int(digest, 16) % 360, sat, val)


def _probe(pm):
    """A small ARGB copy to measure. Scanning a 600 px logo pixel by pixel in
    Python is far too slow; at this size it is a few milliseconds."""
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    if max(img.width(), img.height()) > PROBE:
        img = img.scaled(PROBE, PROBE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img


def _border_test(img):
    """Is this pixel part of the flat border? -- transparent, or the same
    colour the corner is."""
    ref = img.pixelColor(0, 0)
    opaque_ref = ref.alpha() >= 12

    def is_border(x, y):
        c = img.pixelColor(x, y)
        if c.alpha() < 12:
            return True
        if not opaque_ref:
            return False
        return (abs(c.red() - ref.red()) + abs(c.green() - ref.green())
                + abs(c.blue() - ref.blue())) <= TRIM_TOL

    return is_border


def content_box(img):
    """What is left of `img` once a flat or transparent border is trimmed.

    Logos are routinely published inside a lot of empty space; without this
    they land in the art box two sizes too small.
    """
    w, h = img.width(), img.height()
    if w < 4 or h < 4:
        return None
    is_border = _border_test(img)
    # One flat colour edge to edge: there is no content to trim down to.
    # all() stops at the first pixel that differs, so this is normally instant.
    if all(is_border(x, y) for x in range(w) for y in range(h)):
        return None
    left, right, top, bottom = 0, w - 1, 0, h - 1
    limit_x, limit_y = int(w * TRIM_MAX), int(h * TRIM_MAX)
    while left < limit_x and all(is_border(left, y) for y in range(h)):
        left += 1
    while right > w - 1 - limit_x and all(is_border(right, y) for y in range(h)):
        right -= 1
    while top < limit_y and all(is_border(x, top) for x in range(w)):
        top += 1
    while bottom > h - 1 - limit_y and all(is_border(x, bottom) for x in range(w)):
        bottom -= 1
    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right - left + 1, bottom - top + 1


def backdrop(img, dark):
    """What the picture sits on, so a shape that does not fill the square --
    or a white logo on nothing at all -- still reads.

    A logo with an opaque border extends that border, which looks like one
    card. A cut-out one gets a panel chosen to contrast with it.
    """
    edge, light, n = [], 0, 0
    w, h = img.width(), img.height()
    for x, y in ([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
                 + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]):
        c = img.pixelColor(x, y)
        if c.alpha() >= 200:
            edge.append((c.red(), c.green(), c.blue()))
    for x in range(0, w, 3):
        for y in range(0, h, 3):
            c = img.pixelColor(x, y)
            if c.alpha() >= 100:
                n += 1
                light += c.lightness()
    if len(edge) > (w + h):             # a real border, not a stray pixel
        return QColor(*(sum(v) // len(edge) for v in zip(*edge)))
    t = DARK_TILE if dark else theme.tokens()
    pale = n and light / n > 140
    return QColor(t["art_dark"] if pale else t["art_light"])


def fit_pixmap(pm, size, dpr=1.0, dark=False):
    """A finished square tile: trimmed, fitted whole, on its backdrop.

    `size` is in points and `dpr` the screen's ratio, or a 4K desktop shows a
    blurred thumbnail. All of it happens once, here -- never in a paintEvent
    the meter calls fourteen times a second.
    """
    if pm is None or pm.isNull() or size <= 0:
        return None
    px = max(1, round(size * dpr))
    probe = _probe(pm)
    box = content_box(probe)
    if box:                             # map the box back to the full picture
        k = pm.width() / probe.width()
        pm = pm.copy(*(max(0, round(v * k)) for v in box))
    scaled = pm.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(px, px)
    out.fill(backdrop(probe, dark))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap((px - scaled.width()) // 2, (px - scaled.height()) // 2, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def draw_art(painter, rect, radius, pixmap=None, name="", dark=False):
    """The art box: the picture if there is one, else a tile of initials."""
    r = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    painter.save()
    painter.setClipPath(path)
    if pixmap is not None and not pixmap.isNull():
        painter.drawPixmap(r.topLeft(), pixmap)
    else:
        t = DARK_TILE if dark else theme.tokens()
        painter.fillRect(r, tile_color(name, int(t["tile_sat"]), int(t["tile_val"])))
        f = QFont(painter.font())
        f.setBold(True)
        f.setPixelSize(max(8, int(r.height() * 0.4)))
        painter.setFont(f)
        painter.setPen(QColor(t["tile_text"]))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, monogram(name))
    painter.restore()


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

    def set_running(self, on):
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on:
            self._timer.stop()

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
        self.dark = dark            # the tray header does not follow the theme
        self._pm = None
        self._name = ""
        self._key = 0

    def set_art(self, pixmap, name=""):
        # Compare the source pixmap, not the scaled copy: the scaling is the
        # expensive half and it must not run on every state update.
        key = pixmap.cacheKey() if pixmap is not None and not pixmap.isNull() else 0
        if key == self._key and name == self._name:
            return
        self._key, self._name = key, name
        self._pm = fit_pixmap(pixmap, self.width(), self.devicePixelRatioF(),
                              self.dark)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        draw_art(p, self.rect(), self.radius, self._pm, self._name, self.dark)
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
