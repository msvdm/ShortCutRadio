"""The corner card: what's playing, drawn over everything, never clickable.

Same approach the NFSU2 radio proved over a fullscreen Wine/DXVK game: a
normal translucent top-level window kept above the others by the compositor,
not anything injected into the game. It never takes focus and lets every click
through, and it is re-raised every few seconds because a fullscreen window
that raises itself would otherwise cover it.
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

PAD_X, PAD_Y, GAP = 16, 10, 2
FLASH_MS = 1600
RAISE_MS = 3000


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
        self.lines = ("", "", "")

        self._flash_timer = QTimer(self, singleShot=True, interval=FLASH_MS)
        self._flash_timer.timeout.connect(self._end_flash)
        self._raise_timer = QTimer(self, interval=RAISE_MS)
        self._raise_timer.timeout.connect(self.raise_)
        self._apply_fonts()

    def _apply_fonts(self):
        self.title_font = QFont(self.font())
        self.title_font.setPointSize(int(self.conf["title_size"]))
        self.title_font.setBold(True)
        self.small_font = QFont(self.font())
        self.small_font.setPointSize(int(self.conf["track_size"]))

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
        counter = f"{s['index'] + 1}/{s['count']}" if s.get("count") else ""
        if s.get("track_pos") and s.get("track_count"):
            counter += f"  ·  {s['track_pos']}/{s['track_count']}"
        self.lines = (title, counter, self._second_line())

        max_w = int(self.conf["max_width"])
        tf, sf = QFontMetrics(self.title_font), QFontMetrics(self.small_font)
        counter_w = sf.horizontalAdvance(counter) + (12 if counter else 0)
        w = max(tf.horizontalAdvance(title) + counter_w,
                sf.horizontalAdvance(self.lines[2]) if self.lines[2] else 0)
        w = min(max_w, w) + 2 * PAD_X
        h = tf.height() + (GAP + sf.height() if self.lines[2] else 0) + 2 * PAD_Y
        self.resize(max(w, 120), h)
        self._reposition()
        self.update()

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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.fillPath(path, QColor(0, 0, 0, int(255 * float(self.conf["opacity"]))))
        p.setPen(QColor(255, 255, 255, 36))
        p.drawPath(path)

        title, counter, second = self.lines
        inner_w = self.width() - 2 * PAD_X
        tf, sf = QFontMetrics(self.title_font), QFontMetrics(self.small_font)
        counter_w = sf.horizontalAdvance(counter) + (12 if counter else 0)

        y = PAD_Y + tf.ascent()
        p.setFont(self.title_font)
        p.setPen(QColor("#ffffff"))
        title_el = tf.elidedText(title, Qt.TextElideMode.ElideRight, max(40, inner_w - counter_w))
        p.drawText(PAD_X, y, title_el)
        if counter:
            p.setFont(self.small_font)
            p.setPen(QColor("#8a939c"))
            p.drawText(PAD_X + tf.horizontalAdvance(title_el) + 12, y, counter)

        if second:
            y += tf.descent() + GAP + sf.ascent()
            p.setFont(self.small_font)
            p.setPen(QColor("#c7d0d8"))
            p.drawText(PAD_X, y, sf.elidedText(second, Qt.TextElideMode.ElideRight, inner_w))
        p.end()
