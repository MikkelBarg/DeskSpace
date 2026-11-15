"""Checks GitHub for a newer DeskSpace and installs it: on Windows with the release's setup, on Linux
(a copy installed with build/install-linux.sh) from the release's deskspace-linux-<version>.tar.gz.

The check asks GitHub for the latest release and sends nothing about you. Pre-releases don't count.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from .common import APP_NAME, APP_VERSION
from .dialogs import ask, tell
from .system import IS_WINDOWS, open_path

REPO = "MikkelBarg/DeskSpace"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
SETUP_NAME = re.compile(r"DeskSpace-Setup-[\d.]+\.exe$")
LINUX_NAME = re.compile(r"deskspace-linux-[\d.]+\.tar\.gz$")
LINUX_APP_DIR = Path.home() / ".local/share/deskspace"  # where build/install-linux.sh puts the app
CHECK_EVERY = 24 * 60 * 60 * 1000
FIRST_CHECK = 60000
NO_WINDOW, DETACHED = 0x08000000, 0x00000008


def version_numbers(text):
    return tuple(int(n) for n in re.findall(r"\d+", text))


def read_release(data):
    """The newer version in a GitHub release, as {"version", "page", "url", "sha256"}, or None."""
    version = str(data.get("tag_name", "")).lstrip("v")
    if not version_numbers(version) or version_numbers(version) <= version_numbers(APP_VERSION):
        return None
    release = {"version": version, "page": data.get("html_url", f"https://github.com/{REPO}/releases"),
               "url": None, "sha256": None}
    wanted = SETUP_NAME if IS_WINDOWS else LINUX_NAME
    for asset in data.get("assets", []):
        url = asset.get("browser_download_url", "")
        if wanted.search(asset.get("name", "")) and url.startswith(DOWNLOADS):
            digest = asset.get("digest") or ""
            release.update(url=url, sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None)
    return release


def installed_copy():
    """What an update replaces: the installed DeskSpace.exe on Windows, the app folder of a copy installed
    with build/install-linux.sh on Linux; None when run from source or from the .deb (which apt updates)."""
    if IS_WINDOWS:
        exe = Path(sys.executable)
        return exe if exe.name.lower() == "deskspace.exe" else None
    app = LINUX_APP_DIR / "app"
    running = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if running and running.parent == app and os.access(LINUX_APP_DIR, os.W_OK):
        return app
    return None


def unpack_linux_update(data, into):
    """Unpack a deskspace-linux-<version>.tar.gz into `into`; returns its folder. ValueError if it isn't one."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                parts = Path(m.name).parts
                if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                    raise ValueError(f"unexpected entry {m.name}")
            if hasattr(tarfile, "data_filter"):
                tar.extractall(into, filter="data")
            else:  # Python before 3.10.12; the checks above already did the same job
                tar.extractall(into)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise ValueError(str(e)) from e
    folders = [p for p in Path(into).iterdir() if p.is_dir()]
    if len(folders) != 1:
        raise ValueError("expected one folder in the update")
    root = folders[0]
    for needed in ("deskspace.pyw", "fences/app.py", "build/requirements-linux.txt"):
        if not (root / needed).is_file():
            raise ValueError(f"{needed} is missing from the update")
    return root


def swap_app(new_app_source, app_dir):
    """Put the unpacked update in place of `app_dir`, keeping the old one until the new one is there."""
    app_dir = Path(app_dir)
    staged = app_dir.with_name("app.new")
    old = app_dir.with_name("app.old")
    for leftover in (staged, old):
        shutil.rmtree(leftover, ignore_errors=True)
    staged.mkdir(parents=True)
    shutil.copy2(new_app_source / "deskspace.pyw", staged)
    shutil.copytree(new_app_source / "fences", staged / "fences", ignore=shutil.ignore_patterns("__pycache__"))
    app_dir.rename(old)
    try:
        staged.rename(app_dir)
    except OSError:
        old.rename(app_dir)
        raise
    shutil.rmtree(old, ignore_errors=True)


def install_command(setup, exe, script):
    """Waits for us to quit, runs the setup, and restarts this copy if the setup was blocked or failed.
    The setup restarts the new version itself."""
    return (f'cmd /s /c "ping -n 3 127.0.0.1 >nul & "{setup}" /SILENT || start "" "{exe}" "{script}""')


class Updater(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.available = None
        self.pip = None  # the library update a Linux install runs, while it runs
        self.timer = QTimer(self, interval=CHECK_EVERY, timeout=self.check)
        self.timer.start()
        QTimer.singleShot(FIRST_CHECK, self.check)

    def check(self, quiet=True):
        if quiet and not self.app.update_check:
            return
        request = QNetworkRequest(QUrl(LATEST))
        request.setRawHeader(b"User-Agent", APP_NAME.encode())
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(30000)
        reply = self.app.net.get(request)
        reply.finished.connect(lambda: self._checked(reply, quiet))

    def _checked(self, reply, quiet):
        reply.deleteLater()
        try:
            if reply.error() != QNetworkReply.NoError:
                raise ValueError(reply.errorString())
            release = read_release(json.loads(bytes(reply.readAll())))
        except ValueError as e:
            if not quiet:
                tell(f"Couldn't check for updates.\n\n{e}", warning=True)
            return
        if not release:
            if not quiet:
                tell(f"{APP_NAME} {APP_VERSION} is the latest version.")
            return
        known = self.available and self.available["version"] == release["version"]
        self.available = release
        self.app.update_action.setText(f"Install update {release['version']}…")
        self.app.update_action.setVisible(True)
        if not quiet:
            self.install()
        elif not known:
            self.app.tray.showMessage(APP_NAME, f"Version {release['version']} is available. Click to install it.")

    def install(self):
        release = self.available
        if not release:
            return
        exe = installed_copy()
        if not exe or not release["url"]:
            open_path(release["page"])  # running from source, the .deb, or no file for this system
            return
        if ask(f"Install {APP_NAME} {release['version']} now?\n\n{APP_NAME} closes while it updates and then "
               "starts again. Your fences and settings are kept."):
            request = QNetworkRequest(QUrl(release["url"]))
            request.setRawHeader(b"User-Agent", APP_NAME.encode())
            reply = self.app.net.get(request)
            reply.finished.connect(lambda: self._downloaded(reply, release, exe))

    def _downloaded(self, reply, release, exe):
        reply.deleteLater()
        data = bytes(reply.readAll())
        if reply.error() != QNetworkReply.NoError or not data:
            tell(f"The download failed.\n\n{reply.errorString()}", warning=True)
            return
        if release["sha256"] and hashlib.sha256(data).hexdigest() != release["sha256"].lower():
            tell("The download was damaged, so it wasn't installed.", warning=True)
            return
        if not IS_WINDOWS:
            self._install_linux(data, release, exe)
            return
        setup = Path(tempfile.gettempdir()) / f"DeskSpace-Setup-{release['version']}.exe"
        try:
            setup.write_bytes(data)
            subprocess.Popen(install_command(setup, exe, Path(sys.argv[0]).resolve()),
                             creationflags=NO_WINDOW | DETACHED)
        except OSError:
            open_path(release["page"])
            return
        self.app.quit()

    # -- Linux: unpack, update the Python libraries, swap the app folder, start again

    def _install_linux(self, data, release, app_dir):
        work = Path(tempfile.mkdtemp(prefix="deskspace-update-"))
        try:
            source = unpack_linux_update(data, work)
        except ValueError as e:
            shutil.rmtree(work, ignore_errors=True)
            tell(f"The update couldn't be unpacked, so nothing was changed.\n\n{e}", warning=True)
            return
        pip = app_dir.parent / "venv/bin/pip"
        self.pip = QProcess(self)
        self.pip.finished.connect(lambda code, _status: self._libraries_done(code, source, work, release, app_dir))
        self.pip.start(str(pip), ["install", "--quiet", "--disable-pip-version-check", "-r",
                                  str(source / "build/requirements-linux.txt")])
        if not self.pip.waitForStarted(5000):
            self._libraries_done(-1, source, work, release, app_dir)

    def _libraries_done(self, code, source, work, release, app_dir):
        output = bytes(self.pip.readAllStandardError()).decode(errors="replace").strip() if self.pip else ""
        if code != 0:
            shutil.rmtree(work, ignore_errors=True)
            tell(f"The Python libraries for {release['version']} couldn't be installed, so nothing was changed."
                 + (f"\n\n{output[-600:]}" if output else ""), warning=True)
            return
        try:
            swap_app(source, app_dir)
        except OSError as e:
            tell(f"The update couldn't be put in place, so {APP_NAME} keeps running as it was.\n\n{e}",
                 warning=True)
            return
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if not self.app.restart():
            tell(f"{APP_NAME} {release['version']} is installed. Start {APP_NAME} again to use it.")
            self.app.quit()
