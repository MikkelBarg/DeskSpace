"""Games from other launchers: Heroic (GOG, Epic, Amazon and its own added games, on Windows and Linux)
and Lutris (Linux). Both are read from their own files; nothing is changed in them.

Each game is a dict like the console library's: source ("Heroic" or "Lutris"), id, name, played (Unix
time, 0 if never), plus what's needed to start it, show its cover and tell whether it's running.
Shortcuts are .url files with the launcher's own link, the same kind DeskSpace makes for Steam games.
"""
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import psutil

from .common import COVER_CACHE, unique_path
from .system import IS_WINDOWS, open_path

HEROIC_STORES = {"gog": "GOG", "legendary": "Epic", "nile": "Amazon", "sideload": "Added"}


# -- Heroic

def heroic_root():
    if IS_WINDOWS:
        roots = [Path(os.environ.get("APPDATA", Path.home())) / "heroic"]
    else:
        roots = [Path.home() / ".var/app/com.heroicgameslauncher.hgl/config/heroic",  # Flatpak
                 Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "heroic"]
    return next((r for r in roots if (r / "store").is_dir() or (r / "config.json").is_file()), None)


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _played(stamp):
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0


def _installed(root):
    """(runner, app name, folder) for each installed game, from each store's own list."""
    gog = _load(root / "gog_store/installed.json") or {}
    for g in gog.get("installed", []) if isinstance(gog, dict) else []:
        if not g.get("is_dlc"):
            yield "gog", str(g.get("appName", "")), g.get("install_path", "")
    epic = _load(root / "legendaryConfig/legendary/installed.json") or {}
    for name, g in epic.items() if isinstance(epic, dict) else []:
        if isinstance(g, dict) and not g.get("is_dlc"):
            yield "legendary", str(g.get("app_name", name)), g.get("install_path", "")
    amazon = _load(root / "nile_store/installed.json") or []
    for g in amazon if isinstance(amazon, list) else amazon.get("installed", []) if isinstance(amazon, dict) else []:
        if isinstance(g, dict):
            yield "nile", str(g.get("id") or g.get("appName", "")), g.get("path") or g.get("install_path", "")


def _library(root):
    """app name -> the store cache's entry (title, cover art), plus Heroic's own added games."""
    out = {}
    for name in ("gog_library.json", "legendary_library.json", "nile_library.json"):
        data = _load(root / "store_cache" / name) or {}
        for g in data.get("games", data.get("library", [])) if isinstance(data, dict) else []:
            if isinstance(g, dict) and g.get("app_name"):
                out[str(g["app_name"])] = g
    return out


def heroic_games():
    root = heroic_root()
    if root is None:
        return []
    library = _library(root)
    stamps = _load(root / "store/timestamp.json") or {}
    games, seen = [], set()

    def add(runner, app, title, folder, cover):
        if not app or (runner, app) in seen:
            return
        seen.add((runner, app))
        stamp = stamps.get(app, {}) if isinstance(stamps, dict) else {}
        games.append({"source": "Heroic", "id": f"{runner}:{app}", "app": app, "runner": runner,
                      "name": title or app, "store": HEROIC_STORES.get(runner, runner), "folder": folder or "",
                      "played": _played(stamp.get("lastPlayed")), "cover_url": cover or ""})

    for runner, app, folder in _installed(root):
        entry = library.get(app, {})
        add(runner, app, entry.get("title"), folder, entry.get("art_square") or entry.get("art_cover"))
    sideload = _load(root / "sideload_apps/library.json") or {}
    for g in sideload.get("games", []) if isinstance(sideload, dict) else []:
        if isinstance(g, dict) and g.get("is_installed", True):
            add("sideload", str(g.get("app_name", "")), g.get("title"), (g.get("install") or {}).get("executable", ""),
                g.get("art_square") or g.get("art_cover"))
    return games


def heroic_link(game):
    return f"heroic://launch?appName={game['app']}&runner={game['runner']}"


# -- Lutris

def lutris_db():
    for path in (Path.home() / ".local/share/lutris/pga.db", Path.home() / ".var/app/net.lutris.Lutris/data/lutris/pga.db"):
        if path.is_file():
            return path
    return None


def lutris_cover(slug):
    for folder in (Path.home() / ".local/share/lutris/coverart", Path.home() / ".cache/lutris/coverart",
                   Path.home() / ".var/app/net.lutris.Lutris/data/lutris/coverart"):
        for ext in (".jpg", ".png"):
            if (folder / f"{slug}{ext}").is_file():
                return folder / f"{slug}{ext}"
    return None


def lutris_games():
    if IS_WINDOWS:
        return []
    db = lutris_db()
    if db is None:
        return []
    try:
        # Opened read-only, so a running Lutris is never disturbed.
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT id, name, slug, runner, directory, lastplayed FROM games "
                               "WHERE installed = 1").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [{"source": "Lutris", "id": str(gid), "name": name or slug or str(gid), "slug": slug or "",
             "store": runner or "Lutris", "folder": directory or "", "played": float(played or 0)}
            for gid, name, slug, runner, directory, played in rows]


def lutris_link(game):
    return f"lutris:rungameid/{game['id']}"


# -- all of them

def installed_games():
    return heroic_games() + lutris_games()


def link(game):
    return heroic_link(game) if game["source"] == "Heroic" else lutris_link(game)


def launch(game):
    open_path(link(game))


def is_running(game):
    """Is anything running from the game's folder? (Windows games under Wine have it in their command line too.)"""
    folder = str(game.get("folder") or "").rstrip("/\\")
    if len(folder) < 4:
        return False
    wine = "z:" + folder.replace("/", "\\").lower()
    low = folder.lower()
    for p in psutil.process_iter(["exe", "cmdline", "cwd"]):
        try:
            exe = (p.info["exe"] or "").lower()
            cwd = (p.info["cwd"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
        except (psutil.Error, TypeError):
            continue
        if exe.startswith(low) or cwd.startswith(low) or low in cmd or wine in cmd:
            return True
    return False


def cover_key(game):
    return re.sub(r"[^\w.-]", "_", f"{game['source'].lower()}_{game['id']}")


def cover_file(game):
    """A cover on disk for the game, or None (Heroic's are downloaded into our cache on first use)."""
    if game["source"] == "Lutris":
        local = lutris_cover(game.get("slug", ""))
        if local:
            return local
    path = COVER_CACHE / f"{cover_key(game)}.jpg"
    return path if path.exists() else None


# -- shortcuts in a fence

def make_shortcut(folder, game):
    path = unique_path(Path(folder), re.sub(r'[\\/:*?"<>|]', "", game["name"]).strip() + ".url", False)
    path.write_text(f"[InternetShortcut]\nURL={link(game)}\n", encoding="utf-8")
    return path


_LINKS = (re.compile(r"heroic://launch\?appName=([^&\s]+)&runner=(\w+)", re.I),
          re.compile(r"lutris:rungameid/(\d+)", re.I))


def game_from_shortcut(path, games=None):
    """The installed Heroic or Lutris game a .url shortcut starts, or None."""
    if path.suffix.lower() != ".url":
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    heroic, lutris = (r.search(text) for r in _LINKS)
    if not heroic and not lutris:
        return None
    key = ("Heroic", f"{heroic.group(2)}:{heroic.group(1)}") if heroic else ("Lutris", lutris.group(1))
    return next((g for g in (games if games is not None else installed_games()) if (g["source"], g["id"]) == key), None)
