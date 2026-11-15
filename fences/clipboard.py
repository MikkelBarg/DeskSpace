"""Clipboard history: the last texts you copied, in a widget. Click one to copy it again.

Copies that password managers mark as secret (KeePassXC, Bitwarden, 1Password and others set a flag
for clipboard tools, on Windows and on Linux) are never kept. By default the history only lives in
memory and is gone when DeskSpace closes; it can be kept across restarts in the widget's settings,
and then it's saved in config.json like the rest of your notes. Pinned entries stay at the top and
are never pushed out.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QComboBox, QListWidget, QListWidgetItem, QMenu, QPushButton

from .common import LIST_STYLE
from .panel import Panel

KEEP_CHOICES = [10, 25, 50, 100]
MAX_CHARS = 20000  # longer copies are kept cut short
# Clipboard formats that mean "don't record this": the ones Windows' own clipboard history honours,
# and the hint KDE's and other Linux clipboard managers honour.
SECRET_MARKS = ("excludeclipboardcontentfrommonitorprocessing", "canincludeinclipboardhistory",
                "clipboard viewer ignore", "x-kde-passwordmanagerhint")


def is_secret(mime):
    for name in mime.formats():
        low = name.lower()
        if not any(mark in low for mark in SECRET_MARKS):
            continue
        if "canincludeinclipboardhistory" in low:
            # A number: 0 means "leave this out of any history", anything else allows it.
            data = bytes(mime.data(name))
            if data.strip(b"\x00 0"):
                continue
        return True
    return False


def one_line(text, limit=90):
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1] + "…"


class ClipboardFence(Panel):
    kind = "clipboard"
    default_size = (300, 260)

    def build_content(self, data):
        self.keep = data.get("keep", 25)
        self.remember = data.get("remember", False)
        saved = data.get("entries", []) if self.remember else []
        # Pinned ones always survive a restart; that's the point of pinning.
        saved += [e for e in data.get("pinned_entries", []) if e not in saved]
        self.entries = [{"text": e["text"], "pinned": bool(e.get("pinned"))} for e in saved
                        if isinstance(e, dict) and isinstance(e.get("text"), str)]
        self.paused = False
        self.list = QListWidget()
        self.list.setStyleSheet(LIST_STYLE)
        self.list.setWordWrap(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda it: self.copy_back(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.clipboard = QGuiApplication.clipboard()
        self.clipboard.dataChanged.connect(self.on_clipboard)
        self.refresh()
        return self.list

    def content_dict(self):
        out = {"keep": self.keep, "remember": self.remember,
               "pinned_entries": [e for e in self.entries if e["pinned"]]}
        if self.remember:
            out["entries"] = [e for e in self.entries if not e["pinned"]]
        return out

    def rolled_title(self):
        return f"{self.name}  ({len(self.entries)})"

    # -- recording

    def on_clipboard(self):
        if self.paused:
            return
        mime = self.clipboard.mimeData()
        if mime is None or not mime.hasText() or is_secret(mime):
            return
        text = mime.text()
        if not text.strip():
            return
        self.add(text[:MAX_CHARS])

    def add(self, text):
        old = next((e for e in self.entries if e["text"] == text), None)
        if old is not None:
            self.entries.remove(old)
        entry = old or {"text": text, "pinned": False}
        pinned = [e for e in self.entries if e["pinned"]]
        loose = [e for e in self.entries if not e["pinned"]]
        if entry["pinned"]:
            pinned.insert(0, entry)
        else:
            loose.insert(0, entry)
        self.entries = pinned + loose[:self.keep]
        self.refresh()
        if self.remember or entry["pinned"]:
            self.app.schedule_save()

    def copy_back(self, entry):
        self.clipboard.setText(entry["text"])  # comes back through on_clipboard and moves to the top

    # -- list

    def refresh(self):
        self.list.clear()
        for entry in self.entries:
            item = QListWidgetItem(("★ " if entry["pinned"] else "") + one_line(entry["text"]))
            item.setData(Qt.UserRole, entry)
            tip = entry["text"][:600] + ("…" if len(entry["text"]) > 600 else "")
            item.setToolTip(tip + "\n\nClick to copy it again.")
            self.list.addItem(item)
        if not self.entries:
            hint = QListWidgetItem("Copy some text and it shows up here.")
            hint.setFlags(Qt.NoItemFlags)
            self.list.addItem(hint)
        self.update()

    def context_menu(self, pos):
        item = self.list.itemAt(pos)
        entry = item.data(Qt.UserRole) if item is not None else None
        menu = QMenu()
        if entry:
            menu.addAction("Copy", lambda: self.copy_back(entry))
            menu.addAction("Unpin" if entry["pinned"] else "Pin", lambda: self.set_pinned(entry, not entry["pinned"]))
            menu.addAction("Delete", lambda: self.delete(entry))
            menu.addSeparator()
        pause = menu.addAction("Pause recording", lambda: setattr(self, "paused", not self.paused))
        pause.setCheckable(True)
        pause.setChecked(self.paused)
        menu.addAction("Clear history (keeps pinned)", self.clear)
        menu.addSeparator()
        self.show_menu(self.list.mapToGlobal(pos), menu)

    def set_pinned(self, entry, pinned):
        entry["pinned"] = pinned
        self.entries.remove(entry)
        self.entries.insert(0, entry)
        self.entries.sort(key=lambda e: not e["pinned"])  # stable: pinned first, order kept
        self.refresh()
        self.app.schedule_save()

    def delete(self, entry):
        if entry in self.entries:
            self.entries.remove(entry)
            self.refresh()
            self.app.schedule_save()

    def clear(self):
        self.entries = [e for e in self.entries if e["pinned"]]
        self.refresh()
        self.app.schedule_save()

    # -- settings

    def set_keep(self, n):
        self.keep = n
        pinned = [e for e in self.entries if e["pinned"]]
        self.entries = pinned + [e for e in self.entries if not e["pinned"]][:n]
        self.refresh()
        self.app.schedule_save()

    def set_remember(self, on):
        self.remember = on
        self.app.schedule_save()

    def build_settings(self, form):
        keep = QComboBox()
        for n in KEEP_CHOICES:
            keep.addItem(f"{n} entries", n)
        keep.setCurrentIndex(max(0, keep.findData(self.keep)))
        keep.currentIndexChanged.connect(lambda: self.set_keep(keep.currentData()))
        form.addRow("Keep the last", keep)
        remember = QCheckBox("Keep the history when DeskSpace closes (saved in config.json)")
        remember.setChecked(self.remember)
        remember.toggled.connect(self.set_remember)
        form.addRow("", remember)
        clear = QPushButton("Clear history")
        clear.clicked.connect(self.clear)
        form.addRow("", clear)
