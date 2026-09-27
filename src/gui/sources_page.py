"""The Sources tab: the list, with Add Folder / Add Stream under it.

Double-click plays, drag reorders, right-click edits a source. The row that is
playing carries an accent bar and, while something is audible, a level meter.
"""

from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QKeySequence, QPainter,
                           QPainterPath)
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from ..core.artfetch import clean_site, site_for_stream
from ..core.sources import describe, folder_tracks, is_folder, make_folder, make_stream
from . import theme
from .add_stream import AddStreamDialog
from .widgets import Meter, draw_level_bars, level_bars_width

LIST_HINT = "drag to reorder · double-click to play"
NOTE_MS = 4000
# Qt copies whatever is put in an item, so SOURCE_ROLE is a *copy* of the
# source -- fine for drawing the row, useless to write to. Anything that edits
# a source goes through INDEX_ROLE to the real dict in the config.
SOURCE_ROLE = Qt.ItemDataRole.UserRole
INDEX_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_BARS, ROW_BAR_LOW, ROW_BAR_HIGH = 4, 5, 17
ART_EXTS = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg)"


class SourceDelegate(QStyledItemDelegate):
    """One source per row: an accent bar when it plays, name, then describe()."""

    PAD_X, PAD_Y, GAP, BAR_W, BAR_H = 12, 11, 12, 3, 26

    def __init__(self, page):
        super().__init__(page.list)
        self.page = page            # which row plays, and the meter it draws

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
        playing = index.row() == self.page.playing_row
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
        meter = self.page.meter
        if playing and meter.running:
            draw_level_bars(painter, right, r.center().y() + ROW_BAR_HIGH / 2,
                            meter.values, t["accent"], 3, 3, ROW_BAR_LOW, ROW_BAR_HIGH)
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


class SourcesPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.playing_row = -1       # the row the player has loaded, or -1
        self._audible = False
        # The bars cost a repaint every 70 ms, so they only run while this
        # page is on screen and something is actually playing.
        self.meter = Meter(ROW_BARS, self)

        # Sits at the right end of the tab strip, which the window owns.
        self.strip_widget = self.hint = QLabel(LIST_HINT)
        self.hint.setObjectName("tabHint")
        self._note_timer = QTimer(self, singleShot=True, interval=NOTE_MS)
        self._note_timer.timeout.connect(lambda: self.hint.setText(LIST_HINT))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(8)

        self.list = QListWidget()
        self.list.setObjectName("srcList")
        self.list.setItemDelegate(SourceDelegate(self))
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
        self.meter.tick.connect(self.list.viewport().update)

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
        self.refresh()

    # ------------------------------------------------------------------ state
    def set_now_playing(self, s):
        row = s.index if s.loaded else -1
        if row != self.playing_row:
            self.playing_row = row
            self.list.viewport().update()
        self._audible = s.audible
        self._sync_meter()

    def _sync_meter(self):
        self.meter.set_running(self.isVisible() and self._audible)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_meter()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_meter()

    def refresh(self):
        with QSignalBlocker(self.list):
            self.list.clear()
            for i, src in enumerate(self.app.config["sources"]):
                it = QListWidgetItem(src["name"])
                it.setData(SOURCE_ROLE, src)
                it.setData(INDEX_ROLE, i)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                self.list.addItem(it)

    def _note(self, text):
        """A short message where the list hint sits, then back to the hint."""
        self.hint.setText(text)
        self._note_timer.start()

    # ------------------------------------------------------------------ edits
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

    def _context_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        row = self.list.row(it)
        srcs = self.app.config["sources"]
        if not 0 <= row < len(srcs):
            return
        src = srcs[row]         # the real source; the item only holds a copy
        edit = self.app.edit_source
        m = QMenu(self)
        m.addAction("Play", lambda: self.app.player.play_source(row))
        m.addAction("Rename…", lambda: self.rename(src))
        if is_folder(src):
            sh = m.addAction("Shuffle")
            sh.setCheckable(True)
            sh.setChecked(bool(src.get("shuffle")))
            sh.toggled.connect(lambda on: edit(src, shuffle=on))
        m.addSeparator()
        if not is_folder(src):
            m.addAction("Station page…", lambda: self.set_site(src))
        m.addAction("Set artwork…", lambda: self.set_artwork(src))
        if src.get("art"):
            m.addAction("Clear artwork", lambda: edit(src, art=None))
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
        self.app.edit_source(src, site=clean_site(site))
        self._note("Looking for the station's logo…")

    def set_artwork(self, src):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Picture for “{src['name']}”", "", ART_EXTS)
        if path:
            self.app.edit_source(src, art=path)

    def rename(self, src):
        name, ok = QInputDialog.getText(self, "Rename source", "Name:", text=src["name"])
        if ok and name.strip():
            self.app.edit_source(src, name=name.strip())

    def remove_selected(self):
        rows = sorted({self.list.row(it) for it in self.list.selectedItems()})
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
