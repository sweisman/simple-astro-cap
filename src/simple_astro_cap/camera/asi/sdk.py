"""Thin ctypes wrapper around libASICamera2.so."""

from __future__ import annotations

import ctypes
import logging
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char,
    c_double,
    c_float,
    c_int,
    c_long,
    c_uint8,
)
from pathlib import Path

from .constants import ASI_SUCCESS, ControlType, ErrorCode, ImgType

log = logging.getLogger(__name__)


class AsiError(RuntimeError):
    """Error from ASI SDK call."""

    def __init__(self, func_name: str, ret: int):
        try:
            code = ErrorCode(ret)
            super().__init__(f"{func_name} failed: {code.name} ({ret})")
        except ValueError:
            super().__init__(f"{func_name} failed with code {ret}")
        self.func_name = func_name
        self.ret = ret


# --- C Structures ---

class ASI_CAMERA_INFO(Structure):
    _fields_ = [
        ("Name", c_char * 64),
        ("CameraID", c_int),
        ("MaxHeight", c_long),
        ("MaxWidth", c_long),
        ("IsColorCam", c_int),
        ("BayerPattern", c_int),
        ("SupportedBins", c_int * 16),
        ("SupportedVideoFormat", c_int * 8),
        ("PixelSize", c_double),
        ("MechanicalShutter", c_int),
        ("ST4Port", c_int),
        ("IsCoolerCam", c_int),
        ("IsUSB3Host", c_int),
        ("IsUSB3Camera", c_int),
        ("ElecPerADU", c_float),
        ("BitDepth", c_int),
        ("IsTriggerCam", c_int),
        ("Unused", c_char * 16),
    ]


class ASI_CONTROL_CAPS(Structure):
    _fields_ = [
        ("Name", c_char * 64),
        ("Description", c_char * 128),
        ("MaxValue", c_long),
        ("MinValue", c_long),
        ("DefaultValue", c_long),
        ("IsAutoSupported", c_int),
        ("IsWritable", c_int),
        ("ControlType", c_int),
        ("Unused", c_char * 32),
    ]


class ASI_ID(Structure):
    _fields_ = [("id", c_uint8 * 8)]


# Project-local lib directory
_PROJECT_LIB_DIR = Path(__file__).resolve().parents[4] / "lib"

_DEFAULT_LIB_PATHS = [
    str(_PROJECT_LIB_DIR / "libASICamera2.so"),
    "/usr/local/lib/libASICamera2.so",
    "libASICamera2.so",
]


class AsiSdk:
    """Low-level ctypes wrapper for libASICamera2.so."""

    def __init__(self, lib_path: str | Path | None = None):
        self._lib = self._load_lib(lib_path)
        self._setup_signatures()

    @staticmethod
    def _load_lib(lib_path: str | Path | None) -> ctypes.CDLL:
        if lib_path is not None:
            return ctypes.CDLL(str(lib_path))
        for path_str in _DEFAULT_LIB_PATHS:
            path = Path(path_str)
            try:
                return ctypes.CDLL(str(path))
            except OSError:
                continue
        raise OSError("Cannot find libASICamera2.so. Install the ZWO SDK or pass lib_path.")

    def _setup_signatures(self) -> None:
        lib = self._lib

        # Discovery
        lib.ASIGetNumOfConnectedCameras.argtypes = []
        lib.ASIGetNumOfConnectedCameras.restype = c_int

        lib.ASIGetCameraProperty.argtypes = [POINTER(ASI_CAMERA_INFO), c_int]
        lib.ASIGetCameraProperty.restype = c_int

        # Lifecycle
        lib.ASIOpenCamera.argtypes = [c_int]
        lib.ASIOpenCamera.restype = c_int

        lib.ASIInitCamera.argtypes = [c_int]
        lib.ASIInitCamera.restype = c_int

        lib.ASICloseCamera.argtypes = [c_int]
        lib.ASICloseCamera.restype = c_int

        # ROI & format
        lib.ASISetROIFormat.argtypes = [c_int, c_int, c_int, c_int, c_int]
        lib.ASISetROIFormat.restype = c_int

        lib.ASIGetROIFormat.argtypes = [
            c_int, POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_int),
        ]
        lib.ASIGetROIFormat.restype = c_int

        lib.ASISetStartPos.argtypes = [c_int, c_int, c_int]
        lib.ASISetStartPos.restype = c_int

        lib.ASIGetStartPos.argtypes = [c_int, POINTER(c_int), POINTER(c_int)]
        lib.ASIGetStartPos.restype = c_int

        # Controls
        lib.ASIGetNumOfControls.argtypes = [c_int, POINTER(c_int)]
        lib.ASIGetNumOfControls.restype = c_int

        lib.ASIGetControlCaps.argtypes = [c_int, c_int, POINTER(ASI_CONTROL_CAPS)]
        lib.ASIGetControlCaps.restype = c_int

        lib.ASISetControlValue.argtypes = [c_int, c_int, c_long, c_int]
        lib.ASISetControlValue.restype = c_int

        lib.ASIGetControlValue.argtypes = [
            c_int, c_int, POINTER(c_long), POINTER(c_int),
        ]
        lib.ASIGetControlValue.restype = c_int

        # Video capture
        lib.ASIStartVideoCapture.argtypes = [c_int]
        lib.ASIStartVideoCapture.restype = c_int

        lib.ASIStopVideoCapture.argtypes = [c_int]
        lib.ASIStopVideoCapture.restype = c_int

        lib.ASIGetVideoData.argtypes = [c_int, POINTER(c_uint8), c_long, c_int]
        lib.ASIGetVideoData.restype = c_int

        # Dropped frames
        lib.ASIGetDroppedFrames.argtypes = [c_int, POINTER(c_int)]
        lib.ASIGetDroppedFrames.restype = c_int

        # SDK version
        lib.ASIGetSDKVersion.argtypes = []
        lib.ASIGetSDKVersion.restype = ctypes.c_char_p

        # Serial number
        lib.ASIGetSerialNumber.argtypes = [c_int, POINTER(ASI_ID)]
        lib.ASIGetSerialNumber.restype = c_int

    def _check(self, func_name: str, ret: int) -> None:
        if ret != ASI_SUCCESS:
            raise AsiError(func_name, ret)

    # --- Discovery ---

    def get_num_cameras(self) -> int:
        return self._lib.ASIGetNumOfConnectedCameras()

    def get_camera_property(self, index: int) -> ASI_CAMERA_INFO:
        info = ASI_CAMERA_INFO()
        ret = self._lib.ASIGetCameraProperty(byref(info), c_int(index))
        self._check("ASIGetCameraProperty", ret)
        return info

    def get_sdk_version(self) -> str:
        return self._lib.ASIGetSDKVersion().decode("ascii", errors="replace")

    # --- Lifecycle ---

    def open_camera(self, camera_id: int) -> None:
        ret = self._lib.ASIOpenCamera(c_int(camera_id))
        self._check("ASIOpenCamera", ret)

    def init_camera(self, camera_id: int) -> None:
        ret = self._lib.ASIInitCamera(c_int(camera_id))
        self._check("ASIInitCamera", ret)

    def close_camera(self, camera_id: int) -> None:
        ret = self._lib.ASICloseCamera(c_int(camera_id))
        self._check("ASICloseCamera", ret)

    # --- ROI & Format ---

    def set_roi_format(
        self, camera_id: int, width: int, height: int, bin_: int, img_type: ImgType,
    ) -> None:
        ret = self._lib.ASISetROIFormat(
            c_int(camera_id), c_int(width), c_int(height),
            c_int(bin_), c_int(img_type),
        )
        self._check("ASISetROIFormat", ret)

    def get_roi_format(self, camera_id: int) -> tuple[int, int, int, int]:
        """Returns (width, height, bin, img_type)."""
        w, h, b, t = c_int(), c_int(), c_int(), c_int()
        ret = self._lib.ASIGetROIFormat(
            c_int(camera_id), byref(w), byref(h), byref(b), byref(t),
        )
        self._check("ASIGetROIFormat", ret)
        return w.value, h.value, b.value, t.value

    def set_start_pos(self, camera_id: int, x: int, y: int) -> None:
        ret = self._lib.ASISetStartPos(c_int(camera_id), c_int(x), c_int(y))
        self._check("ASISetStartPos", ret)

    # --- Controls ---

    def get_num_controls(self, camera_id: int) -> int:
        n = c_int()
        ret = self._lib.ASIGetNumOfControls(c_int(camera_id), byref(n))
        self._check("ASIGetNumOfControls", ret)
        return n.value

    def get_control_caps(self, camera_id: int, index: int) -> ASI_CONTROL_CAPS:
        caps = ASI_CONTROL_CAPS()
        ret = self._lib.ASIGetControlCaps(c_int(camera_id), c_int(index), byref(caps))
        self._check("ASIGetControlCaps", ret)
        return caps

    def set_control_value(
        self, camera_id: int, control: ControlType, value: int, auto: bool = False,
    ) -> None:
        ret = self._lib.ASISetControlValue(
            c_int(camera_id), c_int(control), c_long(value), c_int(int(auto)),
        )
        self._check("ASISetControlValue", ret)

    def get_control_value(self, camera_id: int, control: ControlType) -> tuple[int, bool]:
        """Returns (value, is_auto)."""
        val = c_long()
        auto = c_int()
        ret = self._lib.ASIGetControlValue(
            c_int(camera_id), c_int(control), byref(val), byref(auto),
        )
        self._check("ASIGetControlValue", ret)
        return val.value, bool(auto.value)

    # --- Video ---

    def start_video_capture(self, camera_id: int) -> None:
        ret = self._lib.ASIStartVideoCapture(c_int(camera_id))
        self._check("ASIStartVideoCapture", ret)

    def stop_video_capture(self, camera_id: int) -> None:
        ret = self._lib.ASIStopVideoCapture(c_int(camera_id))
        self._check("ASIStopVideoCapture", ret)

    def get_video_data(
        self, camera_id: int, buf: ctypes.Array, buf_size: int, timeout_ms: int = 200,
    ) -> bool:
        """Get one frame. Returns True on success, False on timeout."""
        ret = self._lib.ASIGetVideoData(
            c_int(camera_id), buf, c_long(buf_size), c_int(timeout_ms),
        )
        if ret == ErrorCode.ERROR_TIMEOUT:
            return False
        self._check("ASIGetVideoData", ret)
        return True

    def get_dropped_frames(self, camera_id: int) -> int:
        n = c_int()
        ret = self._lib.ASIGetDroppedFrames(c_int(camera_id), byref(n))
        self._check("ASIGetDroppedFrames", ret)
        return n.value

    def get_serial_number(self, camera_id: int) -> str:
        sn = ASI_ID()
        ret = self._lib.ASIGetSerialNumber(c_int(camera_id), byref(sn))
        self._check("ASIGetSerialNumber", ret)
        return bytes(sn.id).hex()
