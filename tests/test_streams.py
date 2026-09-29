import struct

from src.core.artfetch import (image_size, logo_candidates, mentions, name_tokens,
                               site_for_stream)
from src.core.net import parse_icecast, same_site, site_of
from src.core.relay import IcyStripper, OggReader, comment_title, stream_title
from src.core.scraper import (Found, clean_name, harvest, looks_streamy, origin_site,
                              own_scripts, parse_playlist, strip_referrer)
from src.core.sources import name_from_url


BADROCK_SNIPPET = """
<a class="ext-stream-url" href="https://streams.badrockradio.net/hard-heavy">x</a>
<a href="https://streams.badrockradio.net/hard-heavy.pls">pls</a>
<script>var s = {"url":"https:\\/\\/streams.badrockradio.net\\/golden-era"};</script>
<link href="/style.css"><a href="/about">About</a><img src="https://cdn.x.com/logo.png">
"""


def test_harvest_finds_streams_and_skips_assets():
    got = harvest(BADROCK_SNIPPET, "https://badrockradio.net/")
    assert "https://streams.badrockradio.net/hard-heavy" in got
    assert "https://streams.badrockradio.net/hard-heavy.pls" in got
    assert "https://streams.badrockradio.net/golden-era" in got
    assert not any(u.endswith((".css", ".png", "/about")) for u in got)


def test_relative_playlist_links_are_joined():
    got = harvest('<a href="/fluid130.pls">', "https://somafm.com/fluid/")
    assert got == ["https://somafm.com/fluid130.pls"]


def test_looks_streamy():
    assert looks_streamy("http://radio.rn-tv.com:8000/stream/3/")
    assert looks_streamy("https://lb-hls.cdn.bg/2032/fls/Burgas.stream/playlist.m3u8")
    assert not looks_streamy("https://binar.bg/news", "binar.bg")


def test_names():
    assert name_from_url("https://lb-hls.cdn.bg/2032/fls/Burgas.stream/playlist.m3u8") == "Burgas"
    assert name_from_url("https://streams.badrockradio.net/hard-heavy") == "Hard Heavy"
    assert clean_name("SomaFM: Fluid (#1): Drown in the electronic sound of hiphop") == "SomaFM: Fluid"


def test_parse_pls_and_m3u():
    pls = "[playlist]\nFile1=https://ice1.somafm.com/fluid-128-mp3\nTitle1=SomaFM: Fluid\nNumberOfEntries=1\n"
    assert parse_playlist(pls, "https://somafm.com/fluid.pls") == ("SomaFM: Fluid", ["https://ice1.somafm.com/fluid-128-mp3"])
    m3u = "#EXTM3U\n#EXTINF:-1,Radio\nlive.mp3\n"
    assert parse_playlist(m3u, "https://x.com/a/list.m3u") == ("Radio", ["https://x.com/a/live.mp3"])


# ------------------------------------------------------------ station logos
def test_site_for_stream_drops_the_streaming_label():
    assert site_for_stream("https://streams.badrockradio.net/hard-heavy") == \
        "https://badrockradio.net/"
    assert site_for_stream("https://ice6.somafm.com/fluid-128-mp3") == "https://somafm.com/"
    assert site_for_stream("http://radio.rn-tv.com:8000/stream/3/") == \
        "https://radio.rn-tv.com/"
    assert site_for_stream("https://binar.bg/live") == "https://binar.bg/"
    assert site_for_stream("not a url") == ""


def test_site_of_finds_the_registered_name():
    assert site_of("https://ice6.somafm.com/fluid-128-mp3") == "somafm.com"
    assert site_of("https://www.bbc.co.uk/sounds") == "bbc.co.uk"
    assert same_site("https://somafm.com/fluid/", "http://somafm.com")
    assert not same_site("https://www.predavatel.com/bg/live/", "https://www.radio1.bg/")
    assert not same_site("", "")


DIRECTORY = "https://www.predavatel.com/bg/live/"


STW = "https://playerservices.streamtheworld.com/api/livestream-redirect/RADIO_1AAC_H.aac"


def test_only_the_pages_own_scripts_are_read():
    page = ('<script src="/player.js"></script>'
            '<script src="https://cdn.somafm.com/list.js"></script>'
            '<script src="https://notsomafm.com/x.js"></script>'
            '<script src="https://www.googletagmanager.com/gtag.js"></script>')
    assert own_scripts(page, "https://somafm.com/fluid/") == [
        "https://somafm.com/player.js", "https://cdn.somafm.com/list.js"]
    # Two labels are not always the site: co.uk is everybody's.
    bbc = ('<script src="https://static.bbc.co.uk/a.js"></script>'
           '<script src="https://evil.co.uk/b.js"></script>')
    assert own_scripts(bbc, "https://www.bbc.co.uk/sounds") == ["https://static.bbc.co.uk/a.js"]


def test_a_directory_is_a_shortcut_not_the_station():
    # The stream names its own site: that beats the page it was found on.
    found = Found("RADIO_1", STW, site="https://www.radio1.bg/")
    assert origin_site(DIRECTORY, found, False) == "https://www.radio1.bg/"
    # It says nothing, and the page lists many stations: no page at all.
    hls = Found("Burgas", "https://lb-hls.cdn.bg/2032/fls/Burgas.stream/playlist.m3u8")
    assert origin_site(DIRECTORY, hls, False) == ""


def test_a_station_page_stays_the_station():
    # Same site as what the stream announces: the page is more specific.
    fluid = Found("SomaFM: Fluid", "https://ice6.somafm.com/fluid-128-aac",
                  site="http://somafm.com/")
    assert origin_site("https://somafm.com/fluid/", fluid, True) == "https://somafm.com/fluid/"
    # Silent stream on the page's own site, or the page's only station.
    own = Found("BadRock", "https://streams.badrockradio.net/national")
    assert origin_site("https://badrockradio.net/", own, False) == "https://badrockradio.net/"
    cdn = Found("Darik", "https://a12.asurahosting.com/listen/darik_radio/radio.mp3")
    assert origin_site("https://darik.bg/", cdn, True) == "https://darik.bg/"


def test_strip_referrer_drops_only_the_middle_mans_tag():
    assert strip_referrer(STW + "?dist=PREDAVATEL", DIRECTORY) == STW
    assert strip_referrer(STW + "?dist=PREDAVATEL&x=1", DIRECTORY) == STW + "?x=1"
    assert strip_referrer(STW + "?dist=radio1_web", DIRECTORY) == STW + "?dist=radio1_web"
    assert strip_referrer(STW, DIRECTORY) == STW


LOGO_PAGE = """
<link rel="stylesheet" href="/style.css">
<img src="/img/header-logo.png" class="site-logo">
<link rel="icon" href="/favicon-16.png" sizes="16x16">
<meta property="og:image" content="https://cdn.x.net/share&amp;card.jpg">
<link rel="apple-touch-icon" href="/touch.png" sizes="180x180">
"""


def test_logo_candidates_are_ordered_and_unescaped():
    got = logo_candidates(LOGO_PAGE, "https://station.example/listen/")
    assert got[0] == "https://cdn.x.net/share&card.jpg"      # the share card wins
    assert got[1] == "https://station.example/touch.png"     # then the touch icon
    assert got[2] == "https://station.example/favicon-16.png"
    assert got[3] == "https://station.example/img/header-logo.png"
    assert got[-1] == "https://station.example/favicon.ico"  # always the last resort
    assert not any(u.endswith(".css") for u in got)


def test_a_guessed_page_has_to_mention_the_station():
    assert name_tokens("БНР Хоризонт") == ["хоризонт"]      # not just ASCII
    assert name_tokens("Bad Rock Radio") == ["rock"]        # "radio" proves nothing
    assert not mentions("<title>Evolink CDN</title>", ["хоризонт"])
    assert mentions("<title>БНР Хоризонт на живо</title>", ["хоризонт"])
    assert mentions("anything at all", [])                  # nothing to check


def test_image_size_sniffing():
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
           + (400).to_bytes(4, "big") + (300).to_bytes(4, "big"))
    assert image_size(png) == (400, 300)
    assert image_size(b"GIF89a" + (64).to_bytes(2, "little")
                      + (48).to_bytes(2, "little")) == (64, 48)
    jpeg = (b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF" + b"\x00" * 10
            + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
            + (120).to_bytes(2, "big") + (160).to_bytes(2, "big"))
    assert image_size(jpeg) == (160, 120)
    assert image_size(b"<svg xmlns=...") is None


def test_icecast_status_with_one_mount_is_still_a_list():
    one = {"listenurl": "http://h:8000/a", "server_url": "https://a.fm"}
    assert parse_icecast({"icestats": {"source": one}}) == [one]
    assert parse_icecast({"icestats": {"source": [one, "junk"]}}) == [one]
    assert parse_icecast({"icestats": {}}) == []
    assert parse_icecast([]) == []


# ------------------------------------------------------------------ the relay
def test_icy_metadata_is_cut_out_of_the_audio_at_any_chunk_size():
    audio = bytes(range(256)) * 8                       # 2048 bytes
    meta = b"StreamTitle='Song';".ljust(32, b"\0")
    body = audio[:1000] + b"\x02" + meta + audio[1000:2000] + b"\x00" + audio[2000:]
    for size in (1, 7, 1000, 1001, len(body)):
        strip, out, blocks = IcyStripper(1000), b"", []
        for i in range(0, len(body), size):
            a, b = strip.feed(body[i:i + size])
            out += a
            blocks += b
        assert out == audio and blocks == [meta]


def test_stream_title():
    assert stream_title(b"StreamTitle='A - B';StreamUrl='';\0\0") == "A - B"
    assert stream_title(b"StreamTitle='Rock';n'Roll';StreamUrl='x';") == "Rock';n'Roll"
    assert stream_title(b"StreamTitle='';") == ""
    assert stream_title("StreamTitle='БНР';".encode("utf-8")) == "БНР"
    assert stream_title("StreamTitle='Café';".encode("latin-1")) == "Café"
    assert stream_title(b"StreamUrl='x';") is None


def _comments(*tags):
    out = struct.pack("<I", 6) + b"vendor" + struct.pack("<I", len(tags))
    for t in tags:
        out += struct.pack("<I", len(t.encode())) + t.encode()
    return out


def _page(packets, bos=False):
    """An Ogg page holding whole `packets` (the CRC is left blank: nobody checks)."""
    lacing, body = b"", b""
    for p in packets:
        n = len(p)
        lacing += b"\xff" * (n // 255) + bytes([n % 255])
        body += p
    return (b"OggS\x00" + bytes([2 if bos else 0]) + b"\0" * 20 + bytes([len(lacing)])
            + lacing + body)


def test_comment_title():
    assert comment_title(_comments("ARTIST=A", "TITLE=T")) == "A – T"
    assert comment_title(_comments("title=T")) == "T"
    assert comment_title(_comments("ENCODER=butt")) is None
    assert comment_title(b"\x05\x00") is None


def test_ogg_opus_passes_through_and_names_the_song():
    stream = (_page([b"OpusHead" + b"\0" * 11], bos=True)
              + _page([b"OpusTags" + _comments("ARTIST=A", "TITLE=T")])
              + _page([b"\x01" * 300, b"\x02" * 40]))
    reader, out, titles = OggReader(), b"", []
    for i in range(0, len(stream), 50):
        a, t = reader.feed(stream[i:i + 50])
        out += a
        titles += t
    assert out == stream and titles == ["A – T"]


def test_ogg_flac_is_rewrapped_as_plain_flac():
    streaminfo = b"\x00\x00\x00\x22" + bytes(range(34))
    head = b"\x7fFLAC\x01\x00\x00\x01fLaC" + streaminfo
    frame1, frame2 = b"\xff\xf8" + b"a" * 600, b"\xff\xf8" + b"b" * 30
    stream = (_page([head], bos=True)
              + _page([b"\x84" + b"\0\0\0" + _comments("TITLE=One")])
              + _page([frame1, frame2])
              # the next song: a new chain repeats the headers
              + _page([head], bos=True)
              + _page([b"\x84" + b"\0\0\0" + _comments("TITLE=Two")])
              + _page([frame2]))
    out, titles = OggReader().feed(stream)
    assert out == b"fLaC" + b"\x80" + streaminfo[1:] + frame1 + frame2 + frame2
    assert titles == ["One", "Two"]
