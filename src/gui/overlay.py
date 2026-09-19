"""The corner card: what's playing, drawn over everything, never clickable.

Same approach the NFSU2 radio proved over a fullscreen Wine/DXVK game: a
normal translucent top-level window kept above the others by the compositor,
not anything injected into the game. It never takes focus and lets every click
through, and it is re-raised every few seconds because a fullscreen window
that raises itself would otherwise cover it.
"""

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from .widgets import draw_level_bars, level_bars_width, stripe_brush

PAD_X, PAD_Y, GAP = 14, 11, 2
ART, ART_GAP, ART_BAND, ART_RADIUS = 34, 11, 4, 7
ART_A, ART_B = "#2a2f37", "#333942"
BARS, BAR_W, BAR_GAP, BAR_LEFT = (6, 14, 9), 2, 2, 10
BAR_COLOR = "#ff6a2b"
FLASH_MS = 1600
SCROLL_MS = 30         # ticker: 1 px per tick
SCROLL_HOLD = 50       # ticks to rest at each end (1.5 s)
RAISE_MS = 3000


def overlay_family(conf):
    """The configured font family, or the system UI font when unset."""
    return conf.get("font_family") or QGuiApplication.font().family()


def pick_style(styles, wanted, bold):
    """`wanted` if the family has it, else its closest plain or bold style."""
    if wanted in styles:
        return wanted
    for name in (["Bold", "Semibold", "SemiBold", "Medium"] if bold
                 else ["Regular", "Book", "Normal", "Roman", "Medium"]):
        if name in styles:
            return name
    return styles[0] if styles else ""


def make_font(family, style, size, bold):
    styles = QFontDatabase.styles(family)
    style = pick_style(styles, style, bold)
    if style:
        return QFontDatabase.font(family, style, int(size))
    f = QFont(family, int(size))
    f.setBold(bold)
    return f


class Overlay(QWidget):
    def __init__(self, conf, hint_key=""):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.X11BypassWindowManagerHint)
        self.conf = conf
        self.hint_key = hint_key
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("ShortCutRadio overlay")
        self.state = {}
        self.flash = ""
        self.lines = ("", "")
        self._tick = 0

        self._flash_timer = QTimer(self, singleShot=True, interval=FLASH_MS)
        self._flash_timer.timeout.connect(self._end_flash)
        self._raise_timer = QTimer(self, interval=RAISE_MS)
        self._raise_timer.timeout.connect(self.raise_)
        self._scroll_timer = QTimer(self, interval=SCROLL_MS)
        self._scroll_timer.timeout.connect(self._advance)
        self._apply_fonts()

    def _apply_fonts(self):
        c, family = self.conf, overlay_family(self.conf)
        self.title_font = make_font(family, c["title_style"], c["title_size"], bold=True)
        self.small_font = make_font(family, c["text_style"], c["track_size"], bold=False)

    # ------------------------------------------------------------------ state
    def set_state(self, state):
        old = self.state
        self.state = state
        if old and old.get("volume") != state.get("volume") and state.get("loaded"):
            self.show_flash(f"Volume {state['volume']}%")
        self._relayout()

    def show_flash(self, text):
        self.flash = text
        self._flash_timer.start()
        self._relayout()

    def _end_flash(self):
        self.flash = ""
        self._relayout()

    def set_on(self, on):
        if on:
            self._relayout()
            self.show()
            self.raise_()
            self._raise_timer.start()
        else:
            self._raise_timer.stop()
            self.hide()
        self._update_ticker()

    def _second_line(self):
        s = self.state
        if self.flash:
            return self.flash
        if not s or not s.get("count"):
            return "No sources yet – add some in the ShortCutRadio window"
        if s.get("error"):
            return s["error"]
        if not s.get("loaded"):
            return f"Stopped – press {self.hint_key} to play" if self.hint_key else "Stopped"
        if s.get("paused"):
            return "Paused"
        if s.get("connecting"):
            return "Connecting…"
        return s.get("track") or ""

    def _relayout(self):
        s = self.state
        title = s.get("name") or "ShortCutRadio"
        if s.get("loaded") and s.get("paused"):
            title = "❚❚  " + title
        lines = (title, self._second_line())
        if lines != self.lines:
            self.lines = lines
            self._tick = 0          # new text: the ticker starts from the left

        # The size comes from the settings only, never from the text, so the
        # card doesn't jump around as the status and track change.
        tf, sf = QFontMetrics(self.title_font), QFontMetrics(self.small_font)
        w = max(120, int(self.conf["width"]))
        h = tf.height() + GAP + sf.height() + 2 * PAD_Y
        if self.size() != QSize(w, h):
            self.resize(w, h)
        self._reposition()
        self._update_ticker()
        self.update()

    def _playing(self):
        s = self.state
        return bool(s.get("loaded")) and not s.get("paused") and not s.get("connecting")

    def _art_size(self):
        """Never taller than the card: the card's size comes from the settings."""
        return max(0, min(ART, self.height() - 2 * PAD_Y))

    def _text_x(self):
        return PAD_X + self._art_size() + ART_GAP

    def _room(self):
        """Width left for the text, once the art and the meter have their share."""
        right = self.width() - PAD_X
        if self._playing():
            right -= level_bars_width(len(BARS), BAR_W, BAR_GAP) + BAR_LEFT
        return max(20, right - self._text_x())

    def _overflow(self):
        """How far each line sticks out past the card (0 = it fits)."""
        title, second = self.lines
        tf, sf = QFontMetrics(self.title_font), QFontMetrics(self.small_font)
        return (max(0, tf.horizontalAdvance(title) - self._room()),
                max(0, sf.horizontalAdvance(second) - self._room()) if second else 0)

    def _update_ticker(self):
        run = bool(self.conf["scroll"]) and self.isVisible() and max(self._overflow()) > 0
        if run and not self._scroll_timer.isActive():
            self._scroll_timer.start()
        elif not run:
            self._scroll_timer.stop()
            self._tick = 0

    def _advance(self):
        # Hold at the start, scroll 1 px per tick to the end, hold, restart.
        # All overflowing lines share one cycle so they restart together.
        self._tick += 1
        if self._tick > 2 * SCROLL_HOLD + max(self._overflow()):
            self._tick = 0
        self.update()

    def _offset(self, overflow):
        return min(overflow, max(0, self._tick - SCROLL_HOLD))

    def _reposition(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        corner = self.conf["corner"]
        mx, my = int(self.conf["margin_x"]), int(self.conf["margin_y"])
        x = geo.right() - self.width() - mx + 1 if "right" in corner else geo.left() + mx
        y = geo.bottom() - self.height() - my + 1 if "bottom" in corner else geo.top() + my
        self.move(x, y)

    def reload_conf(self):
        self._apply_fonts()
        self._relayout()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _event):
        c = self.conf
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        bg = QColor(c["bg_color"])
        bg.setAlphaF(max(0.0, min(1.0, float(c["opacity"]))))
        p.fillPath(path, bg)
        p.setPen(QColor(255, 255, 255, 36))
        p.drawPath(path)

        art = self._art_size()
        if art:
            art_rect = QRectF(PAD_X, (self.height() - art) / 2, art, art)
            art_path = QPainterPath()
            art_path.addRoundedRect(art_rect, ART_RADIUS, ART_RADIUS)
            p.save()
            p.setClipPath(art_path)
            p.fillRect(art_rect, stripe_brush(ART_BAND, ART_A, ART_B))
            p.restore()
        if self._playing():
            draw_level_bars(p, self.width() - PAD_X, self.height() / 2 + max(BARS) / 2,
                            BARS, BAR_COLOR, BAR_W, BAR_GAP)

        title, second = self.lines
        room = self._room()
        x = self._text_x()
        tf, sf = QFontMetrics(self.title_font), QFontMetrics(self.small_font)
        scroll = bool(c["scroll"])
        title_over, second_over = self._overflow()

        y = PAD_Y + tf.ascent()
        p.setFont(self.title_font)
        p.setPen(QColor(c["title_color"]))
        self._draw_line(p, tf, title, x, y, room, title_over, scroll)

        if second:
            y += tf.descent() + GAP + sf.ascent()
            p.setFont(self.small_font)
            p.setPen(QColor(c["text_color"]))
            self._draw_line(p, sf, second, x, y, room, second_over, scroll)
        p.end()

    def _draw_line(self, p, fm, text, x, y, room, overflow, scroll):
        """Draw one line in `room` px: as is, as a ticker, or elided."""
        if not overflow:
            p.drawText(x, y, text)
            return
        if not scroll:
            p.drawText(x, y, fm.elidedText(text, Qt.TextElideMode.ElideRight, room))
            return
        p.save()
        p.setClipRect(QRectF(x, y - fm.ascent(), room, fm.height()))
        p.drawText(x - self._offset(overflow), y, text)
        p.restore()
