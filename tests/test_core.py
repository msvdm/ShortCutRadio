import base64
import json
import os
import random
import struct
import time

import pytest

from src.core import levels
from src.core.artfetch import (image_size, logo_candidates, mentions, name_tokens,
                               site_for_stream)
from src.core.config import (Config, normalize_theme, opacity_from_percent,
                              transparency_percent)
from src.core.coverart import cover_file, embedded_art
from src.core import hotkeys
from src.core.hotkeys import (Hotkeys, all_bindings, has_modifier, is_media, make_combo,
                              parse_combo, pretty, source_action, source_index,
                              works_everywhere)
from src.core.keygrab import keysym_for
from src.core.keygrab_win import LLKHF_UP, KeyHook, vk_name
from src.core.net import parse_icecast, same_site, site_of
from src.core.player import (EMPTY_STATE, PlayerState, make_state, now_playing,
                             volume_gain)
from src.core.relay import IcyStripper, OggReader, comment_title, stream_title
from src.core.mpris import key_for, metadata, playback_status, player_props
from src.core.scraper import (Found, clean_name, harvest, looks_streamy, origin_site,
                              parse_playlist, strip_referrer)
from src.core.sources import art_label, folder_tracks, name_from_url
# QImage needs no QApplication, so the art maths can be tested like the rest.
from src.gui.art import content_box, monogram
from src.gui.overlay import pick_screen
from src.gui.overlay_page import positions

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
    tracks = [os.path.relpath(p, tmp_path).replace(os.sep, "/")
              for p in folder_tracks(str(tmp_path))]
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
# are handed to Hotkeys directly, exactly as pynput would deliver them. Only
# where pynput is the listener: Windows has its own hook (tested further down).
keyboard = hotkeys.keyboard
pynput_only = pytest.mark.skipif(keyboard is None, reason="pynput is not the listener here")
if keyboard is not None:
    CTRL, ALT = keyboard.Key.ctrl_l, keyboard.Key.alt_l


def _hotkeys(media=False, **bindings):
    hk = Hotkeys(bindings, media_via_desktop=media)
    hk.grabber.available = False
    fired = []
    hk.triggered.connect(fired.append)
    return hk, fired


def _tap(hk, *keys):
    """As pynput 1.8 calls back: (key, injected)."""
    for k in keys:
        hk._press(k, False)
    for k in reversed(keys):
        hk._release(k, False)


@pynput_only
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


@pynput_only
def test_volume_still_rides_the_repeat():
    hk, fired = _hotkeys(vol_up="]")
    hk.live = True
    for _ in range(3):
        hk._press(keyboard.KeyCode(char="]", vk=93))
        time.sleep(0.1)
    assert fired == ["vol_up"] * 3


@pynput_only
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


def test_only_a_combo_that_types_nothing_works_everywhere():
    assert works_everywhere("ctrl+e") and works_everywhere("alt+shift+k")
    assert works_everywhere("media_play_pause")
    assert not works_everywhere("'") and not works_everywhere("shift+e")


@pynput_only
def test_everywhere_needs_no_overlay_but_a_modifier():
    hk, fired = _hotkeys(overlay="ctrl+alt+r", play_pause="ctrl+e", source_next="'")
    grabbed = []

    def set_combos(combos):
        grabbed[:] = [c[0] for c in combos]
    hk.grabber.set_combos = set_combos
    hk.everywhere = True                       # the overlay stays off
    assert sorted(grabbed) == ["ctrl+alt+r", "ctrl+e"]
    assert hk.idle("'") and not hk.idle("ctrl+e") and not hk.idle("ctrl+alt+r")
    _tap(hk, CTRL, keyboard.KeyCode(char="e", vk=101))
    _tap(hk, keyboard.KeyCode(char="'", vk=39))
    assert fired == ["play_pause"]
    hk.everywhere = False                       # back to the overlay rule
    assert grabbed == ["ctrl+alt+r"] and not hk.idle("'")
    _tap(hk, CTRL, keyboard.KeyCode(char="e", vk=101))
    assert fired == ["play_pause"]


@pynput_only
def test_a_key_outside_latin1_is_grabbed_by_its_keysym():
    assert keysym_for("e") == ord("e")          # Latin-1: the code point is it
    assert keysym_for("\u0435") == 1077        # Cyrillic e: not a keysym at all
    assert keysym_for("\u0435", 1765) == 1765  # what the listener saw instead
    hk, _ = _hotkeys(overlay="alt+shift+\u0435")
    _tap(hk, ALT, keyboard.KeyCode(char="\u0435", vk=1765))
    assert hk.keysyms == {"\u0435": 1765}


def test_a_bare_media_key_is_the_desktops():
    assert is_media("media_play_pause") and is_media("media_stop")
    assert not is_media("ctrl+media_next")      # the desktop binds the bare key
    assert not is_media("media_volume_up")      # volume stays the system's
    assert not is_media("e")


@pynput_only
def test_media_keys_come_from_the_desktop_not_the_listener(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    hk, fired = _hotkeys(media=True, play_pause="media_play_pause",
                         source_next="ctrl+media_next", track_next=".")
    grabbed = []
    hk.grabber.set_combos = lambda combos: grabbed.extend(c[0] for c in combos)
    hk.live = True
    assert grabbed == ["ctrl+media_next", "."]  # the desktop holds the bare key
    assert hk.media_keys() == {"media_play_pause"}
    assert hk.via_desktop("media_play_pause") and not hk.via_desktop(".")
    _tap(hk, keyboard.Key.media_play_pause)     # heard, but not acted on:
    assert fired == []                          # the desktop's call is the one
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]
    hk.press_media("media_next")                # bound only with Ctrl
    assert fired == ["play_pause"]
    hk.live = False                             # the overlay rule still holds
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]


@pynput_only
def test_capturing_a_media_key_does_not_also_press_it(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    hk, fired = _hotkeys(media=True, play_pause="media_play_pause")
    hk.live = True
    captured = []
    hk.captured.connect(captured.append)
    hk.begin_capture()
    _tap(hk, keyboard.Key.media_play_pause)
    assert captured == ["media_play_pause"]
    clock[0] += 0.1                             # the desktop's call, right after
    hk.press_media("media_play_pause")
    assert fired == []
    clock[0] += 2
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]


@pynput_only
def test_holding_a_media_key_toggles_once(monkeypatch):
    # The desktop repeats a held key as a stream of calls with no release;
    # the listener, which hears the key too, is what marks them as repeats.
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    hk, fired = _hotkeys(media=True, play_pause="media_play_pause")
    hk.live = True
    play = keyboard.Key.media_play_pause
    hk._press(play)
    hk.press_media("media_play_pause")
    clock[0] += 0.5
    for _ in range(30):
        hk._press(play)
        hk.press_media("media_play_pause")
        clock[0] += 0.03
    hk._release(play)
    hk.press_media("media_play_pause")      # the last repeat's call, late
    assert fired == ["play_pause"]
    clock[0] += 0.3
    hk._press(play)
    hk.press_media("media_play_pause")
    assert fired == ["play_pause", "play_pause"]


@pynput_only
def test_without_the_desktop_media_keys_are_plain_shortcuts():
    hk, fired = _hotkeys(play_pause="media_play_pause")
    hk.live = True
    assert not hk.via_desktop("media_play_pause")
    _tap(hk, keyboard.Key.media_play_pause)
    assert fired == ["play_pause"]


# The Windows hook: the same Hotkeys, fed raw key events the way the hook
# procedure hands them over. The system calls (layout, held modifiers, the
# mask key) are stood in for, so this runs on every platform.
VK = {"ctrl": 0xA2, "alt": 0xA4, "e": 0x45, "r": 0x52, "]": 0xDD, "[": 0xDB,
      "esc": 0x1B, "media_play_pause": 0xB3}
CHARS = {0x45: "E", 0x52: "R", 0xDD: "]", 0xDB: "["}


def _hooked(monkeypatch, **bindings):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    hk = Hotkeys(bindings)
    fired, masks, held = [], [], set()
    hk.triggered.connect(fired.append)
    hook = KeyHook(lambda *a: hk._handle(*a, time.monotonic()))
    hook._name = lambda vk, scan, flags: vk_name(vk, CHARS.get(vk, ""))
    hook._mods = lambda: set(held)
    hook._mask = lambda: masks.append(1)

    def key(name, up=False):
        """One event; True when the hook keeps it from the focused app."""
        if name in ("ctrl", "alt"):
            (held.discard if up else held.add)(name)
        return hook.event(VK[name], 0, LLKHF_UP if up else 0)
    return hk, key, fired, masks, clock


def test_windows_hook_takes_live_keys_only(monkeypatch):
    hk, key, fired, masks, _ = _hooked(monkeypatch, overlay="ctrl+alt+r", vol_up="]")
    assert not key("]") and not key("]", up=True)   # overlay off: Notepad gets ]
    assert fired == []
    key("ctrl"), key("alt")
    assert key("r") and key("r", up=True)           # the toggle is always ours ...
    assert not key("alt", up=True) and not key("ctrl", up=True)
    assert fired == ["overlay"]
    assert masks == [1]     # ... and Alt's lone release must not open a menu bar
    hk.live = True
    assert key("]") and key("]", up=True)           # overlay on: ] is ours
    assert not key("e") and not key("e", up=True)   # an unbound key never is
    assert fired == ["overlay", "vol_up"]


def test_windows_hook_everywhere_takes_combos_only(monkeypatch):
    hk, key, fired, _, clock = _hooked(monkeypatch, play_pause="ctrl+e", vol_up="]",
                                       source_next="media_play_pause")
    hk.everywhere = True                        # the overlay stays off
    key("ctrl")
    assert key("e") and key("e", up=True)       # Ctrl+E is ours, overlay or not
    key("ctrl", up=True)
    assert not key("]") and not key("]", up=True)   # a single key still types
    assert key("media_play_pause")              # a media key types nothing
    assert fired == ["play_pause", "source_next"]


def test_windows_hook_knows_a_repeat_from_the_release(monkeypatch):
    hk, key, fired, _, clock = _hooked(monkeypatch, play_pause="ctrl+e", vol_up="]")
    hk.live = True
    key("ctrl")
    assert key("e")
    clock[0] += 0.5
    for _ in range(20):         # held: presses with no release in between
        assert key("e")         # every repeat is still kept from the app
        clock[0] += 0.03
    key("e", up=True)
    assert fired == ["play_pause"]
    clock[0] += 0.3
    key("e")                    # a new press after the release is not a repeat
    assert fired == ["play_pause"] * 2
    key("e", up=True), key("ctrl", up=True)
    key("]")
    for _ in range(10):         # volume rides the repeat, at its own pace
        clock[0] += 0.1
        key("]")
    assert fired.count("vol_up") == 11


def test_windows_hook_capture_takes_the_key(monkeypatch):
    hk, key, fired, _, _ = _hooked(monkeypatch, play_pause="media_play_pause")
    captured = []
    hk.captured.connect(captured.append)
    hk.begin_capture()
    assert key("esc")           # Esc cancels the capture, not the window
    assert captured == ["esc"] and fired == []
    hk.live = True
    assert key("media_play_pause")      # a media key is an ordinary key here
    assert fired == ["play_pause"]


def test_a_source_key_is_an_action_by_index():
    srcs = [{"name": "a"}, {"name": "b", "shortcut": "ctrl+2"}, {"name": "c", "shortcut": ""}]
    got = all_bindings({"vol_up": "]", "play_pause": ""}, srcs)
    assert got == {"vol_up": "]", "play_pause": "", "source:1": "ctrl+2"}
    assert source_index(source_action(3)) == 3
    assert source_index("vol_up") is None and source_index("source:x") is None


def test_a_source_key_follows_the_overlay_rule(monkeypatch):
    hk, key, fired, _, _ = _hooked(monkeypatch, **{"source:0": "]", "source:1": "ctrl+e"})
    assert not key("]") and not key("]", up=True)   # overlay off: the app gets ]
    hk.live = True
    assert key("]") and key("]", up=True)
    assert fired == ["source:0"]
    hk.live = False
    hk.everywhere = True                # a single key waits, a combo works
    assert hk.idle("]") and not hk.idle("ctrl+e")
    assert not key("]")
    key("ctrl")
    assert key("e")
    assert fired == ["source:0", "source:1"]


def test_ending_a_capture_frees_the_next_key(monkeypatch):
    hk, key, fired, _, _ = _hooked(monkeypatch, vol_up="]")
    hk.live = True
    hk.begin_capture()
    hk.end_capture()                    # a popup closed while recording
    assert key("]") and fired == ["vol_up"]


class _Screen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def test_the_card_falls_back_to_the_main_monitor():
    main, side = _Screen(r"\\.\DISPLAY1"), _Screen(r"\\.\DISPLAY2")
    assert pick_screen(r"\\.\DISPLAY2", [main, side], main) is side
    assert pick_screen(r"\\.\DISPLAY2", [main], main) is main   # unplugged
    assert pick_screen("", [main, side], main) is main


def test_positions_name_the_monitor_only_when_there_are_two():
    main, side = _Screen("A"), _Screen("B")
    assert [p[0] for p in positions([main])] == [
        "Top right", "Top left", "Bottom right", "Bottom left"]
    both = positions([main, side])
    assert len(both) == 8
    assert both[0] == ("Monitor 1 · Top right", "", "top-right")    # the main one
    assert both[7] == ("Monitor 2 · Bottom left", "B", "bottom-left")


def test_windows_key_names_follow_pynput():
    assert vk_name(0xB3) == "media_play_pause" and vk_name(0xB2) == "media_stop"
    assert vk_name(0x78) == "f9" and vk_name(0x22) == "page_down"
    assert vk_name(0x45, "E") == "e" and vk_name(0xDE, "'") == "'"
    assert vk_name(0x67, "7") == "7"
    assert vk_name(0xE8) == "vk232"


def test_mpris_speaks_for_the_player_state():
    playing = PlayerState(count=2, index=1, name="Fluid", kind="stream", loaded=True,
                          track="Artist - Song", volume=70)
    paused = PlayerState(count=2, name="Fluid", kind="stream", loaded=True, paused=True)
    assert playback_status(playing) == "Playing"
    assert playback_status(PlayerState(count=1, loaded=True, connecting=True)) == "Playing"
    assert playback_status(paused) == "Paused"
    assert playback_status(PlayerState(count=1)) == "Stopped"
    assert playback_status(EMPTY_STATE) == "Stopped"
    assert metadata(playing, "file:///a.png") == {
        "mpris:trackid": "/org/shortcutradio/source1", "xesam:title": "Artist - Song",
        "xesam:artist": ["Fluid"], "mpris:artUrl": "file:///a.png"}
    # No track: the station is the title, and no empty artist list goes out.
    assert metadata(paused) == {"mpris:trackid": "/org/shortcutradio/source0",
                                "xesam:title": "Fluid"}
    props = player_props(playing, {"media_play_pause", "media_next"})
    assert props["CanPlay"] and props["CanGoNext"] and not props["CanGoPrevious"]
    assert props["Volume"] == 0.7 and props["CanSeek"] is False


def test_mpris_methods_become_keys():
    assert key_for("PlayPause", True) == "media_play_pause"
    assert key_for("Play", False) == "media_play_pause"
    assert key_for("Play", True) is None        # the applet's Play never pauses
    assert key_for("Pause", False) is None
    assert key_for("Next", False) == "media_next"
    assert key_for("Previous", True) == "media_previous"
    assert key_for("Seek", True) is None


def test_now_playing():
    assert now_playing({"artist": "A", "title": "T"}, "/m/x.flac", "folder") == "A – T"
    assert now_playing({"title": "T"}, "/m/x.flac", "folder") == "T"
    assert now_playing({}, "/m/x.flac", "folder") == "x"
    url = "https://ice1.somafm.com/groovesalad-128-mp3"
    assert now_playing({"title": "Song"}, url, "stream") == "Song"
    assert now_playing({"title": "groovesalad-128-mp3"}, url, "stream") == ""
    assert now_playing({"title": url}, url, "stream") == ""
    assert now_playing({}, url, "stream") == ""


def test_volume_is_cubic_and_capped():
    assert volume_gain(100) == 1.0 and volume_gain(0) == 0.0
    assert volume_gain(50) == 0.125
    assert volume_gain(130) == 1.0


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


def test_site_of_finds_the_registered_name():
    assert site_of("https://ice6.somafm.com/fluid-128-mp3") == "somafm.com"
    assert site_of("https://www.bbc.co.uk/sounds") == "bbc.co.uk"
    assert same_site("https://somafm.com/fluid/", "http://somafm.com")
    assert not same_site("https://www.predavatel.com/bg/live/", "https://www.radio1.bg/")
    assert not same_site("", "")


DIRECTORY = "https://www.predavatel.com/bg/live/"
STW = "https://playerservices.streamtheworld.com/api/livestream-redirect/RADIO_1AAC_H.aac"


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


IDLE_PROPS = {"loaded": False, "paused": False, "ready": False, "volume": 70,
              "meta": {}, "path": None, "icy_url": "", "track_index": None,
              "track_count": 0}


def test_state_phase_follows_one_ladder():
    stream = {"name": "Fluid", "kind": "stream", "target": "https://x/fluid"}
    folder = {"name": "Music", "kind": "folder", "target": "/m"}

    def state(src=stream, count=1, error="", **props):
        return make_state({**IDLE_PROPS, **props}, 0, src, count, error)

    playing = {"loaded": True, "ready": True}
    assert EMPTY_STATE.phase == "empty"
    assert state(src=None, count=0).phase == "empty"
    assert state(error="Reconnecting…", **playing).phase == "error"
    assert state().phase == "stopped"
    paused = state(paused=True, **playing)
    assert paused.phase == "paused" and paused.playing is False
    connecting = state(loaded=True)
    assert connecting.phase == "connecting" and not connecting.audible
    on = state(**playing)
    assert on.phase == "playing" and on.audible and on.playing
    assert not on.can_skip_track
    tracks = state(src=folder, path="/m/a.mp3", track_index=2, track_count=9, **playing)
    assert tracks.can_skip_track and (tracks.track_pos, tracks.track_count) == (3, 9)
    assert tracks.track == "a"
    assert state().track == "" and state().path is None     # nothing loaded


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
