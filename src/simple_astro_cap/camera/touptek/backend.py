"""Touptek camera backend implementing CameraBase."""

from __future__ import annotations

import ctypes
import logging
import time

import numpy as np

from ..abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI
from .constants import ToupOption
from .sdk import ToupcamError, ToupcamSdk

log = logging.getLogger(__name__)


class ToupcamCamera(CameraBase):
    """Touptek camera backend (pull mode)."""

    _sdk: ToupcamSdk | None = None

    def __init__(self, lib_path: str | None = None):
        self._lib_path = lib_path
        self._handle = None
        self._device_id: bytes | None = None
        self._camera_id_str: str | None = None
        self._connected = False
        self._live = False
        self._info: CameraInfo | None = None
        self._roi: ROI | None = None
        self._bin_mode = 1
        self._bit_depth = 8
        self._frame_buf: ctypes.Array | None = None
        self._frame_seq = 0

        self._pending_bit_depth = 8
        self._pending_roi: ROI | None = None

        # Cached ranges
        self._exp_range: tuple[int, int, int] | None = None
        self._gain_range: tuple[int, int, int] | None = None

    def _get_sdk(self) -> ToupcamSdk:
        if ToupcamCamera._sdk is None:
            ToupcamCamera._sdk = ToupcamSdk(self._lib_path)
        return ToupcamCamera._sdk

    # --- Discovery ---

    def enumerate(self) -> list[CameraInfo]:
        sdk = self._get_sdk()
        devices = sdk.enum_v2()
        cameras = []
        for dev in devices:
            name = dev.displayname.decode("ascii", errors="replace").strip()
            dev_id = dev.id.decode("ascii", errors="replace").strip()
            cam_id = f"TOUP-{dev_id}"
            # We can't get full sensor info without opening, so use placeholder
            cameras.append(CameraInfo(
                camera_id=cam_id,
                model=name,
                sensor_width=0,  # filled on connect
                sensor_height=0,
                pixel_width_um=0.0,
                pixel_height_um=0.0,
                max_bit_depth=8,  # updated on connect
                is_color=True,  # updated on connect
            ))
        return cameras

    # --- Pre-open ---

    def pre_open(self, camera_id: str) -> None:
        sdk = self._get_sdk()
        dev_id = self._parse_device_id(camera_id)
        handle = sdk.open(dev_id)
        self._handle = handle
        self._device_id = dev_id
        self._camera_id_str = camera_id
        self._info = self._query_info(camera_id, handle)
        log.info("Pre-opened Touptek camera %s (%dx%d)",
                 camera_id, self._info.sensor_width, self._info.sensor_height)

    def get_pre_open_info(self) -> CameraInfo | None:
        return self._info

    # --- Connection ---

    def set_connect_bit_depth(self, bit_depth: int) -> None:
        self._pending_bit_depth = bit_depth

    def set_connect_roi(self, roi: ROI) -> None:
        self._pending_roi = roi

    def connect(self, camera_id: str) -> None:
        sdk = self._get_sdk()
        dev_id = self._parse_device_id(camera_id)

        # Open if not already opened by pre_open
        if self._handle is None or self._device_id != dev_id:
            if self._handle is not None:
                sdk.close(self._handle)
            self._handle = sdk.open(dev_id)
            self._device_id = dev_id

        self._camera_id_str = camera_id
        self._info = self._query_info(camera_id, self._handle)

        self._bit_depth = self._pending_bit_depth
        self._bin_mode = 1

        # Set bit depth option (0=8bit, 1=16bit)
        try:
            sdk.put_option(self._handle, ToupOption.BITDEPTH,
                           1 if self._bit_depth == 16 else 0)
        except ToupcamError:
            log.debug("Could not set bit depth option")

        # Set RAW mode for mono cameras
        try:
            sdk.put_option(self._handle, ToupOption.RAW, 1)
        except ToupcamError:
            pass

        # Get resolution
        w, h = sdk.get_size(self._handle)
        if self._pending_roi:
            self._roi = self._pending_roi
        else:
            self._roi = ROI(0, 0, w, h)

        # Cache parameter ranges
        try:
            self._exp_range = sdk.get_exp_time_range(self._handle)
        except ToupcamError:
            self._exp_range = None
        try:
            self._gain_range = sdk.get_expo_again_range(self._handle)
        except ToupcamError:
            self._gain_range = None

        # Allocate frame buffer
        bpp = 2 if self._bit_depth == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        self._frame_buf = (ctypes.c_uint8 * buf_size)()
        self._frame_seq = 0

        # Set default exposure
        try:
            sdk.put_expo_time(self._handle, 20000)
            log.info("Set default exposure: 20000us")
        except ToupcamError:
            pass

        self._connected = True
        log.info("Connected to %s (%dx%d %dbit)",
                 camera_id, self._roi.width, self._roi.height, self._bit_depth)

    def disconnect(self) -> None:
        if self._live:
            self.stop_live()
        if self._handle is not None:
            try:
                self._get_sdk().close(self._handle)
            except Exception:
                pass
        self._handle = None
        self._connected = False
        self._device_id = None
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
        if param == Param.EXPOSURE and self._exp_range:
            mn, mx, _ = self._exp_range
            return ParamRange(min_val=float(mn), max_val=float(mx), step=1.0)
        if param == Param.GAIN and self._gain_range:
            mn, mx, _ = self._gain_range
            return ParamRange(min_val=float(mn), max_val=float(mx), step=1.0)
        return None

    def get_supported_bin_modes(self) -> list[int]:
        # Touptek handles binning via resolution presets
        return [1]

    def get_supported_bit_depths(self) -> list[int]:
        self._require_connected()
        sdk = self._get_sdk()
        max_bits = sdk.get_max_bit_depth(self._handle)
        if max_bits >= 16:
            return [8, 16]
        return [8]

    # --- Parameters ---

    def set_exposure(self, microseconds: float) -> None:
        self._require_connected()
        self._get_sdk().put_expo_time(self._handle, int(microseconds))

    def get_exposure(self) -> float:
        self._require_connected()
        return float(self._get_sdk().get_expo_time(self._handle))

    def set_gain(self, value: float) -> None:
        self._require_connected()
        self._get_sdk().put_expo_again(self._handle, int(value))

    def get_gain(self) -> float:
        self._require_connected()
        return float(self._get_sdk().get_expo_again(self._handle))

    # --- Auto exposure ---

    def supports_auto_exposure(self) -> bool:
        return self._connected

    def supports_auto_gain(self) -> bool:
        # Touptek auto-exposure controls both exposure and gain together
        return False

    def auto_exposure_gain_coupled(self) -> bool:
        return True

    def set_auto_exposure(self, enabled: bool) -> None:
        self._require_connected()
        self._get_sdk().put_auto_expo_enable(self._handle, enabled)
        log.info("Auto-exposure %s", "enabled" if enabled else "disabled")

    def get_auto_exposure(self) -> bool:
        if not self._connected or self._handle is None:
            return False
        try:
            return self._get_sdk().get_auto_expo_enable(self._handle)
        except ToupcamError:
            return False

    def get_sensor_temperature(self) -> float | None:
        if not self._connected or self._handle is None:
            return None
        try:
            return self._get_sdk().get_temperature(self._handle)
        except Exception:
            return None

    def set_bin_mode(self, bin_factor: int) -> None:
        self._require_connected()
        self._bin_mode = bin_factor
        # Touptek uses resolution presets rather than separate bin setting
        log.info("Bin mode set to %d (Touptek uses resolution presets)", bin_factor)

    def get_bin_mode(self) -> int:
        return self._bin_mode

    def set_roi(self, roi: ROI) -> None:
        self._require_connected()
        self._roi = roi
        self._get_sdk().put_size(self._handle, roi.width, roi.height)

    def get_roi(self) -> ROI:
        self._require_connected()
        return self._roi  # type: ignore[return-value]

    def set_bit_depth(self, bit_depth: int) -> None:
        self._require_connected()
        self._bit_depth = bit_depth
        try:
            self._get_sdk().put_option(
                self._handle, ToupOption.BITDEPTH,
                1 if bit_depth == 16 else 0)
        except ToupcamError:
            pass

    def get_bit_depth(self) -> int:
        return self._bit_depth

    def set_param(self, param: Param, value: float) -> None:
        self._require_connected()
        if param == Param.EXPOSURE:
            self.set_exposure(value)
        elif param == Param.GAIN:
            self.set_gain(value)
        elif param == Param.OFFSET:
            try:
                self._get_sdk().put_option(
                    self._handle, ToupOption.BLACKLEVEL, int(value))
            except ToupcamError:
                raise ValueError("Offset/black level not supported")
        else:
            raise ValueError(f"Unsupported parameter: {param}")

    def get_param(self, param: Param) -> float:
        self._require_connected()
        if param == Param.EXPOSURE:
            return self.get_exposure()
        if param == Param.GAIN:
            return self.get_gain()
        if param == Param.OFFSET:
            try:
                return float(self._get_sdk().get_option(
                    self._handle, ToupOption.BLACKLEVEL))
            except ToupcamError:
                raise ValueError("Offset/black level not supported")
        raise ValueError(f"Unsupported parameter: {param}")

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
            time.sleep(0.01)
        if not was_live:
            self.stop_live()
        if frame is None:
            raise RuntimeError("Failed to capture frame")
        return frame

    def start_live(self) -> None:
        if self._live:
            return
        self._get_sdk().start_pull_mode(self._handle)
        self._live = True
        log.info("Live streaming started (pull mode)")

    def stop_live(self) -> None:
        if not self._live:
            return
        try:
            self._get_sdk().stop(self._handle)
        except ToupcamError:
            pass
        self._live = False
        log.info("Live streaming stopped")

    def get_live_frame(self, timeout_ms: int = 200) -> Frame | None:
        if not self._live:
            return None
        sdk = self._get_sdk()
        bits = 16 if self._bit_depth == 16 else 8
        bpp = 2 if bits == 16 else 1
        buf_size = self._roi.width * self._roi.height * bpp
        # Ensure buffer is large enough
        if self._frame_buf is None or ctypes.sizeof(self._frame_buf) < buf_size:
            self._frame_buf = (ctypes.c_uint8 * buf_size)()
        info = sdk.pull_image_v3(self._handle, self._frame_buf, bits)
        if info is None:
            return None
        return self._make_frame(info.width, info.height, self._bit_depth)

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

    def _parse_device_id(self, camera_id: str) -> bytes:
        # Format: "TOUP-<device_id>"
        prefix = "TOUP-"
        if camera_id.startswith(prefix):
            return camera_id[len(prefix):].encode("ascii")
        return camera_id.encode("ascii")

    def _query_info(self, camera_id: str, handle) -> CameraInfo:
        sdk = self._get_sdk()
        w, h = sdk.get_size(handle)
        max_bits = sdk.get_max_bit_depth(handle)
        is_mono = sdk.get_mono_mode(handle)
        try:
            px, py = sdk.get_pixel_size(handle, 0)
        except ToupcamError:
            px, py = 0.0, 0.0

        # Get display name from enumeration
        devices = sdk.enum_v2()
        dev_id_bytes = self._parse_device_id(camera_id)
        name = camera_id
        for dev in devices:
            if dev.id.rstrip(b'\x00') == dev_id_bytes:
                name = dev.displayname.decode("ascii", errors="replace").strip()
                break

        return CameraInfo(
            camera_id=camera_id,
            model=name,
            sensor_width=w,
            sensor_height=h,
            pixel_width_um=px,
            pixel_height_um=py,
            max_bit_depth=max_bits,
            is_color=not is_mono,
        )
