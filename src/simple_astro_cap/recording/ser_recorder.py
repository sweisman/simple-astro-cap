"""SER file recorder.

SER format specification:
  - 178-byte header
  - Raw pixel data (frame after frame)
  - Optional trailer: array of int64 timestamps (one per frame)

Reference: https://free-astro.org/index.php/SER
"""

from __future__ import annotations

import logging
import struct
import time
from pathlib import Path

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase

log = logging.getLogger(__name__)

# SER header constants
_FILE_ID = b"LUCAM-RECORDER"
_COLOR_MONO = 0

# Windows FILETIME epoch offset: 100-nanosecond intervals from 1601-01-01 to 1970-01-01
_EPOCH_OFFSET = 116444736000000000


def _unix_to_filetime(unix_ns: int) -> int:
    """Convert Unix nanoseconds to Windows FILETIME (100ns ticks since 1601)."""
    unix_100ns = unix_ns // 100
    return unix_100ns + _EPOCH_OFFSET


def _now_filetime() -> int:
    return _unix_to_filetime(int(time.time() * 1_000_000_000))


class SerRecorder(RecorderBase):
    """Records frames to a SER file.

    The header's FrameCount field is patched on stop() since we don't
    know the final count upfront.  Per-frame timestamps in the trailer
    encode actual capture timing (from which actual FPS is derivable).
    """

    def __init__(self) -> None:
        super().__init__()
        self._file = None
        self._timestamps: list[int] = []
        self._observer = ""
        self._camera_name = ""
        self._telescope = ""

    def start(self, path: Path, **kwargs: object) -> None:
        observer = str(kwargs.get("observer", ""))
        camera_name = str(kwargs.get("camera", ""))
        telescope = str(kwargs.get("telescope", ""))
        bit_depth = int(kwargs.get("bit_depth", 8))
        width = int(kwargs.get("width", 0))
        height = int(kwargs.get("height", 0))
        max_frames = kwargs.get("max_frames")
        max_duration = kwargs.get("max_duration", 0.0)
        target_fps = kwargs.get("target_fps", 0.0)

        self._observer = observer
        self._camera_name = camera_name
        self._telescope = telescope
        self._timestamps = []

        # Ensure .ser extension
        if path.suffix.lower() != ".ser":
            path = path.with_suffix(".ser")

        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "wb")

        now = _now_filetime()
        header = self._pack_header(
            width=width,
            height=height,
            bit_depth=bit_depth,
            frame_count=0,  # patched on stop
            datetime_local=now,
            datetime_utc=now,
        )
        self._file.write(header)

        self._begin(
            max_frames=int(max_frames) if max_frames is not None else None,
            max_duration=float(max_duration) if max_duration else 0.0,
            target_fps=float(target_fps) if target_fps else 0.0,
        )
        log.info("SER recording started: %s (%dx%d %d-bit)", path, width, height, bit_depth)

    def stop(self) -> None:
        if not self._recording:
            return
        self._recording = False
        if self._file is not None:
            # Write timestamp trailer
            for ts in self._timestamps:
                self._file.write(struct.pack("<q", ts))
            # Patch frame count at offset 38
            self._file.seek(38)
            self._file.write(struct.pack("<I", self._count))
            self._file.close()
            self._file = None
        log.info("SER recording stopped: %d frames", self._count)

    def _write_frame(self, frame: Frame) -> None:
        if self._file is None:
            return
        self._file.write(frame.data.tobytes())
        self._timestamps.append(_now_filetime())

    def _pack_header(
        self,
        width: int,
        height: int,
        bit_depth: int,
        frame_count: int,
        datetime_local: int,
        datetime_utc: int,
    ) -> bytes:
        """Pack the 178-byte SER header."""
        header = bytearray(178)
        # FileId (14 bytes)
        header[0:14] = _FILE_ID
        # LuID (4 bytes) = 0
        struct.pack_into("<I", header, 14, 0)
        # ColorID (4 bytes) = MONO
        struct.pack_into("<I", header, 18, _COLOR_MONO)
        # LittleEndian (4 bytes) — 0 means little-endian in practice
        struct.pack_into("<I", header, 22, 0)
        # ImageWidth
        struct.pack_into("<I", header, 26, width)
        # ImageHeight
        struct.pack_into("<I", header, 30, height)
        # PixelDepthPerPlane
        struct.pack_into("<I", header, 34, bit_depth)
        # FrameCount
        struct.pack_into("<I", header, 38, frame_count)
        # Observer (40 bytes, padded)
        obs = self._observer.encode("ascii", errors="replace")[:40]
        header[42 : 42 + len(obs)] = obs
        # Instrument (40 bytes, padded)
        inst = self._camera_name.encode("ascii", errors="replace")[:40]
        header[82 : 82 + len(inst)] = inst
        # Telescope (40 bytes, padded)
        tel = self._telescope.encode("ascii", errors="replace")[:40]
        header[122 : 122 + len(tel)] = tel
        # DateTime (local)
        struct.pack_into("<q", header, 162, datetime_local)
        # DateTime_UTC
        struct.pack_into("<q", header, 170, datetime_utc)
        return bytes(header)
