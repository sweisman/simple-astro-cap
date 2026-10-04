"""MKV recorder — lossless FFV1 video via ffmpeg subprocess."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase, check_free_space

log = logging.getLogger(__name__)


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
            # Keep stderr quiet: it is only drained at stop(), and a full pipe
            # would block ffmpeg, back up stdin, and hang the worker thread.
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

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

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
            self._close_proc()
            self._apply_timestamps()
        log.info("MKV recording stopped: %d frames written to %s", self._count, self._path)

    @property
    def timestamps_path(self) -> Path | None:
        return self._path.with_suffix(".timestamps.txt") if self._path else None

    def _apply_timestamps(self) -> None:
        """Write the v2 timestamps file and remux the part file with it."""
        part, final, ts_path = self._part_path, self._path, self.timestamps_path
        if part is None or final is None or ts_path is None or not part.exists():
            return
        if not self._capture_mono_ns:
            part.unlink(missing_ok=True)
            return
        t0 = self._capture_mono_ns[0]
        lines = ["# timestamp format v2"]
        lines += [f"{(t - t0) / 1e6:.6f}" for t in self._capture_mono_ns]
        try:
            ts_path.write_text("\n".join(lines) + "\n")
            result = subprocess.run(
                ["mkvmerge", "--quiet", "-o", str(final),
                 "--timestamps", f"0:{ts_path}", str(part)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("Could not apply MKV timestamps (%s); untimed video kept at %s", e, part)
            return
        # mkvmerge: 0 = ok, 1 = warnings (output still written), 2 = error
        if result.returncode >= 2:
            log.error("mkvmerge failed (%d): %s; untimed video kept at %s",
                      result.returncode, result.stdout.decode(errors="replace")[-500:], part)
            final.unlink(missing_ok=True)
            return
        part.unlink(missing_ok=True)

    def _close_proc(self) -> None:
        """Close ffmpeg's stdin and reap it; kill on timeout. Idempotent."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
            proc.wait(timeout=10)
            if proc.returncode != 0:
                stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                log.warning("ffmpeg exited with code %d: %s", proc.returncode, stderr[-500:])
        except Exception as e:
            log.warning("Error closing ffmpeg: %s", e)
            proc.kill()
            proc.wait(timeout=5)

    def _write_frame(self, frame: Frame) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        # A broken pipe (ffmpeg died, e.g. disk full) propagates as OSError;
        # RecorderBase puts the recorder into its error state.
        self._proc.stdin.write(memoryview(np.ascontiguousarray(frame.data)))
        self._capture_mono_ns.append(frame.capture_mono_ns)
