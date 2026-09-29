"""The desktop's Now Playing, whatever the platform calls it.

Linux has MPRIS (mpris.py), Windows has SMTC (smtc.py). Both show the
station, the track and its picture, and both turn their buttons back into
the media keys they stand for, which then go through the same bindings as a
key pressed. What they share lives here: the words for a state, the button
-> key rule, the picture as a file, and the seam App talks to
(`MediaSession`: `available`, `delivers_keys`, `set_active`, `set_keys`,
`set_state`, `pressed`, `raise_requested`).
"""

import glob
import os
import sys

# A player method or button -> the media key it stands for.
METHOD_KEYS = {
    "PlayPause": "media_play_pause", "Play": "media_play_pause",
    "Pause": "media_play_pause", "Next": "media_next",
    "Previous": "media_previous", "Stop": "media_stop",
}


def media_session(art_dir):
    """This platform's session: SMTC on Windows, MPRIS everywhere else."""
    if sys.platform == "win32":
        from .smtc import Smtc
        return Smtc(art_dir)
    from .mpris import Mpris
    return Mpris(art_dir)


def key_for(method, playing):
    """The media key a player method stands for, or None when it has nothing
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


def titles(state):
    """(title, artist): the station is the artist when a track is known, and
    the title when it isn't."""
    if state.track and state.name:
        return state.track, state.name
    return state.track or state.name, ""


class ArtFile:
    """The now-playing picture as a file the desktop can read, saved once per
    picture: MPRIS takes a file URL, SMTC a StorageFile."""

    def __init__(self, art_dir):
        self._dir = art_dir
        self._art = (None, "")      # (pixmap cacheKey, the file it was saved to)

    def path(self, pm):
        if pm is None or pm.isNull():
            return ""
        key = pm.cacheKey()
        if key != self._art[0]:
            path = os.path.join(self._dir, f"nowplaying-{key & 0xFFFFFFFF:08x}.png")
            try:
                os.makedirs(self._dir, exist_ok=True)
                for old in glob.glob(os.path.join(self._dir, "nowplaying-*.png")):
                    os.remove(old)
                if not pm.save(path, "PNG"):
                    path = ""
            except OSError:
                path = ""
            self._art = (key, path)
        return self._art[1]


class MediaSession:
    """What MPRIS and SMTC share, mixed in before their Qt class (as
    frameless.Frameless is). Each declares its own `pressed = Signal(str)` and
    `raise_requested = Signal()`, calls `_session()` once, first, and shows
    the state in `_publish()`.

    `delivers_keys`: the desktop hands the bare media keys over through
    `pressed` (MPRIS on the bus). False where the keyboard hook takes them
    like any other key, and the session only shows and presses (SMTC).
    """

    delivers_keys = False

    def _session(self, art_dir):
        self._art = ArtFile(art_dir)
        self._state = None
        self._pixmap = None
        self._keys = frozenset()
        self.available = False

    def set_keys(self, keys):
        """The media keys that are bound: what the desktop may offer to press."""
        self._keys = frozenset(keys)
        self._publish()

    def set_state(self, state, pixmap):
        self._state, self._pixmap = state, pixmap
        self._publish()

    def _press(self, method):
        """A button of the desktop's player, as the media key it stands for."""
        key = key_for(method, self._state is not None and self._state.playing)
        if key:
            self.pressed.emit(key)
