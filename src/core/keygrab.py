"""Take bound keys away from the focused app (X11 passive key grabs).

The listener in hotkeys.py only observes, so on its own every bound key also
lands in whatever app has focus. While a key is grabbed here, X delivers it to
this client instead, so the app never sees it. XRECORD still reports it, so
the action fires exactly once, from the listener.

Only the exact keys given are grabbed, never the whole keyboard. A fullscreen
game that grabs the entire keyboard (Wine does) wins over these passive grabs:
inside such a game the key reaches the game too, as before.

On other platforms/sessions this is a no-op; see `available`.
"""

import os
import queue
import select
import sys
import threading

try:
    from Xlib import X, XK, display as xdisplay, error as xerror
except Exception:
    xdisplay = None

# pynput key names -> X keysym names, where they differ.
KEYSYM_NAMES = {
    "page_up": "Page_Up", "page_down": "Page_Down", "home": "Home", "end": "End",
    "insert": "Insert", "delete": "Delete", "space": "space", "tab": "Tab",
    "enter": "Return", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "scroll_lock": "Scroll_Lock", "pause": "Pause", "print_screen": "Print",
    "backspace": "BackSpace", "esc": "Escape", "menu": "Menu",
    "num_lock": "Num_Lock", "caps_lock": "Caps_Lock",
}


def keysym_for(key):
    if len(key) == 1:
        return ord(key)         # Latin-1 keysyms equal their code points
    if key.startswith("vk") and key[2:].isdigit():
        return int(key[2:])     # pynput's X11 vk *is* the keysym
    if key[0] == "f" and key[1:].isdigit():
        return XK.string_to_keysym(key.upper())
    return XK.string_to_keysym(KEYSYM_NAMES.get(key, key))


class KeyGrabber:
    def __init__(self):
        self.available = (xdisplay is not None and sys.platform.startswith("linux")
                          and bool(os.environ.get("DISPLAY"))
                          and os.environ.get("XDG_SESSION_TYPE") != "wayland")
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
        """Grab exactly these (mods, key) pairs; release everything else."""
        if self.available:
            self._ops.put(list(combos))

    # ------------------------------------------------------------------ X thread
    def _on_error(self, err, *_):
        # BadAccess: another program already owns that key. Not fatal.
        if isinstance(err, xerror.BadAccess):
            print("[keygrab] a key is already grabbed by another program", flush=True)
        else:
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
        want = set()
        for mods, key in combos:
            ks = keysym_for(key)
            if not ks:
                continue
            kc = self.d.keysym_to_keycode(ks)
            if not kc:
                continue
            for mask in self._masks(mods):
                want.add((kc, mask))
        for kc, mask in self._grabbed - want:
            self.root.ungrab_key(kc, mask)
        for kc, mask in want - self._grabbed:
            self.root.grab_key(kc, mask, True, X.GrabModeAsync, X.GrabModeAsync)
        self._grabbed = want
        self.d.sync()

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
