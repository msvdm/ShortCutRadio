import random

from src.core.config import normalize_theme, opacity_from_percent, transparency_percent
from src.core.hotkeys import has_modifier, make_combo, parse_combo, pretty
from src.core.player import now_playing
from src.core.scraper import clean_name, harvest, looks_streamy, name_from_url, parse_playlist
from src.core.sources import folder_tracks

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
