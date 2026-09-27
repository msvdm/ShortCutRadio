import base64
import json
import random
import time

import pytest

from src.core import levels
from src.core.artfetch import (image_size, logo_candidates, mentions, name_tokens,
                               site_for_stream)
from src.core.config import (Config, normalize_theme, opacity_from_percent,
                              transparency_percent)
from src.core.coverart import cover_file, embedded_art
from src.core.hotkeys import Hotkeys, has_modifier, make_combo, parse_combo, pretty
from src.core.keygrab import keysym_for
from src.core.net import parse_icecast
from src.core.player import EMPTY_STATE, make_state, now_playing
from src.core.scraper import clean_name, harvest, looks_streamy, parse_playlist
from src.core.sources import art_label, folder_tracks, name_from_url
# QImage needs no QApplication, so the art maths can be tested like the rest.
from src.gui.art import content_box, monogram

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


def test_folder_tracks(tmp_path):
    (tmp_path / "b").mkdir()
    for f in ("a.mp3", "b/c.FLAC", "cover.jpg", "notes.txt", "d.ogg"):
        (tmp_path / f).write_bytes(b"")
    tracks = [p.replace(str(tmp_path) + "/", "") for p in folder_tracks(str(tmp_path))]
    assert tracks == ["a.mp3", "d.ogg", "b/c.FLAC"]
    shuffled = folder_tracks(str(tmp_path), shuffle=True, rng=random.Random(1))
    assert sorted(shuffled) == sorted(folder_tracks(str(tmp_path)))


def test_combos():
    assert parse_combo("ctrl+alt+r") == ({"ctrl", "alt"}, "r")
    assert parse_combo("ctrl++") == ({"ctrl"}, "+")
    assert make_combo({"alt", "ctrl"}, "r") == "ctrl+alt+r"
    assert has_modifier("ctrl+alt+r") and not has_modifier("'") and not has_modifier("shift+e")
    assert pretty("ctrl+alt+r") == "Ctrl+Alt+R" and pretty("page_down") == "Page Down"


# The listener itself needs a keyboard; its bookkeeping does not, so the keys
# are handed to Hotkeys directly, exactly as pynput would deliver them.
keyboard = pytest.importorskip("pynput.keyboard")
CTRL, ALT = keyboard.Key.ctrl_l, keyboard.Key.alt_l


def _hotkeys(**bindings):
    hk = Hotkeys(bindings)
    hk.grabber.available = False
    fired = []
    hk.triggered.connect(fired.append)
    return hk, fired


def _tap(hk, *keys):
    for k in keys:
        hk._press(k)
    for k in reversed(keys):
        hk._release(k)


def test_auto_repeat_does_not_repeat_the_action(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    hk, fired = _hotkeys(play_pause="ctrl+e", vol_up="]")
    hk.live = True
    hk._press(CTRL)
    e = keyboard.KeyCode(char="e", vk=101)
    hk._press(e)
    clock[0] += 0.5             # X waits half a second before it repeats ...
    hk._press(e)
    for _ in range(20):         # ... then repeats as presses, with no release
        clock[0] += 0.03
        hk._press(e)
    hk._release(e)
    hk._release(CTRL)
    assert fired == ["play_pause"]
    clock[0] += 0.3             # a real second press is not a repeat
    hk._press(CTRL)
    hk._press(e)
    assert fired == ["play_pause", "play_pause"]


def test_volume_still_rides_the_repeat():
    hk, fired = _hotkeys(vol_up="]")
    hk.live = True
    for _ in range(3):
        hk._press(keyboard.KeyCode(char="]", vk=93))
        time.sleep(0.1)
    assert fired == ["vol_up"] * 3


def test_only_the_overlay_key_works_with_the_overlay_off():
    hk, fired = _hotkeys(overlay="ctrl+alt+r", play_pause="ctrl+e", source_next="e")
    _tap(hk, CTRL, keyboard.KeyCode(char="e", vk=101))
    _tap(hk, keyboard.KeyCode(char="e", vk=101))
    assert fired == []
    _tap(hk, CTRL, ALT, keyboard.KeyCode(char="r", vk=114))
    assert fired == ["overlay"]
    hk.live = True
    _tap(hk, CTRL, keyboard.KeyCode(char="e", vk=101))
    assert fired == ["overlay", "play_pause"]


def test_a_key_outside_latin1_is_grabbed_by_its_keysym():
    assert keysym_for("e") == ord("e")          # Latin-1: the code point is it
    assert keysym_for("\u0435") == 1077        # Cyrillic e: not a keysym at all
    assert keysym_for("\u0435", 1765) == 1765  # what the listener saw instead
    hk, _ = _hotkeys(overlay="alt+shift+\u0435")
    _tap(hk, ALT, keyboard.KeyCode(char="\u0435", vk=1765))
    assert hk.keysyms == {"\u0435": 1765}


def test_now_playing():
    assert now_playing({"ARTIST": "A", "TITLE": "T"}, "", "/m/x.flac", "folder") == "A – T"
    assert now_playing({}, "x", "/m/x.flac", "folder") == "x"
    url = "https://ice1.somafm.com/groovesalad-128-mp3"
    assert now_playing({"icy-title": "Song"}, "", url, "stream") == "Song"
    assert now_playing({}, "groovesalad-128-mp3", url, "stream") == ""


def test_transparency_percent():
    assert transparency_percent(0.55) == 45
    assert transparency_percent(1) == 0
    assert transparency_percent("junk") == 45
    assert opacity_from_percent(45) == 0.55
    assert opacity_from_percent(150) == 0.0


def test_normalize_theme():
    assert normalize_theme("dark") == "dark"
    assert normalize_theme("light") == "light"
    assert normalize_theme("auto") == "auto"
    assert normalize_theme("") == "auto"
    assert normalize_theme(None) == "auto"


# --------------------------------------------------------------- level meter
def test_levels_stay_in_range_and_move():
    rng = random.Random(7)
    values, targets = levels.new_levels(4), levels.new_targets(4, rng)
    seen = set()
    for tick in range(60):
        values, targets = levels.step(values, targets, tick, rng)
        assert all(levels.FLOOR <= v <= 1.0 for v in values)
        seen.add(tuple(round(v, 3) for v in values))
    assert len(seen) > 40, "the bars have to actually move"


class _Quiet:
    """An rng that always aims at the floor, so the decay can be measured."""

    def uniform(self, low, _high):
        return low


def test_levels_decay_towards_a_quiet_target():
    values, targets = [1.0, 1.0], [levels.FLOOR] * 2
    for tick in range(40):
        values, targets = levels.step(values, targets, tick, _Quiet())
    assert all(abs(v - levels.FLOOR) < 0.01 for v in values)


# ------------------------------------------------------------ station logos
def test_site_for_stream_drops_the_streaming_label():
    assert site_for_stream("https://streams.badrockradio.net/hard-heavy") == \
        "https://badrockradio.net/"
    assert site_for_stream("https://ice6.somafm.com/fluid-128-mp3") == "https://somafm.com/"
    assert site_for_stream("http://radio.rn-tv.com:8000/stream/3/") == \
        "https://radio.rn-tv.com/"
    assert site_for_stream("https://binar.bg/live") == "https://binar.bg/"
    assert site_for_stream("not a url") == ""


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


# ---------------------------------------------------------------- cover art
def test_cover_file_beside_the_track_then_at_the_root(tmp_path):
    album = tmp_path / "Album" / "CD1"
    album.mkdir(parents=True)
    track = album / "01.mp3"
    track.write_bytes(b"")
    assert cover_file(str(track), str(tmp_path / "Album")) is None
    (tmp_path / "Album" / "folder.jpg").write_bytes(b"x")
    assert cover_file(str(track), str(tmp_path / "Album")).endswith("folder.jpg")
    (album / "Cover.PNG").write_bytes(b"x")          # beside the track wins
    assert cover_file(str(track), str(tmp_path / "Album")).endswith("Cover.PNG")


PICTURE = b"\x89PNG\r\n\x1a\nPRETENDTHISISAPICTURE"


def _picture_block(ptype=3, mime=b"image/png"):
    """A METADATA_BLOCK_PICTURE body, as FLAC and Ogg both store it."""
    return (ptype.to_bytes(4, "big")
            + len(mime).to_bytes(4, "big") + mime
            + (0).to_bytes(4, "big")                 # empty description
            + b"\x00" * 16                           # width, height, depth, colours
            + len(PICTURE).to_bytes(4, "big") + PICTURE)


def _syncsafe(n):
    return bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))


def test_id3_apic_prefers_the_front_cover(tmp_path):
    def frame(ptype, data):
        body = b"\x00" + b"image/png\x00" + bytes((ptype,)) + b"\x00" + data
        return b"APIC" + len(body).to_bytes(4, "big") + b"\x00\x00" + body

    tag = frame(4, b"BACKCOVER") + frame(3, PICTURE)     # front cover comes second
    mp3 = tmp_path / "t.mp3"
    mp3.write_bytes(b"ID3\x03\x00\x00" + _syncsafe(len(tag)) + tag + b"\xff\xfb")
    assert embedded_art(str(mp3)) == PICTURE


def test_flac_picture_block(tmp_path):
    block = _picture_block()
    flac = tmp_path / "t.flac"
    flac.write_bytes(b"fLaC"
                     + b"\x00" + (4).to_bytes(3, "big") + b"\x00" * 4     # STREAMINFO
                     + b"\x86" + len(block).to_bytes(3, "big") + block)   # last PICTURE
    assert embedded_art(str(flac)) == PICTURE


def _ogg_page(body, seq):
    """One Ogg page. The reader ignores the CRC, so zeros will do."""
    segments = [body[i:i + 255] for i in range(0, len(body), 255)] or [b""]
    table = bytes(len(s) for s in segments)
    return (b"OggS\x00\x00" + b"\x00" * 8 + b"\x00" * 4
            + seq.to_bytes(4, "little") + b"\x00" * 4
            + bytes((len(table),)) + table + b"".join(segments))


def test_ogg_picture_stitched_back_across_pages(tmp_path):
    comment = b"METADATA_BLOCK_PICTURE=" + base64.b64encode(_picture_block())
    half = len(comment) // 2
    ogg = tmp_path / "t.opus"
    # The comment header is long enough to span pages, which is the whole
    # reason the page bodies have to be joined before searching.
    ogg.write_bytes(_ogg_page(b"OpusHead" + b"\x00" * 11, 0)
                    + _ogg_page(comment[:half], 1)
                    + _ogg_page(comment[half:], 2))
    assert embedded_art(str(ogg)) == PICTURE


def test_a_broken_file_is_not_an_error(tmp_path):
    junk = tmp_path / "t.mp3"
    junk.write_bytes(b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + b"\x00" * 40)
    assert embedded_art(str(junk)) is None
    assert embedded_art(str(tmp_path / "missing.flac")) is None
    assert embedded_art("/etc/hostname") is None        # not an audio extension


# ------------------------------------------------------------- art fitting
def _image(w, h, bg, box=None):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(bg) if bg else QColor(0, 0, 0, 0))
    if box:
        x0, y0, x1, y1 = box
        for x in range(x0, x1):
            for y in range(y0, y1):
                img.setPixelColor(x, y, QColor("#c01818"))
    return img


def test_content_box_trims_a_flat_border():
    # A logo published inside a lot of white, the usual case.
    assert content_box(_image(100, 100, "#ffffff", (30, 25, 70, 75))) == (30, 25, 40, 50)
    # The same shape on nothing at all: transparency trims too.
    assert content_box(_image(100, 100, None, (30, 25, 70, 75))) == (30, 25, 40, 50)


def test_content_box_leaves_a_full_picture_alone():
    # Content right up to the edge: nothing to trim.
    assert content_box(_image(80, 80, "#ffffff", (0, 0, 79, 79))) == (0, 0, 80, 80)
    assert content_box(_image(80, 80, "#ffffff")) is None       # nothing but border
    assert content_box(_image(80, 80, "#c01818", (0, 0, 80, 80))) is None   # one colour
    assert content_box(_image(2, 2, "#ffffff")) is None         # too small to judge


def test_content_box_never_eats_the_whole_picture():
    # A gradient-ish edge must not let the trim run away: it stops at TRIM_MAX.
    box = content_box(_image(100, 100, "#ffffff", (48, 48, 52, 52)))
    assert box is not None and box[0] <= 42 and box[1] <= 42


def test_monogram():
    assert monogram("БНР Бургас") == "ББ"          # not just ASCII
    assert monogram("SomaFM Fluid") == "SF"
    assert monogram("Drum & Bass") == "DB"         # "&" is not a word
    assert monogram("Burgas") == "BU"              # one word gives two letters
    assert monogram("Fluid 128") == "FL"           # a number is not an initial
    assert monogram("") == "?"


# ------------------------------------------------- art follows the address
def _stream(url):
    return art_label({"name": "whatever", "kind": "stream", "target": url})


def test_art_label_comes_from_the_address():
    assert _stream("https://lb-hls.cdn.bg/2032/fls/Burgas.stream/playlist.m3u8") == "Burgas"
    assert _stream("https://streams.badrockradio.net/hard-heavy") == "Hard Heavy"
    assert _stream("https://ice6.somafm.com/fluid-128-mp3") == "Fluid"   # bitrate trimmed
    # Nothing usable in the path: fall back to the site's own label.
    assert _stream("http://radio.rn-tv.com:8000/stream/3/") == "rn-tv"
    assert _stream("https://nova-radio.neterra.tv/") == "neterra"
    assert art_label({"kind": "folder", "target": "/home/m/Music/Drum & Bass/"}) == "Drum & Bass"
    assert art_label(None) == ""


def test_renaming_a_source_does_not_change_its_art():
    src = {"name": "БНР Бургас", "kind": "stream", "shuffle": False,
           "target": "https://lb-hls.cdn.bg/2032/fls/Burgas.stream/playlist.m3u8"}
    before = art_label(src)
    src["name"] = "something else entirely"
    assert art_label(src) == before
    folder = {"name": "Drum & Bass", "kind": "folder", "target": "/m/dnb"}
    was = art_label(folder)
    folder["name"] = "renamed"
    assert art_label(folder) == was


def test_config_drops_unusable_sources_and_odd_themes(tmp_path):
    good = {"name": "Fluid", "kind": "stream", "target": "https://x/fluid"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": "purple", "sources": [
        good, {"name": "no target", "kind": "stream"}, "junk",
        {"name": "odd kind", "kind": "video", "target": "x"}]}))
    cfg = Config(str(path))
    assert cfg["sources"] == [good]
    assert cfg["theme"] == "auto"
    path.write_text(json.dumps({"sources": {"not": "a list"}}))
    assert Config(str(path))["sources"] == []


def test_icecast_status_with_one_mount_is_still_a_list():
    one = {"listenurl": "http://h:8000/a", "server_url": "https://a.fm"}
    assert parse_icecast({"icestats": {"source": one}}) == [one]
    assert parse_icecast({"icestats": {"source": [one, "junk"]}}) == [one]
    assert parse_icecast({"icestats": {}}) == []
    assert parse_icecast([]) == []


IDLE_PROPS = {"metadata": None, "media-title": None, "path": None, "pause": False,
              "volume": 70, "playlist-pos": None, "playlist-count": 0,
              "core-idle": True, "idle-active": True}


def test_state_phase_follows_one_ladder():
    stream = {"name": "Fluid", "kind": "stream", "target": "https://x/fluid"}
    folder = {"name": "Music", "kind": "folder", "target": "/m"}

    def state(src=stream, count=1, error="", **props):
        return make_state({**IDLE_PROPS, **props}, 0, src, count, error)

    playing = {"idle-active": False, "core-idle": False}
    assert EMPTY_STATE.phase == "empty"
    assert state(src=None, count=0).phase == "empty"
    assert state(error="Reconnecting…", **playing).phase == "error"
    assert state().phase == "stopped"
    paused = state(pause=True, **playing)
    assert paused.phase == "paused" and paused.playing is False
    connecting = state(**{"idle-active": False})
    assert connecting.phase == "connecting" and not connecting.audible
    on = state(**playing)
    assert on.phase == "playing" and on.audible and on.playing
    assert not on.can_skip_track
    tracks = state(src=folder, path="/m/a.mp3", **{"playlist-pos": 2, "playlist-count": 9},
                   **playing)
    assert tracks.can_skip_track and (tracks.track_pos, tracks.track_count) == (3, 9)
    assert tracks.track == "a"
    assert state().track == "" and state().path is None     # nothing loaded
