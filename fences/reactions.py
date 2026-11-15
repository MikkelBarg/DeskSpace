"""Pets react to what the computer is doing: a hard-working CPU, a finished download, music starting,
and a battery running low. Each reaction is a speech bubble (and a hop for the important ones), and
none repeats too often. Only the battery is important enough to float over your apps.

Nothing new is installed or run for this: the CPU is sampled every few seconds, the Downloads folder
is watched for files that finish arriving, music comes from the Media controls widget (when there is
one), and the battery from the system's own battery level.
"""
import random
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer

from .common import is_hidden

DOWNLOADS = Path.home() / "Downloads"
IN_PROGRESS = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")
BUSY_CPU = 85  # percent
BUSY_FOR = 30  # seconds the CPU has to stay busy
LOW_BATTERY = 15  # percent
QUIET = {"cpu": 30 * 60, "download": 20, "music": 10 * 60}  # seconds before the same reaction again


class PetReactions(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.last = {}  # reaction -> when it last happened
        self.busy_since = None
        self.battery_warned = False
        self.playing = False
        psutil.cpu_percent(None)
        self.cpu_timer = QTimer(self, interval=5000, timeout=self.check_cpu)
        self.battery_timer = QTimer(self, interval=60000, timeout=self.check_battery)
        self.downloads = set(self.list_downloads())
        self.download_timer = QTimer(self, singleShot=True, interval=2500, timeout=self.check_downloads)
        self.watcher = QFileSystemWatcher(self)
        if DOWNLOADS.is_dir():
            self.watcher.addPath(str(DOWNLOADS))
        self.watcher.directoryChanged.connect(lambda _: self.download_timer.start())
        app.media.updated.connect(self.on_media)
        self.cpu_timer.start()
        self.battery_timer.start()

    # -- who reacts

    def enabled(self):
        app = self.app
        return app.pet_enabled and app.pet_reactions and app.pet_windows and not app.hidden

    def pets(self, awake_only=True):
        pets = [p for p in self.app.pet_windows if p.isVisible()]
        awake = [p for p in pets if p.state not in ("sleep", "held")]
        return awake if awake_only else pets

    def react(self, key, text, important=False, everyone=False):
        """One pet (or all of them) says `text`, unless this reaction happened too recently."""
        now = time.monotonic()
        if not self.enabled() or now - self.last.get(key, -1e9) < QUIET.get(key, 0):
            return False
        pets = self.pets(awake_only=not important)
        if not pets:
            return False
        self.last[key] = now
        chosen = pets if everyone else [random.choice(pets)]
        for i, pet in enumerate(chosen):
            pet.announce(text if i == 0 else "!", on_top=important, ticks=160)
            if not important and pet.state in ("idle", "walk", "sit"):
                pet.vy, pet.vx = -5.0, 0.0  # a happy little hop
                pet.set_state("jump")
        return True

    # -- the computer

    def check_cpu(self):
        cpu = psutil.cpu_percent(None)
        if cpu < BUSY_CPU:
            self.busy_since = None
            return
        now = time.monotonic()
        self.busy_since = self.busy_since or now
        if now - self.busy_since >= BUSY_FOR:
            self.react("cpu", random.choice(["Phew, the computer is working hard!", "Something's keeping the CPU busy…",
                                             "It's getting warm in here!"]))
            self.busy_since = None

    def list_downloads(self):
        try:
            return [p.name for p in DOWNLOADS.iterdir() if p.is_file() and not is_hidden(p)]
        except OSError:
            return []

    def check_downloads(self):
        names = set(self.list_downloads())
        new = [n for n in names - self.downloads if not n.lower().endswith(IN_PROGRESS) and not n.startswith("~$")]
        self.downloads = names
        if new:
            name = max(new, key=lambda n: (DOWNLOADS / n).stat().st_mtime if (DOWNLOADS / n).exists() else 0)
            short = name if len(name) <= 40 else name[:37] + "…"
            more = f" (and {len(new) - 1} more)" if len(new) > 1 else ""
            self.react("download", f"Your download is ready: {short}{more}")

    def on_media(self, state):
        playing = bool(state and state.get("playing"))
        if playing and not self.playing:
            self.react("music", random.choice(["♪ ♫", "Ooh, I like this one! ♪", "♫ Dance time! ♫"]), everyone=True)
        self.playing = playing

    def check_battery(self):
        try:
            battery = psutil.sensors_battery()
        except (OSError, AttributeError, NotImplementedError):
            battery = None
        if battery is None:
            return
        if battery.power_plugged or battery.percent > LOW_BATTERY + 5:
            self.battery_warned = False  # charging, or charged up again: warn next time it runs low
            return
        if battery.percent <= LOW_BATTERY and not self.battery_warned:
            self.battery_warned = self.react("battery", f"The battery is at {battery.percent:.0f} % - time to charge!",
                                             important=True)
