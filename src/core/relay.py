"""The stream relay: a station's audio for Qt's player, its song titles for us.

Qt's player (FFmpeg inside) plays Icecast streams but hands back no song
title. So the player asks this relay for http://127.0.0.1:<port>/<token>, and
the relay fetches the real stream with Icy-MetaData, strips the metadata
blocks out of the audio, reports the titles, and serves the bare audio.

It is a socket rather than a Python QIODevice because Qt reads a device on its
own thread: a source change then waits for that thread on the GUI thread while
holding the GIL, and the thread waits for the GIL to call readData -- measured,
it hung on the first station change. Here FFmpeg only ever reads a socket.

An Ogg stream carries its titles in comment packets instead, and FLAC-in-Ogg
is rewrapped as plain FLAC: Qt's player stalls on it after four buffers
(measured on five stations, played directly too). Anything else -- HLS, a
plain file -- gets a redirect to its real address, so FFmpeg fetches it itself
and an HLS playlist's segments resolve against the right host.
"""

import re
import socket
import struct
import threading

from .net import NET_ERRORS, open_url


class IcyStripper:
    """Split an Icecast body into audio and metadata blocks: after every
    `metaint` bytes of audio comes a length byte (x16) and that much text."""

    def __init__(self, metaint):
        self.metaint = metaint
        self.left = metaint         # audio bytes until the next length byte
        self.meta_left = None       # metadata bytes still to come, or None
        self.meta = b""

    def feed(self, data):
        audio, blocks, i = [], [], 0
        while i < len(data):
            if self.meta_left is None and self.left:
                n = min(self.left, len(data) - i)
                audio.append(data[i:i + n])
                self.left -= n
                i += n
            elif self.meta_left is None:
                self.meta_left = data[i] * 16
                self.meta = b""
                i += 1
            else:
                n = min(self.meta_left, len(data) - i)
                self.meta += data[i:i + n]
                self.meta_left -= n
                i += n
            if self.meta_left == 0:
                if self.meta.strip(b"\0"):
                    blocks.append(self.meta)
                self.meta_left, self.left = None, self.metaint
        return b"".join(audio), blocks


def stream_title(block):
    """The StreamTitle in an ICY metadata block, "" for an empty one, or None.
    A title may itself contain "';", so it ends at the "';" before the next
    key or the end of the block."""
    raw = block.rstrip(b"\0")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")        # the ICY default
    m = re.search(r"StreamTitle='(.*?)';(?=\s*$|\w+=)", text, re.S)
    return m.group(1).strip() if m else None


def comment_title(b):
    """"Artist – Title" from a Vorbis comment block (Opus, Vorbis, FLAC), or None."""
    tags = {}
    try:
        (vendor,) = struct.unpack_from("<I", b, 0)
        p = 4 + vendor
        (n,) = struct.unpack_from("<I", b, p)
        p += 4
        for _ in range(min(n, 200)):
            (ln,) = struct.unpack_from("<I", b, p)
            p += 4
            key, _, value = b[p:p + ln].decode("utf-8", "replace").partition("=")
            tags[key.lower()] = value.strip()
            p += ln
    except struct.error:
        return None
    artist, title = tags.get("artist", ""), tags.get("title", "")
    return f"{artist} – {title}" if artist and title else (title or None)


class OggReader:
    """Walk an Ogg stream page by page. Titles come from its comment packets;
    FLAC is rewrapped as plain FLAC ("fLaC", STREAMINFO, then the frames);
    every other codec passes through untouched."""

    MAX_PACKET = 1 << 20        # a comment with cover art can be big; skip the rest

    def __init__(self):
        self.buf = bytearray()
        self.packet = bytearray()
        self.flac = False
        self.flac_head = False

    def feed(self, data):
        self.buf += data
        out, titles = [], []
        while len(self.buf) >= 27:
            if self.buf[:4] != b"OggS":         # lost sync: skip to the next page
                i = self.buf.find(b"OggS", 1)
                cut = i if i > 0 else len(self.buf) - 3
                if not self.flac:
                    out.append(bytes(self.buf[:cut]))
                del self.buf[:cut]
                continue
            nseg = self.buf[26]
            if len(self.buf) < 27 + nseg:
                break
            lacing = self.buf[27:27 + nseg]
            size = 27 + nseg + sum(lacing)
            if len(self.buf) < size:
                break
            page = bytes(self.buf[:size])
            del self.buf[:size]
            if page[5] & 2:
                self.packet.clear()             # a new chain begins (a new song)
            body, pos = page[27 + nseg:], 0
            for ln in lacing:
                if len(self.packet) < self.MAX_PACKET:
                    self.packet += body[pos:pos + ln]
                pos += ln
                if ln < 255:                    # the packet ends in this page
                    frame, title = self._packet(bytes(self.packet))
                    self.packet.clear()
                    if frame:
                        out.append(frame)
                    if title is not None:
                        titles.append(title)
            if not self.flac:
                out.append(page)
        return b"".join(out), titles

    def _packet(self, p):
        if p.startswith(b"\x7fFLAC") and len(p) >= 51:
            self.flac = True
            if self.flac_head:
                return None, None               # a later chain: same stream goes on
            self.flac_head = True
            # STREAMINFO, marked as the last metadata block: the rest is tags
            return b"fLaC" + bytes([p[13] | 0x80]) + p[14:51], None
        if self.flac:
            if p[:1] == b"\xff":                # a frame's sync code
                return (p if self.flac_head else None), None
            if p and p[0] & 0x7F == 4:          # VORBIS_COMMENT
                return None, comment_title(p[4:])
            return None, None
        if p.startswith(b"OpusTags"):
            return None, comment_title(p[8:])
        if p.startswith(b"\x03vorbis"):
            return None, comment_title(p[7:])
        return None, None


class Relay:
    """One live stream at a time, served on 127.0.0.1 only.

    `report(token, key, value)` is called on the relay's threads with
    key "title" or "icy_url"; the token says which open() it belongs to, so a
    late report from the previous station can be told apart."""

    def __init__(self, report):
        self._report = report
        self._live = None           # (token, url)
        self._token = 0
        self._sock = socket.create_server(("127.0.0.1", 0))
        self._port = self._sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True, name="relay").start()

    def open(self, url):
        """(token, the address to hand Qt's player) for this stream."""
        self._token += 1
        self._live = (self._token, url)
        return self._token, f"http://127.0.0.1:{self._port}/{self._token}"

    def close(self):
        """Let go of the stream; its connection ends with its next chunk."""
        self._live = None

    def shutdown(self):
        self._live = None
        try:
            self._sock.close()
        except OSError:
            pass

    def _current(self, token):
        live = self._live
        return live is not None and live[0] == token

    def _accept(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return              # shut down
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            try:
                conn.settimeout(8)
                req = b""
                while b"\r\n\r\n" not in req and len(req) < 8192:
                    data = conn.recv(4096)
                    if not data:
                        return
                    req += data
                path = req.split(b" ", 2)[1].decode("latin-1")
                token = int(path.strip("/")) if path.strip("/").isdigit() else -1
                live = self._live
                if live is None or live[0] != token:
                    conn.sendall(b"HTTP/1.0 404 Not Found\r\n\r\n")
                    return
                try:
                    resp = open_url(live[1])
                except NET_ERRORS:
                    conn.sendall(b"HTTP/1.0 502 Bad Gateway\r\n\r\n")
                    return
                with resp:
                    self._relay(token, resp, conn)
            except (NET_ERRORS + (IndexError,)):
                pass            # either side went away: Qt sees the end, the player retries

    def _relay(self, token, resp, conn):
        h = resp.headers
        self._report(token, "icy_url", (h.get("icy-url") or "").strip())
        ctype = (h.get("content-type") or "application/octet-stream").strip()
        metaint = int(h.get("icy-metaint") or 0)
        if not metaint and "ogg" not in ctype.lower():
            # Nothing to add: FFmpeg fetches it itself.
            conn.sendall(b"HTTP/1.0 302 Found\r\nLocation: "
                         + resp.geturl().encode("utf-8") + b"\r\n\r\n")
            return
        conn.settimeout(None)       # paused, Qt stops reading; that is not an error
        strip = IcyStripper(metaint) if metaint else None
        ogg = None if metaint else OggReader()
        read = getattr(resp, "read1", resp.read)
        head = False
        while self._current(token):
            data = read(16384)
            if not data:
                return
            if strip:
                data, blocks = strip.feed(data)
                titles = [t for t in map(stream_title, blocks) if t is not None]
            else:
                data, titles = ogg.feed(data)
            for t in titles:
                self._report(token, "title", t)
            if data:
                if not head:
                    kind = "audio/flac" if ogg and ogg.flac else ctype
                    conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: "
                                 + kind.encode("latin-1", "replace") + b"\r\n\r\n")
                    head = True
                conn.sendall(data)
