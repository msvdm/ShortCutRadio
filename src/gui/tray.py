"""Tray icon and the app icon, drawn in code so there is no asset to ship."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QMenu, QSystemTrayIcon,
                               QVBoxLayout, QWidget, QWidgetAction)

from .widgets import ArtPlaceholder, ElidedLabel

THEMES = [("light", "Light"), ("dark", "Dark"), ("auto", "Auto")]


def make_icon():
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64, 128):
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
        icon.addPixmap(pm)
    return icon


class NowPlayingHeader(QWidget):
    """The non-interactive first row of the menu: art, station, track."""

    def __init__(self):
        super().__init__()
        self.setObjectName("trayHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(9)
        lay.addWidget(ArtPlaceholder(26, 6, 4))
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

    def update_state(self, s):
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
