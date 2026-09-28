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
portable (one folder) → cross-platform (Windows, macOS). Windows 10/11 is
ported (keys, media, builds); macOS is not started.

## Core principles

1. **Keep it simple.** Minimal code, no speculative features.
2. **Never crash on I/O.** Dead streams retry, unreadable config falls back to
   defaults, and scraper errors end up as an empty result.
3. **The README stays short and plain.** It is for people who are not
   programmers: what the app does and how to start it, no internals. Update
   it when something a user sees changes; the reasoning belongs here.

## Architecture

```
shortcutradio.py          entry; single instance via QLocalServer ("show" message)
src/app.py                wires everything; quit = save, stop, os._exit
src/core/config.py        JSON config; portable mode if shortcutradio.portable sits next to the app
src/core/sources.py       source = {name, kind: stream|folder, target, shuffle}; names from URLs
src/core/player.py        Qt Multimedia (QMediaPlayer); one `changed` signal with a PlayerState
src/core/relay.py         localhost stream relay: ICY/Ogg titles out, bare audio in to Qt
src/core/net.py           the one door to the network: open_url, NET_ERRORS, Icecast status
src/core/scraper.py       Add Stream: URL/page/playlist -> list of verified streams (stdlib only)
src/core/artfetch.py      a station's page -> its logo (stdlib only; same style as scraper)
src/core/coverart.py      a local track's cover: a file beside it, or ID3/FLAC/Ogg/MP4 art
src/core/levels.py        the level meters' numbers (pure, so they can be tested)
src/core/hotkeys.py       gating + capture mode; the listener is pynput (X11) or keygrab_win
src/core/keygrab.py       X11 passive grabs so live keys don't reach the focused app
src/core/keygrab_win.py   Windows: one low-level keyboard hook that hears, fires and takes
src/core/mpris.py         media keys: ShortCutRadio as an MPRIS player (QtDBus), sound applet
src/core/mediakeys.py     media keys: the settings daemon's claim (jeepney)
src/core/smtc.py          Windows' Now Playing (SMTC, pywinrt), behind mpris.py's seam
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
requirements.txt          pip dependencies (PySide6 brings the player and its FFmpeg)
shortcutradio.spec        PyInstaller: one folder, dist/ShortCutRadio/
shortcutradio-windows.spec  the same on Windows
packaging/                build.sh (tests, build, tarball, .deb), build-deb.sh, .desktop;
                          build.ps1 (tests, build, zip, installer), shortcutradio.iss
                          (Inno Setup), make_ico.py, THIRD_PARTY(-windows).txt
```

Stack: Python 3.12, PySide6 (Qt Multimedia and its FFmpeg are the player), pynput,
python-xlib, jeepney (pure Python, for the media-key claim only). The venv is `.venv/`. It matches the author's AnyDMX project layout.
On Windows (Python 3.13 here): no pynput, python-xlib or jeepney; pywinrt's
`winrt-*` packages for SMTC. No venv on Windows: the author keeps
one global Python (per-user 3.13 on PATH) for every project, so the
requirements are installed into it and `python` is that interpreter.

## Decisions — do not re-litigate

- **Engine = Qt's own player (Qt Multimedia), not mpv.** mpv came first:
  built to be scripted headless, on every platform, one DLL on Windows. The
  author reopened that for the Windows port, where shinchiro's libmpv-2.dll
  was 116 MB of a 194 MB app and GPL-2.0-or-later -- the MIT app's download
  under GPL terms, with exact sources to host. PySide6 already ships Qt
  Multimedia with its own FFmpeg 7 (avcodec-61): `avcodec_license()` says
  LGPL 2.1 or later, the build has no `--enable-gpl`, and it has what radio
  needs (mp3, aac with HE-AACv2, opus, vorbis, flac; hls, https). So the
  engine is `QMediaPlayer` + `QAudioOutput`; python-mpv, libmpv2 and the DLL
  are gone, the Windows app is 99 MB, and macOS gets an engine for free.
  Measured against mpv on the same mounts (Windows, volume 0), time to
  sound: MP3 0.92 s against 0.81, AAC 0.88 / 0.81, Opus 0.36 / 0.38, HLS
  0.48 / 0.44; a station change about 0.9 s, a stop under 0.1 s, the GUI
  thread never blocked for more than about 0.1 s. What Qt doesn't do is
  ours: song titles (the relay, next) and a folder's playlist (below).
  Volume is cubic, as mpv's was (`volume_gain`), so the 5 % steps sound even.
- **Stream titles come from our own relay** (`core/relay.py`). Qt's metadata
  has codec and bitrate, never Icecast's StreamTitle. So a stream plays from
  `http://127.0.0.1:<port>/<token>`: the relay fetches it with Icy-MetaData,
  cuts the metadata out every `icy-metaint` bytes, reports StreamTitle and
  the `icy-url` header, and serves the bare audio. An Ogg stream's titles
  are in its comment packets (Opus, Vorbis, FLAC). Anything else -- HLS, a
  plain file -- gets a 302 to its real address, so FFmpeg fetches it itself
  and an HLS playlist's segments resolve against the right host. Loopback
  only, one live stream; every report carries its token, so a late one from
  the previous station is dropped.
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
- **Folders are expanded in Python** (walk → sort/shuffle) and the player
  keeps the list and its place: the end of a track moves on, looping, and
  next/previous wrap round at both ends. A file that won't play is skipped,
  unless none of them will. A local track never counts as "connecting" (only
  a stall does), or the status blinked on every track change.
- **Streams retry** 5 s after an end or an error (`Player._stream_ended`).
  Qt's signals can arrive late from a source already replaced: an end
  counts only while something is loaded and Qt still says EndOfMedia, an
  error only while `error()` is set. A dropped stream is that retry; the
  relay does not reconnect on its own.
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
- **Volume stops at 100 %.** Louder is amplifying -- mpv offered 130 and the
  slider used to go there; `Player.VOLUME_MAX` is the one place that says otherwise,
  and a louder value in an older config is clamped on load.
- **A station's page is found before its logo is.** In order: the page the
  streams were harvested from at Add Stream time (`source["site"]`), the
  `icy-url` the stream announces while playing (learned and saved, which is
  what rescues stations added as a bare stream URL), the Icecast mount's `server_url`,
  and last the stream host with its `streams.`/`ice6.` label trimmed. That
  last guess must prove itself: the page has to mention a distinctive word
  from the source's name, or `lb-hls.cdn.bg` hands back the CDN's logo. Wrong
  art is worse than none, which is why the check exists and why it matches
  Unicode -- the first version was ASCII-only and let a CDN logo through for
  "БНР Бургас".
- **The level meters are decorative.** Random targets with a fast attack and a
  slow decay (`core/levels.py`), ~14 fps, and they run only while something is
  audible and the bars are on screen -- the overlay's repaint lands on top of
  a running game. Real levels are possible (Qt's `QAudioBufferOutput` hands
  over the decoded audio), but nobody can check them against the music.
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
- **The tray menu is ours, not the desktop's.** Cinnamon hosts tray icons
  over D-Bus (xapp-sn-watcher, a StatusNotifier host), and then
  `setContextMenu` does not show the QMenu: Qt exports it as dbusmenu and the
  desktop rebuilds it as a GTK menu in the system theme. The stylesheet never
  reached it, a theme switch did nothing, and the now-playing header (a
  widget) cannot travel over dbusmenu at all -- that was the menu the author
  saw. So no menu is given to Qt (the item reports `/NO_DBUSMENU`), the host
  calls `ContextMenu` on a right-click, Qt emits `activated(Context)`, and
  `Tray` pops its own QMenu at the cursor: skinned, themed, header included.
  KDE and the XEmbed tray deliver `Context` the same way. Its window is
  frameless and translucent, or the rounded corners sit on a square.
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
- **The Linux build is a folder.** PyInstaller onedir, not one file:
  portability is "one folder", the app may start at every login (one-file
  unpacks ~100 MB each time), and the LGPL libraries stay replaceable files.
  It carries Qt Multimedia and PySide6's FFmpeg, so the .deb no longer
  depends on `libmpv2` (and the spec no longer has to cut out the 212 MB
  libmpv tree PyInstaller used to drag in). Not yet rebuilt on Mint since
  the switch. Two downloads, one job each, and the
  author chose the order: the `.deb` is **the** download (menu, icon, clean
  removal, settings in `~/.config`); the tarball is the second option,
  portable (it ships with `shortcutradio.portable`, settings in `data/` beside
  the app). Single-file was measured and rejected: it unpacks 170 MB on
  every start (0.9 s here against 0.1 s), and the .deb hides the folder.
  `--version` answers before Qt is imported; the build checks it.
- **Windows keys: one low-level hook, not pynput.** pynput's Windows
  backend cannot observe and take a key separately: a key suppressed in its
  `win32_event_filter` is hidden from its own listener too
  (moses-palmer/pynput#679). A `WH_KEYBOARD_LL` hook (`keygrab_win.KeyHook`,
  ctypes, its own thread and message loop) hears every key before any app
  and asks `Hotkeys._handle` whether it is a live binding; if so the action
  fires and the hook returns non-zero, and the key's *release* is taken as
  well. So Windows has no observe/grab split and no pynput at all. The
  overlay rule is unchanged, and capture takes the key it records (Esc or
  Alt+F4 while recording must not act on the window). Key names follow
  pynput's; a printable key is named by its scan code through the *default*
  input language, so switching the window in front to Bulgarian does not
  change what matches (the X11 group-1 rule). Held modifiers come from
  `GetAsyncKeyState`, not from events seen, so a Win release lost to the
  lock screen cannot leave Win held.
- **A key taken while Alt or Win is held is followed by an unassigned key
  (VK 0xE8, tagged in `dwExtraInfo`).** Measured: without it, a taken Alt+[
  left the app in front a lone Alt release and its menu bar opened; with it,
  it didn't. AutoHotkey does the same. Its tag keeps the hook off it.
- **On Windows the media keys are ordinary shortcuts.** VK_MEDIA_PLAY_PAUSE
  and the rest reach the hook like any key and are taken there -- measured:
  nothing after us (another hook, the shell, SMTC) saw a taken Play key.
  So `media_via_desktop` is False, nothing like `mediakeys.py` exists, and
  `Hotkeys.media_keys()` means "bare media keys that are bound" on both
  platforms. SMTC (`smtc.py`) is what MPRIS is for the sound applet: the
  station, track and logo in the volume flyout and on the lock screen, and
  its buttons press the bound media keys through `press_media`. Same seam
  as `Mpris` (`available`, `set_active`, `set_keys`, `set_state`, `pressed`),
  same rule: a session only while the overlay is on and a media key is
  bound; switched off, it is gone from the flyout. `App.media` holds
  whichever one the platform has.
- **The Windows build is 99 MB** (the installer 30 MB, the zip 41 MB; it
  was 194 MB with libmpv-2.dll). It carries Qt Multimedia's FFmpeg backend
  and PySide6's FFmpeg (21 MB). The spec drops what PySide6's hooks drag in
  unused: the virtual-keyboard plugin (and with it Qt Quick, QML, OpenGL),
  the PDF image plugin, the Media Foundation backend (the player runs on
  FFmpeg), the 20 MB software-OpenGL fallback and Qt's translations. A
  version resource names the exe "ShortCutRadio" for Explorer, Task Manager
  and the Now Playing flyout.
- **Windows downloads: the installer first, the zip second**, the same order
  as .deb/tarball. Inno Setup, per user by default (no UAC prompt; the
  first page offers all users), Start menu entry, optional desktop icon,
  settings left in %APPDATA% on uninstall. Unsigned for now: SmartScreen
  warns, and the README says how to get past it.
- **Closing for an installer.** Setup's Restart Manager closes a running
  copy on upgrade (Qt ends the loop on WM_ENDSESSION, so `main` saves after
  `exec()` returns -- measured: a volume change still waiting on the save
  timer survived). The uninstaller has no Restart Manager, so it runs
  `shortcutradio.exe --quit`, which sends "quit" to the instance on the
  same config over the single-instance socket and waits until it is gone.
  Killing by image name would also stop a portable copy elsewhere.

## Traps — measured, do not re-litigate

- **A Python QIODevice cannot feed QMediaPlayer.** Qt's FFmpeg reads the
  device on its own thread; the next `setSource` waits for that thread on
  the GUI thread while holding the GIL, and the thread waits for the GIL to
  call `readData`. It hung on the first station change (a faulthandler dump
  showed both). Hence the relay: FFmpeg reads a socket, in C. (A device
  would also have to block in `readData`: FFmpeg takes 0 bytes as the end.)
- **Qt's player stalls on FLAC-in-Ogg after four buffers** -- five
  stations, played directly too (Qt 6.11.2). The relay rewraps it as plain
  FLAC: "fLaC", the STREAMINFO marked as the last block, then the frames; a
  later chain's (the next song's) headers are skipped. Then it plays.
- **Most Ogg/Opus mounts send no title**: their comment says only
  `ENCODER=`. mpv showed nothing for them either. Radio Paradise's first
  FLAC chain has an empty comment; its title comes with the next song.
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
- **A low-level hook has no repeat flag.** Bit 30 ("previous key state")
  is in WM_KEYDOWN's lParam, not in KBDLLHOOKSTRUCT. But every release does
  reach the hook, so a press with no release since is a repeat -- exact,
  unlike X11. The 1.5 s gap is only a net for a release lost to the secure
  desktop (Win+L, Ctrl+Alt+Del). `GetAsyncKeyState` can't tell either: the
  hook runs before it is updated, and a taken key never updates it.
- **A new thread inherits the keyboard layout active at that moment.**
  Measured here: the hook thread started in Bulgarian and named `]` as a
  Cyrillic letter, so no shortcut on it matched. Names come from
  `SPI_GETDEFAULTINPUTLANG` (the default input language) instead.
- **ctypes truncates handles unless told otherwise.** `GetModuleHandleW`
  with the default `int` restype hands a 64-bit module handle back cut to
  32 bits, and `SetWindowsHookExW` then fails with no hook and no exception.
  Every user32/kernel32 function the hook calls has its argtypes/restype
  set, on a private `WinDLL`, so nothing else's settings leak in.
- **SMTC needs its thumbnail from a StorageFile.** A `file:///` URI for the
  thumbnail shows no picture (pywinrt 3.2, measured). The file arrives
  asynchronously, and ButtonPressed and async completions run on WinRT's
  thread pool: both come back to the Qt thread through queued signals.
- **Inno only removes an install folder it created.** One left behind by a
  failed uninstall (files in use, before `--quit`) makes the next install's
  uninstaller leave the empty folder too. A clean cycle leaves nothing.
- **A second global hook installed later sees keys first**, and one that
  swallows a key means ours never hears it. Unlike X11's BadAccess there is
  no way to find out, so the Shortcuts tab's ⚠ never shows on Windows.
- **Not measured yet: the hook's time limit.** Windows skips a low-level
  hook that doesn't answer within LowLevelHooksTimeout, and after enough
  timeouts removes it silently. The callback waits for the GIL, so a GUI
  thread holding it for long would cost the shortcuts. Nothing has come
  close so far.

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
- **Build:** `packaging/build.sh` (runs the tests first). To prove a build
  plays, start `dist/ShortCutRadio/shortcutradio --hidden` on a scratch config with
  volume 0, every shortcut on Ctrl+Alt+Shift+F-keys, Play/Pause on
  `media_play_pause` and the overlay on (so MPRIS is up), then `gdbus call
  ... Player.Play` and read `PlaybackStatus` and `Metadata`. Stop it with
  `pkill -f "^/home/.../dist/ShortCutRadio/shortcutradio"` -- anchored, for the same
  reason as above.
- A GUI started with the chat's `!` prefix dies when that command returns. The
  menu has two entries: **ShortCutRadio** is the installed .deb
  (`/usr/share/applications/shortcutradio.desktop`), **ShortCutRadio (dev)** runs this
  checkout (`~/.local/share/applications/shortcutradio-dev.desktop`). The dev one
  must not be named `shortcutradio.desktop`: a user entry of the same name hides
  the package's. Both share `~/.config/ShortCutRadio`, so only one runs at a time.
  Cinnamon caches the menu, so a changed icon can take a re-login to show.

### Windows

- `python -m pytest -q tests` -- the pynput tests skip; the
  hook tests feed `KeyHook.event` raw events on any platform.
- Scratch config: `$env:APPDATA = "<scratch dir>"` before starting (the
  counterpart of `XDG_CONFIG_HOME=/tmp/x`). Stop a test instance with
  `shortcutradio.py --quit` under the same `APPDATA`, or
  `Get-Process shortcutradio | ? Path -eq <that exe> | Stop-Process` --
  anchored to the path, never every shortcutradio.exe.
- **Synthetic key tests:** `SendInput` from ctypes; the hook sees injected
  keys like real ones (it doesn't look at LLKHF_INJECTED). Give each key its
  scan code (`MapVirtualKeyW`), as hardware does. What the focused app
  gets: a Tk window in the test process, focused and checked with
  `GetForegroundWindow` before every key. What *other programs* get: a
  second WH_KEYBOARD_LL hook installed **before** starting ShortCutRadio --
  the newest hook runs first, so the older one sees only what we pass on.
  Auto-repeat is a run of presses with no release between them, 30 ms apart.
  The Alt menu check: the target in its own process (its menu loop blocks),
  then `GetGUIThreadInfo` for GUI_INMENUMODE, with a lone Alt tap as the
  control that proves the check can see a menu at all. Switch the target
  window's language with `ActivateKeyboardLayout` to test the layout rule.
  A test script's own ctypes needs the same care as the hook's: a missing
  `restype` once kept the test's hook from installing, and it hung waiting.
- **Media and SMTC:** `SendInput` of VK_MEDIA_PLAY_PAUSE (0xB3) only while
  the overlay is on -- otherwise it reaches whatever else is playing. Read
  the session the way the flyout does, with `winrt-Windows.Media.Control`:
  `GlobalSystemMediaTransportControlsSessionManager.request_async()`, the
  session whose `source_app_user_model_id` is `python.exe` (dev) or
  `shortcutradio.exe` (build), its media properties, thumbnail and
  playback info; `try_toggle_play_pause_async()` presses the flyout's button.
  Run at volume 0 with a real stream (somafm fluid) so the title changes.
- **Build:** `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
  (Windows PowerShell 5.1 is enough; it runs the tests first). To prove a
  build plays, run the SMTC check above against
  `dist\ShortCutRadio\shortcutradio.exe --hidden`: the session shows, the
  flyout's play gives a track title, the Play key pauses it, the overlay
  off removes it. The installer: `/VERYSILENT /SUPPRESSMSGBOXES
  /CURRENTUSER /DIR=<scratch>`, then run the installed copy and uninstall
  it (`unins000.exe /VERYSILENT`) while it runs; the folder must be gone
  and the settings kept.

## Not done yet

A GitHub Actions release (build on the oldest supported Ubuntu, so the
glibc floor drops below this machine's 2.39, and on a Windows runner with
build.ps1), the Linux side of the switch to Qt Multimedia (the spike on
Mint, running from source without `libmpv2`, `build.sh`, and whether the
.deb needs a sound library in `Depends`), signing the Windows installer, game hooks
(e.g. NFSU2 world-load autostart, in the style of the old radio's
`/proc/<pid>/fd` check), macOS: media keys (Now Playing, same seam as `Mpris`)
and key suppression (pynput `darwin_intercept`), and confirming the overlay
over fullscreen NFSU2 -- and on Windows over a game in exclusive fullscreen,
which bypasses the compositor the overlay draws through.

## Git

Public repo `msvdm/ShortCutRadio` (MIT), branch `main`. Everything pushed is
published: no personal paths, configs or keys in commits. End commits with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
