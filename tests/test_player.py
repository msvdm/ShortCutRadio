import json
import os
import random

from src.core import levels
from src.core.config import (Config, normalize_theme, opacity_from_percent,
                              transparency_percent)
from src.core.mpris import metadata, player_props
from src.core.nowplaying import key_for, playback_status, titles
from src.core.player import EMPTY_STATE, PlayerState, make_state, now_playing, volume_gain
from src.core.sources import art_label, folder_tracks


def test_folder_tracks(tmp_path):
    (tmp_path / "b").mkdir()
    for f in ("a.mp3", "b/c.FLAC", "cover.jpg", "notes.txt", "d.ogg"):
        (tmp_path / f).write_bytes(b"")
    tracks = [os.path.relpath(p, tmp_path).replace(os.sep, "/")
              for p in folder_tracks(str(tmp_path))]
    assert tracks == ["a.mp3", "d.ogg", "b/c.FLAC"]
    shuffled = folder_tracks(str(tmp_path), shuffle=True, rng=random.Random(1))
    assert sorted(shuffled) == sorted(folder_tracks(str(tmp_path)))


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
    assert titles(playing) == ("Artist - Song", "Fluid") and titles(paused) == ("Fluid", "")
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


def test_state_phase_follows_one_ladder():
    stream = {"name": "Fluid", "kind": "stream", "target": "https://x/fluid"}
    folder = {"name": "Music", "kind": "folder", "target": "/m"}

    def state(src=stream, count=1, error="", **props):
        return make_state(src, 0, count, error=error, volume=70, **props)

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
    assert on.tile == "Fluid" and tracks.tile == "m"        # from the address
