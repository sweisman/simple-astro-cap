"""MKV recorder — lossless FFV1 video via ffmpeg subprocess."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase

log = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    """Check whether ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


class MkvRecorder(RecorderBase):
    """Records frames as lossless FFV1 video in an MKV container.

    Spawns an ffmpeg subprocess and pipes raw pixel data to its stdin.
    Supports 8-bit (gray) and 16-bit (gray16le) mono frames.
    """

    def __init__(self) -> None:
        super().__init__()
        self._proc: subprocess.Popen | None = None
        self._path: Path | None = None

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

        # Ensure .mkv extension
        if path.suffix.lower() != ".mkv":
            path = path.with_suffix(".mkv")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

        pix_fmt = "gray16le" if bit_depth > 8 else "gray"

        # Use target FPS for the output file's frame rate metadata.
        # If 0 (max rate), default to 25 — ffmpeg requires a rate,
        # and the actual timing is best-effort anyway.
        output_fps = float(target_fps) if target_fps and float(target_fps) > 0 else 25.0

        cmd = [
            "ffmpeg",
            "-y",                           # overwrite
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

        cmd.append(str(path))

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
        )
        log.info("MKV recording started: %s (%dx%d %d-bit FFV1)", path, width, height, bit_depth)

    def stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=10)
                if self._proc.returncode != 0:
                    stderr = self._proc.stderr.read().decode(errors="replace")
                    log.warning("ffmpeg exited with code %d: %s",
                                self._proc.returncode, stderr[-500:])
            except Exception as e:
                log.warning("Error closing ffmpeg: %s", e)
                self._proc.kill()
            finally:
                self._proc = None
        log.info("MKV recording stopped: %d frames written to %s", self._count, self._path)

    def _write_frame(self, frame: Frame) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(frame.data.tobytes())
        except BrokenPipeError:
            log.error("ffmpeg pipe broken — stopping recording")
            self._recording = False
