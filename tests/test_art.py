import base64

from src.core.coverart import cover_file, embedded_art
# QImage needs no QApplication, so the art maths can be tested like the rest.
from src.gui.art import content_box, monogram
from src.gui.overlay import pick_screen
from src.gui.overlay_page import positions


# ----------------------------------------------------- the overlay's monitor
class _Screen:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def test_the_card_falls_back_to_the_main_monitor():
    main, side = _Screen(r"\\.\DISPLAY1"), _Screen(r"\\.\DISPLAY2")
    assert pick_screen(r"\\.\DISPLAY2", [main, side], main) is side
    assert pick_screen(r"\\.\DISPLAY2", [main], main) is main   # unplugged
    assert pick_screen("", [main, side], main) is main


def test_positions_name_the_monitor_only_when_there_are_two():
    main, side = _Screen("A"), _Screen("B")
    assert [p[0] for p in positions([main])] == [
        "Top right", "Top left", "Bottom right", "Bottom left"]
    both = positions([main, side])
    assert len(both) == 8
    assert both[0] == ("Monitor 1 · Top right", "", "top-right")    # the main one
    assert both[7] == ("Monitor 2 · Bottom left", "B", "bottom-left")


# ---------------------------------------------------------------- cover art
def test_cover_file_beside_the_track_then_at_the_root(tmp_path):
    album = tmp_path / "Album" / "CD1"
    album.mkdir(parents=True)
    track = album / "01.mp3"
    track.write_bytes(b"")
    assert cover_file(str(track), str(tmp_path / "Album")) is None
    (tmp_path / "Album" / "folder.jpg").write_bytes(b"x")
    assert cover_file(str(track), str(tmp_path / "Album")).endswith("folder.jpg")
    (album / "Cover.PNG").write_bytes(b"x")          # beside the track wins
    assert cover_file(str(track), str(tmp_path / "Album")).endswith("Cover.PNG")


PICTURE = b"\x89PNG\r\n\x1a\nPRETENDTHISISAPICTURE"


def _picture_block(ptype=3, mime=b"image/png"):
    """A METADATA_BLOCK_PICTURE body, as FLAC and Ogg both store it."""
    return (ptype.to_bytes(4, "big")
            + len(mime).to_bytes(4, "big") + mime
            + (0).to_bytes(4, "big")                 # empty description
            + b"\x00" * 16                           # width, height, depth, colours
            + len(PICTURE).to_bytes(4, "big") + PICTURE)


def _syncsafe(n):
    return bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))


def test_id3_apic_prefers_the_front_cover(tmp_path):
    def frame(ptype, data):
        body = b"\x00" + b"image/png\x00" + bytes((ptype,)) + b"\x00" + data
        return b"APIC" + len(body).to_bytes(4, "big") + b"\x00\x00" + body

    tag = frame(4, b"BACKCOVER") + frame(3, PICTURE)     # front cover comes second
    mp3 = tmp_path / "t.mp3"
    mp3.write_bytes(b"ID3\x03\x00\x00" + _syncsafe(len(tag)) + tag + b"\xff\xfb")
    assert embedded_art(str(mp3)) == PICTURE


def test_flac_picture_block(tmp_path):
    block = _picture_block()
    flac = tmp_path / "t.flac"
    flac.write_bytes(b"fLaC"
                     + b"\x00" + (4).to_bytes(3, "big") + b"\x00" * 4     # STREAMINFO
                     + b"\x86" + len(block).to_bytes(3, "big") + block)   # last PICTURE
    assert embedded_art(str(flac)) == PICTURE


def _ogg_page(body, seq):
    """One Ogg page. The reader ignores the CRC, so zeros will do."""
    segments = [body[i:i + 255] for i in range(0, len(body), 255)] or [b""]
    table = bytes(len(s) for s in segments)
    return (b"OggS\x00\x00" + b"\x00" * 8 + b"\x00" * 4
            + seq.to_bytes(4, "little") + b"\x00" * 4
            + bytes((len(table),)) + table + b"".join(segments))


def test_ogg_picture_stitched_back_across_pages(tmp_path):
    comment = b"METADATA_BLOCK_PICTURE=" + base64.b64encode(_picture_block())
    half = len(comment) // 2
    ogg = tmp_path / "t.opus"
    # The comment header is long enough to span pages, which is the whole
    # reason the page bodies have to be joined before searching.
    ogg.write_bytes(_ogg_page(b"OpusHead" + b"\x00" * 11, 0)
                    + _ogg_page(comment[:half], 1)
                    + _ogg_page(comment[half:], 2))
    assert embedded_art(str(ogg)) == PICTURE


def test_a_broken_file_is_not_an_error(tmp_path):
    junk = tmp_path / "t.mp3"
    junk.write_bytes(b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + b"\x00" * 40)
    assert embedded_art(str(junk)) is None
    assert embedded_art(str(tmp_path / "missing.flac")) is None
    assert embedded_art("/etc/hostname") is None        # not an audio extension


# ------------------------------------------------------------- art fitting
def _image(w, h, bg, box=None):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(bg) if bg else QColor(0, 0, 0, 0))
    if box:
        x0, y0, x1, y1 = box
        for x in range(x0, x1):
            for y in range(y0, y1):
                img.setPixelColor(x, y, QColor("#c01818"))
    return img


def test_content_box_trims_a_flat_border():
    # A logo published inside a lot of white, the usual case.
    assert content_box(_image(100, 100, "#ffffff", (30, 25, 70, 75))) == (30, 25, 40, 50)
    # The same shape on nothing at all: transparency trims too.
    assert content_box(_image(100, 100, None, (30, 25, 70, 75))) == (30, 25, 40, 50)


def test_content_box_leaves_a_full_picture_alone():
    # Content right up to the edge: nothing to trim.
    assert content_box(_image(80, 80, "#ffffff", (0, 0, 79, 79))) == (0, 0, 80, 80)
    assert content_box(_image(80, 80, "#ffffff")) is None       # nothing but border
    assert content_box(_image(80, 80, "#c01818", (0, 0, 80, 80))) is None   # one colour
    assert content_box(_image(2, 2, "#ffffff")) is None         # too small to judge


def test_content_box_never_eats_the_whole_picture():
    # A gradient-ish edge must not let the trim run away: it stops at TRIM_MAX.
    box = content_box(_image(100, 100, "#ffffff", (48, 48, 52, 52)))
    assert box is not None and box[0] <= 42 and box[1] <= 42


def test_monogram():
    assert monogram("БНР Бургас") == "ББ"          # not just ASCII
    assert monogram("SomaFM Fluid") == "SF"
    assert monogram("Drum & Bass") == "DB"         # "&" is not a word
    assert monogram("Burgas") == "BU"              # one word gives two letters
    assert monogram("Fluid 128") == "FL"           # a number is not an initial
    assert monogram("") == "?"
