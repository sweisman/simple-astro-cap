"""Simulated HDR: gain-bracketed capture and self-calibrated linear merge.

For cameras without native HDR, a snap takes two frames at the same exposure:
a low-gain "planet" frame (bright object unclipped) and a high-gain "star"
frame (faint objects above the noise floor). ``merge_hdr`` fits
``high = k * low + b`` on pixels valid in both and produces one linear frame in
low-gain units, using the high-gain frame's precision wherever it is unclipped.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from simple_astro_cap.camera.abc import CameraBase, Frame
from simple_astro_cap.pipeline.abc import FrameConsumer

log = logging.getLogger(__name__)

# Frames to discard after a gain change before keeping one (frames in flight).
SETTLE_FRAMES = 3
# Give up if the bracket has not completed after this many frames.
_TIMEOUT_FRAMES = 60

# Fraction of full scale above which a high-gain pixel counts as saturated.
_SAT_FRACTION = 0.9
# Low-gain floor (fraction of full scale) below which pixels are too noisy to fit.
_FLOOR_FRACTION = 0.002
# Minimum pixel count for a trustworthy k,b fit.
_MIN_FIT_PIXELS = 500
_FIT_STRIDE = 4


def merge_hdr(low: np.ndarray, high: np.ndarray, max_val: int) -> tuple[np.ndarray, float, float]:
    """Merge a low-gain and a high-gain frame into one 16-bit linear frame.

    Returns ``(merged_uint16, k, b)`` where ``high ≈ k * low + b``.
    The merged frame is in low-gain units rescaled so ``max_val`` maps to 65535.
    """
    lo = low.astype(np.float32)
    hi = high.astype(np.float32)

    sat = _SAT_FRACTION * max_val
    floor = _FLOOR_FRACTION * max_val
    unsat = hi < sat

    fit_lo = lo[::_FIT_STRIDE, ::_FIT_STRIDE]
    fit_hi = hi[::_FIT_STRIDE, ::_FIT_STRIDE]
    valid = (fit_hi < sat) & (fit_lo > floor)
    n = int(valid.sum())
    if n >= _MIN_FIT_PIXELS:
        x = fit_lo[valid].astype(np.float64)
        y = fit_hi[valid].astype(np.float64)
        k, b = np.polyfit(x, y, 1)
        k, b = float(k), float(b)
        if not np.isfinite(k) or k <= 0:
            log.warning("HDR merge: bad fit k=%s; using k=1, b=0", k)
            k, b = 1.0, 0.0
    else:
        log.warning("HDR merge: only %d overlap pixels; using k=1, b=0", n)
        k, b = 1.0, 0.0

    merged = np.where(unsat, (hi - b) / k, lo)
    merged = np.clip(merged, 0.0, float(max_val))
    out = (merged * (65535.0 / max_val)).astype(np.uint16)
    log.info("HDR merge: k=%.3f b=%.2f fit_pixels=%d", k, b, n)
    return out, k, b


BracketCallback = Callable[[Frame | None, Frame | None, str], None]


class HdrBracketCapture(FrameConsumer):
    """One-shot gain bracket driven from the live stream.

    Attach to the harness; it sets the planet gain, waits ``SETTLE_FRAMES``,
    keeps a frame, repeats at the star gain, restores the original gain, then
    invokes ``on_done(low, high, error)`` on the harness thread. Exactly one
    call to ``on_done`` is made; ``error`` is "" on success.
    """

    def __init__(self, camera: CameraBase, planet_gain: float, star_gain: float,
                 on_done: BracketCallback) -> None:
        self._camera = camera
        self._gains = [planet_gain, star_gain]
        self._on_done = on_done
        self._original_gain = camera.get_gain()
        self._stage = -1  # index into _gains; -1 = not started
        self._settle = 0
        self._frames_seen = 0
        self._captured: list[Frame] = []
        self._finished = False

    def on_frame(self, frame: Frame) -> None:
        if self._finished:
            return
        self._frames_seen += 1
        if self._frames_seen > _TIMEOUT_FRAMES:
            self._finish("timed out waiting for bracket frames")
            return
        if self._stage < 0:
            self._advance()
            return
        if self._settle > 0:
            self._settle -= 1
            return
        self._captured.append(frame)
        if len(self._captured) == len(self._gains):
            self._finish("")
        else:
            self._advance()

    def _advance(self) -> None:
        self._stage += 1
        try:
            self._camera.set_gain(self._gains[self._stage])
        except Exception as e:
            self._finish(f"failed to set gain {self._gains[self._stage]}: {e}")
            return
        self._settle = SETTLE_FRAMES

    def _finish(self, error: str) -> None:
        self._finished = True
        try:
            self._camera.set_gain(self._original_gain)
        except Exception:
            log.warning("HDR bracket: failed to restore gain", exc_info=True)
        low = self._captured[0] if len(self._captured) > 0 else None
        high = self._captured[1] if len(self._captured) > 1 else None
        if error:
            log.warning("HDR bracket failed: %s", error)
        self._on_done(low, high, error)
