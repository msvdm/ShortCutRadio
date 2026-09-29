import enum
import time

from src.core import keygrab
from src.core.hotkeys import (Hotkeys, all_bindings, has_modifier, is_media, make_combo,
                              parse_combo, pretty, recorded, source_action, source_index,
                              works_everywhere)
from src.core.keygrab import XKeys, keysym_for
from src.core.keygrab_win import LLKHF_UP, KeyHook, vk_name


def test_combos():
    assert parse_combo("ctrl+alt+r") == ({"ctrl", "alt"}, "r")
    assert parse_combo("ctrl++") == ({"ctrl"}, "+")
    assert make_combo({"alt", "ctrl"}, "r") == "ctrl+alt+r"
    assert has_modifier("ctrl+alt+r") and not has_modifier("'") and not has_modifier("shift+e")
    assert pretty("ctrl+alt+r") == "Ctrl+Alt+R" and pretty("page_down") == "Page Down"


def test_only_a_combo_that_types_nothing_works_everywhere():
    assert works_everywhere("ctrl+e") and works_everywhere("alt+shift+k")
    assert works_everywhere("media_play_pause")
    assert not works_everywhere("'") and not works_everywhere("shift+e")


def test_a_bare_media_key_is_the_desktops():
    assert is_media("media_play_pause") and is_media("media_stop")
    assert not is_media("ctrl+media_next")      # the desktop binds the bare key
    assert not is_media("media_volume_up")      # volume stays the system's
    assert not is_media("e")


def test_what_a_recording_asks_for():
    assert recorded("esc") is None              # keep the old key
    assert recorded("backspace") == "" and recorded("delete") == ""
    assert recorded("ctrl+e") == "ctrl+e"


# ------------------------------------------------------------------ X11
# The listener needs a keyboard; its bookkeeping does not, so the keys are
# handed to XKeys directly, exactly as pynput would deliver them. Where pynput
# is missing (Windows), a stand-in for the two types it hands over does.
class _Keyboard:
    Key = enum.Enum("Key", ["ctrl_l", "alt_l", "media_play_pause"])

    class KeyCode:
        def __init__(self, vk=None, char=None):
            self.vk, self.char = vk, char


if keygrab.keyboard is None:
    keygrab.keyboard = _Keyboard
keyboard = keygrab.keyboard
CTRL, ALT = keyboard.Key.ctrl_l, keyboard.Key.alt_l


def _x11(media=False, **bindings):
    """Hotkeys on the X11 keyboard, whatever this platform's own is; nothing
    is grabbed for real."""
    hk = Hotkeys(bindings, media_via_desktop=media)
    xk = hk.keys = XKeys(hk.on_key)
    xk.grabber.available = False
    hk.set_bindings(bindings)           # grabbed through the new keyboard
    fired = []
    hk.triggered.connect(fired.append)
    return hk, xk, fired


def _tap(xk, *keys):
    """As pynput 1.8 calls back: (key, injected)."""
    for k in keys:
        xk._press(k, False)
    for k in reversed(keys):
        xk._release(k, False)


def _clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    return clock


def test_auto_repeat_does_not_repeat_the_action(monkeypatch):
    clock = _clock(monkeypatch)
    hk, xk, fired = _x11(play_pause="ctrl+e", vol_up="]")
    hk.live = True
    xk._press(CTRL)
    e = keyboard.KeyCode(char="e", vk=101)
    xk._press(e)
    clock[0] += 0.5             # X waits half a second before it repeats ...
    xk._press(e)
    for _ in range(20):         # ... then repeats as presses, with no release
        clock[0] += 0.03
        xk._press(e)
    xk._release(e)
    xk._release(CTRL)
    assert fired == ["play_pause"]
    clock[0] += 0.3             # a real second press is not a repeat
    xk._press(CTRL)
    xk._press(e)
    assert fired == ["play_pause", "play_pause"]


def test_volume_still_rides_the_repeat():
    hk, xk, fired = _x11(vol_up="]")
    hk.live = True
    for _ in range(3):
        xk._press(keyboard.KeyCode(char="]", vk=93))
        time.sleep(0.1)
    assert fired == ["vol_up"] * 3


def test_only_the_overlay_key_works_with_the_overlay_off():
    hk, xk, fired = _x11(overlay="ctrl+alt+r", play_pause="ctrl+e", source_next="e")
    _tap(xk, CTRL, keyboard.KeyCode(char="e", vk=101))
    _tap(xk, keyboard.KeyCode(char="e", vk=101))
    assert fired == []
    _tap(xk, CTRL, ALT, keyboard.KeyCode(char="r", vk=114))
    assert fired == ["overlay"]
    hk.live = True
    _tap(xk, CTRL, keyboard.KeyCode(char="e", vk=101))
    assert fired == ["overlay", "play_pause"]


def test_everywhere_needs_no_overlay_but_a_modifier():
    hk, xk, fired = _x11(overlay="ctrl+alt+r", play_pause="ctrl+e", source_next="'")
    grabbed = []

    def set_combos(combos):
        grabbed[:] = [c[0] for c in combos]
    xk.set_combos = set_combos
    hk.everywhere = True                       # the overlay stays off
    assert sorted(grabbed) == ["ctrl+alt+r", "ctrl+e"]
    assert hk.idle("'") and not hk.idle("ctrl+e") and not hk.idle("ctrl+alt+r")
    _tap(xk, CTRL, keyboard.KeyCode(char="e", vk=101))
    _tap(xk, keyboard.KeyCode(char="'", vk=39))
    assert fired == ["play_pause"]
    hk.everywhere = False                       # back to the overlay rule
    assert grabbed == ["ctrl+alt+r"] and not hk.idle("'")
    _tap(xk, CTRL, keyboard.KeyCode(char="e", vk=101))
    assert fired == ["play_pause"]


def test_a_key_outside_latin1_is_grabbed_by_its_keysym():
    assert keysym_for("e") == ord("e")          # Latin-1: the code point is it
    assert keysym_for("е") == 1077        # Cyrillic e: not a keysym at all
    assert keysym_for("е", 1765) == 1765  # what the listener saw instead
    hk, xk, _ = _x11(overlay="alt+shift+е")
    grabbed = []
    xk.grabber.set_combos = grabbed.extend
    _tap(xk, ALT, keyboard.KeyCode(char="е", vk=1765))
    assert xk.keysyms == {"е": 1765}
    assert ("alt+shift+е", {"alt", "shift"}, "е", 1765) in grabbed


def test_media_keys_come_from_the_desktop_not_the_listener(monkeypatch):
    _clock(monkeypatch)
    hk, xk, fired = _x11(media=True, play_pause="media_play_pause",
                         source_next="ctrl+media_next", track_next=".")
    grabbed = []
    xk.set_combos = lambda combos: grabbed.extend(c[0] for c in combos)
    hk.live = True
    assert grabbed == ["ctrl+media_next", "."]  # the desktop holds the bare key
    assert hk.media_keys() == {"media_play_pause"}
    assert hk.via_desktop("media_play_pause") and not hk.via_desktop(".")
    _tap(xk, keyboard.Key.media_play_pause)     # heard, but not acted on:
    assert fired == []                          # the desktop's call is the one
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]
    hk.press_media("media_next")                # bound only with Ctrl
    assert fired == ["play_pause"]
    hk.live = False                             # the overlay rule still holds
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]


def test_capturing_a_media_key_does_not_also_press_it(monkeypatch):
    clock = _clock(monkeypatch)
    hk, xk, fired = _x11(media=True, play_pause="media_play_pause")
    hk.live = True
    captured = []
    hk.begin_capture(captured.append)
    _tap(xk, keyboard.Key.media_play_pause)
    assert captured == ["media_play_pause"]
    clock[0] += 0.1                             # the desktop's call, right after
    hk.press_media("media_play_pause")
    assert fired == []
    clock[0] += 2
    hk.press_media("media_play_pause")
    assert fired == ["play_pause"]


def test_holding_a_media_key_toggles_once(monkeypatch):
    # The desktop repeats a held key as a stream of calls with no release;
    # the listener, which hears the key too, is what marks them as repeats.
    clock = _clock(monkeypatch)
    hk, xk, fired = _x11(media=True, play_pause="media_play_pause")
    hk.live = True
    play = keyboard.Key.media_play_pause
    xk._press(play)
    hk.press_media("media_play_pause")
    clock[0] += 0.5
    for _ in range(30):
        xk._press(play)
        hk.press_media("media_play_pause")
        clock[0] += 0.03
    xk._release(play)
    hk.press_media("media_play_pause")      # the last repeat's call, late
    assert fired == ["play_pause"]
    clock[0] += 0.3
    xk._press(play)
    hk.press_media("media_play_pause")
    assert fired == ["play_pause", "play_pause"]


def test_without_the_desktop_media_keys_are_plain_shortcuts():
    hk, xk, fired = _x11(play_pause="media_play_pause")
    hk.live = True
    assert not hk.via_desktop("media_play_pause")
    _tap(xk, keyboard.Key.media_play_pause)
    assert fired == ["play_pause"]


# ------------------------------------------------------------------ Windows
# The Windows hook: the same Hotkeys, fed raw key events the way the hook
# procedure hands them over. The system calls (layout, held modifiers, the
# mask key) are stood in for, so this runs on every platform.
VK = {"ctrl": 0xA2, "alt": 0xA4, "e": 0x45, "r": 0x52, "]": 0xDD, "[": 0xDB,
      "esc": 0x1B, "media_play_pause": 0xB3}
CHARS = {0x45: "E", 0x52: "R", 0xDD: "]", 0xDB: "["}


def _hooked(monkeypatch, **bindings):
    clock = _clock(monkeypatch)
    hk = Hotkeys(bindings)
    fired, masks, held = [], [], set()
    hk.triggered.connect(fired.append)
    hook = hk.keys = KeyHook(hk.on_key)
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
    hk.begin_capture(captured.append)
    assert key("esc")           # Esc cancels the capture, not the window
    assert captured == ["esc"] and fired == []
    hk.live = True
    assert key("media_play_pause")      # a media key is an ordinary key here
    assert fired == ["play_pause"]


def test_windows_key_names_follow_pynput():
    assert vk_name(0xB3) == "media_play_pause" and vk_name(0xB2) == "media_stop"
    assert vk_name(0x78) == "f9" and vk_name(0x22) == "page_down"
    assert vk_name(0x45, "E") == "e" and vk_name(0xDE, "'") == "'"
    assert vk_name(0x67, "7") == "7"
    assert vk_name(0xE8) == "vk232"


# ------------------------------------------------------------ source keys
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


# ---------------------------------------------------------------- recording
def test_ending_a_capture_frees_the_next_key(monkeypatch):
    hk, key, fired, _, _ = _hooked(monkeypatch, vol_up="]")
    hk.live = True
    got = []
    hk.begin_capture(got.append)
    hk.end_capture()                    # a popup closed while recording
    assert key("]") and fired == ["vol_up"] and got == []


def test_a_new_recording_gives_up_the_one_before(monkeypatch):
    hk, key, _, _, _ = _hooked(monkeypatch, vol_up="]")
    tab, popup = [], []
    hk.begin_capture(tab.append)        # the Shortcuts tab was recording ...
    hk.begin_capture(popup.append)      # ... when a source's popup began to
    assert tab == ["esc"]
    key("ctrl")
    key("e")
    assert popup == ["ctrl+e"] and tab == ["esc"]
