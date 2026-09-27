"""Claim the keyboard's media keys from the desktop's settings daemon.

MPRIS alone (mpris.py) is not enough to be *the* player: Cinnamon's
csd-media-keys hands a media key to the first MPRIS player that appeared and
stays with it until it quits, so a browser with a video tab open keeps the
Play key even while the overlay is on. But before it asks MPRIS at all, csd
(and GNOME's gsd) serves the apps that claimed the keys with
GrabMediaPlayerKeys, newest claim first, and sends *them* the key as a
MediaPlayerKeyPressed signal. While ShortCutRadio is active it holds that claim,
so the key is ShortCutRadio's, as the overlay rule says; when it lets go, the keys
go back to whoever had them.

The claim is made over its own D-Bus connection, with jeepney: the call's
`time` argument is a uint32 and PySide6 can't marshal one (a Python int goes
out as `i`, or `q` through QDBusArgument), and csd rejects `(si)`. It suits
the job anyway -- csd drops a claim when its connection closes, so closing
the connection is the release, a crash included. csd sends the signal to that
connection only, so its socket is read from Qt's event loop.
"""

from PySide6.QtCore import QObject, QSocketNotifier, Signal

try:
    from jeepney import DBusAddress, HeaderFields, MessageType, new_method_call
    from jeepney.io.blocking import open_dbus_connection
except ImportError:
    open_dbus_connection = None

APP_ID = "ShortCutRadio"
PATH = "/org/gnome/SettingsDaemon/MediaKeys"
IFACE = "org.gnome.SettingsDaemon.MediaKeys"
# Cinnamon's csd serves it under the old shared name, GNOME's gsd under its own.
DAEMONS = ("org.gnome.SettingsDaemon", "org.gnome.SettingsDaemon.MediaKeys")
CALL_TIMEOUT_S = 1.0
# The daemon's key names -> ours. Its "Play" is the play/pause key.
KEYS = {"Play": "media_play_pause", "Pause": "media_play_pause",
        "Next": "media_next", "Previous": "media_previous", "Stop": "media_stop"}


class MediaKeyClaim(QObject):
    pressed = Signal(str)       # one of hotkeys.MEDIA_KEYS

    def __init__(self):
        super().__init__()
        self.available = open_dbus_connection is not None
        self._conn = None
        self._daemon = ""
        self._notifier = None

    @property
    def held(self):
        return self._conn is not None

    def take(self):
        """Claim the keys. False when no daemon offers the claim (KDE, say):
        then MPRIS is all there is, and that is fine."""
        if not self.available or self.held:
            return self.held
        try:
            conn = open_dbus_connection("SESSION")
        except Exception as e:
            print(f"[mediakeys] no session bus: {e}", flush=True)
            return False
        for daemon in DAEMONS:
            addr = DBusAddress(PATH, bus_name=daemon, interface=IFACE)
            try:
                reply = conn.send_and_get_reply(
                    new_method_call(addr, "GrabMediaPlayerKeys", "su", (APP_ID, 0)),
                    timeout=CALL_TIMEOUT_S)
            except Exception:
                continue
            if reply.header.message_type == MessageType.method_return:
                self._conn, self._daemon = conn, daemon
                self._notifier = QSocketNotifier(conn.sock.fileno(),
                                                 QSocketNotifier.Type.Read)
                self._notifier.activated.connect(self._read)
                return True
        conn.close()
        return False

    def drop(self):
        """Let go. Closing the connection alone would do; saying so is polite."""
        if not self.held:
            return
        conn, self._conn = self._conn, None
        self._notifier.setEnabled(False)
        self._notifier.deleteLater()
        self._notifier = None
        try:
            addr = DBusAddress(PATH, bus_name=self._daemon, interface=IFACE)
            conn.send(new_method_call(addr, "ReleaseMediaPlayerKeys", "s", (APP_ID,)))
        except Exception:
            pass
        conn.close()

    def _read(self, *_):
        """Everything that has arrived; the key signals are all we act on."""
        while self._conn is not None:
            try:
                msg = self._conn.receive(timeout=0)
            except TimeoutError:
                return
            except Exception:           # the bus went away: the claim with it
                self._conn.close()
                self._conn = None
                self._notifier.setEnabled(False)
                return
            h = msg.header
            if (h.message_type == MessageType.signal
                    and h.fields.get(HeaderFields.member) == "MediaPlayerKeyPressed"
                    and len(msg.body) == 2 and msg.body[0] == APP_ID):
                key = KEYS.get(msg.body[1])
                if key:
                    self.pressed.emit(key)
