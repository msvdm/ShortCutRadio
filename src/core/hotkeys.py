"""Global shortcuts that observe keys instead of grabbing them.

pynput's X11 backend taps the XRECORD extension, the mechanism the NFSU2 radio
proved: the key still reaches the focused app, and it fires through a
fullscreen game's keyboard grab. Windows and macOS have their own backends.

Because keys are not grabbed, a single-key binding would fire while typing
anywhere. So combos without a modifier are live only while the overlay is on
(`single_keys_live`); combos with Ctrl/Alt/Super always are.

Combo strings are "ctrl+alt+r", "'", "f9", "shift+page_down": modifiers in a
fixed order, then the key. The same normaliser builds them for capture and for
matching, so whatever the settings UI recorded is exactly what will match.
"""

import os
import time
import traceback

from PySide6.QtCore import QObject, Signal

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
DEBUG = os.environ.get("SHORTCUTRADIO_DEBUG_KEYS") == "1"
DEBOUNCE_S = 0.25


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

    def __init__(self, bindings):
        super().__init__()
        self.bindings = {}
        self.set_bindings(bindings)
        self.single_keys_live = False
        self.capturing = False
        self._mods = set()
        self._last = {}
        self._listener = None
        self.error = IMPORT_ERROR

    def set_bindings(self, bindings):
        """{action: combo} -> lookup {combo: action}."""
        self.bindings = {c: a for a, c in bindings.items() if c}

    def start(self):
        if keyboard is None:
            print(f"[hotkeys] unavailable: {self.error}", flush=True)
            return False
        try:
            self._listener = keyboard.Listener(on_press=self._safe(self._press),
                                               on_release=self._safe(self._release))
            self._listener.start()
        except Exception as e:
            self.error = str(e)
            print(f"[hotkeys] could not start: {e}", flush=True)
            return False
        return True

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
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
        combo = make_combo(self._mods, name)
        if DEBUG:
            print(f"[hotkeys] {combo!r} live={self.single_keys_live} "
                  f"capturing={self.capturing} -> {self.bindings.get(combo)}", flush=True)

        if self.capturing:
            self.capturing = False
            self.captured.emit(combo)
            return

        action = self.bindings.get(combo)
        if action is None:
            return
        if not has_modifier(combo) and not self.single_keys_live:
            return
        # Held keys auto-repeat; only volume should ride that.
        now = time.monotonic()
        if action not in REPEATABLE and now - self._last.get(action, 0) < DEBOUNCE_S:
            return
        self._last[action] = now
        self.triggered.emit(action)

    def _release(self, key):
        name = key_name(key)
        if name in MOD_ORDER:
            self._mods.discard(name)
