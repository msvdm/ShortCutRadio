"""The setup window: what's playing on top, then Sources / Shortcuts / Overlay.

Closing it only hides it; ShortCutRadio keeps playing from the tray.

It wears no titlebar (frameless.py), so the window is its own chrome: the hero
and the tab strip stand in for the titlebar, and the only button is the × in
the hero's corner. The tab strip is built from plain buttons rather than a
QTabBar because a page may put something of its own at the right end of that
same strip (`strip_widget`): the list hint on Sources, `Reset to default` on
Overlay.
"""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ..core.player import VOLUME_MAX
from .frameless import FramelessWindow, keep_on_screen
from .overlay_page import OverlayPage
from .shortcuts_page import ShortcutsPage
from .sources_page import SourcesPage
from .widgets import (ArtView, CloseButton, ElidedLabel, RoundPlayButton, TriangleButton,
                      mono_font, repolish)

CLOSE_BTN, CLOSE_INSET = 26, 10


class TabButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("tab")
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", "false")
        # Measured in the font it is drawn in when active (14 px, DemiBold),
        # not the system's default: that one differs from machine to machine,
        # and a narrower guess clipped the label's first letter.
        f = QFont(self.font())
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(text) + 12)
        self.setFont(f)

    def set_active(self, on):
        self.setProperty("active", "true" if on else "false")
        repolish(self)


class Hero(QWidget):
    """Now playing, with the transport. The same on every tab."""

    def __init__(self, app):
        super().__init__()
        self.setObjectName("hero")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        # The right margin keeps the transport out from under the × in the
        # corner, even when the window is at its narrowest.
        lay.setContentsMargins(20, 20, 20 + CLOSE_BTN + CLOSE_INSET, 20)
        lay.setSpacing(18)
        self.art = ArtView(88, 10)
        lay.addWidget(self.art)

        info = QVBoxLayout()
        info.setSpacing(6)
        self.status = QLabel("")
        self.status.setObjectName("heroStatus")
        self.status.setFont(mono_font(10, spacing=0.16))
        info.addWidget(self.status)
        self.name = ElidedLabel("ShortCutRadio")
        self.name.setObjectName("heroName")
        self.track = ElidedLabel("")
        self.track.setObjectName("heroTrack")
        info.addWidget(self.name)
        info.addWidget(self.track)
        lay.addLayout(info, 2)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        transport = QHBoxLayout()
        transport.setSpacing(14)
        self.prev = TriangleButton(forward=False)
        self.prev.setToolTip("Previous source")
        self.prev.clicked.connect(app.player.prev_source)
        self.play = RoundPlayButton(44)
        self.play.setToolTip("Play / Pause")
        self.play.clicked.connect(app.player.toggle)
        self.next = TriangleButton(forward=True)
        self.next.setToolTip("Next source")
        self.next.clicked.connect(app.player.next_source)
        self.track_next = TriangleButton(forward=True, bar=True)
        self.track_next.setToolTip("Next track (folders)")
        self.track_next.clicked.connect(app.player.next_track)
        for b in (self.prev, self.play, self.next, self.track_next):
            transport.addWidget(b)
        right.addLayout(transport)

        vol = QHBoxLayout()
        vol.setSpacing(10)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setToolTip("Volume")
        self.volume.setRange(0, VOLUME_MAX)
        self.volume.setFixedWidth(156)
        self.volume.valueChanged.connect(app.player.set_volume)
        self.vol_label = QLabel("")
        self.vol_label.setObjectName("heroVolume")
        self.vol_label.setFont(mono_font(12))
        self.vol_label.setFixedWidth(34)
        self.vol_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vol.addWidget(self.volume)
        vol.addWidget(self.vol_label)
        right.addLayout(vol)
        # A stretch on each side centres the controls in what is left between
        # the name and the ×, instead of pinning them to the right edge.
        lay.addStretch(1)
        lay.addLayout(right)
        lay.addStretch(1)

    def set_now_playing(self, s, art, tile):
        status, name, track = self._lines(s)
        self.status.setText(status)
        self.name.setText(name)
        self.track.setText(track)
        self.art.set_art(art, tile)
        self.play.set_playing(s.playing)
        self.track_next.setEnabled(s.can_skip_track)
        if not self.volume.isSliderDown():
            with QSignalBlocker(self.volume):
                self.volume.setValue(s.volume)
        self.vol_label.setText(f"{s.volume}%")

    @staticmethod
    def _lines(s):
        """Status line, source name, track line."""
        match s.phase:
            case "empty":
                return "■ STOPPED", "No sources yet", "Use Add Folder or Add Stream."
            case "error":
                return s.error.upper(), s.name, ""
            case "stopped":
                return "■ STOPPED", s.name, ""
            case "paused":
                return "❚❚ PAUSED", s.name, s.track
            case "connecting":
                return "… CONNECTING", s.name, ""
        track = s.track
        if s.track_pos:
            track += f"   ({s.track_pos}/{s.track_count})"
        return ("● PLAYING" if s.kind == "folder" else "● LIVE STREAM"), s.name, track


class MainWindow(FramelessWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("window")
        self.setWindowTitle("ShortCutRadio")
        self.setWindowIcon(app.icon)
        # One fixed size, not whatever the current page happens to need.
        # Each tab has a different layout minimum, and a frameless window that
        # changes its size hints gets re-sized by the window manager: switching
        # to Overlay and back grew the window by a hundred pixels every round
        # trip. Pinning it keeps the hints still. The height fits the Overlay
        # tab, which is the densest page now that the hero is on all three.
        # The author's chosen size, measured; it is not resizable by choice.
        self.setFixedSize(640, 600)
        self._placed = False

        self.hero = Hero(app)
        self.sources = SourcesPage(app)
        self.shortcuts = ShortcutsPage(app)
        self.look = OverlayPage(app)
        self.pages = [self.sources, self.shortcuts, self.look]
        self.tabs = [TabButton(t) for t in ("Sources", "Shortcuts", "Overlay")]

        strip = self.strip = QWidget()
        strip.setObjectName("tabStrip")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(20, 0, 20, 0)
        sl.setSpacing(22)
        for i, b in enumerate(self.tabs):
            b.clicked.connect(lambda _=False, n=i: self.set_tab(n))
            sl.addWidget(b)
        sl.addStretch(1)
        for p in self.pages:
            if p.strip_widget is not None:
                sl.addWidget(p.strip_widget)

        self.shell = QWidget(self)
        self.shell.setObjectName("shell")
        self.shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self.shell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.hero)
        lay.addWidget(strip)
        for p in self.pages:
            lay.addWidget(p, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.shell)

        # The only chrome left. Closing hides to the tray; the music goes on.
        self.close_btn = CloseButton(CLOSE_BTN, self.shell)
        self.close_btn.clicked.connect(self.close)
        self.close_btn.raise_()
        self.set_tab(0)

    def place(self):
        """Before it shows: on the screen under the mouse the first time,
        and wholly on some screen every time."""
        keep_on_screen(self, centre=not self._placed)
        self._placed = True

    def set_tab(self, n):
        for i, (b, p) in enumerate(zip(self.tabs, self.pages)):
            b.set_active(i == n)
            p.setVisible(i == n)
            if p.strip_widget is not None:
                p.strip_widget.setVisible(i == n)

    def set_now_playing(self, s, art=None, tile=""):
        self.hero.set_now_playing(s, art, tile)
        self.sources.set_now_playing(s)

    def apply_theme(self):
        """After a theme change: the hand-painted parts need a repaint."""
        self.look.refresh_colors()
        self.hero.art.apply_theme()
        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    # ------------------------------------------------------------------ chrome
    def is_titlebar(self, pos):
        """The hero and the tab strip stand in for the titlebar.

        Dragging is limited to them: empty space further
        down belongs to the page, and grabbing the window from under the
        source list would be a surprise.
        """
        local = self.shell.mapFrom(self, pos)
        return any(w.geometry().contains(local) for w in (self.hero, self.strip))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.close_btn.move(self.shell.width() - CLOSE_BTN - CLOSE_INSET, CLOSE_INSET)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.shortcuts.capturing is None:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.app.tray is not None:
            event.ignore()
            self.hide()
        else:
            self.app.quit()
