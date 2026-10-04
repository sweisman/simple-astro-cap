from __future__ import annotations

import ctypes
from unittest.mock import Mock

from simple_astro_cap.camera.abc import ROI
from simple_astro_cap.camera.asi.backend import AsiCamera
from simple_astro_cap.camera.asi.constants import ErrorCode
from simple_astro_cap.camera.asi.sdk import AsiError
from simple_astro_cap.pipeline.simple import SimpleHarness


def test_camera_removed_reaches_harness_error(monkeypatch):
    cam = AsiCamera()
    cam._connected = cam._live = True
    cam._roi = ROI(0, 0, 8, 4)
    cam._frame_buf = (ctypes.c_uint8 * 32)()
    sdk = Mock()
    error = AsiError("ASIGetVideoData", ErrorCode.ERROR_CAMERA_REMOVED)
    sdk.get_video_data.side_effect = error
    monkeypatch.setattr(cam, "_get_sdk", lambda: sdk)
    harness = SimpleHarness(cam)
    harness.start()
    harness._capture.join(timeout=1)
    assert harness.error is error
    assert not harness.is_running()
    assert harness.stop()


def test_ordinary_timeout_is_not_fatal(monkeypatch):
    cam = AsiCamera()
    cam._live = True
    cam._roi = ROI(0, 0, 8, 4)
    sdk = Mock()
    sdk.get_video_data.return_value = False
    monkeypatch.setattr(cam, "_get_sdk", lambda: sdk)
    assert cam.get_live_frame() is None
