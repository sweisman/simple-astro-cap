"""Player One camera backend implementing CameraBase."""

from __future__ import annotations

import ctypes
import logging
import time

import numpy as np

from ..abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI
from .constants import POAConfig, POAErrors, POAImgFormat, POAValueType
from .sdk import PlayerOneError, PlayerOneSdk

log = logging.getLogger(__name__)

# Map vendor-neutral Param to POAConfig
_PARAM_MAP: dict[Param, POAConfig] = {
    Param.EXPOSURE: POAConfig.EXPOSURE,
    Param.GAIN: POAConfig.GAIN,
    Param.OFFSET: POAConfig.OFFSET,
    Param.USB_TRAFFIC: POAConfig.USB_BANDWIDTH_LIMIT,
}


class PlayerOneCamera(CameraBase):
    """Player One camera backend."""

    _sdk: PlayerOneSdk | None = None

    def __init__(self, lib_path: str | None = None):
        self._lib_path = lib_path
        self._camera_id: int | None = None
        self._connected = False
        self._live = False
        self._info: CameraInfo | None = None
        self._roi: ROI | None = None
        self._bin_mode = 1
        self._bit_depth = 8
        self._frame_buf: ctypes.Array | None = None
        self._frame_seq = 0

        self._auto_exposure = False
        self._auto_gain = False

        self._pending_bit_depth = 8
        self._pending_roi: ROI | None = None

    def _get_sdk(self) -> PlayerOneSdk:
        if PlayerOneCamera._sdk is None:
            PlayerOneCamera._sdk = PlayerOneSdk(self._lib_path)
        return PlayerOneCamera._sdk

    # --- Discovery ---

    def enumerate(self) -> list[CameraInfo]:
        sdk = self._get_sdk()
        n = sdk.get_camera_count()
        cameras = []
        for i in range(n):
            prop = sdk.get_camera_properties(i)
            name = prop.cameraModelName.decode("ascii", errors="replace").strip()
            cam_id = f"POA-{name}-{prop.cameraID}"
            cameras.append(CameraInfo(
                camera_id=cam_id,
                model=name,
                sensor_width=prop.maxWidth,
                sensor_height=prop.maxHeight,
                pixel_width_um=prop.pixelSize,
                pixel_height_um=prop.pixelSize,
                max_bit_depth=prop.bitDepth,
                is_color=bool(prop.isColorCamera),
            ))
        return cameras

    # --- Pre-open ---

    def pre_open(self, camera_id: str) -> None:
        sdk = self._get_sdk()
        poa_id = self._parse_poa_id(camera_id)
        sdk.open_camera(poa_id)
        prop = self._find_prop(camera_id)
        self._camera_id = poa_id
        self._info = self._make_info(camera_id, prop)
        log.info("Pre-opened Player One camera %s (%dx%d)",
                 camera_id, prop.maxWidth, prop.maxHeight)

    def get_pre_open_info(self) -> CameraInfo | None:
        return self._info

    # --- Connection ---

    def set_connect_bit_depth(self, bit_depth: int) -> None:
        self._pending_bit_depth = bit_depth

    def set_connect_roi(self, roi: ROI) -> None:
        self._pending_roi = roi

    def connect(self, camera_id: str) -> None:
        sdk = self._get_sdk()
        poa_id = self._parse_poa_id(camera_id)

        if self._camera_id != poa_id:
            sdk.open_camera(poa_id)
            self._camera_id = poa_id

        sdk.init_camera(poa_id)

        prop = self._find_prop(camera_id)
        self._info = self._make_info(camera_id, prop)

        self._bit_depth = self._pending_bit_depth
        self._bin_mode = 1

        if self._pending_roi:
            self._roi = self._pending_roi
        else:
            self._roi = ROI(0, 0, prop.maxWidth, prop.maxHeight)

        img_fmt = POAImgFormat.RAW16 if self._bit_depth == 16 else POAImgFormat.RAW8
        sdk.set_image_format(poa_id, img_fmt)
        sdk.set_image_bin(poa_id, self._bin_mode)
        sdk.set_image_size(poa_id, self._roi.width, self._roi.height)
        sdk.set_image_start_pos(poa_id, self._roi.x, self._roi.y)

        # Allocate frame buffer
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        self._frame_buf = (ctypes.c_uint8 * buf_size)()
        self._frame_seq = 0

        # Set defaults
        try:
            sdk.set_config(poa_id, POAConfig.USB_BANDWIDTH_LIMIT, 40)
            log.info("Set default USB bandwidth: 40")
        except PlayerOneError:
            pass
        try:
            sdk.set_config(poa_id, POAConfig.EXPOSURE, 20000)
            log.info("Set default exposure: 20000us")
        except PlayerOneError:
            pass
        try:
            sdk.set_config(poa_id, POAConfig.GAIN, 30)
            log.info("Set default gain: 30")
        except PlayerOneError:
            pass

        self._connected = True
        log.info("Connected to %s (%dx%d %dbit)",
                 camera_id, self._roi.width, self._roi.height, self._bit_depth)

    def disconnect(self) -> None:
        if self._live:
            self.stop_live()
        if self._camera_id is not None:
            try:
                self._get_sdk().close_camera(self._camera_id)
            except PlayerOneError:
                pass
        self._connected = False
        self._camera_id = None
        self._info = None
        log.info("Disconnected")

    def is_connected(self) -> bool:
        return self._connected

    # --- Info ---

    def get_info(self) -> CameraInfo:
        self._require_connected()
        return self._info  # type: ignore[return-value]

    def get_param_range(self, param: Param) -> ParamRange | None:
        self._require_connected()
        cfg = _PARAM_MAP.get(param)
        if cfg is None:
            return None
        sdk = self._get_sdk()
        n = sdk.get_configs_count(self._camera_id)
        for i in range(n):
            attr = sdk.get_config_attributes(self._camera_id, i)
            if attr.configID == cfg:
                return ParamRange(
                    min_val=float(attr.minValue_int),
                    max_val=float(attr.maxValue_int),
                    step=1.0,
                )
        return None

    def get_supported_bin_modes(self) -> list[int]:
        self._require_connected()
        prop = self._find_prop_by_id(self._camera_id)
        modes = []
        for b in prop.bins:
            if b == 0:
                break
            modes.append(b)
        return sorted(modes) if modes else [1]

    def get_supported_bit_depths(self) -> list[int]:
        self._require_connected()
        prop = self._find_prop_by_id(self._camera_id)
        depths = []
        for fmt in prop.imgFormats:
            if fmt == POAImgFormat.END:
                break
            if fmt in (POAImgFormat.RAW8, POAImgFormat.MONO8):
                if 8 not in depths:
                    depths.append(8)
            elif fmt == POAImgFormat.RAW16:
                depths.append(16)
        return sorted(depths) if depths else [8]

    # --- Parameters ---

    def set_exposure(self, microseconds: float) -> None:
        self._require_connected()
        self._get_sdk().set_config(
            self._camera_id, POAConfig.EXPOSURE, int(microseconds),
            auto=self._auto_exposure)

    def get_exposure(self) -> float:
        self._require_connected()
        val, _ = self._get_sdk().get_config(self._camera_id, POAConfig.EXPOSURE)
        return float(val)

    def set_gain(self, value: float) -> None:
        self._require_connected()
        self._get_sdk().set_config(
            self._camera_id, POAConfig.GAIN, int(value),
            auto=self._auto_gain)

    def get_gain(self) -> float:
        self._require_connected()
        val, _ = self._get_sdk().get_config(self._camera_id, POAConfig.GAIN)
        return float(val)

    # --- Auto exposure / auto gain ---

    def supports_auto_exposure(self) -> bool:
        return self._is_auto_supported(POAConfig.EXPOSURE)

    def supports_auto_gain(self) -> bool:
        return self._is_auto_supported(POAConfig.GAIN)

    def set_auto_exposure(self, enabled: bool) -> None:
        self._require_connected()
        self._auto_exposure = enabled
        val, _ = self._get_sdk().get_config(self._camera_id, POAConfig.EXPOSURE)
        self._get_sdk().set_config(
            self._camera_id, POAConfig.EXPOSURE, val, auto=enabled)
        log.info("Auto-exposure %s", "enabled" if enabled else "disabled")

    def set_auto_gain(self, enabled: bool) -> None:
        self._require_connected()
        self._auto_gain = enabled
        val, _ = self._get_sdk().get_config(self._camera_id, POAConfig.GAIN)
        self._get_sdk().set_config(
            self._camera_id, POAConfig.GAIN, val, auto=enabled)
        log.info("Auto-gain %s", "enabled" if enabled else "disabled")

    def get_auto_exposure(self) -> bool:
        if not self._connected:
            return False
        _, auto = self._get_sdk().get_config(self._camera_id, POAConfig.EXPOSURE)
        return auto

    def get_auto_gain(self) -> bool:
        if not self._connected:
            return False
        _, auto = self._get_sdk().get_config(self._camera_id, POAConfig.GAIN)
        return auto

    def _is_auto_supported(self, config: POAConfig) -> bool:
        if not self._connected or self._camera_id is None:
            return False
        sdk = self._get_sdk()
        n = sdk.get_configs_count(self._camera_id)
        for i in range(n):
            attr = sdk.get_config_attributes(self._camera_id, i)
            if attr.configID == config:
                return bool(attr.isSupportAuto)
        return False

    def get_sensor_temperature(self) -> float | None:
        if not self._connected or self._camera_id is None:
            return None
        try:
            val, _ = self._get_sdk().get_config(
                self._camera_id, POAConfig.TEMPERATURE)
            return val / 10.0  # POA returns temperature * 10
        except Exception:
            return None

    def set_bin_mode(self, bin_factor: int) -> None:
        self._require_connected()
        sdk = self._get_sdk()
        self._bin_mode = bin_factor
        sdk.set_image_bin(self._camera_id, bin_factor)
        if self._info:
            w = self._info.sensor_width // bin_factor
            h = self._info.sensor_height // bin_factor
            self._roi = ROI(0, 0, w, h)
        sdk.set_image_size(self._camera_id, self._roi.width, self._roi.height)
        sdk.set_image_start_pos(self._camera_id, 0, 0)
        # Reallocate buffer
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        self._frame_buf = (ctypes.c_uint8 * buf_size)()
        log.info("Bin %dx%d: resolution %dx%d", bin_factor, bin_factor,
                 self._roi.width, self._roi.height)

    def get_bin_mode(self) -> int:
        return self._bin_mode

    def set_roi(self, roi: ROI) -> None:
        self._require_connected()
        sdk = self._get_sdk()
        self._roi = roi
        sdk.set_image_size(self._camera_id, roi.width, roi.height)
        sdk.set_image_start_pos(self._camera_id, roi.x, roi.y)

    def get_roi(self) -> ROI:
        self._require_connected()
        return self._roi  # type: ignore[return-value]

    def set_bit_depth(self, bit_depth: int) -> None:
        self._require_connected()
        self._bit_depth = bit_depth

    def get_bit_depth(self) -> int:
        return self._bit_depth

    def set_param(self, param: Param, value: float) -> None:
        self._require_connected()
        cfg = _PARAM_MAP.get(param)
        if cfg is None:
            raise ValueError(f"Unsupported parameter: {param}")
        self._get_sdk().set_config(self._camera_id, cfg, int(value))

    def get_param(self, param: Param) -> float:
        self._require_connected()
        cfg = _PARAM_MAP.get(param)
        if cfg is None:
            raise ValueError(f"Unsupported parameter: {param}")
        val, _ = self._get_sdk().get_config(self._camera_id, cfg)
        return float(val)

    # --- Capture ---

    def capture_single(self) -> Frame:
        was_live = self._live
        if not was_live:
            self.start_live()
        frame = None
        for _ in range(100):
            frame = self.get_live_frame(timeout_ms=500)
            if frame is not None:
                break
        if not was_live:
            self.stop_live()
        if frame is None:
            raise RuntimeError("Failed to capture frame")
        return frame

    def start_live(self) -> None:
        if self._live:
            return
        self._get_sdk().start_exposure(self._camera_id, single_frame=False)
        self._live = True
        log.info("Live streaming started")

    def stop_live(self) -> None:
        if not self._live:
            return
        self._get_sdk().stop_exposure(self._camera_id)
        self._live = False
        log.info("Live streaming stopped")

    def get_live_frame(self, timeout_ms: int = 200) -> Frame | None:
        if not self._live:
            return None
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        ok = self._get_sdk().get_image_data(
            self._camera_id, self._frame_buf, buf_size, timeout_ms)
        if not ok:
            return None
        return self._make_frame(self._roi.width, self._roi.height, self._bit_depth)

    def is_live(self) -> bool:
        return self._live

    # --- Internal helpers ---

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Camera not connected")

    def _make_frame(self, w: int, h: int, bit_depth: int) -> Frame:
        self._frame_seq += 1
        if bit_depth == 16:
            nbytes = h * w * 2
            arr = np.frombuffer(self._frame_buf, dtype=np.uint8, count=nbytes)
            arr = arr.view(np.uint16).reshape(h, w).copy()
        else:
            nbytes = h * w
            arr = np.frombuffer(self._frame_buf, dtype=np.uint8, count=nbytes)
            arr = arr.reshape(h, w).copy()
        return Frame(
            data=arr,
            width=w,
            height=h,
            bit_depth=bit_depth,
            timestamp_ns=time.time_ns(),
            sequence=self._frame_seq,
        )

    def _parse_poa_id(self, camera_id: str) -> int:
        # Format: "POA-ModelName-123"
        parts = camera_id.rsplit("-", 1)
        return int(parts[-1])

    def _find_prop(self, camera_id: str):
        sdk = self._get_sdk()
        poa_id = self._parse_poa_id(camera_id)
        n = sdk.get_camera_count()
        for i in range(n):
            prop = sdk.get_camera_properties(i)
            if prop.cameraID == poa_id:
                return prop
        raise RuntimeError(f"Camera {camera_id} not found")

    def _find_prop_by_id(self, poa_id: int):
        sdk = self._get_sdk()
        n = sdk.get_camera_count()
        for i in range(n):
            prop = sdk.get_camera_properties(i)
            if prop.cameraID == poa_id:
                return prop
        raise RuntimeError(f"Camera ID {poa_id} not found")

    def _make_info(self, camera_id: str, prop) -> CameraInfo:
        name = prop.cameraModelName.decode("ascii", errors="replace").strip()
        return CameraInfo(
            camera_id=camera_id,
            model=name,
            sensor_width=prop.maxWidth,
            sensor_height=prop.maxHeight,
            pixel_width_um=prop.pixelSize,
            pixel_height_um=prop.pixelSize,
            max_bit_depth=prop.bitDepth,
            is_color=bool(prop.isColorCamera),
        )
