"""ZWO ASI camera backend implementing CameraBase."""

from __future__ import annotations

import ctypes
import logging
import time

import numpy as np

from ..abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI
from .constants import ControlType, ImgType
from .sdk import AsiError, AsiSdk

log = logging.getLogger(__name__)

# Map vendor-neutral Param to ASI ControlType
_PARAM_MAP: dict[Param, ControlType] = {
    Param.EXPOSURE: ControlType.EXPOSURE,
    Param.GAIN: ControlType.GAIN,
    Param.OFFSET: ControlType.OFFSET,
    Param.USB_TRAFFIC: ControlType.BANDWIDTHOVERLOAD,
    Param.GAMMA: ControlType.GAMMA,
    Param.BRIGHTNESS: ControlType.OFFSET,
}


class AsiCamera(CameraBase):
    """ZWO ASI camera backend."""

    # Class-level SDK singleton
    _sdk: AsiSdk | None = None

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

        # Pre-connect settings
        self._pending_bit_depth = 8
        self._pending_roi: ROI | None = None

    def _get_sdk(self) -> AsiSdk:
        if AsiCamera._sdk is None:
            AsiCamera._sdk = AsiSdk(self._lib_path)
            log.info("ASI SDK version: %s", AsiCamera._sdk.get_sdk_version())
        return AsiCamera._sdk

    # --- Discovery ---

    def enumerate(self) -> list[CameraInfo]:
        sdk = self._get_sdk()
        n = sdk.get_num_cameras()
        cameras = []
        for i in range(n):
            prop = sdk.get_camera_property(i)
            name = prop.Name.decode("ascii", errors="replace").strip()
            # Build a unique camera_id from name + ASI ID
            cam_id = f"{name}-{prop.CameraID}"
            cameras.append(CameraInfo(
                camera_id=cam_id,
                model=name,
                sensor_width=prop.MaxWidth,
                sensor_height=prop.MaxHeight,
                pixel_width_um=prop.PixelSize,
                pixel_height_um=prop.PixelSize,
                max_bit_depth=prop.BitDepth,
                is_color=bool(prop.IsColorCam),
            ))
        return cameras

    # --- Pre-open (for UI population before connect) ---

    def pre_open(self, camera_id: str) -> None:
        """Open camera to query info; keep open for connect() to reuse."""
        sdk = self._get_sdk()
        asi_id = self._parse_asi_id(camera_id)
        sdk.open_camera(asi_id)
        prop = self._find_prop(camera_id)
        self._camera_id = asi_id
        self._info = self._make_info(camera_id, prop)
        log.info("Pre-opened ASI camera %s (%dx%d)",
                 camera_id, prop.MaxWidth, prop.MaxHeight)

    def get_pre_open_info(self) -> CameraInfo | None:
        return self._info

    # --- Connection ---

    def set_connect_bit_depth(self, bit_depth: int) -> None:
        self._pending_bit_depth = bit_depth

    def set_connect_roi(self, roi: ROI) -> None:
        self._pending_roi = roi

    def connect(self, camera_id: str) -> None:
        sdk = self._get_sdk()
        asi_id = self._parse_asi_id(camera_id)

        # Open if not already opened by pre_open
        if self._camera_id != asi_id:
            sdk.open_camera(asi_id)
            self._camera_id = asi_id

        # Init
        sdk.init_camera(asi_id)

        # Get camera property for info
        prop = self._find_prop(camera_id)
        self._info = self._make_info(camera_id, prop)

        # Apply settings
        self._bit_depth = self._pending_bit_depth
        self._bin_mode = 1

        if self._pending_roi:
            self._roi = self._pending_roi
        else:
            self._roi = ROI(0, 0, prop.MaxWidth, prop.MaxHeight)

        img_type = ImgType.RAW16 if self._bit_depth == 16 else ImgType.RAW8
        sdk.set_roi_format(asi_id, self._roi.width, self._roi.height,
                           self._bin_mode, img_type)
        sdk.set_start_pos(asi_id, self._roi.x, self._roi.y)

        # Allocate frame buffer
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        self._frame_buf = (ctypes.c_uint8 * buf_size)()
        self._frame_seq = 0

        # Set defaults
        try:
            sdk.set_control_value(asi_id, ControlType.BANDWIDTHOVERLOAD, 40)
            log.info("Set default USB bandwidth: 40")
        except AsiError:
            pass
        try:
            sdk.set_control_value(asi_id, ControlType.EXPOSURE, 20000)
            log.info("Set default exposure: 20000us")
        except AsiError:
            pass
        try:
            sdk.set_control_value(asi_id, ControlType.GAIN, 30)
            log.info("Set default gain: 30")
        except AsiError:
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
            except AsiError:
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
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            return None
        sdk = self._get_sdk()
        # Find this control in the camera's control list
        n = sdk.get_num_controls(self._camera_id)
        for i in range(n):
            caps = sdk.get_control_caps(self._camera_id, i)
            if caps.ControlType == ctrl:
                return ParamRange(
                    min_val=float(caps.MinValue),
                    max_val=float(caps.MaxValue),
                    step=1.0,
                )
        return None

    def get_supported_bin_modes(self) -> list[int]:
        self._require_connected()
        prop = self._find_prop_by_id(self._camera_id)
        modes = []
        for b in prop.SupportedBins:
            if b == 0:
                break
            modes.append(b)
        return sorted(modes)

    def get_supported_bit_depths(self) -> list[int]:
        self._require_connected()
        prop = self._find_prop_by_id(self._camera_id)
        depths = []
        for fmt in prop.SupportedVideoFormat:
            if fmt == ImgType.END:
                break
            if fmt in (ImgType.RAW8, ImgType.Y8):
                if 8 not in depths:
                    depths.append(8)
            elif fmt == ImgType.RAW16:
                depths.append(16)
        return sorted(depths) if depths else [8]

    # --- Parameters ---

    def set_exposure(self, microseconds: float) -> None:
        self._require_connected()
        self._get_sdk().set_control_value(
            self._camera_id, ControlType.EXPOSURE, int(microseconds),
            auto=self._auto_exposure)

    def get_exposure(self) -> float:
        self._require_connected()
        val, _ = self._get_sdk().get_control_value(
            self._camera_id, ControlType.EXPOSURE)
        return float(val)

    def set_gain(self, value: float) -> None:
        self._require_connected()
        self._get_sdk().set_control_value(
            self._camera_id, ControlType.GAIN, int(value),
            auto=self._auto_gain)

    def get_gain(self) -> float:
        self._require_connected()
        val, _ = self._get_sdk().get_control_value(
            self._camera_id, ControlType.GAIN)
        return float(val)

    # --- Auto exposure / auto gain ---

    def supports_auto_exposure(self) -> bool:
        return self._is_auto_supported(ControlType.EXPOSURE)

    def supports_auto_gain(self) -> bool:
        return self._is_auto_supported(ControlType.GAIN)

    def set_auto_exposure(self, enabled: bool) -> None:
        self._require_connected()
        self._auto_exposure = enabled
        # Re-set the current exposure value with the new auto flag
        val, _ = self._get_sdk().get_control_value(
            self._camera_id, ControlType.EXPOSURE)
        self._get_sdk().set_control_value(
            self._camera_id, ControlType.EXPOSURE, val, auto=enabled)
        log.info("Auto-exposure %s", "enabled" if enabled else "disabled")

    def set_auto_gain(self, enabled: bool) -> None:
        self._require_connected()
        self._auto_gain = enabled
        val, _ = self._get_sdk().get_control_value(
            self._camera_id, ControlType.GAIN)
        self._get_sdk().set_control_value(
            self._camera_id, ControlType.GAIN, val, auto=enabled)
        log.info("Auto-gain %s", "enabled" if enabled else "disabled")

    def get_auto_exposure(self) -> bool:
        if not self._connected:
            return False
        _, auto = self._get_sdk().get_control_value(
            self._camera_id, ControlType.EXPOSURE)
        return auto

    def get_auto_gain(self) -> bool:
        if not self._connected:
            return False
        _, auto = self._get_sdk().get_control_value(
            self._camera_id, ControlType.GAIN)
        return auto

    def _is_auto_supported(self, control: ControlType) -> bool:
        """Check if a control supports auto mode via ASI_CONTROL_CAPS."""
        if not self._connected or self._camera_id is None:
            return False
        sdk = self._get_sdk()
        n = sdk.get_num_controls(self._camera_id)
        for i in range(n):
            caps = sdk.get_control_caps(self._camera_id, i)
            if caps.ControlType == control:
                return bool(caps.IsAutoSupported)
        return False

    def get_sensor_temperature(self) -> float | None:
        if not self._connected or self._camera_id is None:
            return None
        try:
            val, _ = self._get_sdk().get_control_value(
                self._camera_id, ControlType.TEMPERATURE)
            return val / 10.0  # ASI returns temperature * 10
        except Exception:
            return None

    def set_bin_mode(self, bin_factor: int) -> None:
        """Set binning. Caller must stop live streaming first."""
        self._require_connected()
        sdk = self._get_sdk()
        self._bin_mode = bin_factor
        # Recalculate ROI from full sensor
        if self._info:
            w = self._info.sensor_width // bin_factor
            h = self._info.sensor_height // bin_factor
            self._roi = ROI(0, 0, w, h)
        img_type = ImgType.RAW16 if self._bit_depth == 16 else ImgType.RAW8
        sdk.set_roi_format(self._camera_id, self._roi.width, self._roi.height,
                           bin_factor, img_type)
        sdk.set_start_pos(self._camera_id, 0, 0)
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
        img_type = ImgType.RAW16 if self._bit_depth == 16 else ImgType.RAW8
        sdk.set_roi_format(self._camera_id, roi.width, roi.height,
                           self._bin_mode, img_type)
        sdk.set_start_pos(self._camera_id, roi.x, roi.y)

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
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            raise ValueError(f"Unsupported parameter: {param}")
        self._get_sdk().set_control_value(self._camera_id, ctrl, int(value))

    def get_param(self, param: Param) -> float:
        self._require_connected()
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            raise ValueError(f"Unsupported parameter: {param}")
        val, _ = self._get_sdk().get_control_value(self._camera_id, ctrl)
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
        self._get_sdk().start_video_capture(self._camera_id)
        self._live = True
        log.info("Live streaming started")

    def stop_live(self) -> None:
        if not self._live:
            return
        self._get_sdk().stop_video_capture(self._camera_id)
        self._live = False
        log.info("Live streaming stopped")

    def get_live_frame(self, timeout_ms: int = 200) -> Frame | None:
        if not self._live:
            return None
        sdk = self._get_sdk()
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        ok = sdk.get_video_data(self._camera_id, self._frame_buf, buf_size, timeout_ms)
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

    def _parse_asi_id(self, camera_id: str) -> int:
        """Extract ASI integer camera ID from our camera_id string."""
        # Format: "ModelName-123"
        parts = camera_id.rsplit("-", 1)
        return int(parts[-1])

    def _find_prop(self, camera_id: str):
        """Find ASI_CAMERA_INFO by our camera_id string."""
        sdk = self._get_sdk()
        asi_id = self._parse_asi_id(camera_id)
        n = sdk.get_num_cameras()
        for i in range(n):
            prop = sdk.get_camera_property(i)
            if prop.CameraID == asi_id:
                return prop
        raise RuntimeError(f"Camera {camera_id} not found")

    def _find_prop_by_id(self, asi_id: int):
        """Find ASI_CAMERA_INFO by ASI integer ID."""
        sdk = self._get_sdk()
        n = sdk.get_num_cameras()
        for i in range(n):
            prop = sdk.get_camera_property(i)
            if prop.CameraID == asi_id:
                return prop
        raise RuntimeError(f"Camera ID {asi_id} not found")

    def _make_info(self, camera_id: str, prop) -> CameraInfo:
        name = prop.Name.decode("ascii", errors="replace").strip()
        return CameraInfo(
            camera_id=camera_id,
            model=name,
            sensor_width=prop.MaxWidth,
            sensor_height=prop.MaxHeight,
            pixel_width_um=prop.PixelSize,
            pixel_height_um=prop.PixelSize,
            max_bit_depth=prop.BitDepth,
            is_color=bool(prop.IsColorCam),
        )
