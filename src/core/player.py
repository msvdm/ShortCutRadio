"""The audio engine: libmpv in-process, wrapped as a QObject.

mpv does all the real work (network, decoding, reconnects, metadata); this
class only knows which source is current and turns mpv's property changes into
one `changed` signal carrying a full state snapshot. mpv calls its observers on
its own thread; a Qt signal emitted there is queued onto the GUI thread, so
receivers never touch mpv state concurrently.
"""

import os
import tempfile
import threading

from PySide6.QtCore import QObject, QTimer, Signal

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


class Player(QObject):
    changed = Signal(dict)
    _stream_ended = Signal()

    def __init__(self, sources, current=0, volume=70):
        super().__init__()
        volume = max(0, min(VOLUME_MAX, volume))        # an older config may be louder
        self.sources = sources          # the config's list, shared by reference
        self.index = current if 0 <= current < len(sources) else 0
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
            p = dict(self._props)
            error = self.error
        src = self.current_source()
        kind = src["kind"] if src else None
        loaded = not p["idle-active"]
        pos, count = p["playlist-pos"], p["playlist-count"] or 0
        return {
            "index": self.index,
            "count": len(self.sources),
            "name": src["name"] if src else "",
            "kind": kind,
            "loaded": loaded,
            "paused": bool(p["pause"]),
            "connecting": loaded and bool(p["core-idle"]) and not p["pause"],
            "volume": int(round(p["volume"] or 0)),
            "track": now_playing(p["metadata"], p["media-title"], p["path"], kind) if loaded else "",
            # For the artwork: which file is playing, and where the station
            # says it lives (most Icecast/SHOUTcast mounts announce icy-url).
            "path": p["path"] if loaded else None,
            "icy_url": _tag(p["metadata"], "icy-url") if loaded else "",
            "track_pos": (pos + 1) if (kind == "folder" and pos is not None and pos >= 0) else None,
            "track_count": count if kind == "folder" else None,
            "error": error,
        }

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
        self.index = index % len(self.sources)
        self._tune()

    def select_source(self, index):
        """Next/previous: change the source, keep the play state.

        Paused stays paused, stopped stays stopped. A stream waiting to
        reconnect counts as playing.
        """
        if not self.sources:
            return
        self.index = index % len(self.sources)
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

    def sources_changed(self, current_source=None):
        """The list was edited. Keep pointing at the same source if it survived."""
        if current_source is not None and any(s is current_source for s in self.sources):
            self.index = next(i for i, s in enumerate(self.sources) if s is current_source)
        else:
            # The playing source was removed: stop rather than keep playing
            # something that is no longer in the list.
            self.index = min(self.index, max(0, len(self.sources) - 1))
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
