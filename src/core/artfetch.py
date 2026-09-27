"""The station's logo, taken from the station's own web page.

A stream source knows an address to listen to; the picture lives on the site in
front of it. So the page has to be found first -- what the author pasted when
the stream was added, the `icy-url` the stream itself announces, the Icecast
server's `server_url`, or, failing all that, the stream's host with its
`streams.` label trimmed off. The page is then read for the images a site
already publishes for exactly this purpose: the share card, the touch icon,
the icon links, a logo image, the favicon.

Stdlib only and blocking, like scraper.py -- the GUI calls this on a worker
thread. Nothing here raises for network trouble; None means "no logo".
"""

import html
import re
import urllib.parse

from .net import NET_ERRORS, icecast_sources, open_url
from .scraper import classify

TIMEOUT_BYTES = 4 * 1024 * 1024
MAX_TRY = 4                 # downloads before we give up on a page
MIN_PX = 48                 # smaller than this is a UI sprite, not a logo
MAX_ASPECT = 2.5            # wider than this is a banner; keep looking

TAG = re.compile(r"<(meta|link|img)\b([^>]*)>", re.I)
ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s">]+))""")
SIZES = re.compile(r"(\d+)\s*[x×]\s*(\d+)")
WORD = re.compile(r"\w{4,}", re.UNICODE)      # station names are not all ASCII
# Words every radio page carries, so finding one proves nothing.
COMMON = {"radio", "stream", "live", "online", "music", "listen", "player", "http",
          "https", "www", "com", "net", "free"}

# Hosts stations put their streams on, in front of the site's real name.
LABEL = re.compile(r"^(stream|streams|streaming|ice|icecast|shoutcast|cast|live|"
                   r"listen|hls|audio|media|cdn|srv|server|sc|s|node|lb|lb-hls)"
                   r"[\d-]*$", re.I)


def clean_site(url):
    """A usable http(s) home page, or "" -- stations put junk in icy-url."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        return ""
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or "/", "", ""))


def site_for_stream(stream_url):
    """Last-resort guess: streams.badrockradio.net -> badrockradio.net."""
    try:
        p = urllib.parse.urlsplit(stream_url)
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if not host or "." not in host:
        return ""
    labels = host.split(".")
    while len(labels) > 2 and LABEL.match(labels[0]):
        labels.pop(0)
    return "https://" + ".".join(labels) + "/"


def icecast_site(stream_url):
    """The `server_url` an Icecast mount advertises, if this is one."""
    try:
        want = urllib.parse.urlsplit(stream_url).path.rstrip("/")
    except ValueError:
        return ""
    best = ""
    for s in icecast_sources(stream_url):
        url = clean_site(s.get("server_url") or "")
        if not url:
            continue
        if urllib.parse.urlsplit(s.get("listenurl") or "").path.rstrip("/") == want:
            return url                  # this very mount: the best answer
        best = best or url
    return best


def _attrs(raw):
    out = {}
    for m in ATTR.finditer(raw):
        value = (m.group(2) or m.group(3) or m.group(4) or "").strip()
        out[m.group(1).lower()] = html.unescape(value)
    return out


def _declared(a):
    """The largest side the tag claims, from sizes= or width/height."""
    best = 0
    for m in SIZES.finditer(a.get("sizes", "")):
        best = max(best, int(m.group(1)), int(m.group(2)))
    for key in ("width", "height"):
        try:
            best = max(best, int(re.sub(r"\D", "", a.get(key, "")) or 0))
        except ValueError:
            pass
    return min(best, 1024)


def logo_candidates(text, base_url):
    """Image URLs on a station page, best first."""
    scored, seen = [], set()

    def add(url, score):
        url = (url or "").strip()
        if not url or url.startswith("data:"):
            return
        url = urllib.parse.urljoin(base_url, url)
        if url.lower().split("?")[0].endswith((".css", ".js", ".html")):
            return
        if url in seen:
            return
        seen.add(url)
        scored.append((score, len(scored), url))

    for m in TAG.finditer(text):
        tag, a = m.group(1).lower(), _attrs(m.group(2))
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:image", "og:image:url", "og:image:secure_url",
                       "twitter:image", "twitter:image:src"):
                add(a.get("content"), 100)
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if "apple-touch-icon" in rel:
                add(a.get("href"), 90 + _declared(a) // 64)
            elif "icon" in rel and "mask-icon" not in rel:
                add(a.get("href"), 70 + _declared(a) // 64)
        else:
            hay = " ".join((a.get("src", ""), a.get("class", ""), a.get("id", ""),
                            a.get("alt", ""))).lower()
            if "logo" in hay:
                add(a.get("src") or a.get("data-src"), 60)

    add(urllib.parse.urljoin(base_url, "/favicon.ico"), 10)
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [url for _, _, url in scored]


def image_size(data):
    """(width, height) sniffed from the first bytes, or None."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return (int.from_bytes(data[6:8], "little"),
                    int.from_bytes(data[8:10], "little"))
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
            if data[12:16] == b"VP8 ":
                return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                        int.from_bytes(data[28:30], "little") & 0x3FFF)
            if data[12:16] == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if data[:4] == b"\x00\x00\x01\x00":                     # ICO
            return (data[6] or 256), (data[7] or 256)
        if data[:2] == b"\xff\xd8":                             # JPEG
            i = 2
            while i + 9 <= len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    return (int.from_bytes(data[i + 7:i + 9], "big"),
                            int.from_bytes(data[i + 5:i + 7], "big"))
                i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    except (IndexError, ValueError):
        return None
    return None


def _download(url):
    try:
        with open_url(url) as resp:
            ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            data = resp.read(TIMEOUT_BYTES)
    except NET_ERRORS:
        return None
    if ct and not (ct.startswith("image/") or ct == "application/octet-stream"):
        return None
    return data or None


def _is_svg(url, data):
    return url.lower().split("?")[0].endswith(".svg") or \
        data[:200].lstrip().lower().startswith((b"<svg", b"<?xml"))


def name_tokens(label):
    """The distinctive words of an address label, for vetting a guessed page."""
    return [w for w in WORD.findall((label or "").lower()) if w not in COMMON]


def mentions(text, tokens):
    """Nothing to check against counts as a pass: absence of evidence only."""
    if not tokens:
        return True
    low = text.lower()
    return any(t in low for t in tokens)


def logo_from_page(site_url, need=()):
    """(bytes, image url) for the best logo on a station page, or None.

    `need` vets the page itself: a guessed address often lands on the CDN or
    the hosting company rather than the station, and their logo is worse than
    no logo at all.
    """
    got = classify(site_url, want_page=True)
    if not got or got[0] != "page":
        return None
    text, final = got[1], got[2]
    if not mentions(text, need):
        return None
    runner_up = None
    for url in logo_candidates(text, final)[:MAX_TRY]:
        data = _download(url)
        if not data:
            continue
        size = image_size(data)
        if size is None:
            if _is_svg(url, data):
                return data, url
            continue
        w, h = size
        if min(w, h) < MIN_PX:
            continue
        if max(w, h) > MAX_ASPECT * min(w, h):
            runner_up = runner_up or (data, url)    # a banner: keep looking
            continue
        return data, url
    return runner_up


def station_logo(stream_url, site="", icy_url="", label=""):
    """The whole chain: find the station's page, then its logo. Or None.

    Returns (bytes, image url, page url). The first three addresses are the
    station's own word for where it lives and are taken at face value; the
    host guess has to prove it landed on the right site.

    `label` vets that guess and comes from the address (`sources.art_label`),
    not from what the source is called -- renaming a station must not change
    which logo it gets.
    """
    guess = site_for_stream(stream_url)
    tokens = name_tokens(label)
    tried = []
    for candidate in (clean_site(site), clean_site(icy_url),
                      icecast_site(stream_url), guess):
        if not candidate or candidate in tried:
            continue
        if candidate == guess and not tokens:
            continue        # nothing to check a guess against: don't risk it
        tried.append(candidate)
        got = logo_from_page(candidate, need=tokens if candidate == guess else ())
        if got:
            return got + (candidate,)
    return None


if __name__ == "__main__":                                  # manual check
    import sys

    for arg in sys.argv[1:]:
        # Works for either: a station page is tried first, a stream URL falls
        # through to the icy/Icecast/host guesses.
        found = station_logo(arg, site=arg)
        if found:
            data, url, page = found
            print(f"{arg}\n  page {page}\n  logo {url} "
                  f"({len(data)} bytes, {image_size(data)})")
        else:
            print(f"{arg}\n  no logo found")
