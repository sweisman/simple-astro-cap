"""Software auto-exposure controller.

Analyzes frame brightness and adjusts camera exposure to reach a target.
Exposure-only — gain remains under manual control.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from simple_astro_cap.camera.abc import CameraBase, Frame, Param
from simple_astro_cap.pipeline.abc import FrameConsumer

log = logging.getLogger(__name__)

# Target brightness as a fraction of the maximum pixel value.
_TARGET_FRACTION = 0.40  # 40% of max (102 for 8-bit, ~26214 for 16-bit)

# Minimum interval between adjustments (seconds).
_EVAL_INTERVAL = 0.5

# Damping factor: 0.0 = no change, 1.0 = full correction each step.
_DAMPING = 0.5

# Dead zone: skip adjustment if measured is within this fraction of target.
_DEAD_ZONE = 0.05


class SoftwareAutoExposure(FrameConsumer):
    """Adjusts camera exposure based on frame brightness.

    Added to the pipeline harness as a FrameConsumer.  Periodically
    samples the frame, computes median brightness, and calls
    ``camera.set_exposure()`` to converge on the target brightness.
    """

    def __init__(self, camera: CameraBase) -> None:
        self._camera = camera
        self._last_eval: float = 0.0
        self._stride = 8  # sample every 8th pixel in each dimension

    def on_frame(self, frame: Frame) -> None:
        now = time.monotonic()
        if (now - self._last_eval) < _EVAL_INTERVAL:
            return
        self._last_eval = now

        # Sample brightness via strided median
        sampled = frame.data[:: self._stride, :: self._stride]
        measured = float(np.median(sampled))

        max_val = 65535.0 if frame.bit_depth > 8 else 255.0
        target = _TARGET_FRACTION * max_val

        # Dead zone check
        if target > 0 and abs(measured - target) / target <= _DEAD_ZONE:
            return

        # Avoid division by zero
        if measured < 1.0:
            measured = 1.0

        ratio = target / measured
        adjustment = 1.0 + _DAMPING * (ratio - 1.0)

        current_us = self._camera.get_exposure()
        new_us = current_us * adjustment

        # Clamp to camera's exposure range
        exp_range = self._camera.get_param_range(Param.EXPOSURE)
        if exp_range is not None:
            new_us = max(exp_range.min_val, min(new_us, exp_range.max_val))

        if new_us != current_us:
            try:
                self._camera.set_exposure(new_us)
            except Exception:
                log.debug("Software auto-exposure: failed to set exposure", exc_info=True)
