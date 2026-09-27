# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for ShortCutRadio: one folder, `dist/ShortCutRadio/`.

Run through packaging/build.sh, which also makes the .deb and the portable
tarball from it. PyInstaller cannot cross-compile, so each platform's build
is made on that platform; so far that is Linux only.

A folder, not a single file, on purpose:
- portability is "one folder" (a `shortcutradio.portable` file beside the
  executable keeps the settings in it -- see core/config.py:data_dir);
- ShortCutRadio may start with every login, and a one-file bundle unpacks ~100 MB
  to a temp directory on each start;
- Qt and the other LGPL libraries stay separate, replaceable files.

libmpv is NOT bundled. python-mpv finds the system's at run time, and the
.deb depends on libmpv2. Bundling it would drag in all of ffmpeg.

There are no data files: the icon is drawn in code (gui/tray.py).
"""

import os
import subprocess

# Never imported by this app. PyInstaller only collects the Qt modules that
# are imported anyway; this keeps stray hooks from pulling the big ones in.
excludes = [
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "unittest", "pydoc", "pytest", "numpy", "PIL",
]

a = Analysis(
    ["shortcutradio.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)


def ldd(path):
    """Names of the shared libraries `path` loads, all the way down."""
    try:
        out = subprocess.run(["ldd", path], capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {line.split()[0] for line in out.splitlines() if "=>" in line}


# PyInstaller sees python-mpv's `find_library("mpv")` and bundles libmpv with
# its whole tree -- ffmpeg, x265, codec2 ... over 200 MB. Drop libmpv and
# every library only it needed; what the rest of the app loads stays.
mpv = [b for b in a.binaries if os.path.basename(b[0]).startswith("libmpv.so")]
if mpv:
    mpv_tree = ldd(mpv[0][1]) | {os.path.basename(b[0]) for b in mpv}
    needed = set()
    for name, src, _ in a.binaries:
        if os.path.basename(name) not in mpv_tree:
            needed |= ldd(src)
    drop = mpv_tree - needed
    a.binaries = [b for b in a.binaries if os.path.basename(b[0]) not in drop]
    print(f"shortcutradio.spec: left out libmpv and {len(drop) - len(mpv)} libraries "
          "only it needed; the system's libmpv2 is used instead")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="shortcutradio",        # lowercase: matches Icon= and the .desktop file
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX compression is a reliable way to get flagged
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ShortCutRadio",
)
