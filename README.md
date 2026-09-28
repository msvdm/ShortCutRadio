# ShortCutRadio

**A radio and music player that stays out of your way. It lives in a corner
of the screen and you drive it with the keyboard. Free, MIT-licensed, no
account, no telemetry.**

<img src="docs/window.png" alt="The ShortCutRadio window: what's playing on top, the list of stations below" width="640">

I wanted music or internet radio while I play or work, without alt-tabbing to
a player every time I want the next station. ShortCutRadio works like the GPU-stats
overlay some graphics drivers have. Press a key and a small card appears in a
corner of the screen showing what's playing. Change station, skip a track or
turn the volume up from the keyboard. Press the key again and it's gone.

<img src="docs/overlay.png" alt="The overlay card: station logo, station name, song title" width="250">

## What it's good at

- **Stays on top of everything**, fullscreen games included. The card lets
  your clicks through, so it never gets in the way.
- **Shortcuts that don't steal your keys.** They only work while the overlay
  is showing. Hide it and every key goes back to your other apps, as if
  ShortCutRadio weren't there.
- **Internet radio made easy.** Paste a station's website and ShortCutRadio finds
  its streams for you. If a stream drops, it reconnects on its own.
- **Your own music folders**, played in order or shuffled, with their cover art.
- **Station logos** are found automatically. If a guess is wrong, set your own
  picture with a right-click.
- **Fits into the desktop:** media keys, the system sound menu, a tray icon,
  and a dark or light look.

## How you use it

1. **Sources** tab: add internet stations (**Add Stream**) or music folders
   (**Add Folder**).
2. **Shortcuts** tab: pick your keys. The defaults are small and out of the
   way: `[` `]` for volume, `;` `'` for the previous or next station,
   `\` to play or pause.
3. Press **Ctrl+Alt+R** to show the overlay. Now your shortcuts work.
4. **Overlay** tab: choose the corner, size, font and colours of the card.

Closing the window keeps ShortCutRadio running in the tray. Click the tray icon to
bring the window back.

## Run it

ShortCutRadio runs on **Linux with X11** (Linux Mint, Ubuntu and similar) and
on **Windows 10 and 11**.

### Linux

You need Python 3.10 or newer.

```bash
sudo apt install python3-venv git
git clone https://github.com/msvdm/ShortCutRadio.git
cd ShortCutRadio
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python shortcutradio.py
```

- `shortcutradio.py --hidden` starts it straight in the tray, which is handy for
  autostart.
- **Portable mode:** put an empty file named `shortcutradio.portable` next to
  `shortcutradio.py`, and the settings will live in a `data` folder inside the app
  folder instead of your home folder. Then the whole folder can move to
  another machine.

**Build it yourself:** `packaging/build.sh` makes two files in `dist/`:

- **`shortcutradio_*_amd64.deb`**, the one most people want. Double-click it to
  install, and ShortCutRadio appears in your menu. Remove it the same way as any
  other program.
- **`ShortCutRadio-*-linux-x64.tar.gz`**, a portable folder. Unpack it anywhere
  and run `shortcutradio` inside. It keeps its settings in the folder, so it can
  live on a USB stick.

### Windows

Build it yourself on Windows: `packaging\build.ps1` makes two files in
`dist\`:

- **`ShortCutRadio-*-windows-x64-setup.exe`**, the installer. It puts
  ShortCutRadio in the Start menu, needs no administrator rights, and
  uninstalls from Settings > Apps. Your settings stay when you uninstall.
- **`ShortCutRadio-*-windows-x64.zip`**, a portable folder. Unzip it anywhere
  and run `shortcutradio.exe` inside. It keeps its settings in the folder.

Both include everything they need. The installer isn't signed yet,
so Windows may warn that it comes from an unknown publisher: choose
**More info**, then **Run anyway**.

On Windows the keyboard's media keys are ordinary shortcuts: bind Play/Pause
to one and, while the overlay is on, it controls ShortCutRadio and nothing
else. ShortCutRadio also shows up in the volume menu and on the lock screen.

## Status

It works well on Linux (X11) and I use it every day. Windows is new: it
works, but the overlay hasn't been tried over a fullscreen game there yet.
macOS is next. Wayland isn't
supported, because the global shortcuts need X11.

## Who wrote this

Claude, Anthropic's AI model, writes the code. I'm a sound engineer, not a
programmer: I decide what ShortCutRadio should do, test every change on my own
machine, and say when something is wrong. The reasons behind the design, and
the bugs we hit along the way, are written down in [CLAUDE.md](CLAUDE.md).

## Problems and ideas

Please open an [issue](https://github.com/msvdm/ShortCutRadio/issues). Say what you
expected, what happened, and which Linux and desktop, or which Windows, you
use.

## License

MIT, see [LICENSE](LICENSE). Use it, change it, share it; just keep the
copyright notice.
