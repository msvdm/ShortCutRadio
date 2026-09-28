"""Global shortcuts that observe keys instead of grabbing them.

pynput's X11 backend taps the XRECORD extension, the mechanism the NFSU2 radio
proved: the key still reaches the focused app, and it fires through a
fullscreen game's keyboard grab. On Windows a low-level keyboard hook does
the observing and the taking in one place (keygrab_win.py), so pynput is not
used there at all.

Every shortcut is live only while the overlay is on (`live`); the
one exception is the overlay toggle itself, which has to work to turn the
overlay back on. Live combos are also grabbed (keygrab.py) so the focused app
doesn't receive them: overlay on, the key is ShortCutRadio's; overlay off, the key
is free -- including combos like Ctrl+E, which the app in front may want.

On Linux the keyboard's media keys are the exception to all of this: the
desktop owns them, so a bare media key is not observed or grabbed here but
delivered by the desktop's player channel (mpris.py) through `press_media` --
see `via_desktop`. On Windows they are ordinary keys to the hook.

Combo strings are "ctrl+alt+r", "'", "f9", "shift+page_down": modifiers in a
fixed order, then the key. The same normaliser builds them for capture and for
matching, so whatever the settings UI recorded is exactly what will match.
"""

import os
import sys
import time
import traceback

from PySide6.QtCore import QObject, Signal

from .keygrab import KeyGrabber
from .keygrab_win import KeyHook

WINDOWS = sys.platform == "win32"
keyboard = None
IMPORT_ERROR = ""
if not WINDOWS:
    try:
        from pynput import keyboard
    except Exception as e:      # no X display, unsupported platform ...
        IMPORT_ERROR = str(e)

MOD_ORDER = ("ctrl", "alt", "shift", "super")
MOD_NAMES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "super", "cmd_l": "super", "cmd_r": "super",
}
# Media keys pynput has no name for, by vk: XF86AudioStop's keysym on X11,
# VK_MEDIA_STOP on Windows. Neither stands for a key that types a character.
MEDIA_VKS = {0x1008FF15: "media_stop", 0xB2: "media_stop"}
# The desktop's media channel delivers these (mpris.py). Volume and mute stay
# the system's: those keys are never ShortCutRadio's.
MEDIA_KEYS = {"media_play_pause", "media_next", "media_previous", "media_stop"}
REPEATABLE = {"vol_up", "vol_down"}
SUPER = "Win" if WINDOWS else "Super"
ALWAYS_LIVE = "overlay"     # the only action that works with the overlay off
DEBUG = os.environ.get("SHORTCUTRADIO_DEBUG_KEYS") == "1"
DEBOUNCE_S = 0.25
REPEAT_S = 0.09             # how fast a held volume key may repeat
REPEAT_GAP_S = 2.0          # a longer gap means we missed the release
CAPTURE_ECHO_S = 1.0        # the desktop's call for a media key just recorded


def parse_combo(combo):
    """"ctrl+alt+r" -> ({"ctrl", "alt"}, "r"). The key itself may be "+"."""
    if not combo:
        return set(), ""
    if combo == "+" or combo.endswith("++"):
        mods, key = combo[:-2] if combo != "+" else "", "+"
    else:
        mods, _, key = combo.rpartition("+")
    return {m for m in mods.split("+") if m}, key


def make_combo(mods, key):
    return "+".join([m for m in MOD_ORDER if m in mods] + [key])


def is_media(combo):
    """A bare media key: the desktop's to deliver. Ctrl+Next is not -- the
    desktop binds the bare key only -- so it stays an ordinary shortcut."""
    mods, key = parse_combo(combo)
    return not mods and key in MEDIA_KEYS


def has_modifier(combo):
    mods, _ = parse_combo(combo)
    return bool(mods - {"shift"})


def pretty(combo):
    """For display: "ctrl+alt+r" -> "Ctrl+Alt+R", "page_down" -> "Page Down"."""
    if not combo:
        return "—"
    mods, key = parse_combo(combo)
    names = [SUPER if m == "super" else m.capitalize() for m in MOD_ORDER if m in mods]
    if len(key) == 1:
        names.append(key.upper())
    else:
        names.append(key.replace("_", " ").title())
    return "+".join(names)


def key_name(key, canonical=None):
    """pynput key -> our name, or None for keys we can't name."""
    if keyboard is None:
        return None
    if isinstance(key, keyboard.Key):
        return MOD_NAMES.get(key.name, key.name)
    if canonical is not None:
        key = canonical(key)
    char = getattr(key, "char", None)
    if char:
        return char.lower()
    vk = getattr(key, "vk", None)
    if vk is None:
        return None
    return MEDIA_VKS.get(vk, f"vk{vk}")


class Hotkeys(QObject):
    triggered = Signal(str)     # action name
    captured = Signal(str)      # combo recorded in capture mode ("esc" = cancel)
    ungrabbed = Signal(list)    # live combos the focused app still receives

    def __init__(self, bindings, keysyms=None, media_via_desktop=False):
        super().__init__()
        # True when the desktop's player channel is there (mpris.py) to deliver
        # the media keys; without it they stay plain observed shortcuts.
        self.media_via_desktop = media_via_desktop
        self.bindings = {}
        # Key name -> the X keysym it came from. `ord(char)` is the keysym only
        # for Latin-1, so without this a Cyrillic key cannot be grabbed at all
        # (see keygrab.keysym_for). Learned from every press, kept in the config.
        self.keysyms = {} if keysyms is None else keysyms
        self._live = False
        if WINDOWS:
            self.grabber = KeyHook(self._safe(self._key, False))
            self.error = ""
        else:
            self.grabber = KeyGrabber(self.ungrabbed.emit)
            self.error = IMPORT_ERROR
        self.set_bindings(bindings)
        self.capturing = False
        self._mods = set()
        self._last = {}
        self._down = {}         # key name -> when it was last pressed
        self._capture_end = 0.0
        self._repeating = {}    # media key -> its last press was a repeat
        self._listener = None

    def set_bindings(self, bindings):
        """{action: combo} -> lookup {combo: action}."""
        self.bindings = {c: a for a, c in bindings.items() if c}
        self._update_grabs()

    @property
    def live(self):
        """True while the overlay is on: every shortcut works, and is taken."""
        return self._live

    @live.setter
    def live(self, on):
        self._live = bool(on)
        self._update_grabs()

    def _is_live(self, action):
        """The one rule: the overlay toggle always works, the rest only while live."""
        return action == ALWAYS_LIVE or self._live

    def via_desktop(self, combo):
        """This combo reaches us from the desktop's media channel, not the
        listener. The desktop holds the key itself, so it is not grabbed --
        a grab would only fail and show a warning for nothing."""
        return self.media_via_desktop and is_media(combo)

    def media_keys(self):
        """The bare media keys bound to something: what the desktop's player
        (MPRIS, SMTC) should offer. On Windows the hook takes the keys
        themselves, so they need not come *from* the desktop to count."""
        return {parse_combo(c)[1] for c in self.bindings if is_media(c)}

    def press_media(self, name):
        """A media key the desktop delivered. Same bindings, same overlay rule
        and same repeat rule as a key the listener saw.

        The desktop passes X's auto-repeat straight on (a 1.5 s hold of Play
        sent 34 calls) and says nothing about releases, but the listener
        still hears the key itself, so it is the one that knows a repeat.
        """
        action = self.bindings.get(name)
        if DEBUG:
            print(f"[hotkeys] desktop {name!r} live={self._live} "
                  f"repeat={self._repeating.get(name, False)} -> {action}", flush=True)
        if action is None or not self._is_live(action) or self.capturing:
            return
        now = time.monotonic()
        if now - self._capture_end < CAPTURE_ECHO_S:
            return      # the key that was just recorded, echoed by the desktop
        self._fire(action, self._repeating.get(name, False), now)

    def _fire(self, action, repeat, now):
        """Only volume rides auto-repeat, and slower than X delivers it; a
        fresh press is still debounced."""
        since = now - self._last.get(action, 0)
        if repeat:
            if action not in REPEATABLE or since < REPEAT_S:
                return
        elif since < DEBOUNCE_S:
            return
        self._last[action] = now
        self.triggered.emit(action)

    def _update_grabs(self):
        live = []
        for combo, action in self.bindings.items():
            if not self._is_live(action) or self.via_desktop(combo):
                continue
            mods, key = parse_combo(combo)
            live.append((combo, mods, key, self.keysyms.get(key)))
        self.grabber.set_combos(live)

    def start(self):
        if WINDOWS:
            if not self.grabber.start():
                self.error = self.grabber.error or "no keyboard hook on this system"
                print(f"[hotkeys] could not start: {self.error}", flush=True)
                return False
            return True
        if keyboard is None:
            print(f"[hotkeys] unavailable: {self.error}", flush=True)
            return False
        try:
            self._listener = keyboard.Listener(on_press=self._safe(self._press),
                                               on_release=self._safe(self._release))
            self._listener.start()
            self.grabber.start()
            self._update_grabs()
        except Exception as e:
            self.error = str(e)
            print(f"[hotkeys] could not start: {e}", flush=True)
            return False
        return True

    def stop(self):
        """Release grabbed keys. The listener thread is a daemon and is left to
        die with the process: pynput's XRECORD stop can block indefinitely."""
        self.grabber.stop()
        self._listener = None

    def begin_capture(self):
        self.capturing = True

    # listener thread ---------------------------------------------------------
    @staticmethod
    def _safe(fn, fallback=None):
        """pynput stops the whole listener on an uncaught callback error; one
        odd key must not cost every shortcut for the rest of the session."""
        def wrapper(*args):
            try:
                return fn(*args)
            except Exception:
                traceback.print_exc()
                return fallback
        return wrapper

    def _key(self, name, mods, repeat):
        """A key press from the Windows hook, which already knows a repeat
        from a fresh press. True: the key is ours, the focused app must not
        get it."""
        return self._handle(name, mods, repeat, time.monotonic())

    # pynput 1.8 calls back with (key, injected) when the callback can take
    # two arguments -- and _safe's wrapper takes any number.
    def _press(self, key, injected=False):
        canonical = self._listener.canonical if self._listener else None
        name = key_name(key, canonical)
        if name is None:
            return
        if name in MOD_ORDER:
            self._mods.add(name)
            return
        self._learn_keysym(name, key)
        # A held key repeats as bare presses, with no release in between (25
        # presses and 1 release in a 1.2 s hold here), so a key we have not
        # seen released is repeating. The gap is only a safety net for a
        # release we never saw: it has to be longer than X's repeat *delay*
        # (500 ms here), not just the interval between repeats.
        now = time.monotonic()
        repeat = now - self._down.get(name, 0) < REPEAT_GAP_S
        self._down[name] = now
        self._handle(name, self._mods, repeat, now)

    def _handle(self, name, mods, repeat, now):
        """One key press, whichever listener heard it. Returns True when the
        key is ours -- a live binding, or the key being recorded -- which the
        Windows hook uses to take it; on X11 keygrab.py already has."""
        combo = make_combo(mods, name)
        if DEBUG:
            print(f"[hotkeys] {combo!r} live={self._live} repeat={repeat} "
                  f"capturing={self.capturing} -> {self.bindings.get(combo)}", flush=True)

        if self.capturing:
            if not repeat:          # the tail of a held key is not a choice
                self.capturing = False
                self._capture_end = now
                self.captured.emit(combo)
            return True

        if self.via_desktop(combo):
            # The desktop delivers it (press_media): acting here too would
            # toggle twice. What only the listener knows is whether it repeats.
            self._repeating[name] = repeat
            return False
        action = self.bindings.get(combo)
        if action is None or not self._is_live(action):
            return False
        self._fire(action, repeat, now)
        return True

    def _release(self, key, injected=False):
        name = key_name(key)
        if name in MOD_ORDER:
            self._mods.discard(name)
            # A held key reports a different character once a modifier is
            # gone (Shift+K is Cyrillic k on a us,bg keymap, K without it),
            # so its release would not match its press. Forget what is held.
            self._down.clear()
        else:
            # `_repeating` stays: the desktop's call for the last repeat can
            # land after the release. The next press is what resets it.
            self._down.pop(name, None)

    def _learn_keysym(self, name, key):
        """Remember which keysym a character came from, and re-grab if it is new.

        `ord(char)` is the keysym only for Latin-1. On a us,bg keymap pynput
        reports Shift+E as Cyrillic e (it mistakes Shift for AltGr), and 1077
        is not a keysym -- the key could not be grabbed without this.
        """
        vk = getattr(key, "vk", None)
        if vk is None or len(name) != 1 or ord(name) <= 0xFF:
            return
        if self.keysyms.get(name) != vk:
            self.keysyms[name] = vk
            self._update_grabs()
