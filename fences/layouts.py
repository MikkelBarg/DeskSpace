"""Layout profiles: where the fences were for each monitor setup (laptop alone, laptop with a TV, ...).

Every save also notes the fences' positions under the setup that's connected now. When a screen is
plugged in or removed, we wait for the change to settle, and if that setup was seen before its fences
go back where they were; otherwise any fence left off-screen is brought back. Nothing is noted while
screens are changing, so the window system shuffling fences around isn't mistaken for a new layout.
"""
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

SETTLE_MS = 3000


def signature(screens=None):
    """A key for the connected monitors: each one's name, size and position."""
    screens = QGuiApplication.screens() if screens is None else screens
    parts = []
    for s in screens:
        g = s.geometry()
        parts.append(f"{s.name()} {g.width()}x{g.height()}+{g.x()}+{g.y()}")
    return " | ".join(sorted(parts))


def describe(sig):
    """'2 screens: 1920×1080 + 3840×2160' for a signature."""
    sizes = [part.split(" ")[-1].split("+")[0].replace("x", "×") for part in sig.split(" | ") if part]
    return f"{len(sizes)} screen{'s' if len(sizes) != 1 else ''}: " + " + ".join(sizes)


class LayoutProfiles(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.changing = False  # screens are being added or removed; don't note positions until settled
        self.current = app.layout_last or signature()
        self.timer = QTimer(self, singleShot=True, interval=SETTLE_MS, timeout=self.settle)
        qapp = QGuiApplication.instance()
        qapp.screenAdded.connect(lambda screen: (self.watch(screen), self.screens_changing()))
        qapp.screenRemoved.connect(self.screens_changing)
        for screen in qapp.screens():
            self.watch(screen)

    def watch(self, screen):
        screen.geometryChanged.connect(self.screens_changing)

    def screens_changing(self, *_):
        self.changing = True
        self.timer.start()

    def settle(self):
        """The screens have stopped changing: put the fences where they were for this setup."""
        self.changing = False
        now = signature()
        if now != self.current:
            self.current = now
            profile = self.app.layouts.get(now) if self.app.layout_profiles else None
            if profile:
                self.apply(profile)
        self.app.rescue_offscreen()
        self.app.save()

    def record(self):
        """Note where the fences are for the current setup (called with every save)."""
        if self.changing or not self.app.layout_profiles:
            return
        panels = {}
        for panel in self.app.fences:
            g = panel.geometry()
            panels[panel.id] = [g.x(), g.y(), g.width(), panel.full_h]
        self.app.layouts[self.current] = {"seen": int(time.time()), "panels": panels}
        self.app.layout_last = self.current

    def apply(self, profile):
        saved = profile.get("panels", {})
        for panel in self.app.fences:
            if panel.id not in saved:
                continue
            x, y, w, h = saved[panel.id]
            panel.full_h = h
            panel.setGeometry(x, y, w, panel.title_h if panel.rolled else h)

    def forget(self, sig):
        self.app.layouts.pop(sig, None)
        self.app.schedule_save()
