"""What a source is, and how a folder source becomes a track list.

A source is a plain dict so it round-trips through the config untouched:
    {"name": str, "kind": "stream" | "folder", "target": url-or-path, "shuffle": bool}
Two optional keys join it later: "site", the station's web page (where its logo
comes from), and "art", a picture the author picked by hand.

A folder is expanded here, in Python, rather than handing mpv the directory:
that makes shuffle and track skipping behave the same on every mpv version and
puts every track straight into mpv's playlist.
"""

import os
import random
import urllib.parse

from .scraper import name_from_url

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac",
              ".wav", ".wma", ".ape", ".wv", ".mka"}
# Trailing words a mount name carries that say nothing about the station:
# "fluid-128-mp3" is Fluid.
NOISE = {"mp3", "aac", "aacp", "ogg", "opus", "flac", "hls", "kbps", "kb",
         "stream", "live", "audio", "high", "low", "hq", "lq"}


def make_stream(name, url, site=""):
    return {"name": name, "kind": "stream", "target": url, "shuffle": False,
            "site": site}


def make_folder(path, name=None, shuffle=True):
    path = os.path.abspath(os.path.expanduser(path))
    return {"name": name or os.path.basename(path.rstrip("/\\")) or path,
            "kind": "folder", "target": path, "shuffle": shuffle}


def is_folder(source):
    return source.get("kind") == "folder"


def folder_tracks(path, shuffle=False, rng=random):
    """All audio files under `path`, recursively. Sorted, or shuffled."""
    path = os.path.expanduser(path)
    tracks = []
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        dirs.sort(key=str.casefold)
        for f in sorted(files, key=str.casefold):
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                tracks.append(os.path.join(root, f))
    if shuffle:
        rng.shuffle(tracks)
    return tracks


def _trim_noise(label):
    words = label.split()
    while len(words) > 1 and (words[-1].isdigit() or words[-1].lower() in NOISE):
        words.pop()
    return " ".join(words) or label


def art_label(source):
    """The text a generated art tile is drawn from.

    Taken from the address, never from the source's name: the picture stands
    for the station, so renaming one must not repaint it. `describe()` is the
    same idea for the list's second line.
    """
    if not source:
        return ""
    target = source.get("target") or ""
    if is_folder(source):
        return os.path.basename(target.rstrip("/\\")) or target
    label = _trim_noise(name_from_url(target))
    host = (urllib.parse.urlsplit(target).hostname or "").lower()
    if not label or label.lower() == host:
        # The path said nothing useful: fall back to the site's own label,
        # radio.rn-tv.com -> rn-tv.
        parts = [x for x in host.split(".") if x]
        label = parts[-2] if len(parts) > 2 else (parts[0] if parts else target)
    return label


def describe(source):
    """Second line for the source list: host for a stream, path for a folder."""
    if is_folder(source):
        return source["target"] + ("  · shuffle" if source.get("shuffle") else "")
    url = source["target"]
    return url.split("://", 1)[-1].split("/", 1)[0]
