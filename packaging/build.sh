#!/usr/bin/env bash
# Build ShortCutRadio for Linux, from this checkout, on this machine.
#
#     packaging/build.sh
#
# Makes, in dist/:
#   ShortCutRadio/                         the built app (a folder)
#   ShortCutRadio-<ver>-linux-x64.tar.gz   that folder, portable: settings
#                                          live in data/ beside the app
#   shortcutradio_<ver>_amd64.deb          the same app, installed to the
#                                          system and the applications menu
#
# Both need the system's libmpv2 (see shortcutradio.spec for why it is not
# bundled). The result runs on this machine's glibc or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=.venv/bin/python
VERSION=$($PY -c "from src import __version__; print(__version__)")
echo "== ShortCutRadio $VERSION"

# The builder is pinned so that two builds of one commit are the same build.
$PY -m pip install -q "pyinstaller==6.22.3"

echo "== tests"
QT_QPA_PLATFORM=offscreen $PY -m pytest -q tests

echo "== build"
$PY -m PyInstaller --noconfirm --clean shortcutradio.spec

# Not dead on arrival: the bundle starts its interpreter and knows its version.
OUT=$(dist/ShortCutRadio/shortcutradio --version)
if [ "$OUT" != "ShortCutRadio $VERSION" ]; then
    echo "expected 'ShortCutRadio $VERSION', the build says '$OUT'" >&2
    exit 1
fi
echo "build says: $OUT"

echo "== portable folder"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
NAME="ShortCutRadio-$VERSION"
cp -a dist/ShortCutRadio "$STAGE/$NAME"
cp README.md LICENSE packaging/THIRD_PARTY.txt "$STAGE/$NAME/"
touch "$STAGE/$NAME/shortcutradio.portable"     # settings stay in the folder
chmod -R go-w "$STAGE/$NAME"
TAR="dist/$NAME-linux-x64.tar.gz"
tar -C "$STAGE" -czf "$TAR" "$NAME"
echo "built $TAR"

echo "== .deb"
packaging/build-deb.sh "$VERSION" dist/ShortCutRadio dist

echo
ls -lh "$TAR" "dist/shortcutradio_${VERSION}_amd64.deb"
