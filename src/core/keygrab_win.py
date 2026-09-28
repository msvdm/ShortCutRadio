"""The Windows keyboard: one low-level hook that hears, fires and takes.

On X11 the listener (pynput/XRECORD) observes and keygrab.py only swallows.
pynput's Windows backend cannot split the work that way: suppressing a key in
its `win32_event_filter` also hides it from its own listener
(moses-palmer/pynput#679). A WH_KEYBOARD_LL hook does both jobs in one place:
it sees every key before any app does, asks hotkeys.py what the key is, and
returns non-zero to keep it from the focused app.

A key that was taken on its way down is taken on its way up as well, so the
app in front never sees half a key. Releases always arrive here, so a key we
have not seen released is repeating -- no timing guess as on X11; the gap is
only a net for a release lost to the secure desktop (Win+L, Ctrl+Alt+Del).

Key names follow pynput's, so configs look the same on both platforms. A
printable key is named by its scan code through the user's *default* input
language, never the one in use: switching the window in front to a second
language does not change what a shortcut matches (as on X11, where pynput
reads group 1). Not the layout the hook thread starts with either -- a new
thread inherits whatever language is active at that moment, and measured
here that was Bulgarian, which named "]" as a Cyrillic letter.
"""

import ctypes
import sys
import threading
import time
import traceback
from ctypes import wintypes

available = sys.platform == "win32"

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_QUIT = 0x0012
LLKHF_EXTENDED = 0x01
LLKHF_UP = 0x80
MAPVK_VK_TO_CHAR = 2
MAPVK_VSC_TO_VK_EX = 3
SPI_GETDEFAULTINPUTLANG = 0x59
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
REPEAT_GAP_S = 1.5          # Windows' longest repeat delay is 1 s

# Unassigned, so no app acts on it. Pressed after a key taken while Alt or
# Win is held: otherwise the lone Alt release opens the app's menu bar, and
# the lone Win release the Start menu. AutoHotkey uses the same key for this.
MASK_VK = 0xE8
MASK_TAG = 0x5343_5244      # dwExtraInfo on our own mask key, "SCRD"

MODIFIERS = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "super", 0x5C: "super",
}
# Virtual keys -> pynput's key names. Everything printable is named by its
# character instead (see KeyHook._name).
NAMES = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x13: "pause",
    0x14: "caps_lock", 0x1B: "esc", 0x20: "space", 0x21: "page_up",
    0x22: "page_down", 0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up",
    0x27: "right", 0x28: "down", 0x2C: "print_screen", 0x2D: "insert",
    0x2E: "delete", 0x5D: "menu", 0x90: "num_lock", 0x91: "scroll_lock",
    0xAD: "media_volume_mute", 0xAE: "media_volume_down",
    0xAF: "media_volume_up", 0xB0: "media_next", 0xB1: "media_previous",
    0xB2: "media_stop", 0xB3: "media_play_pause",
    **{0x70 + i: f"f{i + 1}" for i in range(24)},
}
UNNAMED = {0xE7, MASK_VK, 0xFF}     # VK_PACKET (typed Unicode), ours, none
NUMPAD = range(0x60, 0x70)          # their own vk, whatever the scan code says


def vk_name(vk, char=""):
    """A virtual key (and the character it types, if any) -> our key name."""
    if vk in NAMES:
        return NAMES[vk]
    if char and char.isprintable() and not char.isspace():
        return char.lower()
    return f"vk{vk}"


if available:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM,
                                  wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):     # only here to size the union
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC,
                                         wintypes.HINSTANCE, wintypes.DWORD)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT)
    user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM)
    user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
    user32.GetKeyboardLayout.restype = wintypes.HKL
    user32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.HKL)
    user32.MapVirtualKeyExW.restype = wintypes.UINT
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = wintypes.SHORT
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SystemParametersInfoW.argtypes = (wintypes.UINT, wintypes.UINT,
                                             ctypes.c_void_p, wintypes.UINT)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def default_layout():
    """The keyboard layout of the default input language (Settings > Time &
    language > Typing > Advanced keyboard settings)."""
    hkl = wintypes.HKL()
    if user32.SystemParametersInfoW(SPI_GETDEFAULTINPUTLANG, 0, ctypes.byref(hkl), 0):
        return hkl
    return user32.GetKeyboardLayout(0)


class KeyHook:
    """The Windows counterpart of the pynput listener and KeyGrabber together.

    `on_key(name, mods, repeat)` is called on the hook's thread for every key
    press that is not a modifier, and returns True to take the key.
    """

    def __init__(self, on_key):
        self._on_key = on_key
        self.available = available
        self.error = ""
        self._down = {}         # vk -> when its last press arrived
        self._taken = set()     # vks whose press was taken: take the release too
        self._hkl = None
        self._tid = 0
        self._thread = None

    def start(self):
        if not self.available:
            return False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,),
                                        name="keyhook", daemon=True)
        self._thread.start()
        ready.wait(2)
        return not self.error

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1)

    def set_combos(self, combos):
        """X11 has to grab each live key in advance; the hook asks hotkeys.py
        per key instead, so there is nothing to do. Kept for the same seam."""

    # --------------------------------------------------------------- hook thread
    def _run(self, ready):
        self._tid = kernel32.GetCurrentThreadId()
        self._hkl = default_layout()
        proc = HOOKPROC(self._proc)         # must outlive the hook
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc,
                                        kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self.error = f"keyboard hook refused (error {ctypes.get_last_error()})"
            ready.set()
            return
        ready.set()
        msg = wintypes.MSG()
        # The system calls the hook from inside GetMessage; nothing is posted
        # to this thread but the WM_QUIT that ends it.
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hook)

    def _proc(self, code, wparam, lparam):
        if code == HC_ACTION:
            kb = KBDLLHOOKSTRUCT.from_address(lparam)
            try:
                if kb.dwExtraInfo != MASK_TAG and self.event(
                        kb.vkCode, kb.scanCode, kb.flags):
                    return 1
            except Exception:       # one odd key must not cost every shortcut
                traceback.print_exc()
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def event(self, vk, scan, flags):
        """One key event -> True to keep it from every app after us."""
        if vk in MODIFIERS:
            return False                # never taken: the app keeps its own state
        if flags & LLKHF_UP:
            self._down.pop(vk, None)
            if vk in self._taken:
                self._taken.discard(vk)
                return True
            return False
        name = self._name(vk, scan, flags)
        if name is None:
            return False
        now = time.monotonic()
        repeat = now - self._down.get(vk, -REPEAT_GAP_S) < REPEAT_GAP_S
        self._down[vk] = now
        mods = self._mods()
        if not self._on_key(name, mods, repeat):
            return False
        self._taken.add(vk)
        if mods & {"alt", "super"}:
            self._mask()
        return True

    def _name(self, vk, scan, flags):
        if vk in UNNAMED:
            return None
        if vk in NAMES:
            return NAMES[vk]
        if scan and not flags & LLKHF_EXTENDED and vk not in NUMPAD:
            vk = user32.MapVirtualKeyExW(scan, MAPVK_VSC_TO_VK_EX, self._hkl) or vk
        # The low word is the unshifted character; the top bit marks a dead key.
        char = user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_CHAR, self._hkl) & 0xFFFF
        return vk_name(vk, chr(char) if char else "")

    @staticmethod
    def _mods():
        """The modifiers held right now, from the system rather than from the
        events we saw: a release lost to the secure desktop must not leave
        Win held for every key after it."""
        return {name for vk, name in ((0x11, "ctrl"), (0x12, "alt"),
                                      (0x10, "shift"), (0x5B, "super"),
                                      (0x5C, "super"))
                if user32.GetAsyncKeyState(vk) & 0x8000}

    @staticmethod
    def _mask():
        keys = (INPUT * 2)()
        for i, flags in enumerate((0, KEYEVENTF_KEYUP)):
            keys[i].type = INPUT_KEYBOARD
            keys[i].ki = KEYBDINPUT(MASK_VK, 0, flags, 0, MASK_TAG)
        user32.SendInput(2, keys, ctypes.sizeof(INPUT))
