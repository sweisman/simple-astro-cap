"""Recorder abstract base class with FPS gating, frame counting, and duration limit."""

from __future__ import annotations

import time
from abc import abstractmethod
from pathlib import Path

from simple_astro_cap.camera.abc import Frame
from simple_astro_cap.pipeline.abc import FrameConsumer


class RecorderBase(FrameConsumer):
    """Base class for frame recorders (PNG sequence, SER file, etc.).

    Provides:
    - FPS-gated frame acceptance (skip frames to approximate target FPS)
    - Max-frames auto-stop
    - Max-duration auto-stop
    - Actual FPS tracking

    Subclasses implement ``_write_frame()`` for format-specific I/O and
    call ``_begin()`` from their ``start()`` method to initialise common state.
    """

    def __init__(self) -> None:
        self._recording = False
        self._count = 0
        self._max_frames: int | None = None
        self._max_duration: float = 0.0
        self._target_fps: float = 0.0
        self._min_interval: float = 0.0
        self._last_accept_time: float = 0.0
        self._rec_start_time: float = 0.0
        self._frames_offered: int = 0
        self._first_sequence: int = -1
        self._last_sequence: int = -1
        self._stop_reason: str = ""

    @abstractmethod
    def start(self, path: Path, **kwargs: object) -> None:
        """Begin recording to the given path."""

    @abstractmethod
    def stop(self) -> None:
        """Finish recording and flush/close files."""

    @abstractmethod
    def _write_frame(self, frame: Frame) -> None:
        """Write a single accepted frame (called after FPS gating)."""

    def is_recording(self) -> bool:
        return self._recording

    def frames_written(self) -> int:
        return self._count

    @property
    def actual_fps(self) -> float:
        """Average FPS since recording started."""
        if self._count == 0:
            return 0.0
        elapsed = time.monotonic() - self._rec_start_time
        return self._count / elapsed if elapsed > 0 else 0.0

    @property
    def target_fps(self) -> float:
        return self._target_fps

    @property
    def elapsed(self) -> float:
        """Seconds since recording started."""
        if self._rec_start_time == 0.0:
            return 0.0
        return time.monotonic() - self._rec_start_time

    def _begin(self, *, max_frames: int | None = None,
               max_duration: float = 0.0,
               target_fps: float = 0.0) -> None:
        """Set up common recording state. Call from subclass ``start()``."""
        self._count = 0
        self._max_frames = max_frames
        self._max_duration = max_duration
        self._target_fps = target_fps
        self._min_interval = (1.0 / target_fps) if target_fps > 0 else 0.0
        self._last_accept_time = 0.0
        self._rec_start_time = time.monotonic()
        self._frames_offered = 0
        self._first_sequence = -1
        self._last_sequence = -1
        self._stop_reason = ""
        self._recording = True

    @property
    def stop_reason(self) -> str:
        """Why recording stopped: 'frame_limit', 'time_limit', or '' (manual)."""
        return self._stop_reason

    @property
    def frames_offered(self) -> int:
        """Total frames delivered to this recorder (before FPS gating)."""
        return self._frames_offered

    @property
    def frames_dropped(self) -> int:
        """Estimated frames lost before reaching this recorder.

        Computed from gaps in the frame sequence numbers.  Returns 0 if
        no sequence data is available.
        """
        if self._first_sequence < 0 or self._last_sequence < 0:
            return 0
        expected = self._last_sequence - self._first_sequence + 1
        return max(0, expected - self._frames_offered)

    def on_frame(self, frame: Frame) -> None:
        if not self._recording:
            return
        if self._max_frames is not None and self._count >= self._max_frames:
            self._stop_reason = "frame_limit"
            self.stop()
            return
        if self._max_duration > 0 and self.elapsed >= self._max_duration:
            self._stop_reason = "time_limit"
            self.stop()
            return
        self._frames_offered += 1
        if self._first_sequence < 0:
            self._first_sequence = frame.sequence
        self._last_sequence = frame.sequence
        if self._min_interval > 0:
            now = time.monotonic()
            if (now - self._last_accept_time) < self._min_interval:
                return
            self._last_accept_time = now
        self._write_frame(frame)
        self._count += 1
