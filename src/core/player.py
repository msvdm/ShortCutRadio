"""The audio engine: libmpv in-process, wrapped as a QObject.

mpv does all the real work (network, decoding, reconnects, metadata); this
class only knows which source is current and turns mpv's property changes into
one `changed` signal carrying a full state snapshot. mpv calls its observers on
its own thread; a Qt signal emitted there is queued onto the GUI thread, so
receivers never touch mpv state concurrently.
"""

import os
import sys
import tempfile
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .config import app_dir

if sys.platform == "win32":
    # Windows has no system libmpv, so the app brings libmpv-2.dll: a build
    # keeps it with its other libraries (sys._MEIPASS, the _internal folder),
    # a dev checkout next to shortcutradio.py. python-mpv's find_library()
    # only walks %PATH%, so that folder goes first on it before mpv loads.
    os.environ["PATH"] = (getattr(sys, "_MEIPASS", app_dir()) + os.pathsep
                          + os.environ.get("PATH", ""))

import mpv

from .sources import folder_tracks, is_folder

RETRY_MS = 5000
VOLUME_MAX = 100        # mpv will amplify past this; nothing good comes of it

# Ported from the NFSU2 radio's nfs-radio launcher: survive flaky networks.
STREAM_OPTS = dict(
    network_timeout=15,
    cache=True,
    demuxer_max_bytes="16MiB",
    stream_lavf_o="reconnect=1,reconnect_streamed=1,"
                  "reconnect_on_network_error=1,reconnect_delay_max=5",
)


def _tag(meta, *keys):
    if not isinstance(meta, dict):
        return ""
    lower = {str(k).lower(): v for k, v in meta.items()}
    for k in keys:
        v = lower.get(k)
        if v:
            return str(v).strip()
    return ""


def now_playing(meta, media_title, path, kind):
    """The track line: what is playing right now, or "" if nothing useful.

    Streams: the station's icy-title. Before the first metadata block mpv
    reports the URL or its basename as media-title, which is noise, and HLS
    streams never send any. Local files: "Artist – Title" from the tags,
    falling back to the file name.
    """
    if kind == "folder":
        artist, title = _tag(meta, "artist"), _tag(meta, "title")
        if artist and title:
            return f"{artist} – {title}"
        if title:
            return title
        return os.path.splitext(os.path.basename(path or ""))[0]

    title = _tag(meta, "icy-title", "title") or (media_title or "").strip()
    url = path or ""
    if (not title or title == url or title.startswith(("http://", "https://"))
            or title == url.rstrip("/").rsplit("/", 1)[-1]):
        return ""
    return title


@dataclass(frozen=True)
class PlayerState:
    """What the player is doing, as every view needs it. Immutable: a new one
    is emitted on every change, and receivers may keep the old one."""

    index: int = 0
    count: int = 0              # sources in the list
    name: str = ""
    kind: str | None = None     # "stream" | "folder" | None (no sources)
    loaded: bool = False        # mpv has something open (playing or paused)
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


def make_state(props, index, source, count, error=""):
    """The state from mpv's observed properties and the current source."""
    kind = source["kind"] if source else None
    loaded = not props["idle-active"]
    pos, total = props["playlist-pos"], props["playlist-count"] or 0
    folder = kind == "folder"
    return PlayerState(
        index=index,
        count=count,
        name=source["name"] if source else "",
        kind=kind,
        loaded=loaded,
        paused=bool(props["pause"]),
        connecting=loaded and bool(props["core-idle"]) and not props["pause"],
        volume=int(round(props["volume"] or 0)),
        track=now_playing(props["metadata"], props["media-title"], props["path"], kind)
        if loaded else "",
        path=props["path"] if loaded else None,
        # Most Icecast/SHOUTcast mounts announce their home page in icy-url.
        icy_url=_tag(props["metadata"], "icy-url") if loaded else "",
        track_pos=(pos + 1) if (folder and pos is not None and pos >= 0) else None,
        track_count=total if folder else None,
        error=error,
    )


class Player(QObject):
    changed = Signal(object)        # PlayerState
    _stream_ended = Signal()

    def __init__(self, sources, current=0, volume=70):
        super().__init__()
        volume = max(0, min(VOLUME_MAX, volume))        # an older config may be louder
        self.sources = sources          # the config's list, shared by reference
        self._select(current if 0 <= current < len(sources) else 0)
        self.error = ""
        self._lock = threading.Lock()
        self._props = {"metadata": None, "media-title": None, "path": None,
                       "pause": False, "volume": volume, "playlist-pos": None,
                       "playlist-count": 0, "core-idle": True, "idle-active": True}
        self._playlist_file = os.path.join(tempfile.gettempdir(),
                                           f"shortcutradio-{os.getpid()}.m3u")

        self.mpv = mpv.MPV(
            video=False, ytdl=False, idle=True, terminal=False,
            input_default_bindings=False, input_vo_keyboard=False,
            volume=volume, volume_max=VOLUME_MAX, audio_client_name="ShortCutRadio",
            msg_level="all=warn", **STREAM_OPTS)

        for name in self._props:
            self.mpv.observe_property(name, self._on_prop)
        self.mpv.event_callback("end-file")(self._on_end_file)

        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS)
        self._retry.timeout.connect(self._retry_stream)
        self._stream_ended.connect(self._retry.start)

    # ---------------------------------------------------------------- mpv side
    def _on_prop(self, name, value):
        with self._lock:
            self._props[name] = value
            if name == "core-idle" and value is False:
                self.error = ""
        self._emit()

    def _on_end_file(self, event):
        reason = event.data.reason
        if reason not in (mpv.MpvEventEndFile.EOF, mpv.MpvEventEndFile.ERROR):
            return          # replaced by a station change, or quitting
        src = self.current_source()
        if src is None or is_folder(src):
            return          # folders loop; a track ending is normal
        with self._lock:
            self.error = "Reconnecting…" if reason == mpv.MpvEventEndFile.EOF \
                else "Can't reach this stream – retrying…"
        self._emit()
        self._stream_ended.emit()

    def _retry_stream(self):
        src = self.current_source()
        if src and not is_folder(src) and not self.loaded():
            self._tune(paused=bool(self.mpv.pause))

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

    def loaded(self):
        # Ask mpv, not the observed copy: that one can lag a second behind a
        # stop, and Next right after Stop would then start playing.
        return not self.mpv.idle_active

    def snapshot(self):
        with self._lock:
            props = dict(self._props)
            error = self.error
        return make_state(props, self.index, self.current_source(),
                          len(self.sources), error)

    def _emit(self):
        self.changed.emit(self.snapshot())

    # ---------------------------------------------------------------- commands
    def _tune(self, paused=False):
        src = self.current_source()
        self._retry.stop()
        with self._lock:
            self.error = ""
            # Don't show the old source's track under the new source's name
            # while mpv is still opening it.
            self._props.update({"metadata": None, "media-title": None, "path": None})
        if src is None:
            self.mpv.command("stop")
            self._emit()
            return
        if is_folder(src):
            tracks = folder_tracks(src["target"], src.get("shuffle", False))
            if not tracks:
                self.mpv.command("stop")
                with self._lock:
                    self.error = "No audio files in this folder"
                self._emit()
                return
            with open(self._playlist_file, "w", encoding="utf-8") as fh:
                fh.write("#EXTM3U\n" + "\n".join(tracks) + "\n")
            # Set pause before loading, or the new source is heard starting.
            self.mpv.pause = paused
            self.mpv.loop_playlist = "inf"
            self.mpv.loadlist(self._playlist_file, "replace")
        else:
            self.mpv.pause = paused
            self.mpv.loop_playlist = "no"
            self.mpv.loadfile(src["target"], "replace")
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
        if self.loaded() or self._retry.isActive():
            self._tune(paused=bool(self.mpv.pause))
        else:
            self._retry.stop()
            with self._lock:
                self.error = ""
            self._emit()

    def next_source(self):
        self.select_source(self.index + 1)

    def prev_source(self):
        self.select_source(self.index - 1)

    def next_track(self):
        src = self.current_source()
        if src and is_folder(src) and self.loaded():
            self.mpv.playlist_next("force")

    def prev_track(self):
        src = self.current_source()
        if src and is_folder(src) and self.loaded():
            self.mpv.playlist_prev("force")

    def toggle(self):
        if not self.loaded():
            self._tune()        # nothing playing yet: start the current source
        else:
            self.mpv.pause = not self.mpv.pause

    def stop(self):
        self._retry.stop()
        self.mpv.command("stop")

    def set_volume(self, value):
        self.mpv.volume = max(0, min(VOLUME_MAX, value))

    def change_volume(self, delta):
        self.set_volume((self.mpv.volume or 0) + delta)

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
            if self.loaded():
                self.stop()
        self._emit()

    def shutdown(self):
        self._retry.stop()
        try:
            self.mpv.terminate()
        finally:
            try:
                os.remove(self._playlist_file)
            except OSError:
                pass
