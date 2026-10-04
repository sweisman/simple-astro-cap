from __future__ import annotations

from simple_astro_cap.recording.png_recorder import PngRecorder
from .conftest import make_frame


def test_fps_uses_capture_spacing_after_a_disk_stall(tmp_path, monkeypatch):
    monkeypatch.setattr("time.monotonic_ns", lambda: 100_000_000_000)
    rec = PngRecorder()
    rec.start(tmp_path, target_fps=10)
    # Dispatch a backlog without waiting between calls.
    for i in range(5):
        rec.on_frame(make_frame(i, mono_ns=100_000_000_000 + i * 100_000_000))
    rec.stop()
    assert rec.frames_written() == 5


def test_duration_flushes_captures_before_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("time.monotonic_ns", lambda: 100_000_000_000)
    rec = PngRecorder()
    rec.start(tmp_path, max_duration=1)
    monkeypatch.setattr("time.monotonic_ns", lambda: 102_000_000_000)
    assert rec.duration_expired()
    rec.request_stop("time_limit")
    rec.on_frame(make_frame(1, mono_ns=100_500_000_000))
    rec.on_frame(make_frame(2, mono_ns=101_000_000_000))
    assert rec.frames_written() == 1
    assert rec.stop_reason == "time_limit"
    assert not rec.is_recording()


def test_manual_stop_excludes_later_captures(tmp_path, monkeypatch):
    monkeypatch.setattr("time.monotonic_ns", lambda: 100_000_000_000)
    rec = PngRecorder()
    rec.start(tmp_path)
    rec.request_stop()
    rec.on_frame(make_frame(1, mono_ns=99_900_000_000))
    rec.on_frame(make_frame(2, mono_ns=100_100_000_000))
    rec.stop()
    assert rec.frames_written() == 1


def test_frame_limit_stops_without_an_extra_frame(tmp_path):
    rec = PngRecorder()
    rec.start(tmp_path, max_frames=1)
    rec.on_frame(make_frame(1))
    assert rec.frames_written() == 1
    assert not rec.is_recording()
    assert rec.stop_reason == "frame_limit"
