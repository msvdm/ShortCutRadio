"""The log file: what the app printed, where a user can find and attach it.

The Windows build has no console, so stdout and stderr are None there and
every print and traceback went nowhere. `start` opens `shortcutradio.log` in
the data folder and sends both streams to it -- and, where a console exists
(Linux, a source run), to the console as well. Uncaught exceptions already
go to stderr (sys.excepthook, PySide's slot errors, threading.excepthook),
so they land in the file with no extra code; faulthandler covers a crash
Python never sees.

One old log is kept (`.log.1`), never more. A log that can't be opened means
no log, not no app.
"""

import datetime
import faulthandler
import os
import sys

from .. import __version__

NAME = "shortcutradio.log"
MAX_BYTES = 512 * 1024

_file = None        # kept open for the life of the app (faulthandler holds it)


class Tee:
    """A stream that writes to the console and to the log file."""

    def __init__(self, console, file):
        self._console = console
        self._file = file

    def write(self, text):
        for stream in (self._console, self._file):
            try:
                stream.write(text)
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self):
        for stream in (self._console, self._file):
            try:
                stream.flush()
            except (OSError, ValueError):
                pass

    def __getattr__(self, name):        # encoding, isatty, fileno ...
        return getattr(self._console, name)


def open_log(folder):
    """Rotate past MAX_BYTES, open for appending, write the first line.
    Returns the file, or None if it can't be had."""
    path = os.path.join(folder, NAME)
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass            # no log yet, or it can't be moved: append to it
    try:
        f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"=== {stamp} ShortCutRadio {__version__} {sys.platform} ===\n")
        return f
    except OSError:
        return None


def start(folder):
    """Send stdout and stderr to the log in `folder` as well as the console."""
    global _file
    f = open_log(folder)
    if f is None:
        return None
    _file = f
    sys.stdout = Tee(sys.stdout, f) if sys.stdout is not None else f
    sys.stderr = Tee(sys.stderr, f) if sys.stderr is not None else f
    try:
        faulthandler.enable(f)
    except (OSError, ValueError, RuntimeError):
        pass
    return f
