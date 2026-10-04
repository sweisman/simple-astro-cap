from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simple_astro_cap.camera.abc import Frame  # noqa: E402

# Fixed, deliberately irregular capture times (ns): 0, 25, 60, 61, 140 ms.
BASE_UTC_NS = 1_760_000_000_000_000_000
OFFSETS_MS = [0, 25, 60, 61, 140]


def make_frame(seq: int, *, w: int = 8, h: int = 4, bits: int = 16,
               mono_ns: int = 0, utc_ns: int = BASE_UTC_NS) -> Frame:
    """A frame whose pixels encode its sequence number unmistakably."""
    dtype = np.uint16 if bits > 8 else np.uint8
    data = (np.arange(w * h, dtype=np.uint32).reshape(h, w) + seq * 1000)
    data = (data % (65536 if bits > 8 else 256)).astype(dtype)
    return Frame(data=data, width=w, height=h, bit_depth=bits,
                 capture_mono_ns=mono_ns, capture_utc_ns=utc_ns, sequence=seq)


@pytest.fixture
def irregular_frames():
    def _make(bits: int = 16):
        return [make_frame(i + 1, bits=bits,
                           mono_ns=ms * 1_000_000,
                           utc_ns=BASE_UTC_NS + ms * 1_000_000)
                for i, ms in enumerate(OFFSETS_MS)]
    return _make
