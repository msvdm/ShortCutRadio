"""Tray icon and the app icon, drawn in code so there is no asset to ship.

The one place a drawn icon is not enough is the desktop's menu, which reads a
file: `install_icon()` writes this same mark there, once.
"""

import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QMenu, QSystemTrayIcon,
                               QVBoxLayout, QWidget, QWidgetAction)

from .widgets import ArtView, ElidedLabel

THEMES = [("light", "Light"), ("dark", "Dark"), ("auto", "Auto")]
ICON_NAME = "shortcutradio"
ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def icon_pixmap(size):
    """The broadcast mark: a dot with two arcs on the accent square."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64.0
    p.setBrush(QColor("#e8541c"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QRectF(14 * s, 38 * s, 12 * s, 12 * s))
    pen = QPen(QColor("#ffffff"), max(1.5, 6 * s))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for r in (18, 32):
        p.drawArc(QRectF((20 - r) * s, (44 - r) * s, 2 * r * s, 2 * r * s), 0, 90 * 16)
    p.end()
    return pm


def make_icon():
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(icon_pixmap(size))
    return icon


def install_icon():
    """Put the same mark where the desktop menu looks for `Icon=shortcutradio`.

    The menu entry reads a file, and this app has none -- it drew its way out
    of shipping one, which left the launcher on the system's generic audio
    note. Written once, skipped when it is already there, and never a reason
    to fail to start: a read-only home just means the old icon stays.
    """
    if not sys.platform.startswith("linux"):
        return          # Windows and macOS take the icon from the executable
    root = os.path.join(os.environ.get("XDG_DATA_HOME")
                        or os.path.expanduser("~/.local/share"), "icons", "hicolor")
    for size in ICON_SIZES:
        path = os.path.join(root, f"{size}x{size}", "apps", ICON_NAME + ".png")
        if os.path.exists(path):
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            icon_pixmap(size).save(path, "PNG")
        except OSError as e:
            print(f"[icon] could not install {path}: {e}", flush=True)
            return


class NowPlayingHeader(QWidget):
    """The non-interactive first row of the menu: art, station, track."""

    def __init__(self):
        super().__init__()
        self.setObjectName("trayHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(9)
        # The menu is drawn dark by the desktop as often as not, so this tile
        # does not follow the theme.
        self.art = ArtView(26, 6, dark=True)
        lay.addWidget(self.art)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name = ElidedLabel("ShortCutRadio")
        self.name.setObjectName("trayName")
        self.track = ElidedLabel("")
        self.track.setObjectName("trayTrack")
        col.addWidget(self.name)
        col.addWidget(self.track)
        lay.addLayout(col, 1)
        self.setFixedWidth(210)


class Tray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__(app.icon)
        self.app = app
        self.setToolTip("ShortCutRadio")
        menu = QMenu()

        self.header = NowPlayingHeader()
        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(self.header)
        header_action.setEnabled(False)
        menu.addAction(header_action)
        menu.addSeparator()

        self.play_action = menu.addAction("Play", app.player.toggle)
        menu.addAction("Next source", app.player.next_source)
        menu.addAction("Previous source", app.player.prev_source)
        self.track_action = menu.addAction("Next track", app.player.next_track)
        menu.addSeparator()

        self.overlay_action = menu.addAction("Show overlay")
        self.overlay_action.setCheckable(True)
        self.overlay_action.toggled.connect(app.set_overlay)

        theme_menu = menu.addMenu("Theme")
        group = QActionGroup(theme_menu)
        group.setExclusive(True)
        self.theme_actions = {}
        for key, label in THEMES:
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, k=key: app.set_theme(k))
            group.addAction(act)
            self.theme_actions[key] = act

        menu.addAction("Open ShortCutRadio", app.show_window)
        menu.addAction("Quit", app.quit)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        self.set_theme_checked(app.config["theme"])

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.app.toggle_window()

    def set_overlay_checked(self, on):
        self.overlay_action.blockSignals(True)
        self.overlay_action.setChecked(on)
        self.overlay_action.blockSignals(False)

    def set_theme_checked(self, name):
        act = self.theme_actions.get(name)
        if act:
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)

    def update_state(self, s, art=None, tile=""):
        playing = s["loaded"] and not s["paused"]
        self.play_action.setText("Pause" if playing else "Play")
        self.track_action.setEnabled(s["kind"] == "folder" and s["loaded"])
        if not s["count"]:
            tip = "ShortCutRadio — no sources"
        elif not s["loaded"]:
            tip = f"ShortCutRadio — stopped ({s['name']})"
        else:
            tip = f"ShortCutRadio — {s['name']}" + (f"\n{s['track']}" if s["track"] else "")
            if s["paused"]:
                tip += "\n(paused)"
        self.setToolTip(tip)
        self.header.name.setText(s["name"] or "ShortCutRadio")
        self.header.track.setText(s["track"] if s["loaded"] else "")
        self.header.art.set_art(art, tile)
