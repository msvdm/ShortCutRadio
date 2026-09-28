"""The corner card: what's playing, drawn over everything, never clickable.

Same approach the NFSU2 radio proved over a fullscreen Wine/DXVK game: a
normal translucent top-level window kept above the others by the compositor,
not anything injected into the game. It never takes focus and lets every click
through, and it is re-raised every few seconds because a fullscreen window
that raises itself would otherwise cover it.
"""

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..core.player import EMPTY_STATE
from .art import FittedArt, draw_art
from .widgets import Meter, draw_level_bars, level_bars_width

PAD_X, PAD_Y, GAP = 14, 11, 2
ART, ART_GAP, ART_RADIUS = 34, 11, 7
BARS, BAR_W, BAR_GAP, BAR_LEFT = 3, 2, 2, 10
BAR_LOW, BAR_HIGH = 4, 15
BAR_COLOR = "#ff6a2b"
FLASH_MS = 1600
SCROLL_MS = 30         # ticker: 1 px per tick
SCROLL_HOLD = 50       # ticks to rest at each end (1.5 s)
RAISE_MS = 3000


def overlay_family(conf):
    """The configured font family, or the system UI font when unset."""
    return conf.get("font_family") or QGuiApplication.font().family()


def pick_screen(name, screens, primary):
    """The monitor called `name`, or `primary` when there is none by that
    name (unset, or unplugged: the card comes back when it is)."""
    return next((s for s in screens if name and s.name() == name), primary)


def ordered_screens():
    """Monitor 1 is the main one, the rest follow left to right."""
    primary = QGuiApplication.primaryScreen()
    rest = sorted((s for s in QGuiApplication.screens() if s is not primary),
                  key=lambda s: (s.geometry().x(), s.geometry().y()))
    return ([primary] if primary else []) + rest


def overlay_screen(conf):
    return pick_screen(conf.get("screen", ""), QGuiApplication.screens(),
                       QGuiApplication.primaryScreen())


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
        self.state = EMPTY_STATE
        self.flash = ""
        self.lines = ("", "")
        self._tick = 0
        self._art = FittedArt(dark=True)
        self.tile = ""              # what the generated art says, from the address

        self.meter = Meter(BARS, self)
        self.meter.tick.connect(self.update)

        self._flash_timer = QTimer(self, singleShot=True, interval=FLASH_MS)
        self._flash_timer.timeout.connect(self._end_flash)
        self._raise_timer = QTimer(self, interval=RAISE_MS)
        self._raise_timer.timeout.connect(self.raise_)
        self._scroll_timer = QTimer(self, interval=SCROLL_MS)
        self._scroll_timer.timeout.connect(self._advance)
        self._apply_fonts()
        # The card sits in a corner of its monitor, so it has to follow that
        # monitor: a game switching resolution, a monitor plugged in, unplugged
        # or made the main one, a scale changed. Otherwise it stays where the
        # old corner was until the next title change moves it.
        self._screen = None
        qapp = QGuiApplication.instance()
        for signal in (qapp.primaryScreenChanged, qapp.screenAdded, qapp.screenRemoved):
            signal.connect(self._follow_screen)
        self._follow_screen()

    def _apply_fonts(self):
        c, family = self.conf, overlay_family(self.conf)
        self.title_font = make_font(family, c["title_style"], c["title_size"], bold=True)
        self.small_font = make_font(family, c["text_style"], c["track_size"], bold=False)

    # ------------------------------------------------------------------ state
    def set_now_playing(self, state, art=None, tile=""):
        old = self.state
        self.state = state
        self.tile = tile
        self.set_art(art)
        if old is not EMPTY_STATE and old.volume != state.volume and state.loaded:
            self.show_flash(f"Volume {state.volume}%")
        self._relayout()

    def set_art(self, pixmap):
        self._art.fit(pixmap, self._art_size(), self.devicePixelRatioF())

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
        self._sync_meter()

    def _second_line(self):
        s = self.state
        if self.flash:
            return self.flash
        match s.phase:
            case "empty":
                return "No sources yet – add some in the ShortCutRadio window"
            case "error":
                return s.error
            case "stopped":
                return f"Stopped – press {self.hint_key} to play" if self.hint_key else "Stopped"
            case "paused":
                return "Paused"
            case "connecting":
                return "Connecting…"
        return s.track

    def _relayout(self):
        s = self.state
        title = s.name or "ShortCutRadio"
        if s.loaded and s.paused:
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
        self._sync_meter()
        self.update()

    def _sync_meter(self):
        """Bars move only while the card is up and something is audible: this
        repaints over a running game, so it must stop the moment it can."""
        self.meter.set_running(self.isVisible() and self.state.audible)

    def _art_size(self):
        """Never taller than the card: the card's size comes from the settings."""
        return max(0, min(ART, self.height() - 2 * PAD_Y))

    def _text_x(self):
        return PAD_X + self._art_size() + ART_GAP

    def _room(self):
        """Width left for the text, once the art and the meter have their share."""
        right = self.width() - PAD_X
        if self.state.audible:
            right -= level_bars_width(BARS, BAR_W, BAR_GAP) + BAR_LEFT
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
        screen = self._screen
        if screen is None:
            return
        # The free area, not the whole screen: a visible taskbar is never
        # covered, at whichever edge it sits. One that hides itself reserves
        # nothing, and there the corner is the screen's own.
        geo = screen.availableGeometry()
        corner = self.conf["corner"]
        mx, my = int(self.conf["margin_x"]), int(self.conf["margin_y"])
        x = geo.right() - self.width() - mx + 1 if "right" in corner else geo.left() + mx
        y = geo.bottom() - self.height() - my + 1 if "bottom" in corner else geo.top() + my
        self.move(x, y)

    def _follow_screen(self, *_):
        """Onto the chosen monitor, or the main one while it is not there."""
        screen = overlay_screen(self.conf)
        if screen is not self._screen:
            if self._screen is not None:
                try:
                    self._screen.availableGeometryChanged.disconnect(self._relayout)
                except (RuntimeError, TypeError):
                    pass
            self._screen = screen
            if screen is not None:
                # The free area changes with the resolution and with the
                # taskbar: moved, resized, set to hide itself.
                screen.availableGeometryChanged.connect(self._relayout)
        self._relayout()

    def event(self, event):
        # Now on a screen with another scale: the art was fitted for the old
        # one's pixels.
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            if self._art.refit(self._art_size(), self.devicePixelRatioF()):
                self.update()
        return super().event(event)

    def reload_conf(self):
        self._apply_fonts()
        self._follow_screen()       # the monitor may be what changed
        # The card's height follows the fonts, and the art box follows it.
        self._art.refit(self._art_size(), self.devicePixelRatioF())

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
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            draw_art(p, QRectF(PAD_X, (self.height() - art) / 2, art, art),
                     ART_RADIUS, self._art.pixmap, self.tile, dark=True)
        if self.state.audible:
            draw_level_bars(p, self.width() - PAD_X, self.height() / 2 + BAR_HIGH / 2,
                            self.meter.values, BAR_COLOR, BAR_W, BAR_GAP,
                            BAR_LOW, BAR_HIGH)

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
