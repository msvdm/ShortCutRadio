#!/usr/bin/env bash
# Wrap the built folder in a .deb.
#
# Why a package: a downloaded file arrives without permission to run (HTTP
# cannot carry that bit), so the portable folder always costs a chmod or a
# trip to a file manager's properties first. The package skips that, and puts
# ShortCutRadio in the applications menu with its icon.
#
# Usage: packaging/build-deb.sh <version> <built-folder> <output-dir>
set -euo pipefail

VERSION="${1:?usage: build-deb.sh VERSION FOLDER OUTDIR}"
FOLDER="${2:?usage: build-deb.sh VERSION FOLDER OUTDIR}"
OUTDIR="${3:?usage: build-deb.sh VERSION FOLDER OUTDIR}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# The app is a folder, so it lives in /usr/lib with a link on the PATH.
mkdir -p "$STAGE/usr/lib" "$STAGE/usr/bin"
cp -a "$FOLDER" "$STAGE/usr/lib/shortcutradio"
ln -s ../lib/shortcutradio/shortcutradio "$STAGE/usr/bin/shortcutradio"

install -Dm644 "$ROOT/packaging/shortcutradio.desktop" \
               "$STAGE/usr/share/applications/shortcutradio.desktop"
install -Dm644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/shortcutradio/copyright"
install -Dm644 "$ROOT/packaging/THIRD_PARTY.txt" \
               "$STAGE/usr/share/doc/shortcutradio/THIRD_PARTY.txt"

# The icon is drawn in code (gui/tray.py), so it is drawn here too, at every
# size the app itself installs for a source run.
cd "$ROOT"
QT_QPA_PLATFORM=offscreen python3 - "$STAGE" <<'EOF'
import os, sys
from PySide6.QtWidgets import QApplication
app = QApplication([])
from src.gui.tray import ICON_NAME, ICON_SIZES, icon_pixmap
for size in ICON_SIZES:
    path = os.path.join(sys.argv[1], "usr/share/icons/hicolor",
                        f"{size}x{size}", "apps", ICON_NAME + ".png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not icon_pixmap(size).save(path, "PNG"):
        sys.exit(f"could not draw the {size}px icon")
EOF

# Owned by root (--root-owner-group), writable by root only, whatever the
# umask and mktemp left behind.
chmod -R go-w "$STAGE"
chmod 755 "$STAGE"

# The glibc the package needs is what the built folder asks for: the highest
# GLIBC_x.y any of its files names. The build machine sets it (2.39 on the
# author's Mint, 2.35 on the release runner), so it is read, not written
# down. Without objdump, this machine's own glibc: never too low.
GLIBC=$( { find "$FOLDER" -type f -exec objdump -T {} + 2>/dev/null || true; } \
         | { grep -o 'GLIBC_[0-9][0-9.]*' || true; } | cut -d_ -f2 | sort -uV | tail -n1)
if [ -z "$GLIBC" ]; then
    GLIBC=$(ldd --version | head -n1 | grep -o '[0-9][0-9.]*$')
    echo "no objdump: glibc floor from this machine, $GLIBC"
fi
echo "needs glibc >= $GLIBC"

mkdir -p "$STAGE/DEBIAN"
sed -e "s/@VERSION@/$VERSION/" -e "s/@GLIBC@/$GLIBC/" \
    "$ROOT/packaging/debian/control.in" > "$STAGE/DEBIAN/control"

mkdir -p "$OUTDIR"
DEB="$OUTDIR/shortcutradio_${VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
echo "built $DEB"
