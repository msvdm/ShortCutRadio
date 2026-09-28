"""Write the app's mark as a Windows .ico, for the executable and the installer.

    python packaging/make_ico.py OUT.ico

The mark is drawn in code (gui/tray.py) and no picture of it is checked in;
this draws it at every size Windows asks for and packs them as PNGs, which an
.ico may hold since Vista. Qt's own ICO writer takes one size only.
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from src.gui.tray import icon_pixmap  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png(size):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    icon_pixmap(size).save(buf, "PNG")
    return bytes(buf.data())


def main(out):
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 -- a QPixmap needs one
    images = [png(s) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries = b""
    for size, data in zip(SIZES, images):
        dim = size % 256            # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(out, "wb") as fh:
        fh.write(head + entries + b"".join(images))


if __name__ == "__main__":
    main(sys.argv[1])
