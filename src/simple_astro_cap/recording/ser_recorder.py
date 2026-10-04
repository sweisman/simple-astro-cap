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

import numpy as np

from simple_astro_cap.camera.abc import Frame

from .abc import RecorderBase, check_free_space

log = logging.getLogger(__name__)

# SER header constants
_FILE_ID = b"LUCAM-RECORDER"
_COLOR_MONO = 0

# SER v3 ColorID values for Bayer patterns (16/17 are CYYM/YCMY, not Bayer)
_BAYER_COLOR_ID = {
    "RGGB": 8,
    "GRBG": 9,
    "GBRG": 10,
    "BGGR": 11,
}

# SER timestamps are .NET DateTime ticks: 100-nanosecond intervals since
# 0001-01-01 00:00:00. Offset from the Unix epoch (1970-01-01).
_EPOCH_OFFSET = 621355968000000000


def _unix_to_ticks(unix_ns: int) -> int:
    """Convert Unix nanoseconds to .NET ticks (100ns since 0001-01-01)."""
    return unix_ns // 100 + _EPOCH_OFFSET


def _now_ticks_utc() -> int:
    return _unix_to_ticks(time.time_ns())


def _now_ticks_local() -> int:
    """UTC ticks shifted by the current local UTC offset (SER DateTime field)."""
    return _now_ticks_utc() + time.localtime().tm_gmtoff * 10_000_000


class SerRecorder(RecorderBase):
    """Records frames to a SER file.

    The header's FrameCount field is patched on stop() since we don't
    know the final count upfront.  Per-frame timestamps in the trailer
    are each frame's ``capture_utc_ns`` (stamped when the SDK handed the
    frame over), so disk stalls do not skew them.
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
        bayer_pattern = str(kwargs.get("bayer_pattern", ""))
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
        check_free_space(path.parent)
        self._file = open(path, "wb")

        color_id = _BAYER_COLOR_ID.get(bayer_pattern, _COLOR_MONO)
        header = self._pack_header(
            width=width,
            height=height,
            bit_depth=bit_depth,
            color_id=color_id,
            frame_count=0,  # patched on stop
            datetime_local=_now_ticks_local(),
            datetime_utc=_now_ticks_utc(),
        )
        self._file.write(header)

        self._begin(
            max_frames=int(max_frames) if max_frames is not None else None,
            max_duration=float(max_duration) if max_duration else 0.0,
            target_fps=float(target_fps) if target_fps else 0.0,
            space_path=path.parent,
        )
        log.info("SER recording started: %s (%dx%d %d-bit)", path, width, height, bit_depth)

    def stop(self) -> None:
        with self._lock:  # never interleave with a frame write on the worker
            if not self._recording:
                return
            self._recording = False
            if self._file is not None:
                try:
                    # Patch frame count at offset 38 first: if the trailer
                    # cannot be written (disk full), the frames still read.
                    end = self._file.tell()
                    self._file.seek(38)
                    self._file.write(struct.pack("<I", self._count))
                    self._file.seek(end)
                    self._file.write(struct.pack(f"<{len(self._timestamps)}q", *self._timestamps))
                finally:
                    self._file.close()
                    self._file = None
        log.info("SER recording stopped: %d frames", self._count)

    def _write_frame(self, frame: Frame) -> None:
        if self._file is None:
            return
        pos = self._file.tell()
        try:
            self._file.write(memoryview(np.ascontiguousarray(frame.data)))  # no 24 MB copy
            self._file.flush()  # surface ENOSPC on this frame, not a later one
        except OSError:
            # Drop the partial frame so the trailer stays aligned.
            self._file.seek(pos)
            self._file.truncate()
            raise
        self._timestamps.append(_unix_to_ticks(frame.capture_utc_ns))

    def _pack_header(
        self,
        width: int,
        height: int,
        bit_depth: int,
        color_id: int,
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
        # ColorID (4 bytes) — 0=MONO, 8=RGGB, 9=GRBG, 10=GBRG, 11=BGGR
        struct.pack_into("<I", header, 18, color_id)
        # LittleEndian (4 bytes). The spec says 1 = little-endian, but the
        # de-facto convention (FireCapture, SharpCap; honoured by AS!3, Siril,
        # PIPP) is the reverse: 0 marks the little-endian data we write.
        # Deliberate — do not "fix" without an interop check.
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
