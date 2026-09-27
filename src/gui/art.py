"""The art box's picture: trimmed, fitted whole, on a backdrop -- or a tile.

A station logo is rarely square and usually ships inside a lot of empty space,
so it is trimmed to its content, scaled to fit *inside* the box and centred on
a backdrop that makes it read. With no picture at all, the box shows a tile of
initials on a colour, both derived from the source's address.

All the pixel work happens once per picture (`FittedArt`), never in a
paintEvent the level meter calls fourteen times a second.
"""

import hashlib
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPixmap

from . import theme

PROBE = 96              # art is measured on a copy this big, not full size
TRIM_TOL = 14           # how near the corner's colour still counts as border
TRIM_MAX = 0.42         # never trim more than this much off one side

# The overlay is drawn dark whatever the theme is.
DARK_TILE = {"tile_sat": 120, "tile_val": 96, "tile_text": "#f1f3f6",
             "art_dark": "#1b1f26", "art_light": "#e8eaee"}


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


class FittedArt:
    """One picture fitted to one box, redone only when either changes.

    It keeps the picture it was given, so a new box size is fitted from the
    original -- never from an already trimmed and scaled copy.
    """

    def __init__(self, dark=False):
        self.dark = dark
        self.pixmap = None          # the finished tile, or None: draw initials
        self._source = None
        self._key = None

    def fit(self, pixmap, size, dpr):
        """Fit `pixmap` to a `size`-point box. True if the result changed."""
        if pixmap is not None and pixmap.isNull():
            pixmap = None
        key = (pixmap.cacheKey() if pixmap is not None else 0, size, dpr)
        if key == self._key:
            return False
        self._key, self._source = key, pixmap
        self.pixmap = fit_pixmap(pixmap, size, dpr, self.dark)
        return True

    def refit(self, size, dpr, force=False):
        """Fit the same picture again: to a new box, or (`force`) after a
        theme change, which can change a cut-out logo's backdrop."""
        if force:
            self._key = None
        return self.fit(self._source, size, dpr)
