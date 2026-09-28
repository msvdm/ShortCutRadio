"""The Shortcuts tab: one row per action, its key cap records a new combo."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QWidget)

from ..core.hotkeys import SUPER, has_modifier, pretty, works_everywhere
from .widgets import PillSwitch, mono_font, repolish

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
MEDIA_TIP = ("A media key: your desktop hands it to ShortCutRadio as its media player,\n"
             "while the overlay is on. With the overlay off it goes to other players.\n"
             "Click to record a different key.")
SWITCH_TEXT = "Shortcuts only while the overlay is on"
IDLE_TIP = ("Shortcuts work everywhere now, and a single key would take that\n"
            "character from everything you type. Record it with Ctrl, Alt or\n"
            f"{SUPER}, or switch \"{SWITCH_TEXT}\" back on.")
# The two texts under the switch. Kept about the same length: a label that
# changes height on a click moves everything below it.
HELP_ON = ("All of them except the one that turns the overlay on, which always works. "
           "Hide the overlay and every key goes back to your other apps, so typing is "
           "safe; the music will not stop.")
HELP_OFF = ("Off: shortcuts work all the time, in every app, and the app in front does "
            f"not get them. Each needs Ctrl, Alt or {SUPER}: a single key shows ⚠ and "
            "waits until this is on again.")
SWITCH_W = 34 + 12      # the pill and its gap to the text
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
        # ⚠ comes from the emoji font, which is taller: without a pinned
        # height every row would jump when the switch below is flipped.
        self.key.ensurePolished()
        self.key.setFixedHeight(self.key.sizeHint().height())
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

    def show_combo(self, combo, leaks, media=False, idle=False):
        """`leaks`: the key could not be taken, so the focused app gets it too.
        `media`: the desktop delivers it (see core/mpris.py).
        `idle`: a single key, off while shortcuts work everywhere."""
        self.set_capturing(False)
        self.key.setText(pretty(combo) + (" ⚠" if leaks or idle else ""))
        self.key.setToolTip(IDLE_TIP if idle else UNGRABBED_TIP if leaks
                            else MEDIA_TIP if media else CAPTURE_TIP)
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
        # The overlay rule, as a switch: the pill, its title, and what it means.
        rule = QGridLayout()
        rule.setHorizontalSpacing(SWITCH_W - PillSwitch.W)
        rule.setVerticalSpacing(4)
        self.rule_switch = PillSwitch()
        self.rule_switch.toggled.connect(app.set_shortcuts_need_overlay)
        title = QLabel(SWITCH_TEXT)
        title.setObjectName("toggleLabel")
        self.help_label = QLabel()
        self.help_label.setObjectName("helpText")
        self.help_label.setWordWrap(True)
        self.help_label.setFixedWidth(WRAP_W - SWITCH_W)
        rule.addWidget(self.rule_switch, 0, 0)
        rule.addWidget(title, 0, 1)
        rule.addWidget(self.help_label, 1, 1)
        rule.setColumnStretch(2, 1)
        grid.addLayout(rule, nrows, 0, 1, 2)
        grid.setRowStretch(nrows + 1, 1)
        self.refresh()

    def refresh(self):
        need = self.app.config["shortcuts_need_overlay"]
        self.rule_switch.blockSignals(True)
        self.rule_switch.setChecked(need)
        self.rule_switch.blockSignals(False)
        self.help_label.setText(HELP_ON if need else HELP_OFF)
        sc = self.app.config["shortcuts"]
        hk = self.app.hotkeys
        for row in self.rows:
            combo = sc.get(row.action, "")
            row.show_combo(combo, bool(combo) and combo in self._ungrabbed,
                           hk.via_desktop(combo), bool(combo) and hk.idle(combo))

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
        elif self.app.hotkeys.everywhere and not works_everywhere(combo):
            QMessageBox.information(
                self, "ShortCutRadio",
                f"Shortcuts work everywhere now, so each needs Ctrl, Alt or {SUPER} "
                "(e.g. Ctrl+E): a single key would fire while you type.")
        else:
            for other, c in sc.items():       # one key, one job
                if c == combo and other != row.action:
                    sc[other] = ""
            sc[row.action] = combo
        self.app.shortcuts_changed()
        self.refresh()
