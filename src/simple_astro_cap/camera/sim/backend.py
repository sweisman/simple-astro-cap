"""Simulated camera that generates test patterns."""

from __future__ import annotations

import time

import numpy as np

from ..abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI

_SIM_INFO = CameraInfo(
    camera_id="SIM-001",
    model="Simulator",
    sensor_width=3840,
    sensor_height=2160,
    pixel_width_um=2.9,
    pixel_height_um=2.9,
    max_bit_depth=16,
    is_color=False,
)


def _generate_test_card(w: int, h: int, max_val: int, dtype: np.dtype) -> np.ndarray:
    """Generate a SMPTE-style test card (grayscale)."""
    img = np.zeros((h, w), dtype=np.float32)

    # Top 2/3: 7 vertical bars (white, yellow, cyan, green, magenta, red, blue)
    # In grayscale luminance: 100%, 89%, 70%, 59%, 41%, 30%, 11%
    bar_h = h * 2 // 3
    bar_levels = [1.0, 0.89, 0.70, 0.59, 0.41, 0.30, 0.11]
    bar_w = w // 7
    for i, level in enumerate(bar_levels):
        x0 = i * bar_w
        x1 = (i + 1) * bar_w if i < 6 else w
        img[:bar_h, x0:x1] = level * max_val

    # Middle strip (1/12 height): reverse bars
    strip_h = h // 12
    strip_top = bar_h
    strip_bot = bar_h + strip_h
    rev_levels = list(reversed(bar_levels))
    for i, level in enumerate(rev_levels):
        x0 = i * bar_w
        x1 = (i + 1) * bar_w if i < 6 else w
        img[strip_top:strip_bot, x0:x1] = level * max_val

    # Bottom section: ramp + black/white patches
    bot_top = strip_bot
    # Left third: grayscale ramp
    ramp_w = w // 3
    ramp = np.linspace(0, max_val, ramp_w, dtype=np.float32)
    img[bot_top:, :ramp_w] = ramp[None, :]

    # Middle third: 50% gray
    mid_x0 = ramp_w
    mid_x1 = 2 * ramp_w
    img[bot_top:, mid_x0:mid_x1] = 0.5 * max_val

    # Right third: alternating black/white checkerboard
    check_w = (w - mid_x1)
    check_size = max(4, check_w // 8)
    for y in range(bot_top, h):
        for x in range(mid_x1, w):
            ry = (y - bot_top) // check_size
            rx = (x - mid_x1) // check_size
            if (ry + rx) % 2 == 0:
                img[y, x] = max_val

    return np.clip(img, 0, max_val).astype(dtype)


class SimCamera(CameraBase):
    """Test-pattern camera for GUI development without hardware."""

    def __init__(self) -> None:
        self._connected = False
        self._live = False
        self._exposure_us = 10000.0
        self._gain = 50.0
        self._bin = 1
        self._bit_depth = 8
        self._roi = ROI(0, 0, _SIM_INFO.sensor_width, _SIM_INFO.sensor_height)
        self._seq = 0
        self._pending_roi: ROI | None = None
        self._test_card: np.ndarray | None = None
        self._display_card: np.ndarray | None = None
        self._card_brightness: float = -1.0

    @staticmethod
    def enumerate() -> list[CameraInfo]:
        return [_SIM_INFO]

    def set_connect_roi(self, roi: ROI) -> None:
        self._pending_roi = roi

    def connect(self, camera_id: str) -> None:
        if self._pending_roi is not None:
            self._roi = self._pending_roi
            self._pending_roi = None
        self._connected = True
        self._seq = 0

    def disconnect(self) -> None:
        self._live = False
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_info(self) -> CameraInfo:
        return _SIM_INFO

    def get_param_range(self, param: Param) -> ParamRange | None:
        ranges = {
            Param.EXPOSURE: ParamRange(1.0, 60_000_000.0, 1.0),
            Param.GAIN: ParamRange(0.0, 100.0, 1.0),
            Param.OFFSET: ParamRange(0.0, 255.0, 1.0),
        }
        return ranges.get(param)

    def get_supported_bin_modes(self) -> list[int]:
        return [1, 2, 4]

    def get_supported_bit_depths(self) -> list[int]:
        return [8, 16]

    def set_exposure(self, microseconds: float) -> None:
        self._exposure_us = max(1.0, microseconds)

    def get_exposure(self) -> float:
        return self._exposure_us

    def set_gain(self, value: float) -> None:
        self._gain = max(0.0, min(100.0, value))

    def get_gain(self) -> float:
        return self._gain

    def set_bin_mode(self, bin_factor: int) -> None:
        self._bin = bin_factor

    def get_bin_mode(self) -> int:
        return self._bin

    def set_roi(self, roi: ROI) -> None:
        self._roi = roi

    def get_roi(self) -> ROI:
        return self._roi

    def set_bit_depth(self, bits: int) -> None:
        self._bit_depth = bits

    def get_bit_depth(self) -> int:
        return self._bit_depth

    def set_param(self, param: Param, value: float) -> None:
        if param == Param.EXPOSURE:
            self.set_exposure(value)
        elif param == Param.GAIN:
            self.set_gain(value)
        else:
            pass  # silently ignore unsupported

    def get_param(self, param: Param) -> float:
        if param == Param.EXPOSURE:
            return self.get_exposure()
        elif param == Param.GAIN:
            return self.get_gain()
        return 0.0

    def capture_single(self) -> Frame:
        return self._generate_frame()

    def start_live(self) -> None:
        self._live = True

    def stop_live(self) -> None:
        self._live = False

    def get_live_frame(self, timeout_ms: int = 1000) -> Frame | None:
        if not self._live:
            return None
        # Simulate frame rate limited by exposure time
        delay = min(self._exposure_us / 1_000_000.0, 0.1)
        time.sleep(delay)
        return self._generate_frame()

    def is_live(self) -> bool:
        return self._live

    def _generate_frame(self) -> Frame:
        self._seq += 1
        w = self._roi.width // self._bin
        h = self._roi.height // self._bin
        max_val = 255 if self._bit_depth == 8 else 65535
        dtype = np.uint8 if self._bit_depth == 8 else np.uint16

        # Cache test card; regenerate if dimensions or depth change
        if (self._test_card is None
                or self._test_card.shape != (h, w)
                or self._test_card.dtype != dtype):
            self._test_card = _generate_test_card(w, h, max_val, dtype)
            self._card_brightness = -1.0  # force recalc

        # Cache brightness-adjusted card; only recompute when exposure/gain change
        brightness = min(1.0, (self._gain / 100.0) * (self._exposure_us / 50000.0))
        if brightness != self._card_brightness:
            self._display_card = (
                (self._test_card.astype(np.float32) * brightness)
                .clip(0, max_val)
                .astype(dtype)
            )
            self._card_brightness = brightness

        frame_data = self._display_card

        return Frame(
            data=frame_data,
            width=w,
            height=h,
            bit_depth=self._bit_depth,
            timestamp_ns=time.monotonic_ns(),
            sequence=self._seq,
        )
