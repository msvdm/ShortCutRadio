"""Add Stream popup: paste a URL, pick from the streams found behind it."""

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from ..core.scraper import discover


class _Bridge(QObject):
    progress = Signal(str)
    done = Signal(object)


class AddStreamDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Stream")
        self.resize(720, 420)
        self.selected = []
        self._bridge = _Bridge()
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)
        self._busy = False

        self.url = QLineEdit(placeholderText="Paste a station's web page, playlist or stream URL")
        self.url.returnPressed.connect(self.find)
        self.find_btn = QPushButton("Find streams")
        self.find_btn.clicked.connect(self.find)
        row = QHBoxLayout()
        row.addWidget(self.url, 1)
        row.addWidget(self.find_btn)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Format", "URL"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._update_ok)

        self.toggle_btn = QPushButton("Select none")
        self.toggle_btn.clicked.connect(self._toggle_all)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = self.buttons.addButton("Add selected", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_btn.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.toggle_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.buttons)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addWidget(self.tree, 1)
        lay.addWidget(QLabel("Double-click a name to rename it before adding."))
        lay.addLayout(bottom)

    def find(self):
        url = self.url.text().strip()
        if not url or self._busy:
            return
        self._busy = True
        self.find_btn.setEnabled(False)
        self.tree.clear()
        self._update_ok()
        bridge = self._bridge

        def work():
            try:
                found = discover(url, report=bridge.progress.emit)
            except Exception as e:      # a scraper bug must not kill the dialog
                bridge.progress.emit(f"Error: {e}")
                found = []
            bridge.done.emit(found)

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, msg):
        self.status.setText(msg)

    def _on_done(self, found):
        self._busy = False
        self.find_btn.setEnabled(True)
        if not found:
            self.status.setText("No playable streams found at that address. "
                                "Try the station's “listen” page or a direct stream link.")
            return
        self.status.setText(f"Found {len(found)} stream{'s' if len(found) != 1 else ''}. "
                            "Tick the ones to add.")
        self.tree.blockSignals(True)
        for f in found:
            it = QTreeWidgetItem([f.name, f.detail, f.url])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.setToolTip(2, f.url)
            it.setData(0, Qt.ItemDataRole.UserRole, f.site)
            self.tree.addTopLevelItem(it)
        self.tree.blockSignals(False)
        self._update_ok()

    def _items(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _toggle_all(self):
        items = self._items()
        any_on = any(it.checkState(0) == Qt.CheckState.Checked for it in items)
        state = Qt.CheckState.Unchecked if any_on else Qt.CheckState.Checked
        for it in items:
            it.setCheckState(0, state)

    def _update_ok(self, *_):
        checked = [it for it in self._items() if it.checkState(0) == Qt.CheckState.Checked]
        self.ok_btn.setEnabled(bool(checked))
        self.toggle_btn.setText("Select none" if checked else "Select all")

    def accept(self):
        """(name, url, site) per ticked row -- the site is where its logo lives."""
        self.selected = [(it.text(0).strip() or it.text(2), it.text(2),
                          it.data(0, Qt.ItemDataRole.UserRole) or "")
                         for it in self._items()
                         if it.checkState(0) == Qt.CheckState.Checked]
        super().accept()
