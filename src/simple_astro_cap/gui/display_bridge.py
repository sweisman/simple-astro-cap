"""Thread-safe bridge from pipeline worker thread to Qt GUI."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from simple_astro_cap.camera.abc import Frame


class DisplayBridge(QObject):
    """Receives frames on the worker thread, emits a Qt signal for the GUI.

    The signal is emitted via Qt's queued connection mechanism, so
    the slot runs on the main thread.

    Implements the FrameConsumer protocol (on_frame) without inheriting
    from it, to avoid metaclass conflict with QObject.
    """

    frame_ready = Signal(object)  # Frame

    def on_frame(self, frame: Frame) -> None:
        self.frame_ready.emit(frame)
