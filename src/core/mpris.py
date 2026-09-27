"""The keyboard's media keys, through the desktop's player channel (MPRIS).

The desktop owns the media keys. On Cinnamon, Muffin grabs XF86AudioPlay & co.
and csd-media-keys hands each press to an MPRIS player on the session bus --
or shows a big "Unavailable" when there is none. So a bare media key bound in
ShortCutRadio is not observed and grabbed like the other shortcuts (hotkeys.py
leaves it alone): ShortCutRadio registers as a player and the desktop calls it
(PlayPause, Next, ...). The call is turned back into the key's name and goes
through the same bindings, so the Next key does whatever the user bound to it.

The player is on the bus only while it is `set_active`: the overlay is on and
a media key is bound. Otherwise the media keys belong to other players, exactly
as if ShortCutRadio were not running. While it is on, the sound applet shows it too,
and the keys are also claimed from the settings daemon (mediakeys.py): csd
gives MPRIS players the keys first come, first served, so being on the bus
would not be enough to beat a browser that got there first.

QtDBus quirks, measured with PySide6 6.11:
- `createReply(list)` sends the list as *one* argument; build the reply empty
  and `setArguments` it.
- An empty Python list goes out as `av`, which GLib clients reject where the
  spec says `as`: an empty string array is built typed (`_no_strings`), and the
  metadata never carries an empty list.
- A Python int is always `i`. `Position` must be `x`, so it is left out; the
  applet only asks for it when `CanSeek` is true, which it never is here.
"""

import glob
import os
import sys

from PySide6.QtCore import QMetaType, QObject, QUrl, Signal

from .mediakeys import MediaKeyClaim

try:
    from PySide6.QtDBus import (QDBusArgument, QDBusConnection, QDBusMessage,
                                QDBusObjectPath, QDBusVariant, QDBusVirtualObject)
except ImportError:             # a Qt build without D-Bus: no media channel
    QDBusVirtualObject = QObject
    QDBusConnection = None

PATH = "/org/mpris/MediaPlayer2"
SERVICE = "org.mpris.MediaPlayer2.shortcutradio"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"
INTROSPECTABLE = "org.freedesktop.DBus.Introspectable"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"

# What the desktop calls -> the key it stands for.
METHOD_KEYS = {
    "PlayPause": "media_play_pause", "Play": "media_play_pause",
    "Pause": "media_play_pause", "Next": "media_next",
    "Previous": "media_previous", "Stop": "media_stop",
}

INTROSPECTION = f"""<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
 <interface name="{INTROSPECTABLE}">
  <method name="Introspect"><arg name="xml" type="s" direction="out"/></method>
 </interface>
 <interface name="{PROPS}">
  <method name="Get"><arg name="interface" type="s" direction="in"/>
   <arg name="property" type="s" direction="in"/><arg name="value" type="v" direction="out"/></method>
  <method name="GetAll"><arg name="interface" type="s" direction="in"/>
   <arg name="properties" type="a{{sv}}" direction="out"/></method>
  <method name="Set"><arg name="interface" type="s" direction="in"/>
   <arg name="property" type="s" direction="in"/><arg name="value" type="v" direction="in"/></method>
  <signal name="PropertiesChanged"><arg name="interface" type="s"/>
   <arg name="changed" type="a{{sv}}"/><arg name="invalidated" type="as"/></signal>
 </interface>
 <interface name="{ROOT}">
  <method name="Raise"/><method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/>
  <property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/>
  <property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/>
  <property name="SupportedMimeTypes" type="as" access="read"/>
 </interface>
 <interface name="{PLAYER}">
  <method name="Next"/><method name="Previous"/><method name="Pause"/>
  <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
  <method name="Seek"><arg name="offset" type="x" direction="in"/></method>
  <method name="SetPosition"><arg name="track" type="o" direction="in"/>
   <arg name="position" type="x" direction="in"/></method>
  <method name="OpenUri"><arg name="uri" type="s" direction="in"/></method>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Rate" type="d" access="read"/>
  <property name="Metadata" type="a{{sv}}" access="read"/>
  <property name="Volume" type="d" access="read"/>
  <property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/>
  <property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/>
  <property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
 </interface>
</node>"""


def key_for(method, playing):
    """The media key a Player method stands for, or None when it has nothing
    to do: Play while playing, or Pause while not, must not toggle."""
    if (method == "Play" and playing) or (method == "Pause" and not playing):
        return None
    return METHOD_KEYS.get(method)


def playback_status(state):
    phase = state.phase
    if phase in ("playing", "connecting"):
        return "Playing"
    if phase == "paused":
        return "Paused"
    return "Stopped"


def metadata(state, art_url=""):
    """The now-playing fields. The station is the artist when a track is known,
    the title when it isn't. The track id is a plain path string here."""
    if not state.count:
        return {"mpris:trackid": NO_TRACK}
    meta = {"mpris:trackid": f"/org/shortcutradio/source{state.index}",
            "xesam:title": state.track or state.name}
    if state.track and state.name:
        meta["xesam:artist"] = [state.name]
    if art_url:
        meta["mpris:artUrl"] = art_url
    return meta


def player_props(state, keys, art_url=""):
    """Every Player property for a state and the set of bound media keys."""
    return {
        "PlaybackStatus": playback_status(state),
        "Metadata": metadata(state, art_url),
        "Volume": state.volume / 100.0,
        "Rate": 1.0, "MinimumRate": 1.0, "MaximumRate": 1.0,
        "CanPlay": "media_play_pause" in keys,
        "CanPause": "media_play_pause" in keys,
        "CanGoNext": "media_next" in keys,
        "CanGoPrevious": "media_previous" in keys,
        "CanSeek": False,
        "CanControl": True,
    }


def _no_strings():
    arg = QDBusArgument()
    arg.beginArray(QMetaType(QMetaType.Type.QString))
    arg.endArray()
    return arg


def _wire(props):
    """Our plain values -> what QtDBus marshals to the spec's types."""
    out = dict(props)
    if "Metadata" in out:
        meta = dict(out["Metadata"])
        meta["mpris:trackid"] = QDBusObjectPath(meta["mpris:trackid"])
        out["Metadata"] = meta
    for name in ("SupportedUriSchemes", "SupportedMimeTypes"):
        if name in out:
            out[name] = _no_strings()
    return out


class Mpris(QDBusVirtualObject):
    pressed = Signal(str)           # the media key the desktop delivered
    raise_requested = Signal()

    def __init__(self, art_dir):
        super().__init__()
        self._art_dir = art_dir
        self._art = (None, "")      # (pixmap cacheKey, the file it was saved to)
        self._state = None
        self._pixmap = None
        self._keys = frozenset()
        self._props = {ROOT: {
            "CanQuit": False, "CanRaise": True, "HasTrackList": False,
            "Identity": "ShortCutRadio", "DesktopEntry": "shortcutradio",
            "SupportedUriSchemes": [], "SupportedMimeTypes": [],
        }, PLAYER: {}}
        self._service = ""
        self._bus = None
        self._claim = MediaKeyClaim()
        self._claim.pressed.connect(self.pressed)
        self.available = False
        if QDBusConnection is None or not sys.platform.startswith("linux"):
            return
        bus = QDBusConnection.sessionBus()
        if bus.isConnected() and bus.registerVirtualObject(PATH, self):
            self._bus = bus
            self.available = True
        else:
            print("[mpris] no session bus: media keys stay plain shortcuts", flush=True)

    @property
    def active(self):
        return bool(self._service)

    # ------------------------------------------------------------------ app side
    def set_active(self, on):
        """Be a player on the bus, or not. The name is what the desktop looks
        for; without it the media keys go to someone else."""
        if not self.available or bool(on) == self.active:
            return
        if not on:
            self._claim.drop()
            self._bus.unregisterService(self._service)
            self._service = ""
            return
        self._publish(emit=False)
        # A second ShortCutRadio (a scratch-config test run) gets the spec's suffix.
        for name in (SERVICE, f"{SERVICE}.instance{os.getpid()}"):
            if self._bus.registerService(name):
                self._service = name
                break
        else:
            print("[mpris] could not take a player name on the bus", flush=True)
            return
        self._claim.take()

    def set_keys(self, keys):
        """The media keys that are bound: what the desktop may offer to press."""
        self._keys = frozenset(keys)
        self._publish()

    def set_state(self, state, pixmap):
        self._state, self._pixmap = state, pixmap
        self._publish()

    # ------------------------------------------------------------------ publish
    def _publish(self, emit=True):
        """Work out the Player properties, and tell the desktop what changed.
        Nothing is done while off the bus -- not even saving the artwork --
        except the one silent pass `set_active` makes just before joining."""
        if self._state is None or (emit and not self.active):
            return
        new = player_props(self._state, self._keys, self._art_url())
        old = self._props[PLAYER]
        self._props[PLAYER] = new
        changed = {k: v for k, v in new.items() if old.get(k) != v}
        if emit and changed:
            msg = QDBusMessage.createSignal(PATH, PROPS, "PropertiesChanged")
            msg.setArguments([PLAYER, _wire(changed), _no_strings()])
            self._bus.send(msg)

    def _art_url(self):
        """The picture as a file the applet can read, saved once per picture."""
        pm = self._pixmap
        if pm is None or pm.isNull():
            return ""
        key = pm.cacheKey()
        if key != self._art[0]:
            path = os.path.join(self._art_dir, f"nowplaying-{key & 0xFFFFFFFF:08x}.png")
            try:
                os.makedirs(self._art_dir, exist_ok=True)
                for old in glob.glob(os.path.join(self._art_dir, "nowplaying-*.png")):
                    os.remove(old)
                if not pm.save(path, "PNG"):
                    path = ""
            except OSError:
                path = ""
            self._art = (key, path)
        return QUrl.fromLocalFile(self._art[1]).toString() if self._art[1] else ""

    # ------------------------------------------------------------------ bus side
    def introspect(self, path):
        return ""                   # answered in handleMessage, whole

    def handleMessage(self, msg, conn):
        iface, member, args = msg.interface(), msg.member(), msg.arguments()
        reply = msg.createReply()
        if member == "Introspect":
            reply.setArguments([INTROSPECTION])
        elif iface == PROPS and member == "Get" and len(args) == 2:
            value = self._props.get(args[0], {}).get(args[1])
            if value is None:
                reply = msg.createErrorReply("org.freedesktop.DBus.Error.UnknownProperty",
                                             f"no property {args[1]}")
            else:
                reply.setArguments([QDBusVariant(_wire({args[1]: value})[args[1]])])
        elif iface == PROPS and member == "GetAll" and args:
            reply.setArguments([_wire(self._props.get(args[0], {}))])
        elif iface == PROPS and member == "Set":
            pass                    # everything is read-only
        elif iface in (ROOT, "") and member == "Raise":
            self.raise_requested.emit()
        elif iface in (PLAYER, "") and member in METHOD_KEYS:
            key = key_for(member, self._state is not None and self._state.playing)
            if key:
                self.pressed.emit(key)
        elif iface in (ROOT, PLAYER, ""):
            pass                    # Quit, Seek, SetPosition, OpenUri: nothing to do
        else:
            return False
        conn.send(reply)
        return True
