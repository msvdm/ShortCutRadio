"""The Shortcuts tab: one row per action, its key cap records a new combo."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QWidget)

from ..core.hotkeys import has_modifier, pretty
from .widgets import mono_font, repolish

SHORTCUT_ROWS = [
    ("overlay", "Overlay on / off"),
    ("play_pause", "Play / Pause"),
    ("source_next", "Next source"),
    ("source_prev", "Previous source"),
    ("track_next", "Next track"),
    ("track_prev", "Previous track"),
    ("vol_up", "Volume up"),
    ("vol_down", "Volume down"),
]
CAPTURE_TIP = ("Click, then press the new key (Esc cancels, Backspace clears).\n"
               "Every shortcut but the overlay one works only while the\n"
               "overlay is on, so typing is safe when it's off.")
UNGRABBED_TIP = ("This key cannot be taken: either another program already holds\n"
                 "it, or this keyboard has no such key. The app you are using\n"
                 "will receive it too. Record it again on the layout you type in.")
HELP_TEXT = ("The keyboard shortcuts work only while the overlay is active - all of them "
             "except the one that turns the overlay on, which always works. If you want "
             "to free the keys up for other purposes - such as typing - disable the "
             "overlay; the music will not stop.")
# Every word-wrapped label needs a pinned wrapping width. Qt asks such a label
# how tall it would be at its *minimum* width, and an unpinned one answers with
# a dozen lines -- which the window then grows to fit and never gives back.
WRAP_W = 560


class KeyCap(QPushButton):
    """Click, then press keys to record a new combo.

    Recording goes through the global listener (so what is recorded is exactly
    what will match), but Qt still delivers the same key to this button -- it
    must be swallowed, or Space/Enter would re-click it.
    """

    def __init__(self):
        super().__init__()
        self.capturing = False
        self.setObjectName("keyCap")
        self.setFont(mono_font(12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def keyPressEvent(self, event):
        if self.capturing:
            event.accept()
            return
        super().keyPressEvent(event)


class ShortcutRow(QFrame):
    def __init__(self, action, label):
        super().__init__()
        self.action = action
        self.setObjectName("shortcutRow")
        self.setProperty("capturing", "false")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(12)
        text = QLabel(label)
        text.setObjectName("shortcutLabel")
        self.key = KeyCap()
        self.key.setToolTip(CAPTURE_TIP)
        lay.addWidget(text)
        lay.addStretch(1)
        lay.addWidget(self.key)

    def set_capturing(self, on):
        self.key.capturing = on
        for w in (self, self.key):
            w.setProperty("capturing", "true" if on else "false")
            repolish(w)
        if on:
            self.key.setText("press a key…")

    def show_combo(self, combo, leaks):
        """`leaks`: the key could not be taken, so the focused app gets it too."""
        self.set_capturing(False)
        self.key.setText(pretty(combo) + (" ⚠" if leaks else ""))
        self.key.setToolTip(UNGRABBED_TIP if leaks else CAPTURE_TIP)
        self.key.setDown(False)


class ShortcutsPage(QWidget):
    strip_widget = None

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.capturing = None           # the row recording a key
        self._ungrabbed = set()         # live combos the focused app still gets
        grid = QGridLayout(self)
        grid.setContentsMargins(20, 18, 20, 20)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.rows = []
        for i, (action, label) in enumerate(SHORTCUT_ROWS):
            row = ShortcutRow(action, label)
            row.key.clicked.connect(lambda _=False, r=row: self.begin_capture(r))
            self.rows.append(row)
            grid.addWidget(row, *divmod(i, 2))

        nrows = (len(SHORTCUT_ROWS) + 1) // 2
        if app.hotkeys.error:
            warn = QLabel(f"Global shortcuts are unavailable: {app.hotkeys.error}")
            warn.setObjectName("warnText")
            warn.setWordWrap(True)
            warn.setMinimumWidth(WRAP_W)
            grid.addWidget(warn, nrows, 0, 1, 2)
            nrows += 1
        help_label = QLabel(HELP_TEXT)
        help_label.setObjectName("helpText")
        help_label.setWordWrap(True)
        help_label.setFixedWidth(WRAP_W)
        grid.addWidget(help_label, nrows, 0, 1, 2)
        grid.setRowStretch(nrows + 1, 1)
        self.refresh()

    def refresh(self):
        sc = self.app.config["shortcuts"]
        for row in self.rows:
            combo = sc.get(row.action, "")
            row.show_combo(combo, bool(combo) and combo in self._ungrabbed)

    def on_ungrabbed(self, combos):
        """The grabber's report: which live shortcuts the focused app still
        receives. A key that isn't taken has to look different from one that
        is, or a shortcut that types into the app in front looks fine here."""
        self._ungrabbed = set(combos)
        self.refresh()

    def begin_capture(self, row):
        if self.app.hotkeys.error:
            return
        self.capturing = row
        row.set_capturing(True)
        self.app.hotkeys.begin_capture()

    def on_captured(self, combo):
        row, self.capturing = self.capturing, None
        if row is None:
            return
        row.set_capturing(False)
        sc = self.app.config["shortcuts"]
        if combo == "esc":
            pass
        elif combo in ("backspace", "delete"):
            sc[row.action] = ""
        elif row.action == "overlay" and not has_modifier(combo):
            QMessageBox.information(
                self, "ShortCutRadio",
                "The overlay shortcut needs Ctrl, Alt or Super (e.g. Ctrl+Alt+R): "
                "it works everywhere, so a single key would fire while you type.")
        else:
            for other, c in sc.items():       # one key, one job
                if c == combo and other != row.action:
                    sc[other] = ""
            sc[row.action] = combo
        self.app.shortcuts_changed()
        self.refresh()
