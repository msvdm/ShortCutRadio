"""The audio engine: Qt's own player (Qt Multimedia, FFmpeg inside), as a QObject.

QMediaPlayer does the network, the decoding and the output; this class knows
which source is current, walks a folder's tracks itself, and turns Qt's
signals into one `changed` signal carrying a full state snapshot. Streams go
through the relay (core/relay.py), which is where their song titles come
from. Everything here runs on the GUI thread; the relay's reports arrive
through a queued signal.
"""

import os
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer

from .relay import Relay
from .sources import art_label, folder_tracks, is_folder

RETRY_MS = 5000
VOLUME_MAX = 100        # louder would mean amplifying; nothing good comes of it

_S = QMediaPlayer.MediaStatus
READY = (_S.BufferingMedia, _S.BufferedMedia)       # the audio is running


def _tag(meta, *keys):
    if not isinstance(meta, dict):
        return ""
    lower = {str(k).lower(): v for k, v in meta.items()}
    for k in keys:
        v = lower.get(k)
        if v:
            return str(v).strip()
    return ""


def now_playing(meta, path, kind):
    """The track line: what is playing right now, or "" if nothing useful.

    Streams: the station's title (ICY or an Ogg comment); HLS streams never
    send one, and a station that sends its own address says nothing either.
    Local files: "Artist – Title" from the tags, falling back to the file name.
    """
    if kind == "folder":
        artist, title = _tag(meta, "artist"), _tag(meta, "title")
        if artist and title:
            return f"{artist} – {title}"
        if title:
            return title
        return os.path.splitext(os.path.basename(path or ""))[0]

    title = _tag(meta, "title")
    url = path or ""
    if (not title or title == url or title.startswith(("http://", "https://"))
            or title == url.rstrip("/").rsplit("/", 1)[-1]):
        return ""
    return title


def volume_gain(volume):
    """The output's linear gain for a 0-100 volume: cubic, as mpv's was, so
    the 5 % steps sound even instead of all happening near the bottom."""
    return (max(0, min(VOLUME_MAX, volume)) / 100) ** 3


@dataclass(frozen=True)
class PlayerState:
    """What the player is doing, as every view needs it. Immutable: a new one
    is emitted on every change, and receivers may keep the old one."""

    index: int = 0
    count: int = 0              # sources in the list
    name: str = ""
    tile: str = ""              # what the art says without a picture: from the address
    kind: str | None = None     # "stream" | "folder" | None (no sources)
    loaded: bool = False        # something is open (playing or paused)
    paused: bool = False
    connecting: bool = False    # opened, but no audio yet
    volume: int = 0
    track: str = ""
    path: str | None = None     # for the artwork: the file that is playing
    icy_url: str = ""           # where the station says it lives
    track_pos: int | None = None
    track_count: int | None = None
    error: str = ""

    @property
    def phase(self):
        """One word for the status the views put into their own words:
        empty | error | stopped | paused | connecting | playing."""
        if not self.count:
            return "empty"
        if self.error:
            return "error"
        if not self.loaded:
            return "stopped"
        if self.paused:
            return "paused"
        if self.connecting:
            return "connecting"
        return "playing"

    @property
    def playing(self):
        """Loaded and not paused: the play button shows pause."""
        return self.loaded and not self.paused

    @property
    def audible(self):
        """Sound is coming out right now -- what the level meters follow."""
        return self.loaded and not self.paused and not self.connecting

    @property
    def can_skip_track(self):
        return self.kind == "folder" and self.loaded


EMPTY_STATE = PlayerState()


def make_state(source, index, count, *, loaded=False, paused=False, ready=False,
               volume=0, meta=None, path=None, icy_url="", track_index=None,
               track_count=0, error=""):
    """The state from the current source and the player's own facts.

    ready: Qt has the audio running. meta: a folder track's tags, or a
    stream's {"title"}. path: the file or the stream that is open.
    track_index and track_count: folders only.
    """
    kind = source["kind"] if source else None
    folder = kind == "folder"
    return PlayerState(
        index=index,
        count=count,
        name=source["name"] if source else "",
        tile=art_label(source),
        kind=kind,
        loaded=loaded,
        paused=paused,
        connecting=loaded and not ready and not paused,
        volume=int(round(volume)),
        track=now_playing(meta, path, kind) if loaded else "",
        path=path if loaded else None,
        icy_url=icy_url if loaded else "",
        track_pos=(track_index + 1) if (folder and track_index is not None
                                        and track_index >= 0) else None,
        track_count=track_count if folder else None,
        error=error,
    )


class Player(QObject):
    changed = Signal(object)        # PlayerState
    _relayed = Signal(int, str, str)    # token, "title" | "icy_url", value

    def __init__(self, sources, current=0, volume=70):
        super().__init__()
        self.sources = sources          # the config's list, shared by reference
        self._select(current if 0 <= current < len(sources) else 0)
        self.error = ""
        self._volume = max(0, min(VOLUME_MAX, volume))  # an older config may be louder
        self._loaded = False
        self._paused = False
        self._tracks = []               # a folder's files, in play order
        self._pos = -1
        self._failed = 0                # folder tracks that would not play, in a row
        self._meta = {}
        self._icy_url = ""
        self._token = 0                 # the relay session that is ours

        self.out = QAudioOutput(self)
        self.out.setVolume(volume_gain(self._volume))
        self.qt = QMediaPlayer(self)
        self.qt.setAudioOutput(self.out)
        self.qt.mediaStatusChanged.connect(self._on_status)
        self.qt.playbackStateChanged.connect(self._emit)
        self.qt.errorOccurred.connect(self._on_error)
        self.qt.metaDataChanged.connect(self._on_tags)

        self.relay = Relay(self._relayed.emit)
        self._relayed.connect(self._on_relayed)

        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS)
        self._retry.timeout.connect(self._retry_stream)

    # ---------------------------------------------------------------- Qt side
    def _on_status(self, status):
        if (status == _S.EndOfMedia and self._loaded
                and self.qt.mediaStatus() == _S.EndOfMedia):     # not a stale one
            if self._folder:
                self._failed = 0
                self._step(1)           # folders loop
            else:
                self._stream_ended("Reconnecting…")
            return
        if status in READY:
            self._failed = 0
        self._emit()

    def _on_error(self, *_):
        if self.qt.error() == QMediaPlayer.Error.NoError or not self._loaded:
            return          # stale: the source was replaced or stopped since
        if self._folder:
            # A file that won't play is skipped, unless none of them will.
            self._failed += 1
            if self._failed < len(self._tracks):
                self._step(1)
            else:
                self._halt("Can't play the files in this folder")
            return
        self._stream_ended("Can't reach this stream – retrying…")

    def _stream_ended(self, message):
        self._halt(message)
        self._retry.start()

    def _on_tags(self):
        if not self._folder:
            return          # a stream's title comes from the relay
        m = self.qt.metaData()
        self._meta = {
            "title": m.stringValue(QMediaMetaData.Key.Title),
            "artist": m.stringValue(QMediaMetaData.Key.ContributingArtist)
            or m.stringValue(QMediaMetaData.Key.AlbumArtist),
        }
        self._emit()

    def _on_relayed(self, token, key, value):
        if token != self._token:
            return          # the station before this one, still hanging up
        if key == "title":
            self._meta = {"title": value}
        elif key == "icy_url":
            self._icy_url = value
        self._emit()

    def _retry_stream(self):
        if self.current_source() is not None and not self._folder and not self._loaded:
            self._tune(paused=self._paused)

    # ---------------------------------------------------------------- state
    def _select(self, index):
        """Point at a source. The source itself is remembered, not only its
        place: the list can be reordered or cut under it (sources_changed)."""
        self.index = index
        self._current = self.current_source()

    def current_source(self):
        if 0 <= self.index < len(self.sources):
            return self.sources[self.index]
        return None

    @property
    def _folder(self):
        """The current source is a folder -- else a stream, or nothing at all."""
        src = self.current_source()
        return src is not None and is_folder(src)

    def snapshot(self):
        src = self.current_source()
        folder = self._folder
        if folder:
            path = self._tracks[self._pos] if 0 <= self._pos < len(self._tracks) else None
        else:
            path = src["target"] if src else None
        status = self.qt.mediaStatus()
        return make_state(
            src, self.index, len(self.sources),
            loaded=self._loaded, paused=self._paused,
            # A local file opens in a blink: only a stall counts as waiting.
            ready=status != _S.StalledMedia if folder else status in READY,
            volume=self._volume, meta=self._meta, path=path, icy_url=self._icy_url,
            track_index=self._pos if folder else None,
            track_count=len(self._tracks) if folder else 0,
            error=self.error,
        )

    def _emit(self, *_):
        self.changed.emit(self.snapshot())

    # ---------------------------------------------------------------- commands
    def _halt(self, error=""):
        """Nothing open any more; `error` says why, if it wasn't asked for."""
        self._retry.stop()
        self._loaded = False
        self.error = error          # before Qt's own signals report the stop
        self._drop_stream()
        self.qt.stop()
        self.qt.setSource(QUrl())
        self._emit()

    def _drop_stream(self):
        """Let the relay go; a late report from it no longer counts."""
        self._token = 0
        self.relay.close()

    def _open(self, url):
        """Load `url` into Qt with the play state already decided: pause is
        set before loading, or the new source is heard for a moment."""
        self._meta = {}
        self.qt.setSource(url)
        if self._paused:
            self.qt.pause()
        else:
            self.qt.play()

    def _tune(self, paused=False):
        src = self.current_source()
        self._retry.stop()
        self.error = ""
        self._paused = paused
        self._icy_url = ""
        self._tracks, self._pos, self._failed = [], -1, 0
        if src is None:
            self._halt()
            return
        if is_folder(src):
            self._drop_stream()
            self._tracks = folder_tracks(src["target"], src.get("shuffle", False))
            if not self._tracks:
                self._halt("No audio files in this folder")
                return
            self._pos = 0
            self._loaded = True
            self._open(QUrl.fromLocalFile(self._tracks[0]))
        else:
            self._token, local = self.relay.open(src["target"])
            self._loaded = True
            self._open(QUrl(local))
        self._emit()

    def _step(self, delta):
        """Another track of the folder, wrapping round at either end."""
        if not self._tracks:
            return
        self._pos = (self._pos + delta) % len(self._tracks)
        self._open(QUrl.fromLocalFile(self._tracks[self._pos]))
        self._emit()

    def play_source(self, index):
        """Explicit play (double-click, menu Play): always starts playback."""
        if not self.sources:
            return
        self._select(index % len(self.sources))
        self._tune()

    def select_source(self, index):
        """Next/previous: change the source, keep the play state.

        Paused stays paused, stopped stays stopped. A stream waiting to
        reconnect counts as playing.
        """
        if not self.sources:
            return
        self._select(index % len(self.sources))
        if self._loaded or self._retry.isActive():
            self._tune(paused=self._paused)
        else:
            self._retry.stop()
            self.error = ""
            self._emit()

    def next_source(self):
        self.select_source(self.index + 1)

    def prev_source(self):
        self.select_source(self.index - 1)

    def next_track(self):
        if self._folder and self._loaded:
            self._step(1)

    def prev_track(self):
        if self._folder and self._loaded:
            self._step(-1)

    def toggle(self):
        if not self._loaded:
            self._tune()        # nothing playing yet: start the current source
            return
        self._paused = not self._paused
        if self._paused:
            self.qt.pause()
        else:
            self.qt.play()
        self._emit()

    def set_volume(self, value):
        self._volume = max(0, min(VOLUME_MAX, int(round(value))))
        self.out.setVolume(volume_gain(self._volume))
        self._emit()

    def change_volume(self, delta):
        self.set_volume(self._volume + delta)

    def sources_changed(self):
        """The list was edited. Keep pointing at the same source if it survived.

        Matched by identity: the config's own dicts are the sources, so a
        reorder must hand back the same objects (see sources_page.INDEX_ROLE).
        """
        found = next((i for i, s in enumerate(self.sources) if s is self._current), None)
        if found is not None:
            self._select(found)
        else:
            # The playing source was removed: stop rather than keep playing
            # something that is no longer in the list.
            self._select(min(self.index, max(0, len(self.sources) - 1)))
            if self._loaded:
                self._halt()        # which tells everyone
                return
        self._emit()

    def shutdown(self):
        self._retry.stop()
        self.relay.shutdown()
        self.qt.stop()
