"""What a source is, and how a folder source becomes a track list.

A source is a plain dict so it round-trips through the config untouched:
    {"name": str, "kind": "stream" | "folder", "target": url-or-path, "shuffle": bool}

A folder is expanded here, in Python, rather than handing mpv the directory:
that makes shuffle and track skipping behave the same on every mpv version and
puts every track straight into mpv's playlist.
"""

import os
import random

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac",
              ".wav", ".wma", ".ape", ".wv", ".mka"}


def make_stream(name, url):
    return {"name": name, "kind": "stream", "target": url, "shuffle": False}


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


def describe(source):
    """Second line for the source list: host for a stream, path for a folder."""
    if is_folder(source):
        return source["target"] + ("  · shuffle" if source.get("shuffle") else "")
    url = source["target"]
    return url.split("://", 1)[-1].split("/", 1)[0]
