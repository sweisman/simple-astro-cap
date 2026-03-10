"""QHY camera backend implementing CameraBase."""

from __future__ import annotations

import ctypes
import logging
import time

import numpy as np

from ..abc import CameraBase, CameraInfo, Frame, Param, ParamRange, ROI
from .constants import ControlId, StreamMode
from .sdk import QhyError, QhySdk

log = logging.getLogger(__name__)

# Map our vendor-neutral Param to QHY ControlId
_PARAM_MAP: dict[Param, ControlId] = {
    Param.EXPOSURE: ControlId.EXPOSURE,
    Param.GAIN: ControlId.GAIN,
    Param.OFFSET: ControlId.OFFSET,
    Param.USB_TRAFFIC: ControlId.USBTRAFFIC,
    Param.SPEED: ControlId.SPEED,
    Param.BRIGHTNESS: ControlId.BRIGHTNESS,
    Param.CONTRAST: ControlId.CONTRAST,
    Param.GAMMA: ControlId.GAMMA,
    Param.COOLER_TARGET: ControlId.COOLER,
}

_BIN_CONTROL_MAP: dict[int, ControlId] = {
    1: ControlId.CAM_BIN1X1MODE,
    2: ControlId.CAM_BIN2X2MODE,
    3: ControlId.CAM_BIN3X3MODE,
    4: ControlId.CAM_BIN4X4MODE,
}


class QhyCamera(CameraBase):
    """QHY camera backend using libqhyccd.so via ctypes.

    The QHY SDK requires this initialization order:
      1. OpenQHYCCD
      2. SetQHYCCDStreamMode (before InitQHYCCD)
      3. SetQHYCCDReadMode (before InitQHYCCD)
      4. InitQHYCCD
      5. SetQHYCCDBitsMode
      6. SetQHYCCDBinMode
      7. SetQHYCCDResolution
      8. SetQHYCCDParam (exposure, gain, etc.)
      9. BeginQHYCCDLive

    Bit depth, binning, and resolution must all be set before
    starting live capture. Changing them requires disconnect/reconnect.
    """

    _sdk: QhySdk | None = None
    _sdk_initialized: bool = False

    def __init__(self, lib_path: str | None = None):
        self._lib_path = lib_path
        self._handle = None
        self._pre_open_handle = None
        self._pre_open_camera_id: str | None = None
        self._pre_open_info: CameraInfo | None = None
        self._info: CameraInfo | None = None
        self._connected = False
        self._live = False
        self._frame_buf: ctypes.Array | None = None
        self._frame_seq = 0
        self._bit_depth = 8
        self._bin_mode = 1
        self._roi: ROI | None = None
        self._effective_area: tuple[int, int, int, int] | None = None
        # Pre-connect settings (must be set before connect)
        self._pending_bit_depth: int = 8
        self._pending_roi: ROI | None = None

    @classmethod
    def _get_sdk(cls, lib_path: str | None = None) -> QhySdk:
        if cls._sdk is None:
            cls._sdk = QhySdk(lib_path)
        return cls._sdk

    @classmethod
    def _ensure_init(cls, lib_path: str | None = None) -> QhySdk:
        sdk = cls._get_sdk(lib_path)
        if not cls._sdk_initialized:
            sdk.init_resource()
            cls._sdk_initialized = True
        return sdk

    @staticmethod
    def enumerate(lib_path: str | None = None) -> list[CameraInfo]:
        sdk = QhyCamera._ensure_init(lib_path)
        count = sdk.scan()
        cameras = []
        for i in range(count):
            cam_id = sdk.get_id(i)
            model = cam_id.split("-")[0] if "-" in cam_id else cam_id
            # NOTE: Do NOT open/close the camera here. Opening then closing
            # corrupts the QHY SDK's internal USB state, causing all subsequent
            # SetStreamMode/InitQHYCCD calls to fail until the camera is
            # physically replugged. Sensor info will be populated on connect().
            cameras.append(
                CameraInfo(
                    camera_id=cam_id,
                    model=model,
                    sensor_width=0,
                    sensor_height=0,
                    pixel_width_um=0.0,
                    pixel_height_um=0.0,
                    max_bit_depth=16,
                    is_color=False,
                )
            )
        return cameras

    def pre_open(self, camera_id: str) -> None:
        """Open camera to query chip info. Handle is kept for connect().

        Do NOT close and reopen — that corrupts QHY SDK USB state.
        """
        sdk = self._ensure_init(self._lib_path)

        # Close previous pre-open if different camera
        if self._pre_open_handle is not None and self._pre_open_camera_id != camera_id:
            try:
                sdk.close(self._pre_open_handle)
            except QhyError:
                pass
            self._pre_open_handle = None

        if self._pre_open_handle is None:
            self._pre_open_handle = sdk.open(camera_id)
            self._pre_open_camera_id = camera_id

        _, _, iw, ih, pw, ph, bpp = sdk.get_chip_info(self._pre_open_handle)
        model = camera_id.split("-")[0] if "-" in camera_id else camera_id
        self._pre_open_info = CameraInfo(
            camera_id=camera_id,
            model=model,
            sensor_width=iw,
            sensor_height=ih,
            pixel_width_um=pw,
            pixel_height_um=ph,
            max_bit_depth=bpp,
            is_color=False,
        )

    def get_pre_open_info(self) -> CameraInfo | None:
        return self._pre_open_info

    def set_connect_bit_depth(self, bits: int) -> None:
        """Set bit depth to use on next connect. Must be called before connect()."""
        self._pending_bit_depth = bits

    def set_connect_roi(self, roi: ROI | None) -> None:
        """Set ROI to use on next connect. None = full sensor. Must be called before connect()."""
        self._pending_roi = roi

    def connect(self, camera_id: str) -> None:
        if self._connected:
            self.disconnect()

        sdk = self._ensure_init(self._lib_path)

        # Reuse pre-opened handle if available for the same camera
        if self._pre_open_handle is not None and self._pre_open_camera_id == camera_id:
            self._handle = self._pre_open_handle
            self._pre_open_handle = None
            self._pre_open_camera_id = None
        else:
            self._handle = sdk.open(camera_id)

        # Must set stream mode BEFORE InitQHYCCD
        # NOTE: Do NOT call set_read_mode — AstroDMx doesn't and it works.
        sdk.set_stream_mode(self._handle, StreamMode.LIVE)
        sdk.init_camera(self._handle)

        # Query chip info
        _, _, iw, ih, pw, ph, bpp = sdk.get_chip_info(self._handle)
        self._effective_area = sdk.get_effective_area(self._handle)
        ex, ey, ew, eh = self._effective_area

        self._info = CameraInfo(
            camera_id=camera_id,
            model=camera_id.split("-")[0] if "-" in camera_id else camera_id,
            sensor_width=ew,
            sensor_height=eh,
            pixel_width_um=pw,
            pixel_height_um=ph,
            max_bit_depth=16 if sdk.is_control_available(self._handle, ControlId.CAM_16BITS) else 8,
            is_color=False,
        )

        # Allocate frame buffer
        mem_len = sdk.get_mem_length(self._handle)
        self._frame_buf = (ctypes.c_uint8 * mem_len)()

        # Apply pre-connect settings in the required order:
        # 1. Bit depth
        self._bit_depth = self._pending_bit_depth
        sdk.set_bits_mode(self._handle, self._bit_depth)
        log.info("Set bit depth: %d", self._bit_depth)

        # 2. Binning
        self._bin_mode = 1
        sdk.set_bin_mode(self._handle, 1, 1)

        # 3. Resolution (ROI)
        if self._pending_roi is not None:
            self._roi = self._pending_roi
        else:
            self._roi = ROI(ex, ey, ew, eh)
        sdk.set_resolution(self._handle, self._roi.x, self._roi.y,
                           self._roi.width, self._roi.height)
        log.info("Set resolution: %d,%d %dx%d", self._roi.x, self._roi.y,
                 self._roi.width, self._roi.height)

        # 4. Set default params so camera can produce frames
        for ctrl, val, name in [
            (ControlId.USBTRAFFIC, 30.0, "usbtraffic"),
            (ControlId.EXPOSURE, 20000.0, "exposure"),
            (ControlId.GAIN, 30.0, "gain"),
        ]:
            if sdk.is_control_available(self._handle, ctrl):
                sdk.set_param(self._handle, ctrl, val)
                log.info("Set default %s: %.0f", name, val)

        self._connected = True
        self._frame_seq = 0
        log.info("Connected to %s (%dx%d %dbit)", camera_id, ew, eh, self._bit_depth)

    def disconnect(self) -> None:
        if not self._connected:
            return
        if self._live:
            self.stop_live()
        sdk = self._get_sdk()
        try:
            sdk.close(self._handle)
        except QhyError:
            pass
        self._handle = None
        self._connected = False
        self._info = None
        self._frame_buf = None

    def is_connected(self) -> bool:
        return self._connected

    def get_info(self) -> CameraInfo:
        self._require_connected()
        return self._info  # type: ignore[return-value]

    def get_effective_area(self) -> ROI:
        """Return the full sensor effective area as an ROI."""
        self._require_connected()
        ex, ey, ew, eh = self._effective_area  # type: ignore[misc]
        return ROI(ex, ey, ew, eh)

    def get_param_range(self, param: Param) -> ParamRange | None:
        self._require_connected()
        sdk = self._get_sdk()
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            return None
        if not sdk.is_control_available(self._handle, ctrl):
            return None
        result = sdk.get_param_min_max_step(self._handle, ctrl)
        if result is None:
            return None
        return ParamRange(*result)

    def get_supported_bin_modes(self) -> list[int]:
        """Return bin modes that actually work (validated by trying SetBinMode).

        The SDK's IsControlAvailable can report modes that fail in practice,
        so we try each one and keep only those that succeed.  We restore the
        current bin mode afterwards.
        """
        self._require_connected()
        sdk = self._get_sdk()
        modes = [1]  # 1x1 always works even if not reported by SDK
        for factor, ctrl in _BIN_CONTROL_MAP.items():
            if factor == 1:
                continue
            if not sdk.is_control_available(self._handle, ctrl):
                continue
            try:
                sdk.set_bin_mode(self._handle, factor, factor)
                modes.append(factor)
            except QhyError:
                log.debug("Bin %dx%d reported available but SetBinMode failed", factor, factor)
        # Restore current bin mode
        sdk.set_bin_mode(self._handle, self._bin_mode, self._bin_mode)
        return sorted(modes)

    def get_supported_bit_depths(self) -> list[int]:
        self._require_connected()
        sdk = self._get_sdk()
        depths = []
        if sdk.is_control_available(self._handle, ControlId.CAM_8BITS):
            depths.append(8)
        if sdk.is_control_available(self._handle, ControlId.CAM_16BITS):
            depths.append(16)
        return depths

    def set_exposure(self, microseconds: float) -> None:
        self._set_ctrl(ControlId.EXPOSURE, microseconds)

    def get_exposure(self) -> float:
        return self._get_ctrl(ControlId.EXPOSURE)

    def set_gain(self, value: float) -> None:
        self._set_ctrl(ControlId.GAIN, value)

    def get_gain(self) -> float:
        return self._get_ctrl(ControlId.GAIN)

    # --- Auto-exposure ---
    # QHY SDK has a single auto-exposure system (control ID 88 / 0x58) that
    # manages both exposure and gain together. There is no separate auto-gain.
    # SetQHYCCDParam(h, 88, value): 0=off, 1=on (method 0), 2+ = other methods
    # GetQHYCCDParam(h, 88): returns auto-exposure status

    def supports_auto_exposure(self) -> bool:
        self._require_connected()
        sdk = self._get_sdk()
        return sdk.is_control_available(self._handle, ControlId.CAM_AUTOEXPOSURE)

    def supports_auto_gain(self) -> bool:
        # QHY auto-exposure controls gain too — expose as supported
        return self.supports_auto_exposure()

    def auto_exposure_gain_coupled(self) -> bool:
        return True

    def set_auto_exposure(self, enabled: bool) -> None:
        self._require_connected()
        sdk = self._get_sdk()
        sdk.set_param(self._handle, ControlId.CAM_AUTOEXPOSURE,
                      1.0 if enabled else 0.0)
        log.info("Auto-exposure %s", "enabled" if enabled else "disabled")

    def set_auto_gain(self, enabled: bool) -> None:
        # QHY auto-exposure manages gain too — same toggle
        self.set_auto_exposure(enabled)

    def get_auto_exposure(self) -> bool:
        if not self._connected:
            return False
        sdk = self._get_sdk()
        status = sdk.get_param(self._handle, ControlId.CAM_AUTOEXPOSURE)
        return status != 0.0

    def get_auto_gain(self) -> bool:
        return self.get_auto_exposure()

    def set_bin_mode(self, bin_factor: int) -> None:
        """Set binning mode. Caller must stop live streaming first.

        Recalculates ROI from the full sensor size divided by bin factor.
        """
        self._require_connected()
        sdk = self._get_sdk()
        sdk.set_bin_mode(self._handle, bin_factor, bin_factor)
        self._bin_mode = bin_factor
        # Recalculate resolution: full sensor / bin factor
        if self._info:
            w = self._info.sensor_width // bin_factor
            h = self._info.sensor_height // bin_factor
            self._roi = ROI(0, 0, w, h)
            sdk.set_resolution(self._handle, 0, 0, w, h)
            log.info("Bin %dx%d: resolution %dx%d", bin_factor, bin_factor, w, h)

    def get_bin_mode(self) -> int:
        return self._bin_mode

    def set_roi(self, roi: ROI) -> None:
        self._require_connected()
        sdk = self._get_sdk()
        sdk.set_resolution(self._handle, roi.x, roi.y, roi.width, roi.height)
        self._roi = roi

    def get_roi(self) -> ROI:
        self._require_connected()
        return self._roi  # type: ignore[return-value]

    def set_bit_depth(self, bits: int) -> None:
        if bits not in (8, 16):
            raise ValueError(f"Unsupported bit depth: {bits}")
        self._require_connected()
        sdk = self._get_sdk()
        sdk.set_bits_mode(self._handle, bits)
        self._bit_depth = bits

    def get_bit_depth(self) -> int:
        return self._bit_depth

    def set_param(self, param: Param, value: float) -> None:
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            raise ValueError(f"Unsupported parameter: {param}")
        self._set_ctrl(ctrl, value)

    def get_param(self, param: Param) -> float:
        ctrl = _PARAM_MAP.get(param)
        if ctrl is None:
            raise ValueError(f"Unsupported parameter: {param}")
        return self._get_ctrl(ctrl)

    def capture_single(self) -> Frame:
        self._require_connected()
        if self._live:
            raise RuntimeError("Cannot capture single frame while live streaming")
        sdk = self._get_sdk()
        sdk.begin_live(self._handle)
        try:
            for _ in range(100):  # timeout ~5s at 20fps
                result = sdk.get_live_frame(self._handle, self._frame_buf)
                if result is not None:
                    w, h, bpp, channels = result
                    return self._make_frame(w, h, bpp)
                time.sleep(0.05)
            raise TimeoutError("Timed out waiting for single frame")
        finally:
            sdk.stop_live(self._handle)

    def start_live(self) -> None:
        self._require_connected()
        if self._live:
            return
        sdk = self._get_sdk()
        sdk.begin_live(self._handle)
        self._live = True
        log.info("Live streaming started")

    def stop_live(self) -> None:
        if not self._live:
            return
        sdk = self._get_sdk()
        try:
            sdk.stop_live(self._handle)
        except QhyError:
            pass
        self._live = False
        log.info("Live streaming stopped")

    def get_live_frame(self, timeout_ms: int = 1000) -> Frame | None:
        if not self._live:
            return None
        sdk = self._get_sdk()
        result = sdk.get_live_frame(self._handle, self._frame_buf)
        if result is None:
            return None
        w, h, bpp, channels = result
        return self._make_frame(w, h, bpp)

    def is_live(self) -> bool:
        return self._live

    # --- Internal helpers ---

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Camera not connected")

    def _set_ctrl(self, ctrl: ControlId, value: float) -> None:
        self._require_connected()
        sdk = self._get_sdk()
        sdk.set_param(self._handle, ctrl, value)

    def _get_ctrl(self, ctrl: ControlId) -> float:
        self._require_connected()
        sdk = self._get_sdk()
        return sdk.get_param(self._handle, ctrl)

    def _make_frame(self, w: int, h: int, bpp: int) -> Frame:
        self._frame_seq += 1
        if bpp == 16:
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
            bit_depth=bpp,
            timestamp_ns=time.monotonic_ns(),
            sequence=self._frame_seq,
        )
