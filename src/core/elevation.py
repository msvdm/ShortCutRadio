"""Windows: running as administrator, for games that do.

While a program run as administrator is in front, Windows passes no keys to
a normal program's keyboard hook (UIPI; measured with Need for Speed Most
Wanted, which is set to run elevated). Microsoft lists what reads input
across that line anyway -- low-level hooks, raw input, GetAsyncKeyState --
and every one of them needs the reader to be elevated too, or to be a
signed UIAccess program in Program Files. So ShortCutRadio offers to run as
administrator (the `run_as_admin` setting), the way PowerToys and OBS do:
it starts itself again elevated, and Windows asks the user first.
"""

import ctypes
import functools
import os
import subprocess
import sys
from ctypes import wintypes

available = sys.platform == "win32"

TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20        # TOKEN_INFORMATION_CLASS.TokenElevation
SEE_MASK_NOASYNC = 0x0100
SW_SHOWNORMAL = 1

if available:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE))
    advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD))
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(SHELLEXECUTEINFOW),)


@functools.cache
def is_elevated():
    """True when this process runs as administrator (it never changes)."""
    if not available:
        return False
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(token)):
        return False
    try:
        elevated = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(elevated),
                                          ctypes.sizeof(elevated), ctypes.byref(size))
        return bool(ok and elevated.value)
    finally:
        kernel32.CloseHandle(token)


def command(options, frozen=None, executable=None, script=None):
    """How to start this program again with `options`: (file, parameters).
    From source that is Python and the script -- pythonw.exe when it is
    there, or the elevated copy would come with a console window."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        return executable, subprocess.list2cmdline(options)
    folder, name = os.path.split(executable)
    windowless = os.path.join(folder, "pythonw.exe")
    if name.lower() == "python.exe" and os.path.exists(windowless):
        executable = windowless
    script = os.path.abspath(script or sys.argv[0])
    return executable, subprocess.list2cmdline([script, *options])


def relaunch(options):
    """Start this program again as administrator. Windows asks the user
    first; False when they said no or it failed."""
    if not available:
        return False
    file, params = command(options)
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW),
                             fMask=SEE_MASK_NOASYNC, lpVerb="runas", lpFile=file,
                             lpParameters=params, lpDirectory=os.getcwd(),
                             nShow=SW_SHOWNORMAL)
    if shell32.ShellExecuteExW(ctypes.byref(info)):
        return True
    print(f"[admin] could not start as administrator (error {ctypes.get_last_error()})",
          flush=True)
    return False
