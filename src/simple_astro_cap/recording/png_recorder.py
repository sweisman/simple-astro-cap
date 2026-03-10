"""PNG sequence recorder — writes each frame as an individual PNG file."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase

log = logging.getLogger(__name__)


class PngRecorder(RecorderBase):
    """Saves frames as sequentially numbered PNG files.

    File naming: {YYYY-MM-DD-HH:MM:SS}-{start_sequence:06d}-{sequence:06d}.png
    Sequence is globally monotonic (passed in via start_sequence kwarg).
    Supports 8-bit (mode L) and 16-bit (mode I;16) mono.
    Embeds PNG tEXt metadata per frame.
    """

    def __init__(self) -> None:
        super().__init__()
        self._output_dir: Path | None = None
        self._camera_name: str = ""
        self._telescope: str = ""
        self._start_sequence: int = 0

    def start(self, path: Path, **kwargs: object) -> None:
        max_frames = kwargs.get("max_frames")
        max_duration = kwargs.get("max_duration", 0.0)
        target_fps = kwargs.get("target_fps", 0.0)
        self._camera_name = str(kwargs.get("camera", ""))
        self._telescope = str(kwargs.get("telescope", ""))
        self._start_sequence = int(kwargs.get("start_sequence", 0))

        path.mkdir(parents=True, exist_ok=True)
        self._output_dir = path
        self._begin(
            max_frames=int(max_frames) if max_frames is not None else None,
            max_duration=float(max_duration) if max_duration else 0.0,
            target_fps=float(target_fps) if target_fps else 0.0,
        )
        log.info("PNG recording started: %s", path)

    def stop(self) -> None:
        if self._recording:
            log.info("PNG recording stopped: %d frames written", self._count)
        self._recording = False

    @property
    def end_sequence(self) -> int:
        """Sequence value after all written frames."""
        return self._start_sequence + self._count

    def _write_frame(self, frame: Frame) -> None:
        seq = self._start_sequence + self._count
        timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
        filename = f"{timestamp}-{self._start_sequence:06d}-{seq:06d}.png"
        filepath = self._output_dir / filename  # type: ignore[operator]

        if frame.bit_depth <= 8:
            img = Image.fromarray(frame.data, mode="L")
        else:
            img = Image.fromarray(frame.data.astype(np.uint16), mode="I;16")

        meta = PngInfo()
        meta.add_text("Software", "Simple Astro Cap")
        meta.add_text("Sequence", str(seq))
        meta.add_text("BitDepth", str(frame.bit_depth))
        if frame.timestamp_ns:
            meta.add_text("TimestampNs", str(frame.timestamp_ns))
        if self._target_fps > 0:
            meta.add_text("TargetFPS", f"{self._target_fps:.1f}")
        if self._camera_name:
            meta.add_text("Camera", self._camera_name)
        if self._telescope:
            meta.add_text("Telescope", self._telescope)

        img.save(filepath, pnginfo=meta)

