# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for ShortCutRadio on Windows: one folder, `dist/ShortCutRadio/`.

Run through packaging/build.ps1, which also makes the portable zip and the
installer from it. PyInstaller cannot cross-compile, so this is built on
Windows, as shortcutradio.spec is on Linux -- and a folder rather than one
file for the same reasons given there.

The player is Qt Multimedia (core/player.py), and its FFmpeg -- LGPL, the
build that ships inside PySide6 -- comes along with it, as on Linux.

The icon is the mark drawn in code (gui/tray.py), written out as an .ico at
build time by packaging/make_ico.py.
"""

import os
import re
import subprocess
import sys

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo,
                                                 StringStruct, StringTable,
                                                 VarFileInfo, VarStruct,
                                                 VSVersionInfo)

sys.path.insert(0, SPECPATH)
from src import __version__  # noqa: E402

ICON = os.path.join(SPECPATH, "build", "shortcutradio.ico")
os.makedirs(os.path.dirname(ICON), exist_ok=True)
subprocess.run([sys.executable, os.path.join(SPECPATH, "packaging", "make_ico.py"), ICON],
               check=True)

# Never imported by this app, as in shortcutradio.spec; plus the Linux-only
# keyboard and D-Bus libraries, in case the build machine has them.
excludes = [
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtCharts",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "unittest", "pydoc", "pytest", "numpy", "PIL",
    "pynput", "Xlib", "jeepney",
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

# PySide6's hooks bring the virtual keyboard's input plugin, which drags in
# Qt Quick, QML and OpenGL, and the PDF image plugin, which brings Qt Pdf.
# None of it is used by a widgets app, nor is the 20 MB software-OpenGL
# fallback or Qt's own translations (no QTranslator is ever installed).
# The player runs on Qt's FFmpeg backend, so Windows Media Foundation's
# backend plugin is never loaded either.
UNUSED = re.compile(r"(qtvirtualkeyboardplugin|qpdf|opengl32sw|windowsmediaplugin"
                    r"|Qt6(Quick|Qml|Pdf|OpenGL|VirtualKeyboard)\w*)\.dll$"
                    r"|[\\/]translations[\\/]", re.I)
a.binaries = [b for b in a.binaries if not UNUSED.search(b[0])]
a.datas = [d for d in a.datas if not UNUSED.search(d[0])]

pyz = PYZ(a.pure)

# What Explorer's Properties, Task Manager and the Now Playing flyout call it.
nums = tuple(int(n) for n in __version__.split(".")) + (0,)
version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "msvdm"),
            StringStruct("FileDescription", "ShortCutRadio"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", "shortcutradio"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "shortcutradio.exe"),
            StringStruct("ProductName", "ShortCutRadio"),
            StringStruct("ProductVersion", __version__),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="shortcutradio",
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
    icon=ICON,
    version=version,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ShortCutRadio",
)
