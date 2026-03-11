"""Camera abstraction base class and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Self

import numpy as np


class Param(IntEnum):
    """Vendor-neutral camera parameter identifiers."""

    EXPOSURE = 0  # microseconds
    GAIN = 1
    OFFSET = 2
    USB_TRAFFIC = 3
    SPEED = 4  # readout speed
    BRIGHTNESS = 5
    CONTRAST = 6
    GAMMA = 7
    COOLER_TARGET = 8


@dataclass(frozen=True)
class CameraInfo:
    camera_id: str
    model: str
    sensor_width: int
    sensor_height: int
    pixel_width_um: float
    pixel_height_um: float
    max_bit_depth: int
    is_color: bool


@dataclass(frozen=True)
class ROI:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ParamRange:
    min_val: float
    max_val: float
    step: float


@dataclass
class Frame:
    data: np.ndarray  # 2D uint8 or uint16
    width: int
    height: int
    bit_depth: int
    timestamp_ns: int  # monotonic nanoseconds
    sequence: int


class CameraBase(ABC):
    """Abstract base for all camera backends."""

    # --- Discovery ---

    @staticmethod
    @abstractmethod
    def enumerate() -> list[CameraInfo]:
        """Return list of detected cameras."""

    # --- Lifecycle ---

    @abstractmethod
    def connect(self, camera_id: str) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    # --- Info & capabilities ---

    @abstractmethod
    def get_info(self) -> CameraInfo: ...

    @abstractmethod
    def get_param_range(self, param: Param) -> ParamRange | None:
        """Return range for param, or None if unsupported."""

    @abstractmethod
    def get_supported_bin_modes(self) -> list[int]: ...

    @abstractmethod
    def get_supported_bit_depths(self) -> list[int]: ...

    # --- Parameters ---

    @abstractmethod
    def set_exposure(self, microseconds: float) -> None: ...

    @abstractmethod
    def get_exposure(self) -> float: ...

    @abstractmethod
    def set_gain(self, value: float) -> None: ...

    @abstractmethod
    def get_gain(self) -> float: ...

    @abstractmethod
    def set_bin_mode(self, bin_factor: int) -> None: ...

    @abstractmethod
    def get_bin_mode(self) -> int: ...

    @abstractmethod
    def set_roi(self, roi: ROI) -> None: ...

    @abstractmethod
    def get_roi(self) -> ROI: ...

    @abstractmethod
    def set_bit_depth(self, bits: int) -> None: ...

    @abstractmethod
    def get_bit_depth(self) -> int: ...

    @abstractmethod
    def set_param(self, param: Param, value: float) -> None:
        """Set a generic parameter. Raises ValueError if unsupported."""

    @abstractmethod
    def get_param(self, param: Param) -> float:
        """Get a generic parameter. Raises ValueError if unsupported."""

    # --- Auto exposure / auto gain ---

    def supports_auto_exposure(self) -> bool:
        """Return True if the camera supports hardware auto-exposure."""
        return False

    def supports_auto_gain(self) -> bool:
        """Return True if the camera supports hardware auto-gain."""
        return False

    def auto_exposure_gain_coupled(self) -> bool:
        """Return True if auto-exposure and auto-gain are controlled together."""
        return False

    def set_auto_exposure(self, enabled: bool) -> None:
        """Enable or disable hardware auto-exposure."""
        raise NotImplementedError("Auto-exposure not supported by this backend")

    def set_auto_gain(self, enabled: bool) -> None:
        """Enable or disable hardware auto-gain."""
        raise NotImplementedError("Auto-gain not supported by this backend")

    def get_auto_exposure(self) -> bool:
        """Return True if hardware auto-exposure is currently enabled."""
        return False

    def get_auto_gain(self) -> bool:
        """Return True if hardware auto-gain is currently enabled."""
        return False

    # --- Sensor temperature ---

    def get_sensor_temperature(self) -> float | None:
        """Return sensor temperature in degrees Celsius, or None if unavailable."""
        return None

    # --- Single capture ---

    @abstractmethod
    def capture_single(self) -> Frame: ...

    # --- Live streaming ---

    @abstractmethod
    def start_live(self) -> None: ...

    @abstractmethod
    def stop_live(self) -> None: ...

    @abstractmethod
    def get_live_frame(self, timeout_ms: int = 1000) -> Frame | None: ...

    @abstractmethod
    def is_live(self) -> bool: ...
