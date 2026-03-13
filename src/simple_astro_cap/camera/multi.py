"""Multi-backend camera that aggregates cameras from all available backends."""

from __future__ import annotations

import logging

from .abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI

log = logging.getLogger(__name__)


class MultiCamera(CameraBase):
    """Discovers cameras from multiple backends, delegates to the active one.

    enumerate() scans all backends and returns a combined list.
    connect() delegates to whichever backend owns the selected camera.
    """

    def __init__(self):
        self._backends: list[CameraBase] = []
        self._camera_map: dict[str, CameraBase] = {}  # camera_id -> backend
        self._active: CameraBase | None = None

        # Try to load each backend; skip unavailable ones
        self._try_add_backend("QHY", self._make_qhy)
        self._try_add_backend("ASI", self._make_asi)
        self._try_add_backend("PlayerOne", self._make_playerone)
        self._try_add_backend("Touptek", self._make_touptek)

        if not self._backends:
            log.warning("No camera backends available")

    @staticmethod
    def _make_qhy() -> CameraBase:
        from .qhy.backend import QhyCamera
        return QhyCamera()

    @staticmethod
    def _make_asi() -> CameraBase:
        from .asi.backend import AsiCamera
        return AsiCamera()

    @staticmethod
    def _make_playerone() -> CameraBase:
        from .playerone.backend import PlayerOneCamera
        return PlayerOneCamera()

    @staticmethod
    def _make_touptek() -> CameraBase:
        from .touptek.backend import ToupcamCamera
        return ToupcamCamera()

    def _try_add_backend(self, name: str, factory) -> None:
        try:
            backend = factory()
            self._backends.append(backend)
            log.info("Loaded %s backend", name)
        except Exception as e:
            log.debug("Skipping %s backend: %s", name, e)

    # --- Discovery ---

    def enumerate(self) -> list[CameraInfo]:
        self._camera_map.clear()
        all_cameras = []
        for backend in self._backends:
            try:
                cameras = backend.enumerate()
                for cam in cameras:
                    self._camera_map[cam.camera_id] = backend
                all_cameras.extend(cameras)
            except Exception as e:
                log.debug("Backend enumerate failed: %s", e)
        return all_cameras

    def _get_backend(self, camera_id: str) -> CameraBase:
        backend = self._camera_map.get(camera_id)
        if backend is None:
            raise RuntimeError(f"Unknown camera: {camera_id}")
        return backend

    # --- Pre-open ---

    def pre_open(self, camera_id: str) -> None:
        backend = self._get_backend(camera_id)
        if hasattr(backend, 'pre_open'):
            backend.pre_open(camera_id)
        self._active = backend

    def get_pre_open_info(self) -> CameraInfo | None:
        if self._active and hasattr(self._active, 'get_pre_open_info'):
            return self._active.get_pre_open_info()
        return None

    # --- Delegated to active backend ---

    def set_connect_bit_depth(self, bit_depth: int) -> None:
        if self._active and hasattr(self._active, 'set_connect_bit_depth'):
            self._active.set_connect_bit_depth(bit_depth)

    def set_connect_roi(self, roi: ROI) -> None:
        if self._active and hasattr(self._active, 'set_connect_roi'):
            self._active.set_connect_roi(roi)

    def connect(self, camera_id: str) -> None:
        backend = self._get_backend(camera_id)
        backend.connect(camera_id)
        self._active = backend

    def disconnect(self) -> None:
        if self._active:
            self._active.disconnect()
            self._active = None

    def is_connected(self) -> bool:
        return self._active is not None and self._active.is_connected()

    def get_info(self) -> CameraInfo:
        return self._active.get_info()

    def get_param_range(self, param: Param) -> ParamRange | None:
        return self._active.get_param_range(param)

    def get_supported_bin_modes(self) -> list[int]:
        return self._active.get_supported_bin_modes()

    def get_supported_bit_depths(self) -> list[int]:
        return self._active.get_supported_bit_depths()

    def supports_auto_exposure(self) -> bool:
        return self._active.supports_auto_exposure() if self._active else False

    def supports_auto_gain(self) -> bool:
        return self._active.supports_auto_gain() if self._active else False

    def auto_exposure_gain_coupled(self) -> bool:
        return self._active.auto_exposure_gain_coupled() if self._active else False

    def set_auto_exposure(self, enabled: bool) -> None:
        self._active.set_auto_exposure(enabled)

    def set_auto_gain(self, enabled: bool) -> None:
        self._active.set_auto_gain(enabled)

    def get_auto_exposure(self) -> bool:
        return self._active.get_auto_exposure() if self._active else False

    def get_auto_gain(self) -> bool:
        return self._active.get_auto_gain() if self._active else False

    def get_sensor_temperature(self) -> float | None:
        return self._active.get_sensor_temperature() if self._active else None

    def set_exposure(self, microseconds: float) -> None:
        self._active.set_exposure(microseconds)

    def get_exposure(self) -> float:
        return self._active.get_exposure()

    def set_gain(self, value: float) -> None:
        self._active.set_gain(value)

    def get_gain(self) -> float:
        return self._active.get_gain()

    def set_bin_mode(self, bin_factor: int) -> None:
        self._active.set_bin_mode(bin_factor)

    def get_bin_mode(self) -> int:
        return self._active.get_bin_mode()

    def set_roi(self, roi: ROI) -> None:
        self._active.set_roi(roi)

    def get_roi(self) -> ROI:
        return self._active.get_roi()

    def set_bit_depth(self, bit_depth: int) -> None:
        self._active.set_bit_depth(bit_depth)

    def get_bit_depth(self) -> int:
        return self._active.get_bit_depth()

    def set_param(self, param: Param, value: float) -> None:
        self._active.set_param(param, value)

    def get_param(self, param: Param) -> float:
        return self._active.get_param(param)

    def capture_single(self) -> Frame:
        return self._active.capture_single()

    def start_live(self) -> None:
        self._active.start_live()

    def stop_live(self) -> None:
        self._active.stop_live()

    def get_live_frame(self, timeout_ms: int = 1000) -> Frame | None:
        return self._active.get_live_frame(timeout_ms=timeout_ms)

    def is_live(self) -> bool:
        return self._active is not None and self._active.is_live()
