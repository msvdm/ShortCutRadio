"""The X11 keyboard: pynput hears every key, passive grabs take the live ones.

The listener (pynput's XRECORD tap, the mechanism the NFSU2 radio proved)
only observes: the key still reaches the focused app, and it fires through a
fullscreen game's keyboard grab. So every bound key would also land in
whatever app has focus. While a key is grabbed here (`KeyGrabber`), X
delivers it to this client instead, so the app never sees it. XRECORD still
reports it, so the action fires exactly once, from the listener.

Only the exact keys given are grabbed, never the whole keyboard. A fullscreen
game that grabs the entire keyboard (Wine does) wins over these passive grabs:
inside such a game the key reaches the game too, as before.

`XKeys` is the two together, behind the same seam as the Windows hook
(keygrab_win.KeyHook): it names each key and calls `on_key(name, mods,
repeat)`; hotkeys.py decides what the key means. The grabs are a no-op on
other platforms and sessions; see `KeyGrabber.available`.
"""

import os
import queue
import select
import sys
import threading
import time
import traceback

try:
    from Xlib import X, XK, display as xdisplay, error as xerror
except Exception:
    xdisplay = None

keyboard = None
IMPORT_ERROR = ""
if sys.platform != "win32":     # Windows has its own hook (keygrab_win.py)
    try:
        from pynput import keyboard
    except Exception as e:      # no X display, unsupported platform ...
        IMPORT_ERROR = str(e)

WAYLAND_ERROR = ("this is a Wayland session, and global shortcuts need X11. "
                 "Choose the Xorg (X11) session on the login screen.")


def wayland_session():
    """Under Wayland pynput still starts, through XWayland, but hears only
    X apps' keys, and nothing can be grabbed: half-dead shortcuts."""
    kind = os.environ.get("XDG_SESSION_TYPE", "")
    return kind == "wayland" or (bool(os.environ.get("WAYLAND_DISPLAY")) and kind != "x11")

MOD_NAMES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "super", "cmd_l": "super", "cmd_r": "super",
}
MODS = frozenset(MOD_NAMES.values())
# Media keys pynput has no name for, by vk: XF86AudioStop's keysym on X11,
# VK_MEDIA_STOP on Windows. Neither stands for a key that types a character.
MEDIA_VKS = {0x1008FF15: "media_stop", 0xB2: "media_stop"}
REPEAT_GAP_S = 2.0          # a longer gap means we missed the release

# pynput key names -> X keysym names, where they differ.
KEYSYM_NAMES = {
    "page_up": "Page_Up", "page_down": "Page_Down", "home": "Home", "end": "End",
    "insert": "Insert", "delete": "Delete", "space": "space", "tab": "Tab",
    "enter": "Return", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "scroll_lock": "Scroll_Lock", "pause": "Pause", "print_screen": "Print",
    "backspace": "BackSpace", "esc": "Escape", "menu": "Menu",
    "num_lock": "Num_Lock", "caps_lock": "Caps_Lock",
}


def keysym_for(key, hint=None):
    """The X keysym for one of our key names.

    `hint` is the keysym the listener saw for that key. Latin-1 keysyms equal
    their code points, but nothing else does: on a us,bg keymap pynput reports
    Shift+E as Cyrillic e, whose code point (1077) is not a keysym at all, so
    the hint is the only way to find the key it stands for.
    """
    if hint:
        return hint
    if len(key) == 1:
        return ord(key)         # Latin-1 keysyms equal their code points
    if key.startswith("vk") and key[2:].isdigit():
        return int(key[2:])     # pynput's X11 vk *is* the keysym
    if key[0] == "f" and key[1:].isdigit():
        return XK.string_to_keysym(key.upper())
    return XK.string_to_keysym(KEYSYM_NAMES.get(key, key))


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


def _safe(fn):
    """pynput stops the whole listener on an uncaught callback error; one
    odd key must not cost every shortcut for the rest of the session."""
    def wrapper(*args):
        try:
            return fn(*args)
        except Exception:
            traceback.print_exc()
            return None
    return wrapper


class XKeys:
    """The pynput listener and the grabber together: the X11 counterpart of
    keygrab_win.KeyHook, behind the same seam -- `on_key(name, mods, repeat)`
    for every press that is not a modifier, `start`, `stop`, `set_combos`,
    `error`. Its answer changes nothing here: X11 takes a key by grabbing it
    in advance, and the listener never sees less than everything.
    """

    def __init__(self, on_key, on_ungrabbed=None, keysyms=None):
        self._on_key = on_key
        # Key name -> the X keysym it came from. `ord(char)` is the keysym only
        # for Latin-1, so without this a Cyrillic key cannot be grabbed at all
        # (see keysym_for). Learned from every press, kept in the config.
        self.keysyms = {} if keysyms is None else keysyms
        self.grabber = KeyGrabber(on_ungrabbed)
        self.error = WAYLAND_ERROR if wayland_session() else IMPORT_ERROR
        self._combos = []
        self._listener = None
        self._mods = set()
        self._down = {}         # key name -> when it was last pressed

    def start(self):
        if keyboard is None or self.error:
            return False
        try:
            self._listener = keyboard.Listener(on_press=_safe(self._press),
                                               on_release=_safe(self._release))
            self._listener.start()
            self.grabber.start()
            self._grab()
        except Exception as e:
            self.error = str(e)
            return False
        return True

    def stop(self):
        """Release grabbed keys. The listener thread is a daemon and is left to
        die with the process: pynput's XRECORD stop can block indefinitely."""
        self.grabber.stop()
        self._listener = None

    def set_combos(self, combos):
        """Take exactly these (combo, mods, key) keys; release the rest."""
        self._combos = list(combos)
        self._grab()

    def _grab(self):
        self.grabber.set_combos([(combo, mods, key, self.keysyms.get(key))
                                 for combo, mods, key in self._combos])

    # listener thread ---------------------------------------------------------
    # pynput 1.8 calls back with (key, injected) when the callback can take
    # two arguments -- and _safe's wrapper takes any number.
    def _press(self, key, injected=False):
        canonical = self._listener.canonical if self._listener else None
        name = key_name(key, canonical)
        if name is None:
            return
        if name in MODS:
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
        self._on_key(name, set(self._mods), repeat)

    def _release(self, key, injected=False):
        name = key_name(key)
        if name in MODS:
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
            self._grab()


class KeyGrabber:
    def __init__(self, on_ungrabbed=None):
        # Called with the combos that stayed with the focused app, whenever
        # the set of grabs changes. It runs on the X thread.
        self._report = on_ungrabbed
        self._missed = set()        # what was reported last, to say it once
        self._err = None
        self.available = (xdisplay is not None and sys.platform.startswith("linux")
                          and bool(os.environ.get("DISPLAY"))
                          and not wayland_session())
        self._ops = queue.Queue()
        self._grabbed = set()       # (keycode, modmask)
        self._thread = None
        self._stop = False

    def start(self):
        if not self.available:
            return False
        try:
            self.d = xdisplay.Display()
        except Exception as e:
            print(f"[keygrab] no X display: {e}", flush=True)
            self.available = False
            return False
        self.root = self.d.screen().root
        self.d.set_error_handler(self._on_error)
        self._thread = threading.Thread(target=self._run, name="keygrab", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(1)

    def set_combos(self, combos):
        """Grab exactly these (combo, mods, key, keysym) keys; release the rest."""
        if self.available:
            self._ops.put(list(combos))

    # ------------------------------------------------------------------ X thread
    def _on_error(self, err, *_):
        # BadAccess: another program already owns that key. Not fatal, but the
        # key is not ours -- _apply reports it so the window can say so.
        self._err = err
        if not isinstance(err, xerror.BadAccess):
            print(f"[keygrab] X error: {err}", flush=True)

    def _masks(self, mods):
        m = 0
        if "ctrl" in mods:
            m |= X.ControlMask
        if "alt" in mods:
            m |= X.Mod1Mask
        if "shift" in mods:
            m |= X.ShiftMask
        if "super" in mods:
            m |= X.Mod4Mask
        # A grab only matches the exact modifier state, and Caps Lock/Num Lock
        # count as modifiers -- grab every lock combination too.
        return {m, m | X.LockMask, m | X.Mod2Mask, m | X.LockMask | X.Mod2Mask}

    def _apply(self, combos):
        """Take exactly these keys. A key that cannot be taken is reported, not
        swallowed: a shortcut the focused app still gets looks identical to a
        working one otherwise."""
        want, missed = {}, []
        for combo, mods, key, hint in combos:
            ks = keysym_for(key, hint)
            kc = self.d.keysym_to_keycode(ks) if ks else 0
            if not kc:
                if combo not in self._missed:
                    print(f"[keygrab] no key on this keyboard for {combo!r} "
                          f"(keysym {ks})", flush=True)
                missed.append(combo)
                continue
            for mask in self._masks(mods):
                want[(kc, mask)] = combo
        for kc, mask in self._grabbed - set(want):
            self.root.ungrab_key(kc, mask)
        for (kc, mask), combo in want.items():
            if (kc, mask) in self._grabbed:
                continue
            self._err = None
            self.root.grab_key(kc, mask, True, X.GrabModeAsync, X.GrabModeAsync)
            self.d.sync()           # errors arrive here, so we know which key
            if self._err is not None and combo not in missed:
                if combo not in self._missed:
                    print(f"[keygrab] {combo!r} is already grabbed by another "
                          f"program", flush=True)
                missed.append(combo)
        self._grabbed = set(want)
        self.d.sync()
        self._missed = set(missed)
        if self._report:
            self._report(sorted(self._missed))

    def _run(self):
        fd = self.d.fileno()
        while not self._stop:
            try:
                while True:
                    self._apply(self._ops.get_nowait())
            except queue.Empty:
                pass
            # Grabbed key events are queued to us; drain and drop them (the
            # listener has already acted on the key).
            while self.d.pending_events():
                self.d.next_event()
            select.select([fd], [], [], 0.1)
        try:
            for kc, mask in self._grabbed:
                self.root.ungrab_key(kc, mask)
            self.d.sync()
            self.d.close()
        except Exception:
            pass
