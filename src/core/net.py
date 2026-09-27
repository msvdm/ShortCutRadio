"""The one door to the network for Add Stream and the logo hunt.

Stdlib only and blocking; callers run on worker threads. Everything that can
go wrong on the wire raises one of NET_ERRORS, which callers turn into "found
nothing" -- network trouble is never an error the author has to see.
"""

import http.client
import json
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TIMEOUT = 8
NET_ERRORS = (OSError, ValueError, http.client.HTTPException)


def open_url(url, extra=None):
    headers = {"User-Agent": UA, "Accept": "*/*", "Icy-MetaData": "1"}
    headers.update(extra or {})
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def read_json(url, limit, extra=None):
    """The parsed JSON at `url`, read up to `limit` bytes. Raises NET_ERRORS."""
    with open_url(url, extra) as resp:
        return json.loads(resp.read(limit).decode("utf-8", "replace"))


def icecast_sources(stream_url):
    """The mounts an Icecast server lists in its status-json.xsl, or [].

    Icecast hands back a single dict instead of a list when it has only one
    mount; this always returns a list of dicts.
    """
    try:
        p = urllib.parse.urlsplit(stream_url)
        data = read_json(f"{p.scheme}://{p.netloc}/status-json.xsl", 512 * 1024)
    except NET_ERRORS:
        return []
    return parse_icecast(data)


def parse_icecast(data):
    sources = data.get("icestats", {}).get("source", []) if isinstance(data, dict) else []
    if isinstance(sources, dict):
        sources = [sources]
    return [s for s in sources if isinstance(s, dict)]
