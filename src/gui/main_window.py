"""The setup window: shortcuts on the left, the source list on the right.

Closing it only hides it; ShortCutRadio keeps playing from the tray.
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QFileDialog, QFontComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSlider, QSpinBox, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from ..core.config import DEFAULTS, opacity_from_percent, transparency_percent
from ..core.hotkeys import has_modifier, pretty
from ..core.sources import describe, folder_tracks, is_folder, make_folder, make_stream
from .add_stream import AddStreamDialog
from .overlay import overlay_family, pick_style

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
SOURCE_ROLE = Qt.ItemDataRole.UserRole


class SourceDelegate(QStyledItemDelegate):
    """Two lines per source: name (bold when playing), then host or folder."""

    def sizeHint(self, option, index):
        fm = option.fontMetrics
        return QSize(option.rect.width(), fm.height() * 2 + 12)

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QStyle()
        text = option.text
        option.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        src = index.data(SOURCE_ROLE) or {}
        playing = index.data(Qt.ItemDataRole.UserRole + 1)
        r = option.rect.adjusted(8, 5, -8, -5)
        icon_w = 22
        icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon if is_folder(src)
                                  else QStyle.StandardPixmap.SP_MediaVolume)
        icon.paint(painter, QRect(r.left(), r.top() + 2, 16, 16))

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        pal = option.palette
        fg = pal.highlightedText().color() if selected else pal.text().color()
        dim = fg if selected else pal.placeholderText().color()

        f = QFont(option.font)
        f.setBold(bool(playing))
        painter.save()
        painter.setFont(f)
        painter.setPen(fg)
        fm = painter.fontMetrics()
        name = ("▶ " if playing else "") + text
        painter.drawText(r.left() + icon_w, r.top() + fm.ascent(),
                         fm.elidedText(name, Qt.TextElideMode.ElideRight, r.width() - icon_w))
        painter.setFont(option.font)
        painter.setPen(dim)
        fm = painter.fontMetrics()
        painter.drawText(r.left() + icon_w, r.top() + fm.height() + 2 + fm.ascent(),
                         fm.elidedText(describe(src), Qt.TextElideMode.ElideMiddle, r.width() - icon_w))
        painter.restore()


class ShortcutButton(QPushButton):
    """Shows a combo; click, then press keys to record a new one.

    Recording goes through the global listener (so what is recorded is exactly
    what will match), but Qt still delivers the same key to this button -- it
    must be swallowed, or Space/Enter would re-click it.
    """

    def __init__(self, action, window):
        super().__init__()
        self.action = action
        self.window_ = window
        self.setMinimumWidth(76)
        self.clicked.connect(lambda: window.begin_capture(self))

    def keyPressEvent(self, event):
        if self.window_.capturing is self:
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.capturing = None
        self.setWindowTitle("ShortCutRadio")
        self.setWindowIcon(app.icon)
        self.resize(760, 410)

        # ---------------------------------------------------------- left
        left = QFrame()
        left.setFixedWidth(380)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 12, 0)

        head_row = QHBoxLayout()
        head = QLabel("Overlay Controls")
        head.setStyleSheet("font-size: 15px; font-weight: 600;")
        head_row.addWidget(head)
        head_row.addStretch(1)
        reset = QPushButton("Reset to Default")
        reset.setToolTip("Restore the default size, margins, font, transparency and colors")
        reset.clicked.connect(self._reset_look)
        head_row.addWidget(reset)
        ll.addLayout(head_row)

        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        self.shortcut_buttons = {}
        grid.setColumnMinimumWidth(2, 8)        # gap between the two pairs
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        for i, (action, label) in enumerate(SHORTCUT_ROWS):
            row, col = divmod(i, 2)             # two pairs per row
            col *= 3
            grid.addWidget(QLabel(label), row, col)
            btn = ShortcutButton(action, self)
            btn.setToolTip(CAPTURE_TIP)
            self.shortcut_buttons[action] = btn
            grid.addWidget(btn, row, col + 1)
        ll.addLayout(grid)

        if app.hotkeys.error:
            warn = QLabel(f"Global shortcuts are unavailable: {app.hotkeys.error}")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #c0392b;")
            ll.addWidget(warn)

        ll.addSpacing(4)
        ov_row = QHBoxLayout()
        self.overlay_check = QCheckBox("Show overlay")
        self.overlay_check.toggled.connect(app.set_overlay)
        self.corner = QComboBox()
        for key, label in CORNERS:
            self.corner.addItem(label, key)
        self.corner.currentIndexChanged.connect(
            lambda _: app.set_overlay_option("corner", self.corner.currentData()))
        ov_row.addWidget(self.overlay_check)
        ov_row.addStretch(1)
        ov_row.addWidget(self.corner)
        ll.addLayout(ov_row)
        ll.addLayout(self._build_look())
        self.refresh_look()

        ll.addStretch(1)
        add_row = QHBoxLayout()
        add_folder = QPushButton("Add Folder")
        add_folder.clicked.connect(self.add_folder)
        add_stream = QPushButton("Add Stream")
        add_stream.clicked.connect(self.add_stream)
        for b in (add_folder, add_stream):
            b.setMinimumHeight(34)
            add_row.addWidget(b)

        # ---------------------------------------------------------- right
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        rh = QHBoxLayout()
        src_head = QLabel("Sources")
        src_head.setStyleSheet("font-size: 15px; font-weight: 600;")
        rh.addWidget(src_head)
        rh.addStretch(1)
        tip = QLabel("drag to reorder · double-click to play\nright-click for more")
        tip.setStyleSheet("color: palette(placeholder-text);")
        tip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rh.addWidget(tip)
        rl.addLayout(rh)

        self.list = QListWidget()
        self.list.setItemDelegate(SourceDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemDoubleClicked.connect(lambda it: app.player.play_source(self.list.row(it)))
        self.list.model().rowsMoved.connect(self._rows_moved)
        rl.addWidget(self.list, 1)
        rl.addLayout(add_row)

        delete = QAction(self.list)
        delete.setShortcut(QKeySequence.StandardKey.Delete)
        delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        delete.triggered.connect(self.remove_selected)
        self.list.addAction(delete)

        # Now playing + transport, at the bottom of the left column
        self.now = QLabel("Stopped")
        self.now.setWordWrap(True)
        self.now.setStyleSheet("font-weight: 600;")
        ll.addWidget(self.now)
        tr = QHBoxLayout()
        st = self.style()
        self.b_prev = self._tool(st.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward),
                                 "Previous source", app.player.prev_source)
        self.b_play = self._tool(st.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
                                 "Play / Pause", app.player.toggle)
        self.b_next = self._tool(st.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward),
                                 "Next source", app.player.next_source)
        self.b_track = self._tool(st.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward),
                                  "Next track (folders)", app.player.next_track)
        for b in (self.b_prev, self.b_play, self.b_next, self.b_track):
            tr.addWidget(b)
        tr.addSpacing(8)
        speaker = QLabel()
        speaker.setPixmap(st.standardIcon(QStyle.StandardPixmap.SP_MediaVolume).pixmap(16, 16))
        speaker.setToolTip("Volume")
        tr.addWidget(speaker)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setToolTip("Volume")
        self.volume.setRange(0, 130)
        self.volume.valueChanged.connect(self._volume_moved)
        tr.addWidget(self.volume, 1)
        self.vol_label = QLabel("")
        self.vol_label.setMinimumWidth(40)
        tr.addWidget(self.vol_label)
        ll.addLayout(tr)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(left)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)
        lay.addWidget(right, 1)

        self.refresh_shortcuts()
        self.refresh_sources()

    def _tool(self, icon, tip, fn):
        b = QPushButton(icon, "")
        b.setToolTip(tip)
        b.setFixedWidth(34)
        b.clicked.connect(fn)
        return b

    # ------------------------------------------------------------------ overlay look
    def _build_look(self):
        """Size, margins, scrolling, font, transparency and colors of the card.

        Columns: label | field | field | number box | color box, so the number
        and color boxes line up down the block.
        """
        g = QGridLayout()
        g.setVerticalSpacing(4)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        self.look = {}
        self.color_buttons = {}

        def color(key, tip):
            b = QPushButton()
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False: self._pick_color(key))
            self.color_buttons[key] = b
            return b

        def spin(key, lo, hi, suffix, tip):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setSuffix(suffix)
            sb.setToolTip(tip)
            sb.valueChanged.connect(lambda v: self.app.set_overlay_option(key, v))
            self.look[key] = sb
            return sb

        g.addWidget(QLabel("Width"), 0, 0)
        g.addWidget(spin("width", 200, 1200, " px", "Card width"), 0, 1)
        g.addWidget(QLabel("Margin X"), 0, 2)
        g.addWidget(spin("margin_x", 0, 500, " px", "Distance from the left/right screen edge"), 0, 3)
        self.scroll_check = QCheckBox("Scroll long text")
        self.scroll_check.setToolTip("Text that doesn't fit scrolls like a ticker instead of ending in …")
        self.scroll_check.toggled.connect(lambda on: self.app.set_overlay_option("scroll", on))
        g.addWidget(self.scroll_check, 1, 0, 1, 2)
        g.addWidget(QLabel("Margin Y"), 1, 2)
        g.addWidget(spin("margin_y", 0, 500, " px", "Distance from the top/bottom screen edge"), 1, 3)

        # Font: family for both lines, then style and size per line.
        g.addWidget(QLabel("Font"), 2, 0)
        self.font_family = QFontComboBox()
        self.font_family.setToolTip("Font of the overlay text")
        self.font_family.currentFontChanged.connect(self._family_changed)
        g.addWidget(self.font_family, 2, 1, 1, 4)
        self.style_boxes = {}
        for row, (label, style_key, size_key, color_key, lo, hi, tip) in enumerate(
                [("Row 1", "title_style", "title_size", "title_color", 8, 48, "Row 1 (station name)"),
                 ("Row 2", "text_style", "track_size", "text_color", 6, 36, "Row 2 (track / status)")],
                start=3):
            g.addWidget(QLabel(label), row, 0)
            box = QComboBox()
            box.setToolTip(f"{tip} style")
            box.currentTextChanged.connect(
                lambda t, k=style_key: t and self.app.set_overlay_option(k, t))
            self.style_boxes[style_key] = box
            g.addWidget(box, row, 1, 1, 2)
            g.addWidget(spin(size_key, lo, hi, " pt", f"{tip} size"), row, 3)
            g.addWidget(color(color_key, f"{tip} color"), row, 4)

        g.addWidget(QLabel("Transparency"), 5, 0)
        self.transp_slider = QSlider(Qt.Orientation.Horizontal)
        self.transp_spin = QSpinBox()
        self.transp_spin.setSuffix(" %")
        for w in (self.transp_slider, self.transp_spin):
            w.setRange(0, 100)
            w.setToolTip("Background transparency (the text stays solid)")
            w.valueChanged.connect(self._transparency_changed)
        g.addWidget(self.transp_slider, 5, 1, 1, 2)
        g.addWidget(self.transp_spin, 5, 3)
        g.addWidget(color("bg_color", "Background color"), 5, 4)

        # Color boxes: square, as tall as the number boxes next to them.
        h = self.transp_spin.sizeHint().height()
        for b in self.color_buttons.values():
            b.setFixedSize(h + 6, h)
        return g

    def refresh_look(self):
        """Put the config values into the controls without re-saving them."""
        conf = self.app.config["overlay"]
        widgets = [self.corner, self.scroll_check, self.transp_slider, self.transp_spin,
                   self.font_family, *self.style_boxes.values(), *self.look.values()]
        for w in widgets:
            w.blockSignals(True)
        self.corner.setCurrentIndex(max(0, self.corner.findData(conf["corner"])))
        for key, sb in self.look.items():
            sb.setValue(int(conf[key]))
        self.scroll_check.setChecked(bool(conf["scroll"]))
        t = transparency_percent(conf["opacity"])
        self.transp_slider.setValue(t)
        self.transp_spin.setValue(t)
        family = overlay_family(conf)
        self.font_family.setCurrentFont(QFont(family))
        self._fill_styles(family)
        for w in widgets:
            w.blockSignals(False)
        for key, b in self.color_buttons.items():
            b.setStyleSheet(f"background: {conf[key]}; border: 1px solid #888;")

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
    def update_state(self, s):
        self._state = s
        for i in range(self.list.count()):
            it = self.list.item(i)
            playing = s["loaded"] and i == s["index"]
            if it.data(Qt.ItemDataRole.UserRole + 1) != playing:
                it.setData(Qt.ItemDataRole.UserRole + 1, playing)
        if not s["count"]:
            text = "No sources yet — use Add Folder or Add Stream."
        elif s["error"]:
            text = f"{s['name']} — {s['error']}"
        elif not s["loaded"]:
            text = f"Stopped · next up: {s['name']}"
        elif s["paused"]:
            text = f"Paused · {s['name']}"
        elif s["connecting"]:
            text = f"{s['name']} — connecting…"
        else:
            text = s["name"] + (f" — {s['track']}" if s["track"] else "")
            if s["track_pos"]:
                text += f"   ({s['track_pos']}/{s['track_count']})"
        self.now.setText(text)
        playing = s["loaded"] and not s["paused"]
        self.b_play.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay))
        self.b_track.setEnabled(s["kind"] == "folder" and s["loaded"])
        if not self.volume.isSliderDown():
            self.volume.blockSignals(True)
            self.volume.setValue(s["volume"])
            self.volume.blockSignals(False)
        self.vol_label.setText(f"{s['volume']}%")

    def set_overlay_checked(self, on):
        self.overlay_check.blockSignals(True)
        self.overlay_check.setChecked(on)
        self.overlay_check.blockSignals(False)

    def _volume_moved(self, v):
        self.app.player.set_volume(v)

    # ------------------------------------------------------------------ shortcuts
    def refresh_shortcuts(self):
        sc = self.app.config["shortcuts"]
        for action, btn in self.shortcut_buttons.items():
            btn.setText(pretty(sc.get(action, "")))
            btn.setDown(False)

    def begin_capture(self, btn):
        if self.app.hotkeys.error:
            return
        self.capturing = btn
        btn.setText("Press a key…")
        self.app.hotkeys.begin_capture()

    def on_captured(self, combo):
        btn, self.capturing = self.capturing, None
        if btn is None:
            return
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
        for src in self.app.config["sources"]:
            it = QListWidgetItem(src["name"])
            it.setData(SOURCE_ROLE, src)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if hasattr(self, "_state"):
            self.update_state(self.app.player.snapshot())

    def _rows_moved(self, *_):
        order = [self.list.item(i).data(SOURCE_ROLE) for i in range(self.list.count())]
        self.app.reorder_sources(order)

    def _selected_rows(self):
        return sorted({self.list.row(it) for it in self.list.selectedItems()})

    def _context_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        row = self.list.row(it)
        src = it.data(SOURCE_ROLE)
        m = QMenu(self)
        m.addAction("Play", lambda: self.app.player.play_source(row))
        m.addAction("Rename…", lambda: self.rename(row))
        if is_folder(src):
            sh = m.addAction("Shuffle")
            sh.setCheckable(True)
            sh.setChecked(bool(src.get("shuffle")))
            sh.toggled.connect(lambda on: self.app.set_shuffle(src, on))
        m.addSeparator()
        m.addAction("Remove", self.remove_selected)
        m.exec(self.list.viewport().mapToGlobal(pos))

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
        self.now.setText(f"Added folder with {n} tracks.")

    def add_stream(self):
        dlg = AddStreamDialog(self)
        if dlg.exec() and dlg.selected:
            self.app.add_sources([make_stream(n, u) for n, u in dlg.selected])

    # ------------------------------------------------------------------ window
    def closeEvent(self, event):
        if self.app.tray_available():
            event.ignore()
            self.hide()
            self.app.notify_hidden_once()
        else:
            self.app.quit()
