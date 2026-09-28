"""Windows' Now Playing (SMTC): the counterpart of mpris.py, behind the same seam.

On Windows the media keys need no desktop channel: they reach the keyboard
hook (keygrab_win.py) like any other key and are taken there. What SMTC adds
is the rest of what MPRIS gives the sound applet -- the volume flyout, the
lock screen and Win+G show the station, the track and its picture, and their
buttons press the bound media keys through `pressed`, exactly as an MPRIS
call does. The overlay rule is the same too: the session exists only while
`set_active` (overlay on and a media key bound); switched off, it disappears
from every list.

A desktop app has no SMTC of its own (`GetForCurrentView` is for store apps),
so it borrows one from a MediaPlayer that never plays anything, with the
player's automatic command handling off. Measured with pywinrt 3.2:
- A `file:///` thumbnail URI shows no picture; the thumbnail has to come
  from a StorageFile, which only arrives asynchronously.
- ButtonPressed and async completions run on WinRT's thread pool, so both
  come back to the Qt thread through a queued signal.
"""

import sys

from PySide6.QtCore import QObject, Signal

from .mpris import ArtFile, key_for, metadata, playback_status

try:
    from winrt.windows.foundation import AsyncStatus
    from winrt.windows.media import (MediaPlaybackStatus, MediaPlaybackType,
                                     SystemMediaTransportControlsButton as Button)
    from winrt.windows.media.playback import MediaPlayer
    from winrt.windows.storage import StorageFile
    from winrt.windows.storage.streams import RandomAccessStreamReference
except Exception:               # not Windows, or pywinrt is not installed
    MediaPlayer = None
else:
    BUTTON_METHODS = {Button.PLAY: "Play", Button.PAUSE: "Pause",
                      Button.NEXT: "Next", Button.PREVIOUS: "Previous",
                      Button.STOP: "Stop"}
    STATUS = {"Playing": MediaPlaybackStatus.PLAYING,
              "Paused": MediaPlaybackStatus.PAUSED,
              "Stopped": MediaPlaybackStatus.STOPPED}


class Smtc(QObject):
    pressed = Signal(str)           # the media key a Now Playing button stands for
    raise_requested = Signal()      # never: SMTC has no Raise; kept for the seam
    _button = Signal(str)           # from the thread pool
    _thumb_file = Signal(object, str)

    def __init__(self, art_dir):
        super().__init__()
        self._art = ArtFile(art_dir)
        self._state = None
        self._pixmap = None
        self._keys = frozenset()
        self._on = False
        self._shown = None          # what the session shows now, to skip repeats
        self._thumb = ""            # the picture asked for, by file
        self.available = False
        if MediaPlayer is None or sys.platform != "win32":
            return
        try:
            self._player = MediaPlayer()
            self._player.command_manager.is_enabled = False
            self._smtc = self._player.system_media_transport_controls
            self._smtc.is_enabled = False
            self._smtc.add_button_pressed(
                lambda _, args: self._button.emit(BUTTON_METHODS.get(args.button, "")))
        except OSError as e:
            print(f"[smtc] unavailable: {e}", flush=True)
            return
        self._button.connect(self._press)
        self._thumb_file.connect(self._set_thumbnail)
        self.available = True

    @property
    def active(self):
        return self._on

    # ------------------------------------------------------------------ app side
    def set_active(self, on):
        """Be a Now Playing session, or not. Disabled, the session is gone
        from the flyout, not just paused."""
        if not self.available or bool(on) == self._on:
            return
        self._on = bool(on)
        if self._on:
            self._shown = None
            self._publish()
        self._smtc.is_enabled = self._on

    def set_keys(self, keys):
        """The media keys that are bound: which buttons the flyout offers."""
        self._keys = frozenset(keys)
        self._publish()

    def set_state(self, state, pixmap):
        self._state, self._pixmap = state, pixmap
        self._publish()

    # ------------------------------------------------------------------ publish
    def _publish(self):
        if not self._on or self._state is None:
            return
        meta = metadata(self._state)
        artist = meta.get("xesam:artist", [""])[0]
        shown = (playback_status(self._state), meta.get("xesam:title", ""), artist,
                 self._keys)
        if shown != self._shown:
            self._shown = shown
            smtc, keys = self._smtc, self._keys
            smtc.is_play_enabled = smtc.is_pause_enabled = "media_play_pause" in keys
            smtc.is_next_enabled = "media_next" in keys
            smtc.is_previous_enabled = "media_previous" in keys
            smtc.is_stop_enabled = "media_stop" in keys
            smtc.playback_status = STATUS[shown[0]]
            du = smtc.display_updater
            du.type = MediaPlaybackType.MUSIC
            du.music_properties.title = shown[1]
            du.music_properties.artist = artist
            du.update()
        self._ask_thumbnail(self._art.path(self._pixmap))

    def _ask_thumbnail(self, path):
        if path == self._thumb:
            return
        self._thumb = path
        if not path:
            self._set_thumbnail(None, "")
            return

        def done(op, status):
            if status == AsyncStatus.COMPLETED:
                self._thumb_file.emit(op.get_results(), path)
        StorageFile.get_file_from_path_async(path).completed = done

    def _set_thumbnail(self, file, path):
        if path != self._thumb:
            return                  # a newer picture was asked for meanwhile
        du = self._smtc.display_updater
        du.thumbnail = RandomAccessStreamReference.create_from_file(file) if file else None
        du.update()

    # ------------------------------------------------------------------ flyout
    def _press(self, method):
        key = key_for(method, self._state is not None and self._state.playing)
        if key:
            self.pressed.emit(key)
