"""Global shortcuts: what a key means, and when it is ShortCutRadio's.

Hearing and taking keys is the platform's job, behind one seam: on X11
keygrab.XKeys (pynput observes, passive grabs take), on Windows
keygrab_win.KeyHook (one low-level hook does both). Either names each key
press and calls `Hotkeys.on_key`; everything here is the same on both.

Every shortcut is live only while the overlay is on (`live`); the
one exception is the overlay toggle itself, which has to work to turn the
overlay back on. Live combos are also taken, so the focused app doesn't
receive them: overlay on, the key is ShortCutRadio's; overlay off, the key
is free -- including combos like Ctrl+E, which the app in front may want.

That rule is a switch, on by default. Off (`everywhere`), every shortcut is
live and taken all the time, overlay or not -- but only one with Ctrl, Alt or
Super, or a bare media key (`works_everywhere`): a single key would take a
character from everything the user types. A single-key binding is kept and
simply idle until the switch goes back on.

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

from PySide6.QtCore import QObject, Signal

from .keygrab import XKeys
from .keygrab_win import KeyHook

WINDOWS = sys.platform == "win32"
MOD_ORDER = ("ctrl", "alt", "shift", "super")
# The desktop's media channel delivers these (mpris.py). Volume and mute stay
# the system's: those keys are never ShortCutRadio's.
MEDIA_KEYS = {"media_play_pause", "media_next", "media_previous", "media_stop"}
REPEATABLE = {"vol_up", "vol_down"}
SUPER = "Win" if WINDOWS else "Super"
ALWAYS_LIVE = "overlay"     # the only action that works with the overlay off
SOURCE_ACTION = "source:"   # + the source's index: a key that jumps straight to it
DEBUG = os.environ.get("SHORTCUTRADIO_DEBUG_KEYS") == "1"
DEBOUNCE_S = 0.25
REPEAT_S = 0.09             # how fast a held volume key may repeat
CAPTURE_ECHO_S = 1.0        # the desktop's call for a media key just recorded
CANCEL = "esc"              # recording: given up
CLEAR = ("backspace", "delete")     # recording: no key at all


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


def recorded(combo):
    """What a recording asks for: None to keep the old key (Esc), "" for no
    key at all (Backspace or Delete), else the combo itself."""
    if combo == CANCEL:
        return None
    return "" if combo in CLEAR else combo


def is_media(combo):
    """A bare media key: the desktop's to deliver. Ctrl+Next is not -- the
    desktop binds the bare key only -- so it stays an ordinary shortcut."""
    mods, key = parse_combo(combo)
    return not mods and key in MEDIA_KEYS


def has_modifier(combo):
    mods, _ = parse_combo(combo)
    return bool(mods - {"shift"})


def works_everywhere(combo):
    """May this combo be live all the time? Not if it types something."""
    return has_modifier(combo) or is_media(combo)


def source_action(index):
    return f"{SOURCE_ACTION}{index}"


def source_index(action):
    """"source:3" -> 3; any other action -> None."""
    if not action.startswith(SOURCE_ACTION):
        return None
    try:
        return int(action[len(SOURCE_ACTION):])
    except ValueError:
        return None


def all_bindings(shortcuts, sources):
    """{action: combo}: the Shortcuts tab's actions plus a key per source.

    A source's key is kept on the source itself, so it survives a rename or a
    reorder and leaves with it. Its action is its *index*, which is why this
    is rebuilt after every edit of the list.
    """
    out = dict(shortcuts)
    for i, src in enumerate(sources):
        if src.get("shortcut"):
            out[source_action(i)] = src["shortcut"]
    return out


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


class Hotkeys(QObject):
    triggered = Signal(str)     # action name
    ungrabbed = Signal(list)    # live combos the focused app still receives
    _captured = Signal(str)     # a recorded combo, from the keyboard's thread

    def __init__(self, bindings, keysyms=None, media_via_desktop=False):
        super().__init__()
        # True when the desktop's player channel is there (mpris.py) to deliver
        # the media keys; without it they stay plain observed shortcuts.
        self.media_via_desktop = media_via_desktop
        self.bindings = {}
        self._live = False
        self._everywhere = False
        self.capturing = False
        self._on_capture = None     # who gets the key being recorded
        self._capture_end = 0.0
        self._last = {}
        self._repeating = {}        # media key -> its last press was a repeat
        # The platform's keyboard: it hears every key and asks on_key about it.
        # `keysyms` is X11's (see XKeys) and kept in the config.
        self.keys = (KeyHook(self.on_key) if WINDOWS
                     else XKeys(self.on_key, self.ungrabbed.emit, keysyms))
        self._captured.connect(self._deliver_capture)
        self.set_bindings(bindings)

    @property
    def error(self):
        """Why there are no global shortcuts, or ""."""
        return self.keys.error

    def set_bindings(self, bindings):
        """{action: combo} -> lookup {combo: action}."""
        self.bindings = {c: a for a, c in bindings.items() if c}
        self._update_grabs()

    @property
    def live(self):
        """True while the overlay is on: every shortcut works, and is taken
        (unless `everywhere` has the say, see `_is_live`)."""
        return self._live

    @live.setter
    def live(self, on):
        self._live = bool(on)
        self._update_grabs()

    @property
    def everywhere(self):
        """The Shortcuts tab's switch, off: live without the overlay."""
        return self._everywhere

    @everywhere.setter
    def everywhere(self, on):
        self._everywhere = bool(on)
        self._update_grabs()

    def _is_live(self, action, combo):
        """The one rule: the overlay toggle always works; the rest while the
        overlay is on, or always if the switch says so and the combo can't type."""
        if action == ALWAYS_LIVE:
            return True
        if self._everywhere:
            return works_everywhere(combo)
        return self._live

    def idle(self, combo):
        """Bound, but kept from working by the switch: a single key while
        shortcuts work everywhere."""
        action = self.bindings.get(combo)
        return (self._everywhere and action not in (None, ALWAYS_LIVE)
                and not works_everywhere(combo))

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
        if action is None or not self._is_live(action, name) or self.capturing:
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
            if not self._is_live(action, combo) or self.via_desktop(combo):
                continue
            mods, key = parse_combo(combo)
            live.append((combo, mods, key))
        self.keys.set_combos(live)

    def start(self):
        if not self.keys.start():
            print(f"[hotkeys] could not start: {self.error}", flush=True)
            return False
        return True

    def stop(self):
        self.keys.stop()

    # recording ---------------------------------------------------------------
    def begin_capture(self, on_done):
        """Record the next key: `on_done(combo)` gets it on the GUI thread
        (see `recorded`). A new recording ends the one before, as given up."""
        previous, self._on_capture = self._on_capture, on_done
        self.capturing = True
        if previous is not None:
            previous(CANCEL)

    def end_capture(self):
        """A recording given up without a key: a popup closed mid-way must
        not leave the next key swallowed."""
        self.capturing = False
        self._on_capture = None

    def _deliver_capture(self, combo):
        on_done, self._on_capture = self._on_capture, None
        if on_done is not None:
            on_done(combo)

    # keyboard thread ---------------------------------------------------------
    def on_key(self, name, mods, repeat):
        """One key press, from whichever keyboard heard it. True when the key
        is ours -- a live binding, or the key being recorded -- which the
        Windows hook uses to take it; on X11 the grab already has."""
        now = time.monotonic()
        combo = make_combo(mods, name)
        if DEBUG:
            print(f"[hotkeys] {combo!r} live={self._live} repeat={repeat} "
                  f"capturing={self.capturing} -> {self.bindings.get(combo)}", flush=True)

        if self.capturing:
            if not repeat:          # the tail of a held key is not a choice
                self.capturing = False
                self._capture_end = now
                self._captured.emit(combo)
            return True

        if self.via_desktop(combo):
            # The desktop delivers it (press_media): acting here too would
            # toggle twice. What only the listener knows is whether it
            # repeats. The mark outlives the key's release on purpose: the
            # desktop's call for the last repeat can land after it, and the
            # next press is what resets it.
            self._repeating[name] = repeat
            return False
        action = self.bindings.get(combo)
        if action is None or not self._is_live(action, combo):
            return False
        self._fire(action, repeat, now)
        return True
