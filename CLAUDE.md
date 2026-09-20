# ShortCutRadio — Development Rules

> This file is the working brief for Claude, the AI model that writes this
> project's code with its author. It records the decisions that cost a real
> debugging session, with the reasoning, so they don't get "simplified" back
> into bugs. Sections marked *do not re-litigate* were expensive.

## What this app is

A hidden audio player that feels like part of the OS: a discreet corner
overlay (toggled like the NVIDIA GPU-stats HUD) and a tray icon, controlled by
global shortcuts. The user starts it and a setup window opens: what's playing
across the top, then the tabs **Sources** (the list, with **Add Folder** /
**Add Stream** under it), **Shortcuts** and **Overlay**. Shortcuts cycle
through the list.

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
src/core/artfetch.py      a station's page -> its logo (stdlib only; same style as scraper)
src/core/coverart.py      a local track's cover: a file beside it, or ID3/FLAC/Ogg/MP4 art
src/core/levels.py        the level meters' numbers (pure, so they can be tested)
src/core/hotkeys.py       pynput listener (observes) + gating + capture mode
src/core/keygrab.py       X11 passive grabs so live keys don't reach the focused app
src/gui/theme.py          the skin: two token palettes + the app-wide stylesheet
src/gui/widgets.py        the hand-painted parts: art, pill switch, transport, meters
src/gui/main_window.py    frameless shell + hero strip + tab strip + the three pages
src/gui/artwork.py        which picture a source gets, cached on disk, fetched off-thread
src/gui/                  add_stream dialog, overlay, tray (icon drawn in code)
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
- **The window has no titlebar.** It is frameless: `#window` is a transparent
  carrier holding a 6 px resize margin, `#shell` is the rounded card inside it.
  Dragging and double-click-to-maximise are limited to the hero and the tab
  strip -- they stand in for the titlebar, and grabbing the window from under
  the source list surprised the first build. The edges call Qt's
  `startSystemResize`, the rest `startSystemMove`, both with a manual fallback.
  The only chrome is the × at the hero's top right; it and Esc hide to the
  tray, exactly as closing always did.
- **The hero is the same on all three tabs.** It first shrank to a compact
  strip on Shortcuts and disappeared on Overlay; the author disliked exactly
  that. One `Hero`, full size, always visible: what is playing and its
  transport must not move or vanish because a setting is being changed. The
  window's default height fits the Overlay tab because of it.
- **Station art has four sources, in this order:** a picture the author set by
  hand (right-click a source), a real cover for a folder (`cover|folder|front…`
  beside the track, then art embedded in it), the station's own site logo for
  a stream, and -- when all of that comes up empty -- a tile of the source's
  initials on a colour hashed from its name. The tile replaced the old stripe
  placeholder: the box is never blank, so nothing looks unwired.
- **A station can be told where it lives** (right-click -> `Station page…`).
  Add Stream records the page it harvested, and a playing Icecast/SHOUTcast
  mount announces one in `icy-url`, but an HLS stream announces nothing and
  nothing about `lb-hls.cdn.bg` says `binar.bg` -- radio-browser does not know
  that URL either. The dialog is pre-filled with the guess, so the author can
  see what it tried, and accepting always re-fetches: the old logo and the
  "no logo" marker both go.
- **A source's picture comes from its address, never from its name.** The
  fetched logo was always keyed by URL, but the generated tile was drawn from
  the source's name and the logo hunt vetted its guess with it -- so renaming
  a station repainted it, which is wrong: the picture stands for the station,
  not for what the author happens to call it. `sources.art_label()` derives
  the tile's letters and colour from the stream's mount name (bitrate and
  codec noise trimmed: `fluid-128-mp3` is Fluid), falling back to the site's
  own label (`radio.rn-tv.com` -> rn-tv), or from a folder's basename. The
  only thing a name still decides is nothing at all.
- **Artwork is fitted whole, never cropped to fill.** A station's logo is
  usually not square, and cropping a wide one to a square box left an
  unreadable middle third. The picture is trimmed of its flat or transparent
  border (logos ship inside a lot of empty space), scaled to fit *inside* the
  box, and centred on a backdrop: the logo's own border colour when it has
  one, so the tile looks like one card, else a panel chosen to contrast with
  it -- a white cut-out logo on the light theme was invisible otherwise. All
  of it happens once per picture in `fit_pixmap`, never in a paintEvent.
- **The launcher icon is the same broadcast mark as the tray's**, not the
  system's generic audio note. The menu entry reads a *file* and this app
  deliberately ships none, so `install_icon()` writes the drawn mark into
  `~/.local/share/icons/hicolor/<size>/apps/shortcutradio.png` on startup when it
  is not already there, and the entry says `Icon=shortcutradio`. A read-only home
  is not a reason to fail to start; the old icon just stays.
- **The transport sits between the name and the ×**, centred by a stretch on
  each side rather than pinned to the right edge, with the hero's right margin
  reserving the ×'s corner so they cannot collide at the minimum width.
- **Volume stops at 100 %.** mpv will happily amplify to 130 and the slider
  used to offer it; `Player.VOLUME_MAX` is the one place that says otherwise,
  and a louder value in an older config is clamped on load.
- **A station's page is found before its logo is.** In order: the page the
  streams were harvested from at Add Stream time (`source["site"]`), the
  `icy-url` the stream announces while playing (learned and saved, which is
  what rescues the NFSU2-seeded stations), the Icecast mount's `server_url`,
  and last the stream host with its `streams.`/`ice6.` label trimmed. That
  last guess must prove itself: the page has to mention a distinctive word
  from the source's name, or `lb-hls.cdn.bg` hands back the CDN's logo. Wrong
  art is worse than none, which is why the check exists and why it matches
  Unicode -- the first version was ASCII-only and let a CDN logo through for
  "БНР Бургас".
- **The level meters are decorative.** Random targets with a fast attack and a
  slow decay (`core/levels.py`), ~14 fps, and they run only while something is
  audible and the bars are on screen -- the overlay's repaint lands on top of
  a running game. Asking mpv for real levels would mean an audio filter and a
  metadata poll for something nobody can check against the music.
- **The window is skinned, not native.** One QSS string from `theme.stylesheet()`
  on the QApplication covers the window, the dialogs, the message boxes and the
  menus; `theme.tokens()` serves the parts painted by hand. The style is forced
  to Fusion so the skin sits on predictable metrics. Design direction "1b", both
  themes, was approved from a mock -- its colors, sizes, radii and paddings are
  final values, not suggestions.
- **The tab strip is plain buttons over a QStackedWidget-style show/hide, not a
  QTabBar.** Two tabs put something of their own at the right end of that same
  strip (the list hint on Sources, `Reset to default` on Overlay), which a
  styled QTabBar cannot hold.
- **The overlay card stays dark in both themes.** It renders over games, not
  over the desktop, and takes its colors from the overlay settings only.
- **Theme is `auto` | `dark` | `light`**, stored at the top level of the config
  and switched from the tray. `auto` follows
  `QGuiApplication.styleHints().colorScheme()` and falls back to dark.
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
- **A custom QWidget subclass ignores a stylesheet background** unless it sets
  `WA_StyledBackground`. The tray's now-playing header rendered on the menu's
  background until it did.
- **QSS font-size beats `setFont`.** Anything given a monospace face in code
  (key caps, the status line, the spin boxes) must have its size pinned in the
  stylesheet too, or the class rule overrides it. The family survives, because
  no rule sets `font-family`.
- **Art must be scaled for the screen, not the layout.** This desktop is 4K at
  3x, so a pixmap fitted to the widget's 88 *points* is drawn blurred. Scale to
  `size * devicePixelRatioF()` and set the ratio on the result -- once, in
  `fit_pixmap`, never in a paintEvent the meter calls fourteen times a second.
- **Qt copies what you put in a list item.** `QListWidgetItem.setData(role,
  src)` stores a *copy* of the dict and `item.data(role)` hands back a new one
  every call, so every context-menu action that wrote to it -- shuffle, and
  later artwork and station page -- silently edited a throwaway. Worse, the
  drag-to-reorder handler fed those copies back into the config, which left
  the player holding a source that was no longer in its own list (it matches
  by identity), so **reordering while playing stopped the music**. The items
  now carry an index (`INDEX_ROLE`) and every edit resolves through it to the
  real dict in `config["sources"]`; `SOURCE_ROLE` is for drawing the row only.
- **A frameless window must keep its size hints still.** Each tab's page has a
  different layout minimum, and when Qt sent the new hints Muffin re-applied
  the geometry: Overlay → Sources grew the window ~100 px every round trip,
  and it never shrank back. The same code with a titlebar is rock steady.
  `setMinimumSize` once, in the constructor, and it stops.
- **A word-wrapped QLabel needs a pinned wrapping width.** Qt asks it how tall
  it would be at its *minimum* width, so an unpinned one claims a dozen lines
  and drags the window's minimum up with it (`WRAP_W`).
- **`Qt.Edge` is a flag enum: `int(...)` on it raises.** Use `.value` as the
  dict key for the resize cursors.
- **The single instance is per config, not per user.** It used to be
  `shortcutradio-<user>`, so the scratch-config test run this file prescribes just
  handed its window to the real ShortCutRadio and exited. The name now carries a
  hash of `data_dir()`.
- **A row keeps its last painted frame when the meter stops.** Pausing has to
  repaint the source list itself, or the bars stay frozen on screen instead of
  disappearing.
- **Wayland is not supported** (pynput and X grabs are X11-only). Mint is X11 today.

## Testing

- `.venv/bin/python -m pytest -q tests`
- Run against a scratch config so the real one (`~/.config/ShortCutRadio/`) is
  untouched: `XDG_CONFIG_HOME=/tmp/x .venv/bin/python shortcutradio.py`.
  `SHORTCUTRADIO_DEBUG_KEYS=1` logs every observed combo.
- Use `python -m src.core.scraper URL` to check a station page. Reference
  results: badrockradio.net → 4 channels, binar.bg → 12 BNR HLS stations,
  somafm.com/fluid/ → 4 bitrates.
- Use `python -m src.core.artfetch URL` for the logo side; it takes a station
  page or a stream URL. somafm.com/fluid/ → fluid400.jpg (400x400),
  badrockradio.net → badrock_app_icon.jpg (512x512).
- There is no audio on this machine to test folder covers with. `ffmpeg` can
  make some: `-f lavfi -i sine=d=40 -i cover.jpg -map 0:a -map 1:v -c:v mjpeg
  -disposition:v attached_pic out.mp3` gives embedded art (it cannot do this
  for Ogg/Opus -- that reader is covered by a synthetic file in the tests).
- **Synthetic key tests:** use python-xlib `xtest.fake_input` + `d.sync()`.
  pynput's `Controller` keys are *invisible to a listener in another process*.
  Synthetic keys type into whatever window has focus: focus a test window
  first and check it is active before each tap. One test typed `[[[[` into
  the author's chat box.
- Stopping a test instance: match `^.venv/bin/python shortcutradio`. A bare
  `pkill -f "python shortcutradio.py"` also kills the shell that ran it.
- A GUI started with the chat's `!` prefix dies when that command returns. The
  author launches via the menu entry `~/.local/share/applications/shortcutradio.desktop`
  (`Icon=shortcutradio`, installed by `install_icon()`). Cinnamon caches the menu,
  so a changed icon can take a re-login to show.

## Not done yet

Packaging (PyInstaller / AppImage / Windows zip with mpv-2.dll), game hooks (e.g.
NFSU2 world-load autostart, in the style of the old radio's `/proc/<pid>/fd`
check), MPRIS/SMTC media keys, Windows/macOS key suppression (pynput
`win32_event_filter` / `darwin_intercept`), and confirming the overlay over
fullscreen NFSU2. The tray menu's skin is unconfirmed on this desktop: if
Cinnamon serves the tray over StatusNotifier/DBus the menu is drawn by the
desktop and the stylesheet is ignored (the actions still work) -- the art in
its header is drawn by ShortCutRadio either way, but has not been seen. The author
has an "at work" idea still to explain.

## Git

Private repo `msvdm/ShortCutRadio`, branch `main`. End commits with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
