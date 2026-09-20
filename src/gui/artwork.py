"""Which picture belongs to the source that is playing, and where it came from.

The order is: a file the author picked by hand, then a real cover for a folder
(next to the track, then inside it), then the station's site logo for a stream.
Nothing left? The widgets draw a tile from the name, so the box is never empty.

Only the last of those touches the network, and it does so on one worker
thread, once per station: hits and misses both land in a cache under the
config directory, so a restart costs nothing and a dead site is not re-probed
for a week.
"""

import hashlib
import os
import queue
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from ..core import artfetch, coverart
from ..core.config import data_dir
from ..core.sources import art_label, is_folder

MISS_TTL = 7 * 24 * 3600


def cache_dir():
    return os.path.join(data_dir(), "artwork")


def _file(key, ext):
    name = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir(), name + ext)


def source_key(source):
    """What identifies a station's art: its stream, not its name."""
    return "site:" + (source.get("target") or "") if source else ""


class Artwork(QObject):
    """The art cache. `changed` means: ask again, there is a picture now."""

    changed = Signal()
    _fetched = Signal(str, object)          # key, QImage or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmaps = {}                  # key -> QPixmap or None
        self._queue = queue.Queue()
        self._queued = set()
        self._worker = None
        self._fetched.connect(self._on_fetched)

    # ------------------------------------------------------------------ lookup
    @staticmethod
    def label_for(source):
        """What the tile says when there is no picture -- from the address."""
        return art_label(source)

    def for_source(self, source, track_path=""):
        """The picture for a source, or None when the tile should be drawn."""
        if not source:
            return None
        picked = source.get("art")
        if picked:
            return self._load("file:" + picked, picked)
        if is_folder(source):
            return self._folder(source, track_path)
        return self._station(source)

    def _folder(self, source, track_path):
        cover = coverart.cover_file(track_path, source.get("target") or "")
        if cover:
            return self._load("file:" + cover, cover)
        if not track_path:
            return None
        key = "emb:" + track_path
        if key not in self._pixmaps:
            data = coverart.embedded_art(track_path)
            self._pixmaps[key] = self._from_bytes(data) if data else None
        return self._pixmaps[key]

    def _station(self, source):
        key = source_key(source)
        if key in self._pixmaps:
            return self._pixmaps[key]
        path = _file(key, ".png")
        if os.path.exists(path):
            pm = QPixmap(path)
            self._pixmaps[key] = pm if not pm.isNull() else None
            return self._pixmaps[key]
        if not self._missed_recently(key):
            self._enqueue(key, source)
        return None

    def _load(self, key, path):
        """A picture from disk, remembered by path -- including "not an image"."""
        if key not in self._pixmaps:
            pm = QPixmap(path)
            self._pixmaps[key] = pm if not pm.isNull() else None
        return self._pixmaps[key]

    @staticmethod
    def _from_bytes(data):
        img = QImage()
        return QPixmap.fromImage(img) if img.loadFromData(data) else None

    # ------------------------------------------------------------------ fetching
    def _missed_recently(self, key):
        try:
            return time.time() - os.path.getmtime(_file(key, ".miss")) < MISS_TTL
        except OSError:
            return False

    def _enqueue(self, key, source):
        if key in self._queued:
            return
        self._queued.add(key)
        self._queue.put((key, dict(source)))
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()

    def _run(self):
        """One station at a time, forever. A logo is never urgent."""
        while True:
            key, src = self._queue.get()
            image = None
            try:
                got = artfetch.station_logo(src.get("target") or "",
                                            site=src.get("site") or "",
                                            label=art_label(src))
                if got:
                    candidate = QImage()
                    if candidate.loadFromData(got[0]):
                        image = candidate
            except Exception as e:          # a scraper bug must not kill the thread
                print(f"[artwork] {src.get('name')}: {e}", flush=True)
            self._fetched.emit(key, image)

    def _on_fetched(self, key, image):
        self._queued.discard(key)
        if image is None:
            self._remember_miss(key)
            return
        pm = QPixmap.fromImage(image)
        self._pixmaps[key] = pm if not pm.isNull() else None
        if self._pixmaps[key] is not None:
            try:
                os.makedirs(cache_dir(), exist_ok=True)
                pm.save(_file(key, ".png"), "PNG")
            except OSError as e:
                print(f"[artwork] could not cache: {e}", flush=True)
        self.changed.emit()

    def _remember_miss(self, key):
        try:
            os.makedirs(cache_dir(), exist_ok=True)
            with open(_file(key, ".miss"), "wb"):
                pass
        except OSError:
            pass

    # ------------------------------------------------------------------ edits
    def refetch(self, source):
        """Throw away what we have for a station and look again.

        For when the author points ShortCutRadio at the right page: the logo on
        disk came from the wrong one and has to go with it.
        """
        key = source_key(source)
        self._pixmaps.pop(key, None)
        for ext in (".png", ".miss"):
            try:
                os.remove(_file(key, ext))
            except OSError:
                pass
        self.changed.emit()

    def forget(self, source):
        """After a picture is set or cleared, or a station's site is learned.

        A logo already on disk is kept -- it cost a download and clearing a
        hand-picked picture should fall straight back to it. Only the "no
        logo here" marker goes, so the next look tries again.
        """
        key = source_key(source)
        self._pixmaps.pop(key, None)
        try:
            os.remove(_file(key, ".miss"))
        except OSError:
            pass
        picked = source.get("art")
        if picked:
            self._pixmaps.pop("file:" + picked, None)
        self.changed.emit()
