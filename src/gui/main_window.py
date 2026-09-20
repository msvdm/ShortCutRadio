"""The setup window: what's playing on top, then Sources / Shortcuts / Overlay.

Closing it only hides it; ShortCutRadio keeps playing from the tray.

It wears no titlebar, so the window is its own chrome: a transparent carrier
(#window) holds a resize margin around the card (#shell), the card is dragged
by any empty part of it, and the only button is the × in the hero. The tab
strip is built from plain buttons rather than a QTabBar because two of the tabs
put something of their own at the right end of that same strip -- the list hint
on Sources, `Reset to default` on Overlay.
"""

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics,
                           QKeySequence, QPainter, QPainterPath)
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from ..core.config import DEFAULTS, opacity_from_percent, transparency_percent
from ..core.artfetch import clean_site, site_for_stream
from ..core.hotkeys import has_modifier, pretty
from ..core.player import VOLUME_MAX
from ..core.sources import describe, folder_tracks, is_folder, make_folder, make_stream
from . import theme
from .add_stream import AddStreamDialog
from .overlay import overlay_family, pick_style
from .widgets import (ArtView, CloseButton, ElidedLabel, Meter, PillSwitch,
                      RoundPlayButton, ThemedComboBox, ThemedFontComboBox,
                      TriangleButton, draw_level_bars, level_bars_width, mono_font)

SHORTCUT_ROWS = [
    ("overlay", "Overlay on / off"),
    ("play_pause", "Play / Pause"),
    ("source_next", "Next source"),
    ("source_prev", "Previous source"),
    ("track_next", "Next track"),
    ("track_prev", "Previous track"),
    ("vol_up", "Volume up"),
    ("vol_down", "Volume down"),
]
CORNERS = [("top-right", "Top right"), ("top-left", "Top left"),
           ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left")]
CAPTURE_TIP = ("Click, then press the new key (Esc cancels, Backspace clears).\n"
               "Single-key shortcuts only work while the overlay is on,\n"
               "so typing is safe when it's off.")
HELP_TEXT = ("The keyboard shortcuts work only while the overlay is active. If you want "
             "to free them up for other purposes - such as typing - disable the overlay; "
             "the music will not stop.")
LIST_HINT = "drag to reorder · double-click to play"
# Qt copies whatever is put in an item, so SOURCE_ROLE is a *copy* of the
# source -- fine for drawing the row, useless to write to. Anything that edits
# a source goes through INDEX_ROLE to the real dict in the config.
SOURCE_ROLE = Qt.ItemDataRole.UserRole
PLAYING_ROLE = Qt.ItemDataRole.UserRole + 1
INDEX_ROLE = Qt.ItemDataRole.UserRole + 2
ROW_BARS, ROW_BAR_LOW, ROW_BAR_HIGH = 4, 5, 17
NOTE_MS = 4000
RESIZE_MARGIN = 6           # the transparent grip around the card
CLOSE_BTN, CLOSE_INSET = 26, 10
# Every word-wrapped label needs a pinned wrapping width. Qt asks such a label
# how tall it would be at its *minimum* width, and an unpinned one answers with
# a dozen lines -- which the window then grows to fit and never gives back.
WRAP_W = 560
ART_EXTS = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg)"

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


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class SourceDelegate(QStyledItemDelegate):
    """One source per row: an accent bar when it plays, name, then describe()."""

    PAD_X, PAD_Y, GAP, BAR_W, BAR_H = 12, 11, 12, 3, 26

    def __init__(self, parent, window):
        super().__init__(parent)
        self.window_ = window       # for the meter the playing row draws

    def _fonts(self, option, playing):
        name = QFont(option.font)
        name.setPixelSize(14)
        name.setWeight(QFont.Weight.DemiBold if playing else QFont.Weight.Normal)
        sub = QFont(option.font)
        sub.setPixelSize(12)
        return name, sub

    def sizeHint(self, option, index):
        name, sub = self._fonts(option, False)
        h = 2 * self.PAD_Y + QFontMetrics(name).height() + 2 + QFontMetrics(sub).height()
        return QSize(option.rect.width(), max(48, h))

    def paint(self, painter, option, index):
        t = theme.tokens()
        src = index.data(SOURCE_ROLE) or {}
        playing = bool(index.data(PLAYING_ROLE))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = None
        if playing:
            bg = t["active_row"]
        elif selected:
            bg = t["sel_row"]
        elif hover:
            bg = t["hover_row"]
        if bg:
            path = QPainterPath()
            path.addRoundedRect(QRectF(option.rect), 9, 9)
            painter.fillPath(path, QColor(bg))

        r = option.rect
        x = r.left() + self.PAD_X
        if playing:
            bar = QRectF(x, r.center().y() - self.BAR_H / 2 + 1, self.BAR_W, self.BAR_H)
            path = QPainterPath()
            path.addRoundedRect(bar, 2, 2)
            painter.fillPath(path, QColor(t["accent"]))
        x += self.BAR_W + self.GAP

        right = r.right() - self.PAD_X
        if playing and self.window_.sounding:
            draw_level_bars(painter, right, r.center().y() + ROW_BAR_HIGH / 2,
                            self.window_.meter.values, t["accent"], 3, 3,
                            ROW_BAR_LOW, ROW_BAR_HIGH)
            right -= level_bars_width(ROW_BARS, 3, 3) + 10
        room = max(20, right - x)

        name_font, sub_font = self._fonts(option, playing)
        painter.setFont(name_font)
        fm = painter.fontMetrics()
        top = r.top() + self.PAD_Y
        painter.setPen(QColor(t["text"] if playing else t["text2"]))
        painter.drawText(x, top + fm.ascent(),
                         fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                       Qt.TextElideMode.ElideRight, room))
        top += fm.height() + 2
        painter.setFont(sub_font)
        fm = painter.fontMetrics()
        painter.setPen(QColor(t["muted"] if playing else t["muted_small"]))
        painter.drawText(x, top + fm.ascent(),
                         fm.elidedText(describe(src), Qt.TextElideMode.ElideMiddle, room))
        painter.restore()


class ShortcutButton(QPushButton):
    """The key cap; click, then press keys to record a new combo.

    Recording goes through the global listener (so what is recorded is exactly
    what will match), but Qt still delivers the same key to this button -- it
    must be swallowed, or Space/Enter would re-click it.
    """

    def __init__(self, action, window):
        super().__init__()
        self.action = action
        self.window_ = window
        self.setObjectName("keyCap")
        self.setFont(mono_font(12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: window.begin_capture(self))

    def keyPressEvent(self, event):
        if self.window_.capturing is self:
            event.accept()
            return
        super().keyPressEvent(event)


class ShortcutRow(QFrame):
    def __init__(self, action, label, window):
        super().__init__()
        self.setObjectName("shortcutRow")
        self.setProperty("capturing", "false")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(12)
        text = QLabel(label)
        text.setObjectName("shortcutLabel")
        self.button = ShortcutButton(action, window)
        self.button.setToolTip(CAPTURE_TIP)
        self.button.row = self
        lay.addWidget(text)
        lay.addStretch(1)
        lay.addWidget(self.button)

    def set_capturing(self, on):
        self.setProperty("capturing", "true" if on else "false")
        self.button.setProperty("capturing", "true" if on else "false")
        repolish(self)
        repolish(self.button)


class TabButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("tab")
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", "false")
        f = QFont(self.font())
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFixedWidth(self.fontMetrics().boundingRect(text).width() + 12)
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


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.app = app
        self.capturing = None
        self.sounding = False           # something is audible right now
        self._drag_from = None
        self.meter = Meter(ROW_BARS, self)
        self.setObjectName("window")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setWindowTitle("ShortCutRadio")
        self.setWindowIcon(app.icon)
        # A constant minimum, not the one the current page happens to need.
        # Each tab has a different layout minimum, and a frameless window that
        # changes its size hints gets re-sized by the window manager: switching
        # to Overlay and back grew the window by a hundred pixels every round
        # trip. Pinning it keeps the hints still. The height fits the Overlay
        # tab, which is the densest page now that the hero is on all three.
        self.setMinimumSize(640 + 2 * RESIZE_MARGIN, 600 + 2 * RESIZE_MARGIN)
        self.resize(900 + 2 * RESIZE_MARGIN, 600 + 2 * RESIZE_MARGIN)

        self.hero = Hero(app)
        self.hero.volume.valueChanged.connect(self._volume_moved)

        self.tabs = [TabButton("Sources"), TabButton("Shortcuts"), TabButton("Overlay")]
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
        self.hint = QLabel(LIST_HINT)
        self.hint.setObjectName("tabHint")
        sl.addWidget(self.hint)
        self.reset_btn = QPushButton("Reset to default")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.setToolTip("Restore the default size, margins, font, transparency and colors")
        self.reset_btn.clicked.connect(self._reset_look)
        sl.addWidget(self.reset_btn)
        self._note_timer = QTimer(self, singleShot=True, interval=NOTE_MS)
        self._note_timer.timeout.connect(lambda: self.hint.setText(LIST_HINT))

        self.pages = [self._sources_page(), self._shortcuts_page(), self._overlay_page()]
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
        outer.setContentsMargins(*([RESIZE_MARGIN] * 4))
        outer.addWidget(self.shell)

        # The only chrome left. Closing hides to the tray; the music goes on.
        self.close_btn = CloseButton(CLOSE_BTN, self.shell)
        self.close_btn.clicked.connect(self.close)
        self.close_btn.raise_()

        self.meter.tick.connect(lambda: self.list.viewport().update())

        self.refresh_look()
        self.refresh_shortcuts()
        self.refresh_sources()
        self.set_tab(0)

    # ------------------------------------------------------------------ tabs
    def set_tab(self, n):
        for i, (b, p) in enumerate(zip(self.tabs, self.pages)):
            b.set_active(i == n)
            p.setVisible(i == n)
        self.hint.setVisible(n == 0)
        self.reset_btn.setVisible(n == 2)
        self._sync_meter()

    # ------------------------------------------------------------------ sources
    def _sources_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(8)

        self.list = QListWidget()
        self.list.setObjectName("srcList")
        self.list.setItemDelegate(SourceDelegate(self.list, self))
        self.list.setSpacing(3)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemDoubleClicked.connect(
            lambda it: self.app.player.play_source(self.list.row(it)))
        self.list.model().rowsMoved.connect(self._rows_moved)
        lay.addWidget(self.list, 1)

        delete = QAction(self.list)
        delete.setShortcut(QKeySequence.StandardKey.Delete)
        delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        delete.triggered.connect(self.remove_selected)
        self.list.addAction(delete)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, fn in (("Add Folder", self.add_folder), ("Add Stream", self.add_stream)):
            b = QPushButton(text)
            b.setObjectName("addSource")
            b.clicked.connect(fn)
            row.addWidget(b, 1)
        lay.addLayout(row)
        return page

    # ------------------------------------------------------------------ shortcuts
    def _shortcuts_page(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(20, 18, 20, 20)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.shortcut_buttons = {}
        for i, (action, label) in enumerate(SHORTCUT_ROWS):
            row = ShortcutRow(action, label, self)
            self.shortcut_buttons[action] = row.button
            grid.addWidget(row, *divmod(i, 2))

        nrows = (len(SHORTCUT_ROWS) + 1) // 2
        if self.app.hotkeys.error:
            warn = QLabel(f"Global shortcuts are unavailable: {self.app.hotkeys.error}")
            warn.setObjectName("warnText")
            warn.setWordWrap(True)
            warn.setMinimumWidth(WRAP_W)
            grid.addWidget(warn, nrows, 0, 1, 2)
            nrows += 1
        help_label = QLabel(HELP_TEXT)
        help_label.setObjectName("helpText")
        help_label.setWordWrap(True)
        help_label.setFixedWidth(WRAP_W)
        grid.addWidget(help_label, nrows, 0, 1, 2)
        grid.setRowStretch(nrows + 1, 1)
        return page

    # ------------------------------------------------------------------ overlay look
    def _overlay_page(self):
        """Size, margins, font, transparency and colors of the card."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(14)
        self.look = {}
        self.color_buttons = {}

        def label(text):
            lb = QLabel(text)
            lb.setObjectName("fieldLabel")
            return lb

        def color(key, tip):
            b = QPushButton()
            b.setObjectName("colorBtn")
            b.setToolTip(tip)
            b.setFixedSize(34, 30)
            b.clicked.connect(lambda _=False: self._pick_color(key))
            self.color_buttons[key] = b
            return b

        def spin(key, lo, hi, suffix, tip):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setSuffix(suffix)
            sb.setToolTip(tip)
            sb.setFont(mono_font(13))
            sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            sb.valueChanged.connect(lambda v: self.app.set_overlay_option(key, v))
            self.look[key] = sb
            return sb

        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.setVerticalSpacing(10)
        top.setColumnStretch(1, 1)
        top.setColumnStretch(3, 1)
        self.corner = ThemedComboBox()
        self.corner.setToolTip("Which screen corner the card sits in")
        for key, text in CORNERS:
            self.corner.addItem(text, key)
        self.corner.currentIndexChanged.connect(
            lambda _: self.app.set_overlay_option("corner", self.corner.currentData()))
        top.addWidget(label("Width"), 0, 0)
        top.addWidget(spin("width", 200, 1200, " px", "Card width"), 0, 1)
        top.addWidget(label("Corner"), 0, 2)
        top.addWidget(self.corner, 0, 3)
        top.addWidget(label("Margin X"), 1, 0)
        top.addWidget(spin("margin_x", 0, 500, " px",
                           "Distance from the left/right screen edge"), 1, 1)
        top.addWidget(label("Margin Y"), 1, 2)
        top.addWidget(spin("margin_y", 0, 500, " px",
                           "Distance from the top/bottom screen edge"), 1, 3)
        top.addWidget(label("Font"), 2, 0)
        self.font_family = ThemedFontComboBox()
        self.font_family.setToolTip("Font of the overlay text")
        self.font_family.currentFontChanged.connect(self._family_changed)
        top.addWidget(self.font_family, 2, 1, 1, 3)
        lay.addLayout(top)
        lay.addWidget(self._hairline())

        rows = QGridLayout()
        rows.setHorizontalSpacing(14)
        rows.setVerticalSpacing(10)
        rows.setColumnStretch(1, 1)
        self.style_boxes = {}
        for row, (text, style_key, size_key, color_key, lo, hi, tip) in enumerate(
                [("Row 1 · station", "title_style", "title_size", "title_color",
                  8, 48, "Row 1 (station name)"),
                 ("Row 2 · track", "text_style", "track_size", "text_color",
                  6, 36, "Row 2 (track / status)")]):
            rows.addWidget(label(text), row, 0)
            box = ThemedComboBox()
            box.setToolTip(f"{tip} style")
            box.currentTextChanged.connect(
                lambda t, k=style_key: t and self.app.set_overlay_option(k, t))
            self.style_boxes[style_key] = box
            rows.addWidget(box, row, 1)
            rows.addWidget(spin(size_key, lo, hi, " pt", f"{tip} size"), row, 2)
            rows.addWidget(color(color_key, f"{tip} color"), row, 3)

        rows.addWidget(label("Transparency"), 2, 0)
        self.transp_slider = QSlider(Qt.Orientation.Horizontal)
        self.transp_spin = QSpinBox()
        self.transp_spin.setSuffix(" %")
        self.transp_spin.setFont(mono_font(13))
        self.transp_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        for w in (self.transp_slider, self.transp_spin):
            w.setRange(0, 100)
            w.setToolTip("Background transparency (the text stays solid)")
            w.valueChanged.connect(self._transparency_changed)
        rows.addWidget(self.transp_slider, 2, 1)
        rows.addWidget(self.transp_spin, 2, 2)
        rows.addWidget(color("bg_color", "Background color"), 2, 3)
        lay.addLayout(rows)

        scroll_row = QHBoxLayout()
        scroll_row.setSpacing(10)
        self.scroll_switch = PillSwitch()
        self.scroll_switch.setToolTip(
            "Text that doesn't fit scrolls like a ticker instead of ending in …")
        self.scroll_switch.toggled.connect(lambda on: self.app.set_overlay_option("scroll", on))
        scroll_label = QLabel("Scroll long text instead of cutting it with …")
        scroll_label.setObjectName("toggleLabel")
        scroll_row.addWidget(self.scroll_switch)
        scroll_row.addWidget(scroll_label)
        scroll_row.addStretch(1)
        lay.addLayout(scroll_row)

        lay.addStretch(1)
        lay.addWidget(self._hairline())
        footer = QHBoxLayout()
        footer.setSpacing(14)
        footer.addStretch(1)
        box = QFrame()
        box.setObjectName("showOverlayBox")
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        bl = QHBoxLayout(box)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(10)
        show = QLabel("Show overlay")
        show.setObjectName("showOverlayLabel")
        self.overlay_switch = PillSwitch()
        self.overlay_switch.toggled.connect(self.app.set_overlay)
        bl.addWidget(show)
        bl.addWidget(self.overlay_switch)
        footer.addWidget(box)
        lay.addLayout(footer)
        return page

    def _hairline(self):
        line = QFrame()
        line.setObjectName("hair")
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return line

    def refresh_look(self):
        """Put the config values into the controls without re-saving them."""
        conf = self.app.config["overlay"]
        widgets = [self.corner, self.scroll_switch, self.transp_slider, self.transp_spin,
                   self.font_family, *self.style_boxes.values(), *self.look.values()]
        for w in widgets:
            w.blockSignals(True)
        self.corner.setCurrentIndex(max(0, self.corner.findData(conf["corner"])))
        for key, sb in self.look.items():
            sb.setValue(int(conf[key]))
        self.scroll_switch.setChecked(bool(conf["scroll"]))
        t = transparency_percent(conf["opacity"])
        self.transp_slider.setValue(t)
        self.transp_spin.setValue(t)
        family = overlay_family(conf)
        self.font_family.setCurrentFont(QFont(family))
        self._fill_styles(family)
        for w in widgets:
            w.blockSignals(False)
        self.refresh_colors()

    def refresh_colors(self):
        conf = self.app.config["overlay"]
        strong = theme.tokens()["strong"]
        for key, b in self.color_buttons.items():
            b.setStyleSheet(f"background: {conf[key]}; border: 1px solid {strong};"
                            "border-radius: 7px;")

    def _fill_styles(self, family):
        """List the family's styles; keep the saved style, else the nearest one."""
        conf = self.app.config["overlay"]
        styles = sorted(QFontDatabase.styles(family) or ["Regular", "Bold"],
                        key=lambda st: ("Condensed" in st, QFontDatabase.italic(family, st),
                                        QFontDatabase.weight(family, st)))
        for key, box in self.style_boxes.items():
            box.clear()
            box.addItems(styles)
            box.setCurrentText(pick_style(styles, conf[key], bold=(key == "title_style")))

    def _family_changed(self, font):
        conf = self.app.config["overlay"]
        conf["font_family"] = font.family()
        boxes = list(self.style_boxes.values())
        for b in boxes:
            b.blockSignals(True)
        self._fill_styles(font.family())
        for b in boxes:
            b.blockSignals(False)
        for key, box in self.style_boxes.items():
            conf[key] = box.currentText()
        self.app.set_overlay_option("font_family", font.family())   # reload + save

    def _transparency_changed(self, t):
        for w in (self.transp_slider, self.transp_spin):
            if w.value() != t:
                w.blockSignals(True)
                w.setValue(t)
                w.blockSignals(False)
        self.app.set_overlay_option("opacity", opacity_from_percent(t))

    def _pick_color(self, key):
        conf = self.app.config["overlay"]
        c = QColorDialog.getColor(QColor(conf[key]), self, self.color_buttons[key].toolTip())
        if c.isValid():
            self.app.set_overlay_option(key, c.name())
            self.refresh_look()

    def _reset_look(self):
        conf = self.app.config["overlay"]
        for key, value in DEFAULTS["overlay"].items():
            if key not in ("visible", "corner"):
                conf[key] = value
        self.app.set_overlay_option("corner", conf["corner"])   # reload + save
        self.refresh_look()

    # ------------------------------------------------------------------ state
    def update_state(self, s, art=None, tile=""):
        self._state = s
        sounding = s["loaded"] and not s["paused"] and not s["connecting"]
        if sounding != self.sounding:
            # The meter stops on pause, so nothing else would repaint the row
            # that is still showing its last frame of bars.
            self.sounding = sounding
            self.list.viewport().update()
        for i in range(self.list.count()):
            it = self.list.item(i)
            playing = s["loaded"] and i == s["index"]
            if it.data(PLAYING_ROLE) != playing:
                it.setData(PLAYING_ROLE, playing)
        status, name, track = self._hero_lines(s)
        self.hero.status.setText(status)
        self.hero.name.setText(name)
        self.hero.track.setText(track)
        self.hero.art.set_art(art, tile)
        self._sync_meter()
        playing = s["loaded"] and not s["paused"]
        self.hero.play.set_playing(playing)
        self.hero.track_next.setEnabled(s["kind"] == "folder" and s["loaded"])
        if not self.hero.volume.isSliderDown():
            self.hero.volume.blockSignals(True)
            self.hero.volume.setValue(s["volume"])
            self.hero.volume.blockSignals(False)
        self.hero.vol_label.setText(f"{s['volume']}%")

    def _hero_lines(self, s):
        """Status line, source name, track line -- the states update_state had."""
        if not s["count"]:
            return "■ STOPPED", "No sources yet", "Use Add Folder or Add Stream."
        if s["error"]:
            return s["error"].upper(), s["name"], ""
        if not s["loaded"]:
            return "■ STOPPED", s["name"], ""
        if s["paused"]:
            return "❚❚ PAUSED", s["name"], s["track"] or ""
        if s["connecting"]:
            return "… CONNECTING", s["name"], ""
        track = s["track"] or ""
        if s["track_pos"]:
            track += f"   ({s['track_pos']}/{s['track_count']})"
        return ("● PLAYING" if s["kind"] == "folder" else "● LIVE STREAM"), s["name"], track

    def set_overlay_checked(self, on):
        self.overlay_switch.blockSignals(True)
        self.overlay_switch.setChecked(on)
        self.overlay_switch.blockSignals(False)

    def apply_theme(self):
        """After a theme change: the hand-painted parts need a repaint."""
        self.refresh_colors()
        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    def _volume_moved(self, v):
        self.app.player.set_volume(v)

    def _note(self, text):
        """A short message where the list hint sits, then back to the hint."""
        self.hint.setText(text)
        self._note_timer.start()

    # ------------------------------------------------------------------ shortcuts
    def refresh_shortcuts(self):
        sc = self.app.config["shortcuts"]
        for action, btn in self.shortcut_buttons.items():
            btn.setText(pretty(sc.get(action, "")) or "—")
            btn.row.set_capturing(False)
            btn.setDown(False)

    def begin_capture(self, btn):
        if self.app.hotkeys.error:
            return
        self.capturing = btn
        btn.row.set_capturing(True)
        btn.setText("press a key…")
        self.app.hotkeys.begin_capture()

    def on_captured(self, combo):
        btn, self.capturing = self.capturing, None
        if btn is None:
            return
        btn.row.set_capturing(False)
        sc = self.app.config["shortcuts"]
        if combo == "esc":
            pass
        elif combo in ("backspace", "delete"):
            sc[btn.action] = ""
        elif btn.action == "overlay" and not has_modifier(combo):
            QMessageBox.information(
                self, "ShortCutRadio",
                "The overlay shortcut needs Ctrl, Alt or Super (e.g. Ctrl+Alt+R): "
                "it works everywhere, so a single key would fire while you type.")
        else:
            for other, c in sc.items():       # one key, one job
                if c == combo and other != btn.action:
                    sc[other] = ""
            sc[btn.action] = combo
        self.app.shortcuts_changed()
        self.refresh_shortcuts()

    # ------------------------------------------------------------------ sources
    def refresh_sources(self):
        self.list.blockSignals(True)
        self.list.clear()
        for i, src in enumerate(self.app.config["sources"]):
            it = QListWidgetItem(src["name"])
            it.setData(SOURCE_ROLE, src)
            it.setData(INDEX_ROLE, i)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if hasattr(self, "_state"):
            self.app.refresh_state()

    def _rows_moved(self, *_):
        """The rows carry copies, so reorder the real dicts by their index.

        Handing the copies back would replace every source in the config with
        a new object, and the player -- which holds on to the one that is
        playing -- would no longer recognise it and would stop.
        """
        srcs = self.app.config["sources"]
        order = []
        for i in range(self.list.count()):
            n = self.list.item(i).data(INDEX_ROLE)
            if isinstance(n, int) and 0 <= n < len(srcs):
                order.append(srcs[n])
        if len(order) == len(srcs):
            self.app.reorder_sources(order)

    def _selected_rows(self):
        return sorted({self.list.row(it) for it in self.list.selectedItems()})

    def _context_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        row = self.list.row(it)
        srcs = self.app.config["sources"]
        if not 0 <= row < len(srcs):
            return
        src = srcs[row]         # the real source; the item only holds a copy
        m = QMenu(self)
        m.addAction("Play", lambda: self.app.player.play_source(row))
        m.addAction("Rename…", lambda: self.rename(row))
        if is_folder(src):
            sh = m.addAction("Shuffle")
            sh.setCheckable(True)
            sh.setChecked(bool(src.get("shuffle")))
            sh.toggled.connect(lambda on: self.app.set_shuffle(src, on))
        m.addSeparator()
        if not is_folder(src):
            m.addAction("Station page…", lambda: self.set_site(src))
        m.addAction("Set artwork…", lambda: self.set_artwork(src))
        if src.get("art"):
            m.addAction("Clear artwork", lambda: self.clear_artwork(src))
        m.addSeparator()
        m.addAction("Remove", self.remove_selected)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def set_site(self, src):
        """Where the station lives -- its logo is taken from that page.

        Add Stream records this by itself. A station that arrived as a bare
        URL cannot know it: nothing about `lb-hls.cdn.bg` says `binar.bg`,
        and guessing lands on the CDN's own logo.
        """
        current = src.get("site") or site_for_stream(src.get("target") or "")
        site, ok = QInputDialog.getText(
            self, "Station page", f"Where “{src['name']}” lives on the web.\n"
            "Its logo is taken from that page; leave it empty to guess.",
            text=current)
        if not ok:
            return
        src["site"] = clean_site(site)
        self.app.site_changed(src)
        self._note("Looking for the station's logo…")

    def set_artwork(self, src):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Picture for “{src['name']}”", "", ART_EXTS)
        if path:
            src["art"] = path
            self.app.artwork_changed(src)

    def clear_artwork(self, src):
        src.pop("art", None)
        self.app.artwork_changed(src)

    def rename(self, row):
        src = self.app.config["sources"][row]
        name, ok = QInputDialog.getText(self, "Rename source", "Name:", text=src["name"])
        if ok and name.strip():
            self.app.rename_source(src, name.strip())

    def remove_selected(self):
        rows = self._selected_rows()
        if rows:
            self.app.remove_sources(rows)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a music folder")
        if not path:
            return
        n = len(folder_tracks(path))
        if n == 0:
            QMessageBox.warning(self, "ShortCutRadio", f"No audio files found in\n{path}")
            return
        self.app.add_sources([make_folder(path)])
        self._note(f"Added folder with {n} tracks.")

    def add_stream(self):
        dlg = AddStreamDialog(self)
        if dlg.exec() and dlg.selected:
            self.app.add_sources([make_stream(n, u, site) for n, u, site in dlg.selected])

    # ------------------------------------------------------------------ meter
    def _sync_meter(self):
        """The bars cost a repaint every 70 ms, so only run them when they
        are on screen and something is actually playing."""
        self.meter.set_running(self.isVisible() and self.pages[0].isVisible()
                               and self.sounding)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_meter()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_meter()

    # ------------------------------------------------------------------ chrome
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

    def _on_titlebar(self, pos):
        """The hero and the tab strip stand in for the titlebar.

        Dragging and double-clicking are limited to them: empty space further
        down belongs to the page, and grabbing the window from under the
        source list would be a surprise.
        """
        local = self.shell.mapFrom(self, pos)
        return any(w.geometry().contains(local) for w in (self.hero, self.strip))

    def mousePressEvent(self, event):
        """Presses the children did not want: the edges resize, the top drags.

        Only plain widgets let a press through, so the list keeps its
        drag-to-reorder and every button keeps its click.
        """
        pos = event.position().toPoint()
        if event.button() != Qt.MouseButton.LeftButton or self.isMaximized():
            return super().mousePressEvent(event)
        handle = self.windowHandle()
        edges = self._edges(pos)
        if edges and handle is not None:
            handle.startSystemResize(edges)
        elif not edges and not self._on_titlebar(pos):
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
        elif self._on_titlebar(event.position().toPoint()):
            self.showMaximized()

    def changeEvent(self, event):
        # Maximised there is nothing to grip, and the margin would show as a
        # transparent frame around the card.
        if event.type() == event.Type.WindowStateChange and self.layout():
            m = 0 if self.isMaximized() else RESIZE_MARGIN
            self.layout().setContentsMargins(m, m, m, m)
        super().changeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.close_btn.move(self.shell.width() - CLOSE_BTN - CLOSE_INSET, CLOSE_INSET)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.capturing is None:
            self.close()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ window
    def closeEvent(self, event):
        if self.app.tray_available():
            event.ignore()
            self.hide()
            self.app.notify_hidden_once()
        else:
            self.app.quit()
