"""Wires the pieces together: config, player, hotkeys, overlay, window, tray."""

import getpass
import hashlib
import locale
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .core.artfetch import clean_site
from .core.config import Config, data_dir, normalize_theme
from .core.hotkeys import Hotkeys, pretty
from .core.mpris import Mpris
from .core.player import Player
from .core.sources import art_label
from .gui import theme
from .gui.artwork import Artwork, cache_dir
from .gui.main_window import MainWindow
from .gui.overlay import Overlay
from .gui.tray import Tray, install_icon, make_icon

# One instance per config, not per machine: a test run on a scratch config
# (XDG_CONFIG_HOME=..., see CLAUDE.md) must not hand its window to the real
# ShortCutRadio and quit, and two portable copies are two apps.
INSTANCE_NAME = (f"shortcutradio-{getpass.getuser()}-"
                 f"{hashlib.sha1(data_dir().encode('utf-8')).hexdigest()[:8]}")
VOLUME_STEP = 5
SAVE_DELAY_MS = 1500


class App:
    def __init__(self, qapp, argv):
        self.qapp = qapp
        self.icon = make_icon()
        qapp.setWindowIcon(self.icon)
        install_icon()          # so the desktop's menu shows it too
        self.config = Config()
        cfg = self.config
        self.window = self.tray = None
        self.apply_theme()

        self.artwork = Artwork()
        self.player = Player(cfg["sources"], cfg["current"], cfg["volume"])
        self.mpris = Mpris(cache_dir())
        self.hotkeys = Hotkeys(cfg["shortcuts"], cfg["keysyms"],
                               media_via_desktop=self.mpris.available)
        self.overlay = Overlay(cfg["overlay"], pretty(cfg["shortcuts"]["play_pause"]))
        self.window = MainWindow(self)
        self.tray = Tray(self) if QSystemTrayIcon.isSystemTrayAvailable() else None

        self._save_timer = QTimer(singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save)

        self.player.changed.connect(self._on_state)
        self.artwork.changed.connect(lambda: self.refresh_state())
        self.hotkeys.triggered.connect(self._on_action)
        self.hotkeys.captured.connect(self.window.shortcuts.on_captured)
        self.hotkeys.ungrabbed.connect(self.window.shortcuts.on_ungrabbed)
        self.mpris.pressed.connect(self.hotkeys.press_media)
        self.mpris.raise_requested.connect(self.show_window)

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

        # Follow the desktop while the theme is "auto".
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._scheme_changed)

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
        self._push(s)
        self._learn_site(s)
        cfg = self.config
        if cfg["volume"] != s.volume or cfg["current"] != s.index:
            cfg["volume"], cfg["current"] = s.volume, s.index
            self._save_timer.start()

    def _push(self, s):
        """One state, one artwork lookup, three places that show it.

        `tile` is what the generated art says when there is no picture. It
        comes from the source's address, so renaming a station leaves its
        picture alone.
        """
        src = self.player.current_source()
        art = self.artwork.for_source(src, s.path or "")
        tile = art_label(src)
        self.overlay.set_now_playing(s, art, tile)
        self.mpris.set_state(s, art)
        self.window.set_now_playing(s, art, tile)
        if self.tray:
            self.tray.set_now_playing(s, art, tile)

    def refresh_state(self):
        self._push(self.player.snapshot())

    def _learn_site(self, s):
        """Most Icecast/SHOUTcast mounts announce their home page. That is
        where the logo lives, and a station added as a bare stream URL has
        no other way of telling us."""
        src = self.player.current_source()
        if not src or src.get("kind") != "stream" or src.get("site"):
            return
        site = clean_site(s.icy_url)
        if site:
            src["site"] = site
            self.artwork.forget(src)        # drops the "no logo" marker
            self._save_timer.start()

    def _on_action(self, action):
        fn = self.actions.get(action)
        if fn:
            fn()

    # ------------------------------------------------------------------ theme
    def apply_theme(self):
        """Re-skin everything. The overlay is left out on purpose: it renders
        over games, so it stays dark and follows the overlay settings only."""
        theme.set_current(theme.resolve(self.config["theme"]))
        self.qapp.setStyleSheet(theme.stylesheet())
        if self.window:
            self.window.apply_theme()
        if self.tray:
            self.tray.apply_theme()

    def set_theme(self, name):
        self.config["theme"] = normalize_theme(name)
        self.apply_theme()
        if self.tray:
            self.tray.set_theme_checked(self.config["theme"])
        self._save_timer.start()

    def _scheme_changed(self, *_):
        if self.config["theme"] == "auto":
            self.apply_theme()

    # ------------------------------------------------------------------ overlay
    def set_overlay(self, on):
        on = bool(on)
        self.config["overlay"]["visible"] = on
        self.hotkeys.live = on
        self._sync_media()
        self.overlay.set_on(on)
        self.window.look.set_overlay_checked(on)
        if self.tray:
            self.tray.set_overlay_checked(on)
        self._save_timer.start()

    def _sync_media(self):
        """Be the desktop's media player only while the overlay is on and a
        media key is bound; otherwise those keys belong to other players."""
        keys = self.hotkeys.media_keys()
        self.mpris.set_keys(keys)
        self.mpris.set_active(self.config["overlay"]["visible"] and bool(keys))

    def update_overlay(self, **changes):
        """Change any of the card's settings in one go: reload, then save."""
        self.config["overlay"].update(changes)
        self.overlay.reload_conf()
        self._save_timer.start()

    # ------------------------------------------------------------------ edits
    def shortcuts_changed(self):
        self.hotkeys.set_bindings(self.config["shortcuts"])
        self._sync_media()
        self.overlay.hint_key = pretty(self.config["shortcuts"]["play_pause"])
        self.refresh_state()
        self.save()

    def _sources_edited(self):
        # The rows first: the player's state, emitted next, is what marks
        # the one that is playing.
        self.window.sources.refresh()
        self.player.sources_changed()
        self.save()

    def add_sources(self, new):
        self.config["sources"].extend(new)
        self._sources_edited()

    def remove_sources(self, rows):
        srcs = self.config["sources"]
        for r in sorted(rows, reverse=True):
            del srcs[r]
        self._sources_edited()

    def reorder_sources(self, order):
        self.config["sources"][:] = order
        self._sources_edited()

    def edit_source(self, src, **changes):
        """Change one source's settings; a value of None removes the setting.

        A new station page means the logo on disk came from the wrong one,
        so it goes; a picture set or cleared only needs the cache dropped.
        """
        for key, value in changes.items():
            if value is None:
                src.pop(key, None)
            else:
                src[key] = value
        if "site" in changes:
            self.artwork.forget(src, logo=True)
        elif "art" in changes:
            self.artwork.forget(src)
        self._sources_edited()

    # ------------------------------------------------------------------ window
    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def toggle_window(self):
        if self.window.isVisible() and self.window.isActiveWindow():
            self.window.hide()
        else:
            self.show_window()

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
    # The skin assumes Fusion's metrics; the platform style would shift them.
    qapp.setStyle("Fusion")
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
