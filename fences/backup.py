"""Back up and restore everything DeskSpace keeps: config.json (fences, notes, to-dos, settings) and the
fences' own folders, all in one zip.

Folder portals are saved as the path they show; the folders themselves aren't copied. Restoring first
saves what's there now to DeskSpace/Backups, then unpacks the backup over the data folder: files from
the backup replace ones with the same name, and nothing else is deleted.
"""
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from .common import APP_NAME, APP_VERSION, DATA_ROOT

MANIFEST = "deskspace-backup.json"
CONFIG = "config.json"
BACKUPS = "Backups"
SKIP_TOP = {".covers", BACKUPS}  # downloaded cover art (fetched again by itself) and earlier backups
SKIP_ANY = {"__pycache__"}


class BackupError(Exception):
    pass


def default_name():
    return f"{APP_NAME} backup {datetime.now():%Y-%m-%d}.zip"


def create(target, data_root=DATA_ROOT):
    """Write a backup of `data_root` to `target`; returns how many files went in."""
    target, data_root = Path(target), Path(data_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    manifest = {"app": APP_NAME, "version": APP_VERSION, "data_root": str(data_root),
                "created": datetime.now().isoformat(timespec="seconds")}
    count = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for folder, dirs, files in os.walk(data_root):
                here = Path(folder)
                top = here == data_root
                dirs[:] = [d for d in dirs if d not in SKIP_ANY and not (top and d in SKIP_TOP)
                           and not (here / d).is_symlink()]
                for name in files:
                    path = here / name
                    if path in (target, tmp) or name.endswith((".tmp", ".part")) or path.is_symlink():
                        continue
                    try:
                        z.write(path, path.relative_to(data_root).as_posix())
                        count += 1
                    except OSError:
                        pass  # open in another program or vanished meanwhile; back up the rest
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return count


def _safe_name(name):
    """The member's path inside the data folder, or None if it would land outside it (or is a folder)."""
    name = name.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if not parts or name.endswith("/") or name.startswith("/") or ".." in parts or ":" in parts[0]:
        return None
    return parts


def check(source):
    """The backup's manifest, or BackupError with a reason that can be shown as it is."""
    try:
        with zipfile.ZipFile(source) as z:
            names = set(z.namelist())
            if MANIFEST not in names or CONFIG not in names:
                raise BackupError("This file isn't a DeskSpace backup.")
            manifest = json.loads(z.read(MANIFEST))
            json.loads(z.read(CONFIG))
            bad = z.testzip()
            if bad:
                raise BackupError(f"The backup is damaged ({bad} can't be read).")
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as e:
        raise BackupError(f"The backup can't be read.\n\n{e}") from e
    return manifest


def remap(path, old_root, new_root):
    """A fence folder saved under the backup's data folder, moved to this PC's data folder.

    Backups can come from Windows or Linux, so the paths are read the way they were written."""
    flavour = PureWindowsPath if ("\\" in old_root or ":" in old_root[:3]) else PurePosixPath
    try:
        rel = flavour(path).relative_to(flavour(old_root))
    except ValueError:
        return path  # somewhere else, like a portal's folder: leave it
    return str(Path(new_root).joinpath(*rel.parts))


def _remap_folders(node, old_root, new_root):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "folder" and isinstance(value, str):
                node[key] = remap(value, old_root, new_root)
            else:
                _remap_folders(value, old_root, new_root)
    elif isinstance(node, list):
        for value in node:
            _remap_folders(value, old_root, new_root)


def restore(source, data_root=DATA_ROOT):
    """Unpack the backup over `data_root`, after saving what's there now. Returns that safety backup's path."""
    data_root = Path(data_root)
    manifest = check(source)
    safety = data_root / BACKUPS / f"Before restore {datetime.now():%Y-%m-%d %H.%M.%S}.zip"
    create(safety, data_root)
    with zipfile.ZipFile(source) as z:
        for info in z.infolist():
            parts = _safe_name(info.filename)
            if parts is None or info.filename in (MANIFEST, CONFIG):
                continue
            dest = data_root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
        cfg = json.loads(z.read(CONFIG))
    _remap_folders(cfg, manifest.get("data_root", str(data_root)), data_root)
    tmp = data_root / (CONFIG + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(data_root / CONFIG)
    return safety
