"""Global shortcuts that observe keys instead of grabbing them.

pynput's X11 backend taps the XRECORD extension, the mechanism the NFSU2 radio
proved: the key still reaches the focused app, and it fires through a
fullscreen game's keyboard grab. Windows and macOS have their own backends.

Every shortcut is live only while the overlay is on (`single_keys_live`); the
one exception is the overlay toggle itself, which has to work to turn the
overlay back on. Live combos are also grabbed (keygrab.py) so the focused app
doesn't receive them: overlay on, the key is ShortCutRadio's; overlay off, the key
is free -- including combos like Ctrl+E, which the app in front may want.

Combo strings are "ctrl+alt+r", "'", "f9", "shift+page_down": modifiers in a
fixed order, then the key. The same normaliser builds them for capture and for
matching, so whatever the settings UI recorded is exactly what will match.
"""

import os
import time
import traceback

from PySide6.QtCore import QObject, Signal

from .keygrab import KeyGrabber

try:
    from pynput import keyboard
except Exception as e:          # no X display, unsupported platform ...
    keyboard = None
    IMPORT_ERROR = str(e)
else:
    IMPORT_ERROR = ""

MOD_ORDER = ("ctrl", "alt", "shift", "super")
MOD_NAMES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "super", "cmd_l": "super", "cmd_r": "super",
}
REPEATABLE = {"vol_up", "vol_down"}
ALWAYS_LIVE = "overlay"     # the only action that works with the overlay off
DEBUG = os.environ.get("SHORTCUTRADIO_DEBUG_KEYS") == "1"
DEBOUNCE_S = 0.25
REPEAT_S = 0.09             # how fast a held volume key may repeat
REPEAT_GAP_S = 2.0          # a longer gap means we missed the release


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


def has_modifier(combo):
    mods, _ = parse_combo(combo)
    return bool(mods - {"shift"})


def pretty(combo):
    """For display: "ctrl+alt+r" -> "Ctrl+Alt+R", "page_down" -> "Page Down"."""
    if not combo:
        return "—"
    mods, key = parse_combo(combo)
    names = [m.capitalize() for m in MOD_ORDER if m in mods]
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
    return f"vk{vk}" if vk is not None else None


class Hotkeys(QObject):
    triggered = Signal(str)     # action name
    captured = Signal(str)      # combo recorded in capture mode ("esc" = cancel)
    ungrabbed = Signal(list)    # live combos the focused app still receives

    def __init__(self, bindings, keysyms=None):
        super().__init__()
        self.bindings = {}
        # Key name -> the X keysym it came from. `ord(char)` is the keysym only
        # for Latin-1, so without this a Cyrillic key cannot be grabbed at all
        # (see keygrab.keysym_for). Learned from every press, kept in the config.
        self.keysyms = {} if keysyms is None else keysyms
        self._single_live = False
        self.grabber = KeyGrabber(self.ungrabbed.emit)
        self.set_bindings(bindings)
        self.capturing = False
        self._mods = set()
        self._last = {}
        self._down = {}         # key name -> when it was last pressed
        self._listener = None
        self.error = IMPORT_ERROR

    def set_bindings(self, bindings):
        """{action: combo} -> lookup {combo: action}."""
        self.bindings = {c: a for a, c in bindings.items() if c}
        self._update_grabs()

    @property
    def single_keys_live(self):
        return self._single_live

    @single_keys_live.setter
    def single_keys_live(self, on):
        self._single_live = bool(on)
        self._update_grabs()

    def _update_grabs(self):
        live = []
        for combo, action in self.bindings.items():
            if action != ALWAYS_LIVE and not self._single_live:
                continue
            mods, key = parse_combo(combo)
            live.append((combo, mods, key, self.keysyms.get(key)))
        self.grabber.set_combos(live)

    def start(self):
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

    def cancel_capture(self):
        self.capturing = False

    # pynput thread ----------------------------------------------------------
    @staticmethod
    def _safe(fn):
        """pynput stops the whole listener on an uncaught callback error; one
        odd key must not cost every shortcut for the rest of the session."""
        def wrapper(key):
            try:
                fn(key)
            except Exception:
                traceback.print_exc()
        return wrapper

    def _press(self, key):
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
        combo = make_combo(self._mods, name)
        if DEBUG:
            print(f"[hotkeys] {combo!r} live={self._single_live} repeat={repeat} "
                  f"capturing={self.capturing} -> {self.bindings.get(combo)}", flush=True)

        if self.capturing:
            if repeat:              # the tail of a held key is not a choice
                return
            self.capturing = False
            self.captured.emit(combo)
            return

        action = self.bindings.get(combo)
        if action is None:
            return
        if action != ALWAYS_LIVE and not self._single_live:
            return
        if repeat:
            # Only volume rides auto-repeat, and slower than X delivers it.
            if action not in REPEATABLE or now - self._last.get(action, 0) < REPEAT_S:
                return
        elif now - self._last.get(action, 0) < DEBOUNCE_S:
            return
        self._last[action] = now
        self.triggered.emit(action)

    def _release(self, key):
        name = key_name(key)
        if name in MOD_ORDER:
            self._mods.discard(name)
            # A held key reports a different character once a modifier is
            # gone (Shift+K is Cyrillic k on a us,bg keymap, K without it),
            # so its release would not match its press. Forget what is held.
            self._down.clear()
        else:
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
