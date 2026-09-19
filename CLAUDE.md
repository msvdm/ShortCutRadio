# ShortCutRadio — Development Rules

> This file is the working brief for Claude, the AI model that writes this
> project's code with its author. It records the decisions that cost a real
> debugging session, with the reasoning, so they don't get "simplified" back
> into bugs. Sections marked *do not re-litigate* were expensive.

## What this app is

A hidden audio player that feels like part of the OS: a discreet corner
overlay (toggled like the NVIDIA GPU-stats HUD) and a tray icon, controlled by
global shortcuts. The user starts it and a small setup window opens: shortcuts
on the left with **Add Folder** / **Add Stream** below them, and the source list
on the right. Shortcuts cycle through the list.

It grew out of the NFSU2 in-game radio (`~/Games/NFSU2/radio/`), which is now
bypassed in that game's `play.sh` (`NFS_RADIO=1` still starts it). ShortCutRadio
is meant to serve every game and non-game use, at home and at work.

Goals, in order: works reliably on this Linux Mint (X11, Cinnamon) machine →
portable (one folder) → cross-platform (Windows, macOS).

## Core principles

1. **Keep it simple.** Minimal code, no speculative features.
2. **Never crash on I/O.** Dead streams retry, unreadable config falls back to
   defaults, and scraper errors end up as an empty result.
3. **No README/requirements files until the author asks.** They'll be written
   once the app is ready.

## Architecture

```
shortcutradio.py               entry; single instance via QLocalServer ("show" message)
src/app.py                wires everything; quit = save, stop, os._exit
src/core/config.py        JSON config; portable mode if shortcutradio.portable sits next to the app
src/core/sources.py       source = {name, kind: stream|folder, target, shuffle}
src/core/player.py        libmpv (python-mpv) in-process; one `changed` signal with a state snapshot
src/core/scraper.py       Add Stream: URL/page/playlist -> list of verified streams (stdlib only)
src/core/hotkeys.py       pynput listener (observes) + gating + capture mode
src/core/keygrab.py       X11 passive grabs so live keys don't reach the focused app
src/gui/                  main_window, add_stream dialog, overlay, tray (icon drawn in code)
tests/test_core.py        pytest, pure functions only
```

Stack: Python 3.12, PySide6, python-mpv (needs system libmpv2), pynput,
python-xlib. The venv is `.venv/`. It matches the author's AnyDMX project layout.

## Decisions — do not re-litigate

- **Engine = mpv, in-process via libmpv.** The author asked whether any player
  would do. Most can play audio, but mpv is built to be scripted headless, runs
  on Windows, macOS and Linux, and on Windows ships as one DLL. MPRIS/SMTC
  media-key integration is a later add-on at the edges, not a reason to switch.
- **Single-key shortcuts are live only while the overlay is on, and while
  live they are TAKEN.** The focused app must not receive them. The author
  asked for exactly this: *overlay visible → key taken; overlay hidden → key
  free.* The overlay toggle must include Ctrl/Alt/Super; it is always live and
  always grabbed.
- **Observe + grab, not grab alone.** The pynput listener (XRECORD) fires the
  actions. keygrab.py only swallows keys. XRECORD still sees grabbed keys, so
  each action fires once, and it also sees keys inside fullscreen Wine games,
  where the game's own keyboard grab beats our passive grabs. There the key
  reaches the game too, which is unavoidable: pick keys the game doesn't use.
- **Folders are expanded in Python** (walk → sort/shuffle → temp m3u →
  `loadlist`), and `loop-playlist=inf` is set for folders, `no` for streams.
  This makes shuffle and skip behave the same on mpv 0.37, where `loadfile`
  has no index argument.
- **Streams retry** 5 s after an EOF or error (see `Player._on_end_file`).
  Replacing a file ends it with reason ABORTED, which must be ignored.
- **Next/previous source keep the play state:** paused stays paused, stopped
  stays stopped (`Player.select_source`). Only an explicit play (double-click,
  menu Play, Play/Pause) starts playback. `pause` is set *before* loading, or
  the new source is heard for a moment.
- **Overlay card size comes from the settings only** (width, font sizes), never
  from the text, so it doesn't jump. Text that doesn't fit scrolls (ticker) or
  is elided. The look is set in the window's Overlay Controls column.
- **Overlay:** a frameless Qt window that stays on top, lets input through
  (`WindowTransparentForInput`) and bypasses the window manager, and is re-raised every
  3 s. Click-through was verified: its X input shape is empty. Drawing over a
  fullscreen game works because Muffin keeps compositing fullscreen windows
  (`unredirect-fullscreen-windows=false`).

## Traps — measured, do not re-litigate

- **libmpv refuses a non-C numeric locale.** Reset `LC_NUMERIC` to `C` *after*
  `QApplication()` is created (Qt sets the locale from the environment).
- **Never call pynput `Listener.stop()` on quit.** Its XRECORD stop blocked
  forever and left a "quit" ShortCutRadio running, still holding the keys. Quit
  saves, releases the grabs, then `os._exit`.
- **Wrap pynput callbacks** (`Hotkeys._safe`): an uncaught exception silently
  stops the whole listener.
- **Key-press debouncing:** X auto-repeat sends press/release pairs, so holding
  a key repeats it. Only volume may repeat; other actions are debounced to 250 ms.
- **Wayland is not supported** (pynput and X grabs are X11-only). Mint is X11 today.

## Testing

- `.venv/bin/python -m pytest -q tests`
- Run against a scratch config so the real one (`~/.config/ShortCutRadio/`) is
  untouched: `XDG_CONFIG_HOME=/tmp/x .venv/bin/python shortcutradio.py`.
  `SHORTCUTRADIO_DEBUG_KEYS=1` logs every observed combo.
- Use `python -m src.core.scraper URL` to check a station page. Reference
  results: badrockradio.net → 4 channels, binar.bg → 12 BNR HLS stations,
  somafm.com/fluid/ → 4 bitrates.
- **Synthetic key tests:** use python-xlib `xtest.fake_input` + `d.sync()`.
  pynput's `Controller` keys are *invisible to a listener in another process*.
  Synthetic keys type into whatever window has focus: focus a test window
  first and check it is active before each tap. One test typed `[[[[` into
  the author's chat box.
- Stopping a test instance: match `^.venv/bin/python shortcutradio`. A bare
  `pkill -f "python shortcutradio.py"` also kills the shell that ran it.
- A GUI started with the chat's `!` prefix dies when that command returns. The
  author launches via the menu entry `~/.local/share/applications/shortcutradio.desktop`.

## Not done yet

Packaging (PyInstaller / AppImage / Windows zip with mpv-2.dll), game hooks (e.g.
NFSU2 world-load autostart, in the style of the old radio's `/proc/<pid>/fd`
check), MPRIS/SMTC media keys, Windows/macOS key suppression (pynput
`win32_event_filter` / `darwin_intercept`), and confirming the overlay over
fullscreen NFSU2. The author has an "at work" idea still to explain.

## Git

Private repo `msvdm/ShortCutRadio`, branch `main`. End commits with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
