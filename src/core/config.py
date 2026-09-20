"""Settings on disk: sources, shortcuts, overlay look, volume.

One JSON file. In portable mode (a `shortcutradio.portable` file next to the app)
it lives beside the app so the whole folder can move between machines;
otherwise in the per-user config dir of the OS.
"""

import copy
import json
import os
import sys

APP_NAME = "ShortCutRadio"

DEFAULT_SHORTCUTS = {
    "overlay": "ctrl+alt+r",
    "source_next": "'",
    "source_prev": ";",
    "track_next": ".",
    "track_prev": ",",
    "vol_up": "]",
    "vol_down": "[",
    "play_pause": "\\",
}

DEFAULTS = {
    "sources": [],
    "current": 0,
    "volume": 70,
    "theme": "auto",           # "auto" follows the desktop; else "dark" / "light"
    "shortcuts": DEFAULT_SHORTCUTS,
    # Key name -> X keysym, learned from the keys actually pressed. Only keys
    # outside Latin-1 need it; see hotkeys.Hotkeys._learn_keysym.
    "keysyms": {},
    "overlay": {
        "visible": False,
        "corner": "top-right",
        "margin_x": 28,
        "margin_y": 24,
        "opacity": 0.55,
        "font_family": "",        # "" = the system UI font
        "title_style": "Bold",
        "text_style": "Regular",
        "title_size": 15,
        "track_size": 11,
        "width": 250,
        "scroll": True,
        "bg_color": "#000000",
        "title_color": "#ffffff",
        "text_color": "#c7d0d8",
    },
}

# The NFSU2 radio this app grew out of. Its live stations seed the source list
# on first run so the switch costs nothing.
NFSU2_STATIONS = os.path.expanduser("~/Games/NFSU2/radio/stations.conf")


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def data_dir():
    base = app_dir()
    if os.path.exists(os.path.join(base, "shortcutradio.portable")):
        return os.path.join(base, "data")
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, APP_NAME)


def _merge(defaults, loaded):
    out = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def transparency_percent(opacity):
    """The overlay's stored background opacity (0..1) as transparency in %."""
    try:
        return max(0, min(100, round(100 - float(opacity) * 100)))
    except (TypeError, ValueError):
        return transparency_percent(DEFAULTS["overlay"]["opacity"])


def opacity_from_percent(transparency):
    return round(1 - max(0, min(100, transparency)) / 100, 2)


THEMES = ("auto", "dark", "light")


def normalize_theme(value):
    """One of "auto" | "dark" | "light"; anything else means "auto"."""
    return value if value in THEMES else "auto"


def read_stations_conf(path):
    """[{name, kind, target, shuffle}] from an NFSU2-style `Name | URL` file."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                name, url = (p.strip() for p in line.split("|", 1))
                if name and url:
                    out.append({"name": name, "kind": "stream", "target": url, "shuffle": False})
    except OSError:
        pass
    return out


class Config:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "config.json")
        self.data = copy.deepcopy(DEFAULTS)
        self.first_run = not os.path.exists(self.path)
        if self.first_run:
            self.data["sources"] = read_stations_conf(NFSU2_STATIONS)
        else:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    self.data = _merge(DEFAULTS, json.load(fh))
            except (OSError, ValueError) as e:
                # A corrupt file must not stop the app; keep it for inspection.
                print(f"[config] unreadable {self.path}: {e} -- using defaults", flush=True)
                try:
                    os.replace(self.path, self.path + ".bad")
                except OSError:
                    pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
