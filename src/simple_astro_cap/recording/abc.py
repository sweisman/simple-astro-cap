"""Recorder abstract base class with FPS gating, frame counting, and duration limit."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from simple_astro_cap.camera.abc import Frame
from simple_astro_cap.pipeline.abc import FrameConsumer

log = logging.getLogger(__name__)

# Refuse to start, and stop cleanly while recording, below this much free
# space — a recorder that runs the disk dry produces a truncated file and
# can take the OS down with it on small field machines.
MIN_FREE_BYTES = 512 * 1024 * 1024
_SPACE_CHECK_INTERVAL = 2.0  # seconds


def utc_iso(unix_ns: int) -> str:
    """Format a Unix-epoch nanosecond stamp as ISO 8601 UTC with microseconds."""
    return datetime.fromtimestamp(unix_ns / 1e9, tz=timezone.utc).isoformat(timespec="microseconds")


def check_free_space(path: Path) -> None:
    """Raise OSError if the filesystem holding ``path`` is below MIN_FREE_BYTES."""
    free = shutil.disk_usage(path).free
    if free < MIN_FREE_BYTES:
        raise OSError(f"Only {free // (1024 * 1024)} MB free on {path}; "
                      f"need at least {MIN_FREE_BYTES // (1024 * 1024)} MB to record")


class RecorderBase(FrameConsumer):
    """Base class for frame recorders (PNG sequence, SER file, etc.).

    Provides:
    - FPS-gated frame acceptance (skip frames to approximate target FPS)
    - Max-frames auto-stop
    - Max-duration auto-stop
    - Actual FPS tracking
    - Low-disk auto-stop and an error state: a failed write finalises the
      file and stops the recorder instead of silently failing every frame

    Subclasses implement ``_write_frame()`` for format-specific I/O and
    call ``_begin()`` from their ``start()`` method to initialise common state.
    """

    def __init__(self) -> None:
        # Held across on_frame (worker thread) and stop() (GUI thread) so a
        # frame write can never interleave with finalising the file. RLock
        # because on_frame calls stop() for auto-stop.
        self._lock = threading.RLock()
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
        self._error: BaseException | None = None
        self._space_path: Path | None = None
        self._last_space_check: float = 0.0

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
               target_fps: float = 0.0,
               space_path: Path | None = None) -> None:
        """Set up common recording state. Call from subclass ``start()``.

        ``space_path`` is any path on the destination filesystem; when given,
        free space is re-checked periodically and recording stops cleanly
        with reason ``'disk_low'`` before the disk fills.
        """
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
        self._error = None
        self._space_path = space_path
        self._last_space_check = self._rec_start_time
        self._recording = True

    @property
    def stop_reason(self) -> str:
        """Why recording stopped: 'frame_limit', 'time_limit', 'disk_low',
        'error' (see ``error``), or '' (manual)."""
        return self._stop_reason

    @property
    def error(self) -> BaseException | None:
        """The write failure that stopped this recording, if any."""
        return self._error

    @property
    def frames_offered(self) -> int:
        """Total frames delivered to this recorder (before FPS gating)."""
        return self._frames_offered

    @property
    def frames_dropped(self) -> int:
        """Frames received from the SDK that never reached this recorder.

        Computed from gaps in the host-side frame sequence. This does NOT
        include frames the SDK/camera dropped before handing them over —
        see ``CameraBase.sdk_dropped_frames()`` and the harness queue
        overflow counter for those.
        """
        if self._first_sequence < 0 or self._last_sequence < 0:
            return 0
        expected = self._last_sequence - self._first_sequence + 1
        return max(0, expected - self._frames_offered)

    def on_frame(self, frame: Frame) -> None:
        with self._lock:
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
            if self._space_path is not None and self._space_low():
                log.error("Free space below %d MB; stopping recording",
                          MIN_FREE_BYTES // (1024 * 1024))
                self._stop_reason = "disk_low"
                self.stop()
                return
            try:
                self._write_frame(frame)
            except Exception as exc:
                self._fail(exc)
                return
            self._count += 1

    def _space_low(self) -> bool:
        now = time.monotonic()
        if now - self._last_space_check < _SPACE_CHECK_INTERVAL:
            return False
        self._last_space_check = now
        try:
            return shutil.disk_usage(self._space_path).free < MIN_FREE_BYTES  # type: ignore[arg-type]
        except OSError:
            return False

    def _fail(self, exc: BaseException) -> None:
        """Enter the error state: remember why, finalise what was written."""
        log.error("Recording write failed after %d frames: %s", self._count, exc)
        self._error = exc
        self._stop_reason = "error"
        try:
            self.stop()
        except Exception:
            log.exception("Finalising recording after write failure also failed")
            self._recording = False
