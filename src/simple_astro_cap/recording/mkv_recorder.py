"""MKV recorder — lossless FFV1 video via ffmpeg subprocess."""

from __future__ import annotations

import logging
import os
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase, check_free_space

log = logging.getLogger(__name__)

_IO_TIMEOUT_S = 10.0
_REMUX_TIMEOUT_S = 600.0


def ffmpeg_available() -> bool:
    """Check whether ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def mkvmerge_available() -> bool:
    """Check whether mkvmerge (mkvtoolnix) is on PATH."""
    return shutil.which("mkvmerge") is not None


class MkvRecorder(RecorderBase):
    """Records frames as lossless FFV1 video in an MKV container.

    Spawns an ffmpeg subprocess and pipes raw pixel data to its stdin.
    Supports 8-bit (gray) and 16-bit (gray16le) mono frames.

    A rawvideo pipe cannot carry per-frame timestamps, so ffmpeg encodes
    to a temporary ``.part.mkv`` at a nominal rate while each frame's
    capture time is collected. On stop the capture times are written as a
    Matroska v2 timestamps file (``<name>.timestamps.txt``, kept as
    provenance) and ``mkvmerge`` remuxes the video with them, so the
    file's timeline is the real capture cadence rather than an assumed fps.
    """

    def __init__(self) -> None:
        super().__init__()
        self._proc: subprocess.Popen | None = None
        self._path: Path | None = None
        self._part_path: Path | None = None
        self._capture_mono_ns: list[int] = []
        self._stderr = None

    def start(self, path: Path, **kwargs: object) -> None:
        width = int(kwargs.get("width", 0))
        height = int(kwargs.get("height", 0))
        bit_depth = int(kwargs.get("bit_depth", 8))
        max_frames = kwargs.get("max_frames")
        max_duration = kwargs.get("max_duration", 0.0)
        target_fps = kwargs.get("target_fps", 0.0)
        camera = str(kwargs.get("camera", ""))
        telescope = str(kwargs.get("telescope", ""))
        bayer_pattern = str(kwargs.get("bayer_pattern", ""))

        if not ffmpeg_available():
            raise RuntimeError("ffmpeg not found on PATH")
        if not mkvmerge_available():
            raise RuntimeError("mkvmerge not found on PATH (install mkvtoolnix) — "
                               "needed to write real per-frame timestamps")

        # Ensure .mkv extension
        if path.suffix.lower() != ".mkv":
            path = path.with_suffix(".mkv")
        path.parent.mkdir(parents=True, exist_ok=True)
        check_free_space(path.parent)
        self._path = path
        self._part_path = path.with_suffix(".part.mkv")
        self._capture_mono_ns = []

        pix_fmt = "gray16le" if bit_depth > 8 else "gray"

        # Nominal rate only — the real per-frame timestamps replace it at
        # stop(). ffmpeg requires some rate for rawvideo input.
        output_fps = float(target_fps) if target_fps and float(target_fps) > 0 else 25.0

        cmd = [
            "ffmpeg",
            "-y",                           # overwrite
            # Keep the temporary diagnostic file small during long recordings.
            "-hide_banner", "-nostats", "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", pix_fmt,
            "-s", f"{width}x{height}",
            "-r", str(output_fps),
            "-i", "pipe:0",                 # stdin
            "-c:v", "ffv1",
            "-level", "3",                  # FFV1 version 3 (multithreaded, checksums)
            "-g", "1",                      # every frame is a keyframe (for seekability)
        ]

        # Embed metadata
        cmd += ["-metadata", "encoder=Simple Astro Cap"]
        if camera:
            cmd += ["-metadata", f"artist={camera}"]
        if telescope:
            cmd += ["-metadata", f"comment={telescope}"]
        if bayer_pattern:
            cmd += ["-metadata", f"bayer_pattern={bayer_pattern}"]

        cmd.append(str(self._part_path))

        # A file cannot fill a stderr pipe and deadlock the encoder. Unbuffered,
        # nonblocking stdin lets us cancel a stalled write without its lock.
        self._stderr = tempfile.TemporaryFile()
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._stderr, bufsize=0,
            )
            os.set_blocking(self._proc.stdin.fileno(), False)
        except Exception:
            if self._proc is not None:
                self._proc.kill()
                self._proc.wait(timeout=5)
                self._proc = None
            self._stderr.close()
            self._stderr = None
            raise

        self._begin(
            max_frames=int(max_frames) if max_frames is not None else None,
            max_duration=float(max_duration) if max_duration else 0.0,
            target_fps=float(target_fps) if target_fps else 0.0,
            space_path=path.parent,
        )
        log.info("MKV recording started: %s (%dx%d %d-bit FFV1)", path, width, height, bit_depth)

    def stop(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            try:
                self._close_proc()
                self._apply_timestamps()
            except Exception as exc:
                previous = f"{self.error}; " if self.error is not None else ""
                recovery = self.recovery_path
                detail = f" Recovery file (may be incomplete): {recovery}" if recovery else ""
                self.report_error(RuntimeError(f"{previous}MKV finalization failed: {exc}.{detail}"))
                log.error("%s", self.error)
        log.info("MKV recording stopped: %d frames written to %s", self._count, self._path)

    @property
    def timestamps_path(self) -> Path | None:
        return self._path.with_suffix(".timestamps.txt") if self._path else None

    @property
    def recovery_path(self) -> Path | None:
        return self._part_path if self._part_path and self._part_path.exists() else None

    def _apply_timestamps(self) -> None:
        """Write the v2 timestamps file and remux the part file with it."""
        part, final, ts_path = self._part_path, self._path, self.timestamps_path
        if part is None or final is None or ts_path is None or not part.exists():
            raise RuntimeError("Encoder did not create its output file")
        if not self._capture_mono_ns:
            part.unlink(missing_ok=True)
            return
        t0 = self._capture_mono_ns[0]
        lines = ["# timestamp format v2"]
        lines += [f"{(t - t0) / 1e6:.6f}" for t in self._capture_mono_ns]
        try:
            ts_path.write_text("\n".join(lines) + "\n")
            proc = subprocess.Popen(
                ["mkvmerge", "--quiet", "-o", str(final),
                 "--timestamps", f"0:{ts_path}", str(part)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + _REMUX_TIMEOUT_S
            try:
                while True:
                    if self._cancel_io.is_set() or time.monotonic() >= deadline:
                        raise TimeoutError("MKV remux cancelled or timed out")
                    try:
                        output, _ = proc.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=5)
            # mkvmerge: 0 = ok, 1 = warnings, everything else is failure.
            if proc.returncode not in (0, 1):
                raise RuntimeError(f"mkvmerge exited {proc.returncode}: "
                                   f"{output.decode(errors='replace')[-500:]}")
            if not final.exists():
                raise RuntimeError("mkvmerge did not create the final file")
        except Exception:
            final.unlink(missing_ok=True)
            raise
        part.unlink(missing_ok=True)

    def _close_proc(self) -> None:
        """Close ffmpeg's stdin and reap it; kill on timeout. Idempotent."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # unbuffered: no blocking flush
            deadline = time.monotonic() + _IO_TIMEOUT_S
            while proc.poll() is None:
                if self._cancel_io.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("ffmpeg shutdown cancelled or timed out")
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue
            if proc.returncode != 0:
                stderr = ""
                if self._stderr is not None:
                    self._stderr.seek(0, os.SEEK_END)
                    self._stderr.seek(max(0, self._stderr.tell() - 500))
                    stderr = self._stderr.read().decode(errors="replace")
                raise RuntimeError(f"ffmpeg exited {proc.returncode}: {stderr}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            if self._stderr is not None:
                self._stderr.close()
                self._stderr = None

    def _write_frame(self, frame: Frame) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("ffmpeg is not running")
        data = memoryview(np.ascontiguousarray(frame.data)).cast("B")
        fd = self._proc.stdin.fileno()
        deadline = time.monotonic() + _IO_TIMEOUT_S
        while data:
            if self._cancel_io.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("ffmpeg frame write cancelled or timed out")
            if not select.select([], [fd], [], 0.1)[1]:
                continue
            try:
                written = os.write(fd, data)
            except BlockingIOError:
                continue
            if written == 0:
                raise BrokenPipeError("ffmpeg accepted no frame data")
            data = data[written:]
        self._capture_mono_ns.append(frame.capture_mono_ns)
