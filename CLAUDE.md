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
3. **The README stays short and plain.** It is for people who are not
   programmers: what the app does and how to start it, no internals. Update
   it when something a user sees changes; the reasoning belongs here.

## Architecture

```
shortcutradio.py               entry; single instance via QLocalServer ("show" message)
src/app.py                wires everything; quit = save, stop, os._exit
src/core/config.py        JSON config; portable mode if shortcutradio.portable sits next to the app
src/core/sources.py       source = {name, kind: stream|folder, target, shuffle}; names from URLs
src/core/player.py        libmpv (python-mpv) in-process; one `changed` signal with a PlayerState
src/core/net.py           the one door to the network: open_url, NET_ERRORS, Icecast status
src/core/scraper.py       Add Stream: URL/page/playlist -> list of verified streams (stdlib only)
src/core/artfetch.py      a station's page -> its logo (stdlib only; same style as scraper)
src/core/coverart.py      a local track's cover: a file beside it, or ID3/FLAC/Ogg/MP4 art
src/core/levels.py        the level meters' numbers (pure, so they can be tested)
src/core/hotkeys.py       pynput listener (observes) + gating + capture mode
src/core/keygrab.py       X11 passive grabs so live keys don't reach the focused app
src/core/mpris.py         media keys: ShortCutRadio as an MPRIS player (QtDBus), sound applet
src/core/mediakeys.py     media keys: the settings daemon's claim (jeepney)
src/gui/theme.py          the skin: two token palettes + the app-wide stylesheet
src/gui/widgets.py        the hand-painted parts: pill switch, transport, meters, labels
src/gui/art.py            the art box: trim, fit, backdrop, initials tile (FittedArt)
src/gui/frameless.py      a titlebar-less window: resize margin, move, maximise
src/gui/main_window.py    hero + tab strip; each tab is its own page module:
src/gui/sources_page.py     the list, its row delegate, add/edit/remove
src/gui/shortcuts_page.py   key caps and capture
src/gui/overlay_page.py     the card's look
src/gui/artwork.py        which picture a source gets, cached on disk, fetched off-thread
src/gui/                  add_stream dialog, overlay, tray (icon drawn in code)
tests/test_core.py        pytest, pure functions only
README.md, LICENSE        the public face (MIT); docs/ holds its screenshots
requirements.txt          pip dependencies (libmpv comes from the system)
```

Stack: Python 3.12, PySide6, python-mpv (needs system libmpv2), pynput,
python-xlib, jeepney (pure Python, for the media-key claim only). The venv is `.venv/`. It matches the author's AnyDMX project layout.

## Decisions — do not re-litigate

- **Engine = mpv, in-process via libmpv.** The author asked whether any player
  would do. Most can play audio, but mpv is built to be scripted headless, runs
  on Windows, macOS and Linux, and on Windows ships as one DLL. MPRIS/SMTC
  media-key integration is a later add-on at the edges, not a reason to switch.
- **Shortcuts are live only while the overlay is on, and while live they are
  TAKEN.** The focused app must not receive them. The author asked for exactly
  this: *overlay visible → key taken; overlay hidden → key free* -- and for
  **every** shortcut, not only the single-key ones. The first build exempted
  combos with Ctrl/Alt/Super, so Play/Pause on Ctrl+E kept firing while the
  overlay was off and the app in front never got its own Ctrl+E; that was
  wrong. The one exception is the overlay toggle itself (`hotkeys.ALWAYS_LIVE`):
  it must include Ctrl/Alt/Super, and it is always live and always grabbed,
  because nothing else could turn the overlay back on.
- **Observe + grab, not grab alone.** The pynput listener (XRECORD) fires the
  actions. keygrab.py only swallows keys. XRECORD still sees grabbed keys, so
  each action fires once, and it also sees keys inside fullscreen Wine games,
  where the game's own keyboard grab beats our passive grabs. There the key
  reaches the game too, which is unavoidable: pick keys the game doesn't use.
- **Media keys go through the desktop, not the listener + a grab.** Muffin
  owns bare XF86AudioPlay/Next/Prev/Stop and csd-media-keys passes each press
  to a player -- with no player it showed a big "Unavailable" every time the
  author pressed Play, even though the listener had acted on it. So a *bare*
  media key bound in ShortCutRadio is neither grabbed nor acted on by the listener
  (`Hotkeys.via_desktop`); the desktop delivers it (`press_media`) and it goes
  through the same bindings, so the Next key can mean "next source". Two
  channels, both needed: the claim (`mediakeys.py`, GrabMediaPlayerKeys),
  because csd serves claimed apps before MPRIS players and gives MPRIS players
  the keys first come, first served -- a browser with a video tab that got
  there first kept the Play key with our overlay on; and the MPRIS player
  (`mpris.py`) for the sound applet and for desktops without the claim (KDE).
  The author chose the overlay rule for these too: ShortCutRadio is a player and
  holds the claim only while the overlay is on **and** a media key is bound
  (`App._sync_media`); otherwise it is off the bus and the keys go wherever
  they would without ShortCutRadio. Ctrl+Next and the like stay ordinary grabbed
  shortcuts (the desktop binds the bare key only). Volume/mute keys stay the
  system's. Without a session bus the media keys fall back to the listener.
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
  tray, exactly as closing always did -- silently: the author disliked the
  "still running in the tray" notice, so there is none.
- **The hero is the same on all three tabs.** It first shrank to a compact
  strip on Shortcuts and disappeared on Overlay; the author disliked exactly
  that. One `Hero`, full size, always visible: what is playing and its
  transport must not move or vanish because a setting is being changed. The
  window's default height fits the Overlay tab because of it.
- **Station art has four sources, in this order:** a picture the author set by
  hand (right-click a source), a real cover for a folder (`cover|folder|front…`
  beside the track, then art embedded in it), the station's own site logo for
  a stream, and -- when all of that comes up empty -- a tile of initials on a
  colour, both from the source's address (see below). The tile replaced the old
  stripe placeholder: the box is never blank, so nothing looks unwired.
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
- **One state, one edit path.** The player emits a frozen `PlayerState`;
  the hero, the overlay and the tray each turn its `phase` (empty, error,
  stopped, paused, connecting, playing) into their own words, and read
  `audible` / `playing` / `can_skip_track` instead of re-deriving them. They
  used to run three if-ladders over a dict, in three different orders. Every
  change to a source goes through `App.edit_source(src, **changes)` and every
  change to the card through `App.update_overlay(**changes)`; nothing else
  writes to the config's dicts. The player remembers its source *object*, so
  an edited, reordered or trimmed list needs only `sources_changed()`.
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
- **Auto-repeat re-fires the action, and a repeat carries no release.**
  Measured here: holding a key sends 25 presses and 1 release in 1.2 s -- the
  first repeat 500 ms after the press, the rest every 30 ms (`xset q`). The
  old 250 ms debounce only thinned that to 4/s, so holding Ctrl+E for 0.8 s
  toggled play/pause three times and looked like a dead shortcut; that was the
  "sometimes it works" bug. A key not yet seen released is repeating
  (`Hotkeys._down`) and only volume rides it. The gap that forgives a release
  we never saw must be longer than the repeat *delay*, not the interval
  between repeats, and a modifier's release clears the held keys -- a held key
  reports a different character once Shift is gone.
- **pynput reads Shift as AltGr on any keymap without Mode_switch.** It looks
  up the Mode_switch keycode, gets 0, then finds 0 in the zero padding of the
  modifier table's *shift* row, so its AltGr mask is ShiftMask. Every Shift+key
  is then read at level 4 of the keymap, which on `us,bg` is the Bulgarian
  letter: Alt+Shift+E records `alt+shift+е`. It is consistent, so it matches --
  but `ord("е")` is 1077, which is not a keysym, so that key could not be
  grabbed and leaked into the focused app. The keysym pynput reports
  (`KeyCode.vk`) is learned from every press, kept in the config (`keysyms`)
  and preferred by `keygrab.keysym_for`.
- **The active layout does not change what matches.** Cinnamon switches
  layouts by locking the XKB group, and pynput ignores the group (it reads
  index 0/1 of the keycode's keysym list), so the E key reports `e` in both
  us and bg -- verified by switching and re-reading. What a binding would not
  survive is a different *order* of the input sources, which makes another
  layout group 1.
- **A key that cannot be grabbed has to say so.** `_apply` used to skip an
  unresolvable keysym and swallow BadAccess, so a shortcut that also typed
  into the focused app looked exactly like a working one. It now reports what
  it could not take (`Hotkeys.ungrabbed`) and the Shortcuts tab marks those
  rows with a ⚠ and a tooltip.
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
  `art.FittedArt` keeps the original picture, so a new box size is fitted from
  it; the overlay used to re-fit its own fitted copy, and compared points with
  pixels, so on this 3x screen it re-fitted on every state change.
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
- **A row keeps its last painted frame when the meter stops.** Without a
  repaint the bars stay frozen on screen instead of disappearing, so
  `Meter.set_running(False)` emits one last `tick` and every consumer repaints
  without them.
- **PySide6's QtDBus mis-types what the spec insists on.** `createReply(list)`
  sends the list as *one* argument (build the reply empty, then
  `setArguments`); an empty Python list goes out as `av` where MPRIS says `as`
  (build it typed, `mpris._no_strings`); a Python int is always `i` (`q`
  through QDBusArgument) and nothing makes a `u` or an `x`. `Position` is left
  out for that reason (the applet only reads it when `CanSeek`), and the claim
  -- `GrabMediaPlayerKeys(su)`, csd rejects `(si)` -- is sent with jeepney.
- **csd drops a claim when the claiming connection closes**, and sends the
  key signal *to that connection only*. So the claim lives on its own jeepney
  connection whose socket Qt's event loop reads (`QSocketNotifier`); closing
  it is the release, a crash included. On Cinnamon the service is the old
  shared name `org.gnome.SettingsDaemon`, path `/org/gnome/SettingsDaemon/MediaKeys`.
- **The desktop passes a held media key's auto-repeat straight on** (a 1.5 s
  hold of Play: 34 calls, no release) and the last repeat's call can land
  *after* the listener has seen the release. The listener still hears media
  keys, so it marks each press as a repeat or not (`Hotkeys._repeating`) and
  `press_media` applies the same rule as for any key. The mark survives the
  release on purpose; the next real press resets it, and the listener always
  sees that press before the desktop's call arrives (measured).
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
  A press with no release lets X's own auto-repeat run, which is the only way
  to test the repeat rule; `xtest.fake_input` of Ctrl+Shift_L switches the
  layout, which is how the group questions above were answered.
  pynput's `Controller` keys are *invisible to a listener in another process*.
  Synthetic keys type into whatever window has focus: focus a test window
  first and check it is active before each tap. One test typed `[[[[` into
  the author's chat box.
- **Media key tests:** python-xlib's `XK` doesn't know the XF86 names without
  loading them, so fake the keysym number (Play 0x1008FF14, Next 0x1008FF17,
  Stop 0x1008FF15) -- it goes the whole way, Muffin → csd → ShortCutRadio. Media keys
  type nothing into the focused window. Watch with `dbus-monitor --session
  "type='signal',member='MediaPlayerKeyPressed'"`, read state with `gdbus call
  --session --dest org.mpris.MediaPlayer2.shortcutradio --object-path
  /org/mpris/MediaPlayer2 --method org.freedesktop.DBus.Properties.Get
  org.mpris.MediaPlayer2.Player PlaybackStatus`. A tiny QDBusVirtualObject
  registered as `org.mpris.MediaPlayer2.<x>` *before* ShortCutRadio starts stands in
  for the browser that got there first.
- Stopping a test instance: match `^.venv/bin/python shortcutradio`. A bare
  `pkill -f "python shortcutradio.py"` also kills the shell that ran it.
- A GUI started with the chat's `!` prefix dies when that command returns. The
  author launches via the menu entry `~/.local/share/applications/shortcutradio.desktop`
  (`Icon=shortcutradio`, installed by `install_icon()`). Cinnamon caches the menu,
  so a changed icon can take a re-login to show.

## Not done yet

Packaging (PyInstaller / AppImage / Windows zip with mpv-2.dll), game hooks (e.g.
NFSU2 world-load autostart, in the style of the old radio's `/proc/<pid>/fd`
check), media keys on Windows (SMTC) and macOS (Now Playing) -- same seam as
`Mpris` (`available`, `set_active`, `set_keys`, `set_state`, `pressed`); until
then they fall back to the listener, which is fine there as no "Unavailable"
shows -- Windows/macOS key suppression (pynput
`win32_event_filter` / `darwin_intercept`), and confirming the overlay over
fullscreen NFSU2. The tray menu's skin is unconfirmed on this desktop: if
Cinnamon serves the tray over StatusNotifier/DBus the menu is drawn by the
desktop and the stylesheet is ignored (the actions still work) -- the art in
its header is drawn by ShortCutRadio either way, but has not been seen.

## Git

Public repo `msvdm/ShortCutRadio` (MIT), branch `main`. Everything pushed is
published: no personal paths, configs or keys in commits. End commits with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
