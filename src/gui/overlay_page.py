"""The Overlay tab: size, margins, font, transparency and colors of the card."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

from ..core.config import DEFAULTS, opacity_from_percent, transparency_percent
from . import theme
from .dialogs import pick_color
from .overlay import ordered_screens, overlay_family, overlay_screen, pick_style
from .widgets import PillSwitch, ThemedComboBox, ThemedFontComboBox, mono_font

CORNERS = [("top-right", "Top right"), ("top-left", "Top left"),
           ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left")]
# What `Reset to default` restores: the look, not whether the card is on or
# where it was put.
LOOK_KEYS = [k for k in DEFAULTS["overlay"] if k not in ("visible", "screen", "corner")]


def positions(screens):
    """(label, screen, corner) for the Position list. One monitor: just the
    corners. More: each monitor's four, Monitor 1 being the main one, which
    is kept as "" so the card follows whichever monitor is the main one."""
    out = []
    for n, screen in enumerate(screens):
        for corner, text in CORNERS:
            label = f"Monitor {n + 1} · {text}" if len(screens) > 1 else text
            out.append((label, "" if n == 0 else screen.name(), corner))
    return out


def _label(text):
    lb = QLabel(text)
    lb.setObjectName("fieldLabel")
    return lb


def _hairline():
    line = QFrame()
    line.setObjectName("hair")
    line.setFixedHeight(1)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line


class OverlayPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.spins = {}             # config key -> QSpinBox
        self.color_buttons = {}     # config key -> QPushButton
        self.style_boxes = {}       # config key -> ThemedComboBox

        # Sits at the right end of the tab strip, which the window owns.
        self.strip_widget = QPushButton("Reset to default")
        self.strip_widget.setObjectName("resetBtn")
        self.strip_widget.setToolTip(
            "Restore the default size, margins, font, transparency and colors")
        self.strip_widget.clicked.connect(self._reset_look)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(14)

        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.setVerticalSpacing(10)
        top.setColumnStretch(1, 1)
        top.setColumnStretch(3, 1)
        self.position = ThemedComboBox()
        self.position.setToolTip("Where the card sits: which corner, and with more than\n"
                                 "one monitor, which monitor. Monitor 1 is the main one.")
        self._positions = []        # (screen, corner) per item of the list
        self.position.currentIndexChanged.connect(self._position_changed)
        qapp = QGuiApplication.instance()
        for signal in (qapp.screenAdded, qapp.screenRemoved, qapp.primaryScreenChanged):
            signal.connect(self._fill_positions)
        top.addWidget(_label("Width"), 0, 0)
        top.addWidget(self._spin("width", 200, 1200, " px", "Card width"), 0, 1)
        top.addWidget(_label("Position"), 0, 2)
        top.addWidget(self.position, 0, 3)
        top.addWidget(_label("Margin X"), 1, 0)
        top.addWidget(self._spin("margin_x", 0, 500, " px",
                                 "Distance from the left/right screen edge"), 1, 1)
        top.addWidget(_label("Margin Y"), 1, 2)
        top.addWidget(self._spin("margin_y", 0, 500, " px",
                                 "Distance from the top/bottom screen edge"), 1, 3)
        top.addWidget(_label("Font"), 2, 0)
        self.font_family = ThemedFontComboBox()
        self.font_family.setToolTip("Font of the overlay text")
        self.font_family.currentFontChanged.connect(self._family_changed)
        top.addWidget(self.font_family, 2, 1, 1, 3)
        lay.addLayout(top)
        lay.addWidget(_hairline())

        rows = QGridLayout()
        rows.setHorizontalSpacing(14)
        rows.setVerticalSpacing(10)
        rows.setColumnStretch(1, 1)
        for row, (text, style_key, size_key, color_key, lo, hi, tip) in enumerate(
                [("Row 1 · station", "title_style", "title_size", "title_color",
                  8, 48, "Row 1 (station name)"),
                 ("Row 2 · track", "text_style", "track_size", "text_color",
                  6, 36, "Row 2 (track / status)")]):
            rows.addWidget(_label(text), row, 0)
            box = ThemedComboBox()
            box.setToolTip(f"{tip} style")
            box.currentTextChanged.connect(
                lambda t, k=style_key: t and app.update_overlay(**{k: t}))
            self.style_boxes[style_key] = box
            rows.addWidget(box, row, 1)
            rows.addWidget(self._spin(size_key, lo, hi, " pt", f"{tip} size"), row, 2)
            rows.addWidget(self._color(color_key, f"{tip} color"), row, 3)

        rows.addWidget(_label("Transparency"), 2, 0)
        self.transp_slider = QSlider(Qt.Orientation.Horizontal)
        self.transp_spin = QSpinBox()
        self.transp_spin.setSuffix(" %")
        self.transp_spin.setFont(mono_font(13))
        self.transp_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        for w in (self.transp_slider, self.transp_spin):
            w.setRange(0, 100)
            w.setToolTip("Background transparency (the text stays solid)")
            w.valueChanged.connect(self._transparency_changed)
        rows.addWidget(self.transp_slider, 2, 1)
        rows.addWidget(self.transp_spin, 2, 2)
        rows.addWidget(self._color("bg_color", "Background color"), 2, 3)
        lay.addLayout(rows)

        scroll_row = QHBoxLayout()
        scroll_row.setSpacing(10)
        self.scroll_switch = PillSwitch()
        self.scroll_switch.setToolTip(
            "Text that doesn't fit scrolls like a ticker instead of ending in …")
        self.scroll_switch.toggled.connect(lambda on: app.update_overlay(scroll=on))
        scroll_label = QLabel("Scroll long text instead of cutting it with …")
        scroll_label.setObjectName("toggleLabel")
        scroll_row.addWidget(self.scroll_switch)
        scroll_row.addWidget(scroll_label)
        scroll_row.addStretch(1)
        lay.addLayout(scroll_row)

        lay.addStretch(1)
        lay.addWidget(_hairline())
        footer = QHBoxLayout()
        footer.setSpacing(14)
        footer.addStretch(1)
        box = QFrame()
        box.setObjectName("showOverlayBox")
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        bl = QHBoxLayout(box)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(10)
        show = QLabel("Show overlay")
        show.setObjectName("showOverlayLabel")
        self.overlay_switch = PillSwitch()
        self.overlay_switch.toggled.connect(app.set_overlay)
        bl.addWidget(show)
        bl.addWidget(self.overlay_switch)
        footer.addWidget(box)
        lay.addLayout(footer)
        self.refresh()

    def _spin(self, key, lo, hi, suffix, tip):
        sb = QSpinBox()
        sb.setRange(lo, hi)
        sb.setSuffix(suffix)
        sb.setToolTip(tip)
        sb.setFont(mono_font(13))
        sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        sb.valueChanged.connect(lambda v: self.app.update_overlay(**{key: v}))
        self.spins[key] = sb
        return sb

    def _color(self, key, tip):
        b = QPushButton()
        b.setObjectName("colorBtn")
        b.setToolTip(tip)
        b.setFixedSize(34, 30)
        b.clicked.connect(lambda _=False: self._pick_color(key))
        self.color_buttons[key] = b
        return b

    # ------------------------------------------------------------------ state
    def refresh(self):
        """Put the config values into the controls without re-saving them."""
        conf = self.app.config["overlay"]
        widgets = [self.scroll_switch, self.transp_slider, self.transp_spin,
                   self.font_family, *self.style_boxes.values(), *self.spins.values()]
        blockers = [QSignalBlocker(w) for w in widgets]
        self._fill_positions()
        for key, sb in self.spins.items():
            sb.setValue(int(conf[key]))
        self.scroll_switch.setChecked(bool(conf["scroll"]))
        t = transparency_percent(conf["opacity"])
        self.transp_slider.setValue(t)
        self.transp_spin.setValue(t)
        family = overlay_family(conf)
        self.font_family.setCurrentFont(QFont(family))
        self._fill_styles(family)
        for b in blockers:
            b.unblock()
        self.refresh_colors()

    def refresh_colors(self):
        conf = self.app.config["overlay"]
        strong = theme.tokens()["strong"]
        for key, b in self.color_buttons.items():
            b.setStyleSheet(f"background: {conf[key]}; border: 1px solid {strong};"
                            "border-radius: 7px;")

    def set_overlay_checked(self, on):
        with QSignalBlocker(self.overlay_switch):
            self.overlay_switch.setChecked(on)

    def _fill_positions(self, *_):
        """List the positions of the monitors connected now, and select where
        the card is. A chosen monitor that is unplugged shows as the main
        one -- where the card is -- but stays saved, so it goes back there."""
        conf = self.app.config["overlay"]
        items = positions(ordered_screens())
        self._positions = [(screen, corner) for _, screen, corner in items]
        screen = conf["screen"]
        if overlay_screen(conf) is QGuiApplication.primaryScreen():
            screen = ""
        want = (screen, conf["corner"])
        with QSignalBlocker(self.position):
            self.position.clear()
            for label, _, _ in items:
                self.position.addItem(label)
            if want in self._positions:
                self.position.setCurrentIndex(self._positions.index(want))
            elif ("", conf["corner"]) in self._positions:
                self.position.setCurrentIndex(self._positions.index(("", conf["corner"])))

    def _position_changed(self, index):
        if 0 <= index < len(self._positions):
            screen, corner = self._positions[index]
            self.app.update_overlay(screen=screen, corner=corner)

    def _fill_styles(self, family):
        """List the family's styles; keep the saved style, else the nearest one."""
        conf = self.app.config["overlay"]
        styles = sorted(QFontDatabase.styles(family) or ["Regular", "Bold"],
                        key=lambda st: ("Condensed" in st, QFontDatabase.italic(family, st),
                                        QFontDatabase.weight(family, st)))
        for key, box in self.style_boxes.items():
            box.clear()
            box.addItems(styles)
            box.setCurrentText(pick_style(styles, conf[key], bold=(key == "title_style")))

    # ------------------------------------------------------------------ edits
    def _family_changed(self, font):
        """A new family has its own styles: pick the nearest to the old ones,
        and save the family and both styles as one change."""
        family = font.family()
        blockers = [QSignalBlocker(b) for b in self.style_boxes.values()]
        self._fill_styles(family)
        for b in blockers:
            b.unblock()
        self.app.update_overlay(font_family=family, **{
            key: box.currentText() for key, box in self.style_boxes.items()})

    def _transparency_changed(self, t):
        for w in (self.transp_slider, self.transp_spin):
            if w.value() != t:
                with QSignalBlocker(w):
                    w.setValue(t)
        self.app.update_overlay(opacity=opacity_from_percent(t))

    def _pick_color(self, key):
        conf = self.app.config["overlay"]
        c = pick_color(self, conf[key], self.color_buttons[key].toolTip())
        if c.isValid():
            self.app.update_overlay(**{key: c.name()})
            self.refresh()

    def _reset_look(self):
        self.app.update_overlay(**{key: DEFAULTS["overlay"][key] for key in LOOK_KEYS})
        self.refresh()
