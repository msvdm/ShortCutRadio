"""The cover of a local track: a file beside it, or a picture inside it.

Stdlib only, and bounded everywhere: each reader takes a header, seeks past
what it does not need, caps what it reads and answers None rather than raising.
A tag written by some forgotten ripper must never stop playback or a repaint.

Returns raw bytes; Qt does the decoding.
"""

import base64
import os

COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "artwork")
COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MAX_PICTURE = 8 * 1024 * 1024
FRONT_COVER = 3                     # the picture type both ID3 and FLAC use
B64 = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


def cover_file(track_path, root=""):
    """cover.jpg & co next to the track, then at the source's folder root."""
    dirs = []
    for d in (os.path.dirname(track_path or ""), root):
        if d and d not in dirs:
            dirs.append(d)
    for d in dirs:
        try:
            names = {e.lower(): e for e in os.listdir(d)}
        except OSError:
            continue
        for stem in COVER_NAMES:
            for ext in COVER_EXTS:
                hit = names.get(stem + ext)
                if hit:
                    return os.path.join(d, hit)
    return None


def embedded_art(path):
    """The picture stored inside an audio file, as bytes, or None."""
    reader = READERS.get(os.path.splitext(path or "")[1].lower())
    if reader is None:
        return None
    try:
        with open(path, "rb") as fh:
            return reader(fh)
    except (OSError, ValueError, IndexError):
        return None


# ------------------------------------------------------------------- ID3 (mp3)
def _syncsafe(raw):
    n = 0
    for b in raw:
        n = (n << 7) | (b & 0x7F)
    return n


def _id3_apic(fh):
    head = fh.read(10)
    # v2.2 and older store frames differently and are not worth the code.
    if len(head) < 10 or head[:3] != b"ID3" or head[3] not in (3, 4):
        return None
    v4 = head[3] == 4
    body = fh.read(min(_syncsafe(head[6:10]), MAX_PICTURE + 64 * 1024))
    pos = 0
    if head[5] & 0x40:                              # extended header
        if len(body) < 4:
            return None
        pos = _syncsafe(body[:4]) if v4 else int.from_bytes(body[:4], "big") + 4

    best = None
    while pos + 10 <= len(body):
        fid, raw = body[pos:pos + 4], body[pos + 4:pos + 8]
        if not fid.strip(b"\0"):
            break                                   # padding: the tag is over
        size = _syncsafe(raw) if v4 else int.from_bytes(raw, "big")
        pos += 10
        frame, pos = body[pos:pos + size], pos + size
        if fid != b"APIC" or size <= 0:
            continue
        got = _apic(frame)
        if got and (best is None or got[1] == FRONT_COVER):
            best = got
            if got[1] == FRONT_COVER:
                break
    return best[0] if best else None


def _apic(frame):
    """(bytes, picture type) from an APIC frame body."""
    if len(frame) < 4:
        return None
    enc, rest = frame[0], frame[1:]
    mime, sep, rest = rest.partition(b"\0")
    if not sep or mime.strip() == b"-->":           # "-->" means a URL, not art
        return None
    ptype, desc = rest[0], rest[1:]
    if enc in (1, 2):                               # UTF-16: a two-byte end
        i = 0
        while i + 1 < len(desc) and desc[i:i + 2] != b"\0\0":
            i += 2
        data = desc[i + 2:]
    else:
        i = desc.find(b"\0")
        if i < 0:
            return None
        data = desc[i + 1:]
    return (data, ptype) if data else None


# ----------------------------------------------------------------- FLAC / Ogg
def _picture_block(b):
    """(bytes, picture type) from a METADATA_BLOCK_PICTURE body."""
    if len(b) < 32:
        return None
    ptype = int.from_bytes(b[0:4], "big")
    p = 8 + int.from_bytes(b[4:8], "big")           # past the mime string
    p += 4 + int.from_bytes(b[p:p + 4], "big")      # past the description
    p += 16                                         # width, height, depth, colours
    size = int.from_bytes(b[p:p + 4], "big")
    data = b[p + 4:p + 4 + size]
    return (data, ptype) if data and len(data) == size else None


def _flac_picture(fh):
    if fh.read(4) != b"fLaC":
        return None
    best = None
    while True:
        head = fh.read(4)
        if len(head) < 4:
            break
        size = int.from_bytes(head[1:4], "big")
        if head[0] & 0x7F == 6 and size <= MAX_PICTURE:     # PICTURE block
            got = _picture_block(fh.read(size))
            if got and (best is None or got[1] == FRONT_COVER):
                best = got
                if got[1] == FRONT_COVER:
                    break
        else:
            fh.seek(size, os.SEEK_CUR)
        if head[0] & 0x80:                                  # last block
            break
    return best[0] if best else None


def _ogg_picture(fh):
    """Ogg puts the same block, base64'd, in a comment -- but a big one spans
    pages, so the page bodies have to be stitched back together first."""
    data = b"".join(_ogg_bodies(fh))
    i = data.find(b"METADATA_BLOCK_PICTURE=")
    if i < 0:
        return None
    i += len(b"METADATA_BLOCK_PICTURE=")
    end = i
    while end < len(data) and data[end] in B64:
        end += 1
    raw = data[i:end]
    raw = raw[:len(raw) - len(raw) % 4]
    try:
        got = _picture_block(base64.b64decode(raw))
    except ValueError:
        return None
    return got[0] if got else None


def _ogg_bodies(fh, max_pages=256):
    total = 0
    for _ in range(max_pages):
        head = fh.read(27)
        if len(head) < 27 or head[:4] != b"OggS":
            return
        table = fh.read(head[26])
        if len(table) < head[26]:
            return
        body = fh.read(sum(table))
        total += len(body)
        yield body
        if total > MAX_PICTURE + 64 * 1024:
            return


# -------------------------------------------------------------------- MP4/M4A
def _mp4_covr(fh):
    fh.seek(0, os.SEEK_END)
    box = _mp4_find(fh, 0, fh.tell(),
                    [b"moov", b"udta", b"meta", b"ilst", b"covr", b"data"])
    if box is None:
        return None
    start, stop = box
    fh.seek(start + 8)                  # past the data atom's type and locale
    size = min(stop - start - 8, MAX_PICTURE)
    data = fh.read(size) if size > 0 else b""
    return data or None


def _mp4_find(fh, start, end, path):
    """(body start, end) of the last atom in `path`, or None."""
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return None
        size, name = int.from_bytes(head[:4], "big"), head[4:8]
        body = pos + 8
        if size == 1:                   # 64-bit size follows the name
            size = int.from_bytes(fh.read(8), "big")
            body = pos + 16
        elif size == 0:
            size = end - pos
        if size < 8:
            return None
        stop = min(pos + size, end)
        if name == path[0]:
            if len(path) == 1:
                return (body, stop)
            if name == b"meta":
                body += 4               # meta carries a version/flags word
            got = _mp4_find(fh, body, stop, path[1:])
            if got:
                return got
        pos += size
    return None


READERS = {
    ".mp3": _id3_apic, ".aac": _id3_apic,
    ".flac": _flac_picture,
    ".ogg": _ogg_picture, ".oga": _ogg_picture, ".opus": _ogg_picture,
    ".m4a": _mp4_covr, ".m4b": _mp4_covr, ".mp4": _mp4_covr,
}
