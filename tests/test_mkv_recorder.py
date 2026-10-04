from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from simple_astro_cap.recording.mkv_recorder import MkvRecorder

from .conftest import OFFSETS_MS

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("mkvmerge")),
    reason="needs ffmpeg, ffprobe and mkvmerge",
)


def test_mkv_carries_real_irregular_frame_times(tmp_path, irregular_frames):
    frames = irregular_frames(16)
    rec = MkvRecorder()
    rec.start(tmp_path / "t.mkv", width=8, height=4, bit_depth=16)
    for f in frames:
        rec.on_frame(f)
    rec.stop()

    out = tmp_path / "t.mkv"
    assert out.exists() and not (tmp_path / "t.part.mkv").exists()
    assert rec.timestamps_path.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=pts_time", "-of", "json", str(out)],
        capture_output=True, check=True, text=True)
    pts_ms = [round(float(f["pts_time"]) * 1000) for f in json.loads(probe.stdout)["frames"]]
    assert pts_ms == OFFSETS_MS
