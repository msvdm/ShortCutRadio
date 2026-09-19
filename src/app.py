"""Wires the pieces together: config, player, hotkeys, overlay, window, tray."""

import getpass
import locale
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .core.config import Config
from .core.hotkeys import Hotkeys, pretty
from .core.player import Player
from .gui.main_window import MainWindow
from .gui.overlay import Overlay
from .gui.tray import Tray, make_icon

INSTANCE_NAME = f"shortcutradio-{getpass.getuser()}"
VOLUME_STEP = 5
SAVE_DELAY_MS = 1500


class App:
    def __init__(self, qapp, argv):
        self.qapp = qapp
        self.icon = make_icon()
        qapp.setWindowIcon(self.icon)
        self.config = Config()
        cfg = self.config

        self.player = Player(cfg["sources"], cfg["current"], cfg["volume"])
        self.hotkeys = Hotkeys(cfg["shortcuts"])
        self.overlay = Overlay(cfg["overlay"], pretty(cfg["shortcuts"]["play_pause"]))
        self.window = MainWindow(self)
        self.tray = Tray(self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        self._told_hidden = False

        self._save_timer = QTimer(singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save)

        self.player.changed.connect(self._on_state)
        self.hotkeys.triggered.connect(self._on_action)
        self.hotkeys.captured.connect(self.window.on_captured)

        self.actions = {
            "overlay": lambda: self.set_overlay(not cfg["overlay"]["visible"]),
            "play_pause": self.player.toggle,
            "source_next": self.player.next_source,
            "source_prev": self.player.prev_source,
            "track_next": self.player.next_track,
            "track_prev": self.player.prev_track,
            "vol_up": lambda: self.player.change_volume(VOLUME_STEP),
            "vol_down": lambda: self.player.change_volume(-VOLUME_STEP),
        }

        self.hotkeys.start()
        if self.tray:
            self.tray.show()
        self.set_overlay(cfg["overlay"]["visible"])
        self._on_state(self.player.snapshot())
        if "--hidden" not in argv:
            self.show_window()
        if cfg.first_run:
            self.save()

    # ------------------------------------------------------------------ events
    def _on_state(self, s):
        self.overlay.set_state(s)
        self.window.update_state(s)
        if self.tray:
            self.tray.update_state(s)
        cfg = self.config
        if cfg["volume"] != s["volume"] or cfg["current"] != s["index"]:
            cfg["volume"], cfg["current"] = s["volume"], s["index"]
            self._save_timer.start()

    def _on_action(self, action):
        fn = self.actions.get(action)
        if fn:
            fn()

    # ------------------------------------------------------------------ overlay
    def set_overlay(self, on):
        on = bool(on)
        self.config["overlay"]["visible"] = on
        self.hotkeys.single_keys_live = on
        self.overlay.set_on(on)
        self.window.set_overlay_checked(on)
        if self.tray:
            self.tray.set_overlay_checked(on)
        self._save_timer.start()

    def set_overlay_option(self, key, value):
        self.config["overlay"][key] = value
        self.overlay.reload_conf()
        self._save_timer.start()

    # ------------------------------------------------------------------ edits
    def shortcuts_changed(self):
        self.hotkeys.set_bindings(self.config["shortcuts"])
        self.overlay.hint_key = pretty(self.config["shortcuts"]["play_pause"])
        self.overlay.set_state(self.player.snapshot())
        self.save()

    def _sources_edited(self, keep):
        self.player.sources_changed(keep)
        self.window.refresh_sources()
        self.save()

    def add_sources(self, new):
        keep = self.player.current_source()
        self.config["sources"].extend(new)
        self._sources_edited(keep)

    def remove_sources(self, rows):
        keep = self.player.current_source()
        srcs = self.config["sources"]
        for r in sorted(rows, reverse=True):
            del srcs[r]
        self._sources_edited(keep)

    def reorder_sources(self, order):
        keep = self.player.current_source()
        self.config["sources"][:] = order
        self._sources_edited(keep)

    def rename_source(self, src, name):
        src["name"] = name
        self._sources_edited(self.player.current_source())

    def set_shuffle(self, src, on):
        src["shuffle"] = on
        self._sources_edited(self.player.current_source())

    # ------------------------------------------------------------------ window
    def tray_available(self):
        return self.tray is not None

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def toggle_window(self):
        if self.window.isVisible() and self.window.isActiveWindow():
            self.window.hide()
        else:
            self.show_window()

    def notify_hidden_once(self):
        if self.tray and not self._told_hidden:
            self._told_hidden = True
            self.tray.showMessage("ShortCutRadio", "Still running in the tray.",
                                  self.icon, 3000)

    def save(self):
        try:
            self.config.save()
        except OSError as e:
            print(f"[config] could not save: {e}", flush=True)

    def quit(self):
        self._save_timer.stop()
        self.save()
        if self.tray:
            self.tray.hide()
        self.overlay.hide()
        self.player.shutdown()
        self.hotkeys.stop()
        self.qapp.quit()


def _already_running():
    """Hand over to a running instance (it shows its window) and say so."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if sock.waitForConnected(500):
        sock.write(b"show\n")
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True
    return False


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    qapp = QApplication(argv)
    qapp.setApplicationName("ShortCutRadio")
    qapp.setDesktopFileName("shortcutradio")
    qapp.setQuitOnLastWindowClosed(False)

    if _already_running():
        print("ShortCutRadio is already running -- showing its window.", flush=True)
        return 0

    # libmpv refuses to start under a non-C numeric locale, and Qt has just
    # set the locale from the environment.
    locale.setlocale(locale.LC_NUMERIC, "C")

    QLocalServer.removeServer(INSTANCE_NAME)     # stale socket after a crash
    server = QLocalServer()
    server.listen(INSTANCE_NAME)

    app = App(qapp, argv)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), app.show_window()))

    server.newConnection.connect(on_connection)

    # Ctrl-C in a terminal: Python only sees signals when it gets to run, so
    # tick the interpreter periodically.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    tick = QTimer(interval=300)
    tick.timeout.connect(lambda: None)
    tick.start()

    rc = qapp.exec()
    # Everything worth keeping is saved by now. Leave without waiting on the
    # native threads (pynput's XRECORD reader, libmpv, Qt's D-Bus): a stop
    # that never returns there once left a quit ShortCutRadio running forever.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
