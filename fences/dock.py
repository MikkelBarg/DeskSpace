"""App dock: a row of app icons on the desktop. One click starts an app.

Unlike an icon fence, nothing is moved: the dock keeps a list of launchers (Start-menu shortcuts,
.desktop files, programs, or any file or folder) in config.json. Drop apps on it to add them, drag the
icons to reorder them, and right-click one to remove it.
"""
import os
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
)

from .common import LIST_STYLE, display_name, local_paths
from .panel import Panel
from .search import APP_FILES, START_MENUS
from .system import FILE_MANAGER, IS_WINDOWS, open_path, shell_icon, show_in_folder

if not IS_WINDOWS:
    from .system import desktop_file_field

ICON_SIZES = [("Small", 32), ("Medium", 48), ("Large", 64)]


def app_name(path):
    """The name to show for a launcher: a .desktop file's own Name, else the file's name."""
    path = Path(path)
    if not IS_WINDOWS and path.suffix.lower() == ".desktop":
        name = desktop_file_field(path, "Name")
        if name:
            return name
    return display_name(path, limit=60)


def shown_in_menu(path):
    """Would this desktop's own app menu list the .desktop launcher? (Hidden ones, links and settings
    panels meant for another desktop are left out, the way the menu does.)"""
    if (desktop_file_field(path, "NoDisplay").lower() == "true" or desktop_file_field(path, "Hidden").lower() == "true"
            or desktop_file_field(path, "Type") not in ("", "Application")):
        return False
    here = {d.lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d}
    only = {d.lower() for d in desktop_file_field(path, "OnlyShowIn").split(";") if d}
    never = {d.lower() for d in desktop_file_field(path, "NotShowIn").split(";") if d}
    return (not only or bool(only & here)) and not (never & here)


def installed_apps():
    """(name, path) for each app in the Start menu (Windows) or the application menus (Linux), by name."""
    found = {}
    for root in START_MENUS:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in APP_FILES or "uninstall" in p.name.lower():
                continue
            if not IS_WINDOWS and not shown_in_menu(p):
                continue
            found.setdefault(app_name(p).lower(), (app_name(p), str(p)))
    return sorted(found.values(), key=lambda a: a[0].lower())


class AppPicker(QDialog):
    """Pick apps from the menus to add to a dock."""

    def __init__(self, icon_provider, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add apps to the dock")
        self.resize(420, 520)
        layout = QVBoxLayout(self)
        self.filter = QLineEdit(placeholderText="Type to find an app…")
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(24, 24))
        for name, path in installed_apps():
            item = QListWidgetItem(shell_icon(path) or icon_provider.icon(QFileInfo(path)), name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.list.addItem(item)
        self.filter.textChanged.connect(self.apply_filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(self.filter)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def chosen(self):
        return [it.data(Qt.UserRole) for it in self.list.selectedItems() if not it.isHidden()]


class DockList(QListWidget):
    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Snap)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(LIST_STYLE)
        self.setAcceptDrops(True)
        self.itemClicked.connect(lambda it: self.dock.launch(it.data(Qt.UserRole)))

    def dragEnterEvent(self, e):
        if e.source() is self or local_paths(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self:
            super().dragMoveEvent(e)
        elif local_paths(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.source() is self:  # reordering
            target = self.itemAt(e.position().toPoint())
            moving = self.currentItem()
            if moving is not None:
                self.dock.move_app(moving.data(Qt.UserRole), target.data(Qt.UserRole) if target else None)
            e.setDropAction(Qt.IgnoreAction)
            e.accept()
            return
        paths = local_paths(e.mimeData())
        if paths:
            e.setDropAction(Qt.CopyAction)  # the files stay where they are
            e.accept()
            self.dock.add_apps(paths)

    def contextMenuEvent(self, e):
        item = self.itemAt(e.pos())
        menu = QMenu()
        if item is not None:
            path = item.data(Qt.UserRole)
            menu.addAction("Open", lambda: self.dock.launch(path))
            menu.addAction(f"Show in {FILE_MANAGER}", lambda: show_in_folder(path))
            menu.addAction("Remove from dock", lambda: self.dock.remove_app(path))
            menu.addSeparator()
        menu.addAction("Add apps…", self.dock.pick_apps)
        menu.addSeparator()
        self.dock.show_menu(e.globalPos(), menu)


class DockFence(Panel):
    kind = "dock"
    default_size = (380, 120)

    def build_content(self, data):
        self.apps = [str(p) for p in data.get("apps", [])]
        self.icon_size = data.get("icon_size", 48)
        self.labels = data.get("labels", False)
        self.list = DockList(self)
        self.refresh()
        return self.list

    def content_dict(self):
        return {"apps": self.apps, "icon_size": self.icon_size, "labels": self.labels}

    def rolled_title(self):
        return f"{self.name}  ({len(self.apps)})"

    def refresh(self):
        size = self.icon_size
        self.list.setIconSize(QSize(size, size))
        self.list.setGridSize(QSize(size + (44 if self.labels else 14), size + (34 if self.labels else 12)))
        self.list.clear()
        for path in self.apps:
            exists = Path(path).exists()
            icon = (shell_icon(path, jumbo=size > 48) or self.app.icon_provider.icon(QFileInfo(path))) if exists \
                else self.app.icon_provider.icon(QFileInfo(path))
            item = QListWidgetItem(icon, app_name(path) if self.labels else "")
            item.setData(Qt.UserRole, path)
            item.setToolTip(app_name(path) if exists else f"{app_name(path)}\n(not found: {path})")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            if not exists:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(item)
        self.update()

    def launch(self, path):
        if Path(path).exists():
            open_path(path)

    def add_apps(self, paths):
        new = [str(p) for p in paths if str(p) not in self.apps]
        if new:
            self.apps.extend(new)
            self.refresh()
            self.app.schedule_save()
        return new

    def move_app(self, path, before=None):
        """Move `path` to just before `before` (or to the end)."""
        if path not in self.apps or path == before:
            return
        self.apps.remove(path)
        self.apps.insert(self.apps.index(before) if before in self.apps else len(self.apps), path)
        self.refresh()
        self.app.schedule_save()

    def remove_app(self, path):
        if path in self.apps:
            self.apps.remove(path)
            self.refresh()
            self.app.schedule_save()

    def pick_apps(self):
        picker = AppPicker(self.app.icon_provider)
        if picker.exec() == QDialog.Accepted:
            self.add_apps(picker.chosen())

    def set_icon_size(self, size):
        self.icon_size = size
        self.refresh()
        self.app.schedule_save()

    def set_labels(self, on):
        self.labels = on
        self.refresh()
        self.app.schedule_save()

    def build_settings(self, form):
        sizes = QComboBox()
        for label, size in ICON_SIZES:
            sizes.addItem(label, size)
        sizes.setCurrentIndex(max(0, sizes.findData(self.icon_size)))
        sizes.currentIndexChanged.connect(lambda: self.set_icon_size(sizes.currentData()))
        form.addRow("Icon size", sizes)
        labels = QCheckBox("Show app names under the icons")
        labels.setChecked(self.labels)
        labels.toggled.connect(self.set_labels)
        form.addRow("", labels)
        add = QPushButton("Add apps…")
        add.clicked.connect(self.pick_apps)
        form.addRow("Apps", add)
