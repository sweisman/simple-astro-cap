from __future__ import annotations

import io
import subprocess
import sys
from unittest.mock import Mock

import pytest

from simple_astro_cap.recording import mkv_recorder as mkv
from .conftest import make_frame


def prepared(tmp_path):
    rec = mkv.MkvRecorder()
    rec._path = tmp_path / "test.mkv"
    rec._part_path = tmp_path / "test.part.mkv"
    rec._part_path.write_bytes(b"recovery data")
    rec._capture_mono_ns = [1]
    rec._begin()
    rec._count = 1
    return rec


@pytest.mark.parametrize("code", [2, -9, 127])
def test_remux_error_keeps_recovery_and_reports_failure(tmp_path, monkeypatch, code):
    rec = prepared(tmp_path)
    rec._path.write_bytes(b"partial final")
    proc = Mock(returncode=code)
    proc.communicate.return_value = (b"mux failed", None)
    proc.poll.return_value = code
    monkeypatch.setattr(mkv.subprocess, "Popen", lambda *a, **kw: proc)
    rec.stop()
    assert not rec.is_recording()
    assert rec.stop_reason == "error"
    assert str(code) in str(rec.error)
    assert str(rec._part_path) in str(rec.error)
    assert rec.recovery_path.read_bytes() == b"recovery data"
    assert not rec._path.exists()


def test_remux_timeout_kills_child_and_reports_failure(tmp_path, monkeypatch):
    rec = prepared(tmp_path)
    proc = Mock()
    proc.poll.return_value = None
    proc.communicate.return_value = (b"", None)
    monkeypatch.setattr(mkv.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(mkv, "_REMUX_TIMEOUT_S", 0)
    rec.stop()
    proc.kill.assert_called_once()
    assert rec.error is not None
    assert rec.recovery_path.exists()


def test_sidecar_failure_is_reported(tmp_path, monkeypatch):
    rec = prepared(tmp_path)
    monkeypatch.setattr(type(rec.timestamps_path), "write_text",
                        Mock(side_effect=OSError("disk full")))
    rec.stop()
    assert "disk full" in str(rec.error)
    assert rec.stop_reason == "error"
    assert rec.recovery_path.exists()


def test_encoder_exit_failure_is_reported(tmp_path):
    rec = prepared(tmp_path)
    proc = Mock(returncode=1)
    proc.poll.return_value = 1
    rec._proc = proc
    rec._stderr = io.BytesIO(b"encoder failure")
    rec.stop()
    assert "encoder failure" in str(rec.error)
    assert rec.stop_reason == "error"
    assert rec.recovery_path.exists()


def test_stalled_encoder_write_is_bounded(tmp_path, monkeypatch):
    import os
    rec = prepared(tmp_path)
    # Real pipe whose child never reads. No camera or ffmpeg needed.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"],
                            stdin=subprocess.PIPE, bufsize=0)
    rec._proc = proc
    os.set_blocking(proc.stdin.fileno(), False)
    monkeypatch.setattr(mkv, "_IO_TIMEOUT_S", 0.05)
    try:
        rec.on_frame(make_frame(2, w=256, h=256))
        assert rec.stop_reason == "error"
        assert "timed out" in str(rec.error)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=1)
