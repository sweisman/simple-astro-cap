from __future__ import annotations

import errno
import struct

import numpy as np
import pytest

from simple_astro_cap.recording import abc as rec_abc
from simple_astro_cap.recording.ser_recorder import SerRecorder, _unix_to_ticks

HEADER = 178


def _read_ser(path):
    raw = path.read_bytes()
    hdr = raw[:HEADER]
    assert hdr[:14] == b"LUCAM-RECORDER"
    color_id, little_endian, w, h, depth, count = struct.unpack_from("<6I", hdr, 18)
    bpp = 2 if depth > 8 else 1
    frame_bytes = w * h * bpp
    data_end = HEADER + count * frame_bytes
    dtype = "<u2" if bpp == 2 else "u1"
    frames = [np.frombuffer(raw, dtype=dtype, count=w * h,
                            offset=HEADER + i * frame_bytes).reshape(h, w)
              for i in range(count)]
    trailer = raw[data_end:]
    stamps = list(struct.unpack(f"<{len(trailer) // 8}q", trailer))
    return dict(color_id=color_id, little_endian=little_endian, w=w, h=h,
                depth=depth, count=count, frames=frames, stamps=stamps)


def _record(tmp_path, frames, **kw):
    rec = SerRecorder()
    f0 = frames[0]
    rec.start(tmp_path / "t.ser", width=f0.width, height=f0.height,
              bit_depth=f0.bit_depth, **kw)
    for f in frames:
        rec.on_frame(f)
    rec.stop()
    return rec, tmp_path / "t.ser"


@pytest.mark.parametrize("bits", [8, 16])
def test_roundtrip_header_pixels_and_capture_timestamps(tmp_path, irregular_frames, bits):
    frames = irregular_frames(bits)
    rec, path = _record(tmp_path, frames)
    ser = _read_ser(path)
    assert (ser["w"], ser["h"], ser["depth"]) == (8, 4, bits)
    assert ser["count"] == len(frames) == rec.frames_written()
    assert ser["color_id"] == 0
    assert ser["little_endian"] == 0  # de-facto convention, see recorder comment
    for got, f in zip(ser["frames"], frames):
        np.testing.assert_array_equal(got, f.data)
    # Trailer = each frame's capture time, not the time it was written.
    assert ser["stamps"] == [_unix_to_ticks(f.capture_utc_ns) for f in frames]


@pytest.mark.parametrize("pattern,cid", [("RGGB", 8), ("GRBG", 9), ("GBRG", 10), ("BGGR", 11)])
def test_bayer_color_ids_match_ser_v3(tmp_path, irregular_frames, pattern, cid):
    _, path = _record(tmp_path, irregular_frames(16), bayer_pattern=pattern)
    assert _read_ser(path)["color_id"] == cid


def test_unix_to_ticks_epoch():
    # 1970-01-01 is 621355968000000000 .NET ticks.
    assert _unix_to_ticks(0) == 621355968000000000
    assert _unix_to_ticks(100) == 621355968000000001


class _FailAfter:
    """File wrapper whose frame writes fail with ENOSPC after n successes."""

    def __init__(self, f, ok_writes):
        self._f, self._left = f, ok_writes

    def write(self, b):
        if isinstance(b, memoryview):  # frames only; header/trailer are bytes
            if self._left <= 0:
                self._f.write(bytes(b)[: len(b) // 2])  # partial frame hits disk
                raise OSError(errno.ENOSPC, "No space left on device")
            self._left -= 1
        return self._f.write(b)

    def __getattr__(self, name):
        return getattr(self._f, name)


def test_disk_full_enters_error_state_and_finalises_file(tmp_path, irregular_frames):
    frames = irregular_frames(16)
    rec = SerRecorder()
    rec.start(tmp_path / "t.ser", width=8, height=4, bit_depth=16)
    rec._file = _FailAfter(rec._file, ok_writes=2)
    for f in frames:
        rec.on_frame(f)

    assert not rec.is_recording()
    assert rec.stop_reason == "error"
    assert isinstance(rec.error, OSError) and rec.error.errno == errno.ENOSPC
    assert rec.frames_written() == 2
    ser = _read_ser(tmp_path / "t.ser")
    assert ser["count"] == 2
    # Partial third frame was truncated, so the trailer is aligned.
    assert ser["stamps"] == [_unix_to_ticks(f.capture_utc_ns) for f in frames[:2]]


def test_refuses_to_start_when_disk_low(tmp_path, monkeypatch, irregular_frames):
    monkeypatch.setattr(rec_abc, "MIN_FREE_BYTES", 1 << 62)
    with pytest.raises(OSError, match="free"):
        SerRecorder().start(tmp_path / "t.ser", width=8, height=4, bit_depth=16)
