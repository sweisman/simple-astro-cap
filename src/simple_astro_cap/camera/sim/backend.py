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

    @staticmethod
    def enumerate() -> list[CameraInfo]:
        return [_SIM_INFO]

    def connect(self, camera_id: str) -> None:
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

        # Gradient + noise pattern that responds to gain/exposure
        brightness = min(1.0, (self._gain / 100.0) * (self._exposure_us / 50000.0))
        y_grad = np.linspace(0, brightness * max_val * 0.7, h, dtype=np.float32)
        x_grad = np.linspace(0, brightness * max_val * 0.3, w, dtype=np.float32)
        pattern = (y_grad[:, None] + x_grad[None, :]).clip(0, max_val).astype(dtype)

        # Add some noise
        noise_scale = max(1, int(max_val * 0.02 * (self._gain / 100.0)))
        noise = np.random.randint(0, noise_scale, (h, w), dtype=dtype)
        frame_data = np.clip(pattern.astype(np.int32) + noise, 0, max_val).astype(dtype)

        return Frame(
            data=frame_data,
            width=w,
            height=h,
            bit_depth=self._bit_depth,
            timestamp_ns=time.monotonic_ns(),
            sequence=self._seq,
        )
