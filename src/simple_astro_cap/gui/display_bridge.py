"""Thread-safe bridge from pipeline capture thread to Qt GUI."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from simple_astro_cap.camera.abc import Frame


class DisplayBridge(QObject):
    """One-frame mailbox between the capture thread and the GUI.

    ``on_frame`` (capture thread) replaces the latest frame and emits
    ``frame_ready`` only if the GUI has not yet collected the previous one,
    so at most one update is ever queued in Qt's event loop no matter how
    far the GUI falls behind. The slot calls ``take()`` to get the newest
    frame.

    ``request_snapshot()`` arms a one-shot: the next frame acquired after
    the request is delivered via ``snapshot_ready``.

    Implements the FrameConsumer protocol (on_frame) without inheriting
    from it, to avoid metaclass conflict with QObject.
    """

    frame_ready = Signal()
    snapshot_ready = Signal(object)  # Frame

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._pending = False
        self._snapshot_armed = False

    def on_frame(self, frame: Frame) -> None:
        with self._lock:
            self._latest = frame
            notify = not self._pending
            self._pending = True
            snap = self._snapshot_armed
            self._snapshot_armed = False
        if snap:
            self.snapshot_ready.emit(frame)
        if notify:
            self.frame_ready.emit()

    def take(self) -> Frame | None:
        """Return the newest frame (GUI thread) and re-open the mailbox."""
        with self._lock:
            frame, self._latest = self._latest, None
            self._pending = False
        return frame

    def request_snapshot(self) -> None:
        with self._lock:
            self._snapshot_armed = True

    def cancel_snapshot(self) -> None:
        with self._lock:
            self._snapshot_armed = False
