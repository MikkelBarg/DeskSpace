"""Icon fences: an owned fence keeps its items in its own folder under DeskSpace; a folder
portal shows any existing folder (like Downloads) without moving anything."""
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QFileInfo, QFileSystemWatcher, QMimeData, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl,
)
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
)

from . import dialogs, gog, libraries, steam
from .common import (
    DATA_ROOT, DESKTOP, LIST_STYLE, display_name, is_hidden, local_paths, move_into, moved_path, safe_name,
    unique_path,
)
from .panel import Panel
from .system import FILE_MANAGER, IS_WINDOWS, open_path, shell_icon, show_in_folder

TILE = QSize(104, 156)  # 2:3, the shape of Steam's library covers
PATH_SEP = " › "
# How a fence can order its items; folders always come first, like in a file manager.
SORTS = [("name", "Name (A to Z)"), ("name_desc", "Name (Z to A)"), ("date_new", "Date modified (newest first)"),
         ("date_old", "Date modified (oldest first)"), ("size_big", "Size (largest first)"),
         ("size_small", "Size (smallest first)"), ("type", "Type")]


def sort_entries(paths, how):
    def stat(p):
        try:
            return p.stat()
        except OSError:  # vanished or unreadable since it was listed
            return None

    def mtime(p):
        s = stat(p)
        return s.st_mtime if s else 0

    def size(p):
        s = stat(p)
        return s.st_size if s and not p.is_dir() else 0

    name = lambda p: p.name.lower()  # noqa: E731
    keys = {"name": (name, False), "name_desc": (name, True), "date_new": (mtime, True), "date_old": (mtime, False),
            "size_big": (lambda p: (size(p), p.name.lower()), True),
            "size_small": (lambda p: (size(p), p.name.lower()), False),
            "type": (lambda p: (p.suffix.lower(), p.name.lower()), False)}
    key, reverse = keys.get(how, keys["name"])
    folders = sorted((p for p in paths if p.is_dir()), key=key, reverse=reverse)
    files = sorted((p for p in paths if not p.is_dir()), key=key, reverse=reverse)
    return folders + files
UP_ROLE = Qt.UserRole + 1  # marks the "Up" item a portal shows while it is inside a subfolder


def is_up(item):
    return item is not None and bool(item.data(UP_ROLE))


def up_icon(dpr):
    """A white arrow in a soft circle: drawn here so it reads on any fence colour and in any Qt style."""
    size = 64
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 45))
    p.drawEllipse(QRectF(4, 4, size - 8, size - 8))
    pen = QPen(QColor(255, 255, 255, 235), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(32, 46, 32, 19)
    p.drawPolyline([QPointF(20, 30), QPointF(32, 18), QPointF(44, 30)])
    p.end()
    return QIcon(pm)


def button(text, slot):
    b = QPushButton(text)
    b.clicked.connect(slot)
    return b


class FenceList(QListWidget):
    def __init__(self, fence):
        super().__init__(fence)
        self.fence = fence
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideRight)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setFrameShape(QListWidget.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(LIST_STYLE)
        self.setMouseTracking(True)
        self.itemActivated.connect(self.fence.activate)

    # -- hover previews (icon view only; game tiles already are pictures)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        item = self.itemAt(e.position().toPoint())
        preview = self.fence.app.preview
        if item is None or is_up(item) or self.fence.view != "icons" or e.buttons():
            preview.cancel()
            return
        rect = self.visualItemRect(item)
        top_left = self.viewport().mapToGlobal(rect.topLeft())
        preview.hover(item.data(Qt.UserRole), QRect(top_left, rect.size()))

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:  # the mouse's back button goes up a folder, like in Explorer
            self.fence.go_up()
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        alt = bool(e.modifiers() & Qt.AltModifier)
        if e.key() == Qt.Key_Backspace or (alt and e.key() in (Qt.Key_Up, Qt.Key_Left)):
            self.fence.go_up()
            return
        super().keyPressEvent(e)

    def viewportEvent(self, e):
        if e.type() in (QEvent.Leave, QEvent.Wheel, QEvent.MouseButtonPress):
            self.fence.app.preview.cancel()
        return super().viewportEvent(e)

    def set_view(self, view):
        if view == "tiles":
            self.setIconSize(TILE)
            self.setGridSize(QSize(TILE.width() + 10, TILE.height() + 10))
        else:
            self.setIconSize(QSize(40, 40))
            self.setGridSize(QSize(88, 86))

    def selected_paths(self):
        return [it.data(Qt.UserRole) for it in self.selectedItems()]

    def startDrag(self, actions):
        paths = self.selected_paths()
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.selectedItems()[0].icon().pixmap(36, 36))
        drag.exec(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        self.fence.schedule_refresh()

    def dragEnterEvent(self, e):
        self.fence.handle_drag_enter(e)

    def dragMoveEvent(self, e):
        self.fence.handle_drag_enter(e)

    def dragLeaveEvent(self, e):
        self.fence.set_drop_hover(False)

    def dropEvent(self, e):
        self.fence.handle_drop(e)

    def contextMenuEvent(self, e):
        item = self.itemAt(e.pos())
        if is_up(item):
            item = None
        menu = QMenu()
        if not item:
            sort = menu.addMenu("Sort by")
            for key, label in SORTS:
                action = sort.addAction(label, lambda k=key: self.fence.set_sort(k))
                action.setCheckable(True)
                action.setChecked(key == self.fence.sort)
            menu.addSeparator()
        if item:
            if not item.isSelected():
                self.clearSelection()
                item.setSelected(True)
            paths = self.selected_paths()
            menu.addAction("Open", lambda: [open_path(p) for p in paths])
            menu.addAction(f"Show in {FILE_MANAGER}", lambda: show_in_folder(paths[0]))
            menu.addAction("Move to desktop", lambda: self.fence.move_out(paths, DESKTOP))
            others = [f for f in self.fence.app.folder_fences() if f is not self.fence]
            if others:
                sub = menu.addMenu("Move to fence")
                for other in others:
                    sub.addAction(other.name, lambda o=other: self.fence.move_out(paths, o.folder, o))
            menu.addSeparator()
        self.fence.show_menu(e.globalPos(), menu)


def make_tile(name, dpr, cover=None, header=None, icon=None):
    """A 2:3 tile: the game's cover art, or its icon and name on a dark card."""
    pm = QPixmap(TILE * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    w, h = TILE.width(), TILE.height()
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
    p.setClipPath(clip)
    art = QPixmap(str(cover or header)) if (cover or header) else QPixmap()
    if cover and not art.isNull():
        scaled = art.scaled(TILE * dpr, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        p.drawPixmap(int((w - scaled.width() / dpr) / 2), int((h - scaled.height() / dpr) / 2), scaled)
    else:
        p.fillRect(0, 0, w, h, QColor(255, 255, 255, 28))
        text_top = h - 46
        if not art.isNull():  # landscape header: full width across the top
            scaled = art.scaledToWidth(int(w * dpr), Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            p.drawPixmap(0, 0, scaled)
            text_top = int(scaled.height() / dpr) + 8
        elif icon:
            p.drawPixmap(int((w - 64) / 2), 26, icon.pixmap(QSize(64, 64), dpr))
        font = QFont()
        font.setPointSizeF(9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 230))
        if art.isNull() and not icon:  # nothing but the name: give it the whole card
            p.drawText(QRectF(8, 8, w - 16, h - 16), Qt.AlignCenter | Qt.TextWordWrap, name)
        else:
            p.drawText(QRectF(6, text_top, w - 12, h - text_top - 6), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       name)
    p.end()
    return pm


class FolderFence(Panel):
    kind = "folder"

    def build_content(self, data):
        self.folder = moved_path(data["folder"])  # saved before the data folder was renamed?
        self.portal = data.get("kind") == "portal"
        self.kind = "portal" if self.portal else "folder"
        self.view = data.get("view", "icons")
        self.rules = data.get("rules", [])
        self.sort = data.get("sort", "name")
        self.count = 0
        self.current = self.folder  # a portal can be browsed into its subfolders; this is the one on show
        if not self.portal:
            self.folder.mkdir(parents=True, exist_ok=True)
        self.setAcceptDrops(True)

        self.list = FenceList(self)
        self.list.set_view(self.view)
        self.refresh_timer = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule_refresh)
        self.refresh()
        return self.list

    def content_dict(self):
        return {"folder": str(self.folder), "view": self.view, "rules": self.rules, "sort": self.sort}

    def title_text(self):
        return PATH_SEP.join(text for text, _ in self.path_parts())

    def rolled_title(self):
        return f"{self.title_text()}  ({self.count})"

    # -- the path in the title bar: each folder above the one on show can be clicked to go back to it

    def path_parts(self):
        """(text, folder to open) for the portal's name and each subfolder below it; the last one is on show."""
        parts, folder = [(self.name, self.folder)], self.folder
        if self.current != self.folder:
            for name in self.current.relative_to(self.folder).parts:
                folder = folder / name
                parts.append((name, folder))
        return [(text, None if folder == self.current else folder) for text, folder in parts]

    def title_runs(self, width):
        """The title as (text, folder or None, x offset, width) pieces that fit in `width`, centred.

        When the whole path is too long, the folders at the start give way to "…" first, so the
        folder on show stays readable."""
        fm = QFontMetrics(self.title_font)
        parts = self.path_parts()
        suffix = [(f"  ({self.count})", None)] if self.rolled else []

        def pieces(parts, cut):
            out = [("…", None), (PATH_SEP, None)] if cut else []
            for i, part in enumerate(parts):
                out += [(PATH_SEP, None), part] if i else [part]
            return out + suffix

        cut = False
        runs = pieces(parts, cut)
        while len(parts) > 1 and sum(fm.horizontalAdvance(text) for text, _ in runs) > width:
            parts, cut = parts[1:], True
            runs = pieces(parts, cut)
        if sum(fm.horizontalAdvance(text) for text, _ in runs) > width:  # even the last folder alone is too long
            runs = [(fm.elidedText("".join(text for text, _ in runs), Qt.ElideLeft, width), None)]
        total = sum(fm.horizontalAdvance(text) for text, _ in runs)
        x, out = (width - total) / 2, []
        for text, target in runs:
            w = fm.horizontalAdvance(text)
            out.append((text, target, x, w))
            x += w
        return out

    def title_area(self):
        r = self.rect().adjusted(1, 1, -1, -1)
        return r.left() + 12, r.width() - 24

    def paint_title(self, p, r):
        if self.current == self.folder:
            super().paint_title(p, r)
            return
        left, width = self.title_area()
        fm = QFontMetrics(self.title_font)
        baseline = (self.title_h - fm.height()) / 2 + fm.ascent()
        for text, target, x, w in self.title_runs(width):
            font = QFont(self.title_font)
            font.setUnderline(target is not None and target == self.hover_link)
            p.setFont(font)
            # Folders you can go back to are a little dimmer than the one on show.
            p.setPen(QColor(255, 255, 255, 190 if target is not None else 230))
            p.drawText(QPointF(left + x, baseline), text)

    def title_link_at(self, pos):
        if self.current == self.folder or pos.y() >= self.title_h:
            return None
        left, width = self.title_area()
        for _, target, x, w in self.title_runs(width):
            if target is not None and left + x <= pos.x() < left + x + w:
                return target
        return None

    def title_link_clicked(self, target):
        self.set_hover_link(None)
        self.browse(target)

    def schedule_refresh(self, *_):
        self.refresh_timer.start()

    def refresh(self):
        self.refresh_count = getattr(self, "refresh_count", 0) + 1
        if not self.portal:
            self.folder.mkdir(parents=True, exist_ok=True)
        if not self.folder.is_dir():  # a portal whose folder was deleted or is on an unplugged drive
            self.list.clear()
            self.count = 0
            self.update()
            return
        self.fall_back_to_existing()
        if str(self.current) not in self.watcher.directories():
            self.watcher.addPath(str(self.current))
        try:
            entries = sort_entries([p for p in self.current.iterdir() if not is_hidden(p)], self.sort)
        except OSError:  # no permission to list this subfolder
            entries = []
        self.list.clear()
        dpr = self.devicePixelRatioF()
        if self.current != self.folder:
            self.list.addItem(self.up_item(dpr))
        for p in entries:
            item = QListWidgetItem()
            if self.view == "tiles":
                item.setIcon(QIcon(self.tile_for(p, dpr)))
            else:
                item.setIcon(shell_icon(p) or self.app.icon_provider.icon(QFileInfo(str(p))))
                item.setText(display_name(p))
            item.setData(Qt.UserRole, str(p))
            item.setToolTip(p.name)
            self.list.addItem(item)
        self.count = len(entries)
        self.update()

    def up_item(self, dpr):
        icon = up_icon(dpr)
        item = QListWidgetItem()
        if self.view == "tiles":
            item.setIcon(QIcon(make_tile("Up", dpr, icon=icon)))
        else:
            item.setIcon(icon)
            item.setText("Up")
        parent = self.current.parent
        item.setData(Qt.UserRole, str(parent))
        item.setData(UP_ROLE, True)
        item.setToolTip(f"Back to {parent.name or parent}  (Backspace or the mouse's back button)")
        item.setFlags(Qt.ItemIsEnabled)  # can't be selected, dragged or moved like a real file
        return item

    # -- browsing a portal's subfolders

    def activate(self, item):
        if is_up(item):
            self.go_up()
            return
        path = Path(item.data(Qt.UserRole))
        if self.portal and path.is_dir():
            self.browse(path)
        else:
            open_path(path)

    def browse(self, folder):
        if Path(folder) == self.current:
            return
        self.watcher.removePath(str(self.current))
        self.current = Path(folder)
        self.app.preview.cancel()
        self.refresh()
        self.list.scrollToTop()

    def go_up(self):
        if self.current != self.folder:
            self.browse(self.current.parent)

    def fall_back_to_existing(self):
        """If the subfolder on show was deleted or renamed, step up to the nearest one that's still there."""
        current = self.current
        while current != self.folder and (not current.is_dir() or not current.is_relative_to(self.folder)):
            if not current.is_relative_to(self.folder) or current.parent == current:
                current = self.folder
                break
            current = current.parent
        if current != self.current:
            self.watcher.removePath(str(self.current))
            self.current = current

    def tile_for(self, path, dpr):
        name = display_name(path, limit=40)
        appid = steam.appid_from_shortcut(path)
        if appid:
            cover = steam.cover_file(appid)
            if cover:
                return make_tile(name, dpr, cover=cover)
            self.app.fetch_cover(appid)
            header = steam.header_file(appid)
            if header:
                return make_tile(name, dpr, header=header)
        game_id = gog.id_from_shortcut(path)
        if game_id:
            cover = gog.cover_file(game_id)
            if cover:
                return make_tile(name, dpr, cover=cover)
            self.app.fetch_gog_cover(game_id)
        game = libraries.game_from_shortcut(path, self.library_games()) if path.suffix.lower() == ".url" else None
        if game:
            cover = libraries.cover_file(game)
            if cover:
                return make_tile(name, dpr, cover=cover)
            if game.get("cover_url"):
                self.app.fetch_cover_url(libraries.cover_key(game), game["cover_url"])
        icon = shell_icon(path, jumbo=True) or self.app.icon_provider.icon(QFileInfo(str(path)))
        return make_tile(name, dpr, icon=icon)

    # -- moving files

    def receive(self, paths):
        results = [move_into(p, self.current) for p in paths]
        self.refresh()
        if False in results:
            self.app.warn("Some items could not be moved.\n\nShortcuts shared by all users "
                          "(Public Desktop) need admin rights, and open files can't be moved.")

    def move_out(self, paths, target, target_fence=None):
        results = [move_into(p, target) for p in paths]
        self.refresh()
        if target_fence:
            target_fence.refresh()
        if False in results:
            self.app.warn("Some items could not be moved (they may be open in another program).")

    # -- drag & drop

    def handle_drag_enter(self, e):
        if e.mimeData().hasUrls() and e.source() is not self.list and self.current.is_dir():
            e.setDropAction(Qt.MoveAction)
            e.accept()
            self.set_drop_hover(True)
        else:
            e.ignore()

    def handle_drop(self, e):
        self.set_drop_hover(False)
        if e.source() is self.list:
            e.ignore()
            return
        paths = local_paths(e.mimeData())
        # We move the files ourselves; report "copy" so Explorer doesn't also try to delete the source.
        e.setDropAction(Qt.CopyAction)
        e.accept()
        if isinstance(e.source(), FenceList):
            QTimer.singleShot(0, lambda: self.receive(paths))
        else:
            self.receive(paths)

    def set_drop_hover(self, on):
        if self.drop_hover != on:
            self.drop_hover = on
            self.update()
            if self.group is not None:  # as a tab, it's the group's border that's visible
                self.group.drop_hover = on
                self.group.update()

    def dragEnterEvent(self, e):
        self.handle_drag_enter(e)

    def dragMoveEvent(self, e):
        self.handle_drag_enter(e)

    def dragLeaveEvent(self, e):
        self.set_drop_hover(False)

    def dropEvent(self, e):
        self.handle_drop(e)

    # -- settings

    def build_settings(self, form):
        folder_row = QHBoxLayout()
        path = QLineEdit(str(self.folder))
        path.setReadOnly(True)
        folder_row.addWidget(path, 1)
        folder_row.addWidget(button("Open", lambda: open_path(self.folder)))
        if self.portal:
            def change():
                chosen = dialogs.get_folder("Choose a folder to show", self.folder)
                if chosen:
                    self.set_folder(chosen)
                    path.setText(chosen)
            folder_row.addWidget(button("Change…", change))
        form.addRow("Folder", folder_row)

        view = QComboBox()
        view.addItem("Icons", "icons")
        view.addItem("Game tiles (cover art)", "tiles")
        view.setCurrentIndex(view.findData(self.view))
        view.currentIndexChanged.connect(lambda: self.set_view(view.currentData()))
        form.addRow("View", view)

        sort = QComboBox()
        for key, label in SORTS:
            sort.addItem(label, key)
        sort.setCurrentIndex(max(0, sort.findData(self.sort)))
        sort.currentIndexChanged.connect(lambda: self.set_sort(sort.currentData()))
        form.addRow("Sort by", sort)

        rules = QLineEdit(", ".join(self.rules))
        rules.setPlaceholderText("e.g.  *.xlsx, *.docx, invoice*")
        rules.editingFinished.connect(lambda: self.set_rules(rules.text()))
        form.addRow("Auto-sort rules", rules)
        hint = QLabel("Files that land on the desktop and match these patterns move into this fence "
                      "automatically (including matching files already there). Leave empty to turn off.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow("", hint)
        if steam.steam_root():
            form.addRow("Steam", button("Add installed Steam games", self.add_steam_games))
        if IS_WINDOWS:  # GOG Galaxy and its registry entries only exist there
            form.addRow("GOG", button("Add installed GOG games", self.add_gog_games))
        others = [name for name, found in (("Heroic", libraries.heroic_root()), ("Epic", libraries.epic_manifests()),
                                           ("Lutris", libraries.lutris_db())) if found]
        if others:
            form.addRow(" and ".join(others), button(f"Add installed {' and '.join(others)} games",
                                                    self.add_library_games))

    def remove_label(self):
        return "Remove portal (files stay)" if self.portal else "Remove fence (items go back to desktop)"

    def set_sort(self, how):
        if how != self.sort:
            self.sort = how
            self.refresh()
            self.app.schedule_save()

    def set_view(self, view):
        self.view = view
        self.list.set_view(view)
        self.refresh()
        self.app.schedule_save()

    def add_steam_games(self):
        have = {steam.appid_from_shortcut(p) for p in self.folder.iterdir()} if self.folder.is_dir() else set()
        exe = steam.steam_exe()
        added = []
        for appid, name in steam.installed_games():
            if appid in have:
                continue
            path = unique_path(self.folder, safe_name(name) + ".url", False)
            path.write_text(f"[InternetShortcut]\nURL=steam://rungameid/{appid}\nIconIndex=0\nIconFile={exe}\n",
                            encoding="utf-8")
            added.append(name)
        self.refresh()
        if added:
            self.app.warn(f"Added {len(added)} game(s):\n\n" + "\n".join(added), info=True)
        else:
            self.app.warn("All your installed Steam games are already in this fence.", info=True)

    def add_gog_games(self):
        games = gog.installed_games()
        if not games:
            self.app.warn("No installed GOG games were found on this PC.\n\nGames installed with GOG Galaxy or "
                          "GOG's offline installers show up here. You can also drag a GOG game's shortcut into "
                          "the fence.", info=True)
            return
        have = {gog.id_from_shortcut(p) for p in self.folder.iterdir()} if self.folder.is_dir() else set()
        added = []
        for game in games:
            if game["id"] in have:
                continue
            gog.make_shortcut(unique_path(self.folder, safe_name(game["name"]) + ".lnk", False), game)
            added.append(game["name"])
        self.refresh()
        if added:
            self.app.warn(f"Added {len(added)} game(s):\n\n" + "\n".join(added), info=True)
        else:
            self.app.warn("All your installed GOG games are already in this fence.", info=True)

    def library_games(self):
        """Heroic, Epic and Lutris games, read once per refresh (each tile would otherwise read them again)."""
        stamp = getattr(self, "_library_stamp", None)
        if stamp is None or stamp[0] != self.refresh_count:
            self._library_stamp = (self.refresh_count, libraries.installed_games())
        return self._library_stamp[1]

    def add_library_games(self):
        games = libraries.installed_games()
        if not games:
            self.app.warn("No installed Heroic, Epic or Lutris games were found.", info=True)
            return
        have = set()
        for p in self.folder.iterdir() if self.folder.is_dir() else []:
            found = libraries.game_from_shortcut(p, games)
            if found:
                have.add((found["source"], found["id"]))
        added = [libraries.make_shortcut(self.folder, g) and g["name"] for g in games
                 if (g["source"], g["id"]) not in have]
        self.refresh()
        if added:
            self.app.warn(f"Added {len(added)} game(s):\n\n" + "\n".join(added), info=True)
        else:
            self.app.warn("All your installed Heroic, Epic and Lutris games are already in this fence.", info=True)

    def set_rules(self, text):
        rules = [r.strip() for r in text.replace(";", ",").split(",") if r.strip()]
        if rules == self.rules:
            return
        self.rules = rules
        self.app.schedule_save()
        self.app.apply_rules()

    def set_folder(self, folder):
        self.watcher.removePath(str(self.current))
        self.folder = self.current = Path(folder)
        self.refresh()
        self.app.schedule_save()

    def on_renamed(self):
        if self.portal:
            return
        new_folder = DATA_ROOT / safe_name(self.name)
        if not new_folder.exists():
            self.watcher.removePath(str(self.folder))
            try:
                self.folder.rename(new_folder)
                self.folder = self.current = new_folder
            except OSError:
                pass  # keep the old folder name; the fence still works
        self.refresh()

    def confirm_remove(self):
        if self.portal:
            return dialogs.ask(f"Remove the portal '{self.name}'?\n\nThe folder {self.folder} and its files "
                               "are left untouched.")
        if not dialogs.ask(f"Remove the fence '{self.name}'?\n\n"
                           f"Its {self.count} item(s) will be moved back to your desktop."):
            return False
        self.watcher.removePath(str(self.folder))
        failed = [p for p in list(self.folder.iterdir()) if move_into(p, DESKTOP) is False]
        if failed:
            self.refresh()
            self.app.warn("Some items could not be moved back (they may be open). The fence was kept.")
            return False
        try:
            self.folder.rmdir()
        except OSError:
            pass  # hidden files left behind; harmless
        return True
