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

The player is Qt Multimedia (core/player.py), with the FFmpeg that ships
inside PySide6 (LGPL): nothing audio-related is needed from the system
beyond what Qt itself loads.

There are no data files: the icon is drawn in code (gui/tray.py).
"""

# Never imported by this app. PyInstaller only collects the Qt modules that
# are imported anyway; this keeps stray hooks from pulling the big ones in.
excludes = [
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtCharts",
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
