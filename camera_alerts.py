"""Stable detection alerts and short, non-blocking local sounds."""

from __future__ import annotations

import logging
import threading

try:
    import winsound
except ImportError:
    winsound = None

LOGGER = logging.getLogger(__name__)


class AlertGate:
    """Require consecutive detections; cooldowns use a monotonic clock."""

    def __init__(self, stable_frames=3, animal_interval=10, human_interval=30):
        self.stable_frames = stable_frames
        self.intervals = {"animal": animal_interval, "unknown_human": human_interval}
        self.streaks = {key: 0 for key in self.intervals}
        self.last_sent = {key: -float("inf") for key in self.intervals}

    def observe(self, objects, now, enrolling=False):
        animals = [obj for obj in objects if obj.kind == "animal"]
        # A hidden face cannot be classified as registered or unregistered.
        unknown = [obj for obj in objects if obj.kind == "human" and
                   obj.embedding is not None and obj.profile_id is None]
        present = {"animal": animals, "unknown_human": [] if enrolling else unknown}
        alerts = []
        for kind, detections in present.items():
            self.streaks[kind] = self.streaks[kind] + 1 if detections else 0
            if (self.streaks[kind] >= self.stable_frames and
                    now - self.last_sent[kind] >= self.intervals[kind]):
                self.last_sent[kind] = now
                if kind == "animal":
                    labels = ", ".join(dict.fromkeys(obj.label for obj in detections))
                    message = f"Амьтан илэрлээ: {labels} · {len(detections)} амьтан"
                else:
                    message = f"Бүртгэлгүй хүн илэрлээ · {len(detections)} хүн"
                alerts.append({"kind": kind, "message": message, "count": len(detections)})
        return alerts


class SoundPlayer:
    """One short sound at a time. No sound backlog and no Tk calls in a thread."""

    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    def play(self, kind):
        if self.cancelled.is_set():
            return True
        if winsound is None:
            return False  # Caller may use Tk's bell on the main thread.
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return True
            self.thread = threading.Thread(target=self._play, args=(kind,), name="camera-sound", daemon=True)
            self.thread.start()
        return True

    def _play(self, kind):
        try:
            if kind == "animal":
                for frequency in (1200, 1600):
                    if self.cancelled.is_set():
                        return
                    winsound.Beep(frequency, 160)
                    if self.cancelled.wait(0.06):
                        return
            elif not self.cancelled.is_set():
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            LOGGER.warning("Could not play camera alert sound", exc_info=True)
            if not self.cancelled.is_set():
                try:
                    winsound.MessageBeep()
                except RuntimeError:
                    LOGGER.warning("System notification sound is unavailable")

    def close(self):
        self.cancelled.set()
