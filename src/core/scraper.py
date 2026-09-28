"""Add Stream: turn whatever URL the user pastes into a list of playable streams.

The URL can be a stream, a playlist (.pls/.m3u/HLS) or a station's web page.
Pages are harvested for stream-looking URLs (in attributes, inline JS/JSON and
same-site scripts), every candidate is probed, and only the ones that answer as
audio survive. Icecast servers are asked for their other mounts too, which is
how one channel link on a page turns into the whole network. If a page yields
nothing, radio-browser.info is searched by the page title.

A page that links a stream is often only a shortcut to it (a directory, a
list), so each stream gets the station's own page, not the one it was found
on, and loses the tags that credit the linking site (`origin_site`).

Stdlib only, blocking: the GUI runs `discover()` on a worker thread.
"""

import html
import http.client
import re
import socket
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .net import (NET_ERRORS, TIMEOUT, clean_site, icecast_sources, open_url,
                  read_json, same_site, site_of)
from .sources import name_from_url

PAGE_MAX = 3 * 1024 * 1024
MAX_CANDIDATES = 80
MAX_SCRIPTS = 6
MAX_ICECAST_HOSTS = 3

STREAM_EXTS = {".mp3", ".aac", ".aacp", ".ogg", ".oga", ".opus", ".flac",
               ".m3u8", ".m3u", ".pls"}
STATIC_EXTS = {".js", ".mjs", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
               ".webp", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".html",
               ".htm", ".xml", ".xsl", ".json", ".txt", ".pdf", ".mp4", ".webm",
               ".zip"}
STREAMY_SEGMENTS = {"stream", "live", "listen", ";", "radio.mp3", "stream.mp3"}
STREAMY_HOST_WORDS = ("stream", "icecast", "shoutcast", "hls", "cast", "radio.")

ABS_URL = re.compile(r"""https?://[^\s"'<>()\\\[\]{}|^`]+""")
ATTR_URL = re.compile(r"""(?:href|src|data-[\w-]+)\s*=\s*["']([^"']+)["']""", re.I)
SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


@dataclass
class Found:
    name: str
    url: str
    detail: str = ""
    site: str = ""          # the station's own page: where its logo lives


# ------------------------------------------------------------------ helpers
def normalize_input(url):
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def _ext(path):
    last = path.rsplit("/", 1)[-1]
    return ("." + last.rsplit(".", 1)[-1].lower()) if "." in last else ""


def _key(url):
    """Dedupe key: the same stream over http and https is one stream."""
    return url.split("://", 1)[-1].rstrip("/").lower()


def looks_streamy(url, page_host=""):
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    ext = _ext(p.path)
    if ext in STATIC_EXTS:
        return False
    if ext in STREAM_EXTS:
        return True
    try:
        port = p.port
    except ValueError:
        return False
    if port and port not in (80, 443):
        return True
    host = p.hostname.lower()
    # Plain pages on the station's own site are the site, not the stream.
    if host == page_host:
        return False
    if any(w in host for w in STREAMY_HOST_WORDS):
        return True
    segs = [s.lower() for s in p.path.split("/")]
    return any(s in STREAMY_SEGMENTS for s in segs)


def harvest(text, base_url):
    """Candidate stream URLs in a page or script, in order of appearance."""
    text = text.replace("\\/", "/").replace("\\u002F", "/")
    page_host = (urllib.parse.urlsplit(base_url).hostname or "").lower()
    seen, out = set(), []

    def add(u):
        u = html.unescape(u).strip().rstrip(".,;:'\")")
        if looks_streamy(u, page_host) and _key(u) not in seen:
            seen.add(_key(u))
            out.append(u)

    for m in ABS_URL.finditer(text):
        add(m.group(0))
    for m in ATTR_URL.finditer(text):
        v = m.group(1)
        if not v.startswith(("javascript:", "mailto:", "#", "data:")):
            add(urllib.parse.urljoin(base_url, v))
    return out


def parse_playlist(body, base_url):
    """(title, [urls]) from .pls or plain .m3u text."""
    title, urls = "", []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("file") and "=" in line:
            urls.append(line.split("=", 1)[1].strip())
        elif low.startswith("title") and "=" in line and not title:
            title = line.split("=", 1)[1].strip()
        elif line.startswith("#EXTINF") and "," in line and not title:
            title = line.split(",", 1)[1].strip()
        elif not line.startswith(("#", "[")) and "=" not in line.split("/", 1)[0]:
            urls.append(urllib.parse.urljoin(base_url, line))
    return title, [u for u in urls if u.startswith(("http://", "https://"))]


def _detail(ct, headers):
    codec = {"audio/mpeg": "MP3", "audio/aac": "AAC", "audio/aacp": "AAC+",
             "audio/ogg": "Ogg", "application/ogg": "Ogg", "audio/flac": "FLAC",
             "audio/opus": "Opus"}.get(ct, ct.split("/")[-1].upper() if ct else "")
    br = headers.get("icy-br", "").split(",")[0].strip()
    return " · ".join(x for x in (codec, f"{br} kbps" if br else "") if x)


# ------------------------------------------------------------------ probing
def classify(url, want_page=False):
    """Look at one URL. Returns one of
        ("audio", Found, server_header)
        ("playlist", title, [urls])
        ("page", text, final_url)
        None  -- unreachable or not interesting
    Page bodies are only read when `want_page` (the user's own URL, scripts).
    """
    try:
        resp = open_url(url)
    except http.client.BadStatusLine as e:
        # Old SHOUTcast v1 answers "ICY 200 OK", which http.client rejects --
        # that answer itself proves it is a stream.
        if "ICY" in str(e):
            return ("audio", Found(name_from_url(url), url, "SHOUTcast"), "shoutcast")
        return None
    except NET_ERRORS:
        return None

    with resp:
        final = resp.geturl()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        ct = headers.get("content-type", "").split(";")[0].strip().lower()
        server = headers.get("server", "").lower()
        try:
            head = resp.read(4096)
        except NET_ERRORS:
            head = b""
        text_head = head.decode("utf-8", "replace").lstrip("﻿").lstrip()

        is_hls = "mpegurl" in ct and "#EXT-X-" in text_head or \
            text_head.startswith("#EXTM3U") and "#EXT-X-" in text_head
        if is_hls:
            return ("audio", Found(name_from_url(url), url, "HLS"), server)

        if ct in ("audio/x-scpls", "audio/scpls") or text_head.lower().startswith("[playlist]") \
                or "mpegurl" in ct or (_ext(urllib.parse.urlsplit(final).path) in (".pls", ".m3u")
                                       and ct.startswith("text")):
            body = text_head + _read_rest(resp, 64 * 1024)
            title, urls = parse_playlist(body, final)
            return ("playlist", title, urls) if urls else None

        if ct.startswith("audio/") or ct in ("application/ogg", "video/mp2t") \
                or "icy-name" in headers or "icy-metaint" in headers or "icy-br" in headers:
            name = headers.get("icy-name", "").strip()
            if not name or name.lower() in ("no name", "unspecified description"):
                name = name_from_url(url)
            return ("audio", Found(name, url, _detail(ct, headers),
                                   clean_site(headers.get("icy-url"))), server)

        if want_page and (ct.startswith("text/") or "javascript" in ct or "json" in ct or not ct):
            body = head + _read_rest(resp, PAGE_MAX).encode("utf-8", "surrogateescape")
            charset = resp.headers.get_content_charset() or "utf-8"
            return ("page", body.decode(charset, "replace"), final)
    return None


def _read_rest(resp, limit):
    try:
        return resp.read(limit).decode("utf-8", "surrogateescape")
    except NET_ERRORS:
        return ""


def resolve(url, depth=0):
    """Candidate URL -> [(Found, server)]. Playlists are followed one level:
    a .pls usually lists mirrors of one stream, so its first working entry
    stands for it, named after the playlist's title."""
    r = classify(url)
    if r is None:
        return []
    if r[0] == "audio":
        return [(r[1], r[2])]
    if r[0] == "playlist" and depth == 0:
        title, urls = r[1], r[2]
        for u in urls[:6]:
            got = resolve(u, depth + 1)
            if got:
                found, server = got[0]
                if title:
                    found.name = title
                return [(found, server)]
    return []


def icecast_mounts(stream_url):
    """Other mounts on the same Icecast server, via its status-json.xsl."""
    p = urllib.parse.urlsplit(stream_url)
    out = []
    for s in icecast_sources(stream_url)[:30]:
        listen = s.get("listenurl") or ""
        path = urllib.parse.urlsplit(listen).path
        if not path:
            continue
        # listenurl often carries the server's internal host name; keep the
        # host the user can actually reach.
        url = f"{p.scheme}://{p.netloc}{path}"
        name = (s.get("server_name") or "").strip() or name_from_url(url)
        br = s.get("bitrate") or s.get("audio_bitrate")
        ct = (s.get("server_type") or "").lower()
        detail = _detail(ct, {"icy-br": str(br) if br else ""})
        out.append(Found(name, url, detail, clean_site(s.get("server_url"))))
    return out


def radio_browser(query, report=lambda m: None):
    q = re.split(r"\s[|–—:-]\s", query)[0].strip()
    if not q:
        return []
    report(f"Searching radio-browser.info for “{q}”…")
    api = ("https://all.api.radio-browser.info/json/stations/search?"
           + urllib.parse.urlencode({"name": q, "limit": 20, "hidebroken": "true",
                                     "order": "clickcount", "reverse": "true"}))
    try:
        rows = read_json(api, 1024 * 1024, {"User-Agent": "ShortCutRadio/0.1"})
    except NET_ERRORS:
        return []
    out = []
    for r in rows:
        url = r.get("url_resolved") or r.get("url")
        if url:
            bits = [r.get("codec") or "", f"{r['bitrate']} kbps" if r.get("bitrate") else "",
                    "radio-browser.info"]
            out.append(Found(r.get("name", "").strip() or name_from_url(url), url,
                             " · ".join(b for b in bits if b),
                             (r.get("homepage") or "").strip()))
    return out


# ------------------------------------------------------------------ entry
def discover(url, report=lambda m: None):
    """All playable streams behind `url`, best guess first. Never raises for
    network trouble; an empty list means nothing was found."""
    url = normalize_input(url)
    report("Opening the address…")
    first = classify(url, want_page=True)
    if first is None:
        return []

    results, servers = [], {}
    if first[0] == "audio":
        results.append(first[1])
        servers[_key(first[1].url)] = first[2]
        page_title = ""
    elif first[0] == "playlist":
        results += [f for f, _ in resolve(url)]
        page_title = first[1]
    else:
        text, final = first[1], first[2]
        m = TITLE.search(text)
        page_title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
        candidates = _page_candidates(text, final)
        report(f"Checking {len(candidates)} possible stream"
               f"{'s' if len(candidates) != 1 else ''}…")
        with ThreadPoolExecutor(max_workers=12) as pool:
            for got in pool.map(resolve, candidates):
                for found, server in got:
                    results.append(found)
                    servers[_key(found.url)] = server
        one_station = len({f.name for f in results}) == 1
        for f in results:
            f.site = origin_site(final, f, one_station)
            if not same_site(final, f.site or f.url):
                f.url = strip_referrer(f.url, final)

    # One channel of an Icecast server usually means there are more.
    hosts = []
    for f in results:
        if "icecast" in servers.get(_key(f.url), ""):
            netloc = urllib.parse.urlsplit(f.url).netloc
            if netloc not in hosts:
                hosts.append(netloc)
    for netloc in hosts[:MAX_ICECAST_HOSTS]:
        sample = next(f.url for f in results if urllib.parse.urlsplit(f.url).netloc == netloc)
        report(f"Asking {netloc} for its other channels…")
        results += icecast_mounts(sample)

    results = _dedupe(results)
    if not results and page_title:
        results = _dedupe(radio_browser(page_title, report))
    return results


def origin_site(page, found, one_station):
    """The station's own page for a stream found on `page`, or "".

    A page that links to a stream is often only a shortcut to it -- a
    directory, a list, a blog post -- and its logo is not the station's. The
    stream's own word (icy-url, an Icecast server_url) is the original; the
    page is kept only where it is on that same site, being the more specific
    of the two (somafm.com/fluid/, not somafm.com). A stream that says nothing
    keeps the page only when the page is provably its: the stream lives on
    the page's site, or the page offers just this one station.
    """
    if found.site:
        return page if same_site(page, found.site) else found.site
    if same_site(page, found.url) or one_station:
        return page
    return ""


def strip_referrer(url, page):
    """The stream without the tags that credit the page that linked it:
    ?dist=PREDAVATEL, utm_source=... -- the listening belongs to the station."""
    name = site_of(page).split(".")[0]
    p = urllib.parse.urlsplit(url)
    if len(name) < 4 or not p.query:
        return url
    pairs = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if name not in (k + "=" + v).lower()]
    if len(kept) == len(pairs):
        return url
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(kept)))


def _page_candidates(text, final):
    """Stream-looking URLs on a page and in its same-site scripts."""
    candidates = harvest(text, final)
    page_host = (urllib.parse.urlsplit(final).hostname or "").lower()
    site = ".".join(page_host.split(".")[-2:])
    scripts = []
    for s in SCRIPT_SRC.findall(text):
        su = urllib.parse.urljoin(final, html.unescape(s))
        if (urllib.parse.urlsplit(su).hostname or "").endswith(site):
            scripts.append(su)
    for su in scripts[:MAX_SCRIPTS]:
        r = classify(su, want_page=True)
        if r and r[0] == "page":
            seen = {_key(c) for c in candidates}
            candidates += [c for c in harvest(r[1], su) if _key(c) not in seen]
    return candidates[:MAX_CANDIDATES]


def clean_name(name):
    """Stations stuff descriptions into their titles ("SomaFM: Fluid (#1):
    Drown in the electronic sound of..."). Keep the part that names it."""
    name = re.sub(r"\s*\(#\d+\)", "", html.unescape(name)).strip()
    if len(name) > 40:
        parts = [p.strip() for p in name.split(":") if p.strip()]
        name = ": ".join(parts[:2]) if len(parts) > 1 else name
        if len(name) > 40:
            name = parts[0] if len(parts[0]) <= 40 else name[:40].rstrip() + "…"
    return name


def _dedupe(results):
    out, seen = [], set()
    for f in results:
        f.name = clean_name(f.name)
        k = _key(f.url)
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    # Several channels sharing one station name: tell them apart by path.
    names = [f.name for f in out]
    for name in set(n for n in names if names.count(n) > 1):
        group = [f for f in out if f.name == name]
        details = [f.detail for f in group]
        use_detail = all(details) and len(set(details)) == len(details)
        for f in group:
            f.name = f"{name} ({f.detail if use_detail else name_from_url(f.url)})"
    return out


if __name__ == "__main__":     # quick manual check: python -m src.core.scraper URL
    import sys
    socket.setdefaulttimeout(TIMEOUT)
    for f in discover(sys.argv[1], report=lambda m: print("..", m)):
        print(f"{f.name:40s} {f.detail:22s} {f.url}")
