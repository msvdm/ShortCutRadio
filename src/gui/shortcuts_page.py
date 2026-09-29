"""The Shortcuts tab: one row per action, its key cap records a new combo.

Also the Shortcut popup of a source (right-click on the Sources tab), which
records the same way and under the same rules (`refusal`).
"""

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.hotkeys import (ALWAYS_LIVE, SUPER, has_modifier, pretty, recorded,
                            works_everywhere)
from .dialogs import FramelessDialog, inform, wrapped_label
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
OVERLAY_REFUSAL = (f"The overlay shortcut needs Ctrl, Alt or {SUPER} (e.g. Ctrl+Alt+R): "
                   "it works everywhere, so a single key would fire while you type.")
EVERYWHERE_REFUSAL = (f"Shortcuts work everywhere now, so each needs Ctrl, Alt or {SUPER} "
                      "(e.g. Ctrl+E): a single key would fire while you type.")
# A source's Shortcut popup: one line for each state of the switch.
SOURCE_HELP_ON = ("Like every shortcut, it works while the overlay is on. "
                  "Backspace clears it.")
SOURCE_HELP_OFF = (f"Shortcuts work all the time now, so it needs Ctrl, Alt or {SUPER}. "
                   "Backspace clears it.")
SOURCE_IDLE = (f"A single key waits while shortcuts work everywhere: record it with "
               f"Ctrl, Alt or {SUPER}, or switch \"{SWITCH_TEXT}\" back on.")
SOURCE_TIP = "Right-click the source, then Shortcut…, to change it."
# Qt still gets its own copy of a key the listener recorded (X11), and it can
# arrive just after the recording ended: Esc would then close the popup.
CAPTURE_ECHO_S = 0.4
SWITCH_W = 34 + 12     # the pill and its gap to the text
WRAP_W = 560           # the tab's text column, pinned: see dialogs.WRAP_W


class KeyCap(QPushButton):
    """Click, then press keys to record a new combo.

    Recording goes through the global listener (so what is recorded is exactly
    what will match), but Qt still delivers the same key to this button -- it
    must be swallowed, or Space/Enter would re-click it. The cap shows that it
    is recording; what it shows otherwise is up to its owner.
    """

    def __init__(self):
        super().__init__()
        self.capturing = False
        self._ended = 0.0
        self.setObjectName("keyCap")
        self.setFont(mono_font(12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)      # Enter goes to a popup's OK

    def set_capturing(self, on):
        if self.capturing and not on:
            self._ended = time.monotonic()
        self.capturing = on
        self.setProperty("capturing", "true" if on else "false")
        repolish(self)
        if on:
            self.setText("press a key…")

    def keyPressEvent(self, event):
        if self.capturing or time.monotonic() - self._ended < CAPTURE_ECHO_S:
            event.accept()
            return
        super().keyPressEvent(event)


def refusal(app, action, combo):
    """Why `combo` cannot be recorded for `action`, or None. The one place
    the rules live, for the Shortcuts tab and a source's popup alike."""
    if action == ALWAYS_LIVE and not has_modifier(combo):
        return OVERLAY_REFUSAL
    if app.hotkeys.everywhere and not works_everywhere(combo):
        return EVERYWHERE_REFUSAL
    return None


def combo_owner(app, combo, src=None):
    """Who holds `combo` now, other than `src`: an action's label, a
    source's name, or ""."""
    if not combo:
        return ""
    labels = dict(SHORTCUT_ROWS)
    for action, c in app.config["shortcuts"].items():
        if c == combo:
            return labels.get(action, action)
    for other in app.config["sources"]:
        if other is not src and other.get("shortcut") == combo:
            return f"“{other['name']}”"
    return ""


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
        self.key.set_capturing(on)
        self.setProperty("capturing", "true" if on else "false")
        repolish(self)

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
        self.help_label = wrapped_label("", WRAP_W - SWITCH_W)
        self.help_label.setObjectName("helpText")
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
        # First: it ends a recording still under way, this row's included.
        self.app.hotkeys.begin_capture(lambda combo: self._captured(row, combo))
        self.capturing = row
        row.set_capturing(True)

    def _captured(self, row, combo):
        if self.capturing is row:
            self.capturing = None
        row.set_capturing(False)
        new = recorded(combo)
        if new is not None:
            if why := new and refusal(self.app, row.action, new):
                inform(self, why)
            else:
                self.app.free_combo(new)            # one key, one job
                self.app.config["shortcuts"][row.action] = new
        self.app.shortcuts_changed()
        self.refresh()


class SourceShortcutDialog(FramelessDialog):
    """Record a key that jumps straight to one source.

    Recording starts as it opens, through the same listener as the Shortcuts
    tab. Nothing changes until OK: `combo` is then the new key, "" for none.
    """

    def __init__(self, parent, app, src):
        super().__init__(parent, "Shortcut")
        self.app, self.src = app, src
        self.combo = src.get("shortcut", "")
        self._refused = ""
        hk = app.hotkeys

        self.body.addWidget(wrapped_label(f"A key that switches straight to “{src['name']}”."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.key = KeyCap()
        self.key.setToolTip("Click, then press the new key (Esc cancels, Backspace clears).")
        self.key.clicked.connect(self._record)
        clear = QPushButton("Clear")
        clear.setAutoDefault(False)
        clear.clicked.connect(self._clear)
        row.addWidget(self.key, 1)
        row.addWidget(clear)
        self.body.addLayout(row)
        self.note = wrapped_label("")
        self.note.setObjectName("warnText")
        self.body.addWidget(self.note)
        help_text = wrapped_label(SOURCE_HELP_OFF if hk.everywhere else SOURCE_HELP_ON)
        help_text.setObjectName("helpText")
        self.body.addWidget(help_text)
        self.add_buttons()

        if hk.error:
            self.key.setEnabled(False)
            clear.setEnabled(False)
            self._refused = f"Global shortcuts are unavailable: {hk.error}"
            self._show()
        else:
            self._record()

    def _record(self):
        self.app.hotkeys.begin_capture(self._captured)
        self.key.set_capturing(True)
        self.key.setFocus()     # swallows Qt's copy of the key being recorded
        self._refused = ""
        self._show()

    def _clear(self):
        if self.key.capturing:
            self.key.set_capturing(False)
            self.app.hotkeys.end_capture()
        self.combo, self._refused = "", ""
        self._show()

    def _captured(self, combo):
        self.key.set_capturing(False)
        new = recorded(combo)
        if new is not None:
            self._refused = new and refusal(self.app, None, new) or ""
            if not self._refused:
                self.combo = new
        self._show()

    def _show(self):
        if not self.key.capturing:
            self.key.setText(pretty(self.combo))
        note = self._refused
        if not note and self.combo:
            owner = combo_owner(self.app, self.combo, self.src)
            if owner:
                note = f"Now used by {owner}: OK moves it here."
            elif self.app.hotkeys.everywhere and not works_everywhere(self.combo):
                note = SOURCE_IDLE
        self.note.setText(note)
        self.note.setVisible(bool(note))

    def done(self, result):
        if self.key.capturing:
            self.key.set_capturing(False)
            self.app.hotkeys.end_capture()
        super().done(result)
