"""Player One camera SDK ctypes bindings.

Wraps libPlayerOneCamera.so (Player One Astronomy USB camera SDK).
API is similar to ZWO ASI SDK.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from pathlib import Path

from .constants import POABool, POAConfig, POAErrors, POAImgFormat, POAValueType

log = logging.getLogger(__name__)

# Max supported bins array length in POACameraProperties
_MAX_BINS = 16
_MAX_FORMATS = 8


class POACameraProperties(ctypes.Structure):
    """POACameraProperties — camera info returned by POAGetCameraProperties."""

    _fields_ = [
        ("cameraModelName", ctypes.c_char * 64),
        ("userCustomID", ctypes.c_char * 16),
        ("cameraID", ctypes.c_int),
        ("maxWidth", ctypes.c_int),
        ("maxHeight", ctypes.c_int),
        ("bitDepth", ctypes.c_int),
        ("isColorCamera", ctypes.c_int),  # POABool
        ("isHasCooler", ctypes.c_int),  # POABool
        ("isHasUSBHub", ctypes.c_int),  # POABool
        ("isHasST4Port", ctypes.c_int),  # POABool
        ("isHasMechanicalShutter", ctypes.c_int),  # POABool
        ("pixelSize", ctypes.c_double),
        ("SN", ctypes.c_char * 64),
        ("sensorModelName", ctypes.c_char * 32),
        ("bayerPattern", ctypes.c_int),
        ("localPath", ctypes.c_char * 256),
        ("bins", ctypes.c_int * _MAX_BINS),
        ("imgFormats", ctypes.c_int * _MAX_FORMATS),
        ("pID", ctypes.c_int),
    ]


class POAConfigAttributes(ctypes.Structure):
    """POAConfigAttributes — control/config info."""

    _fields_ = [
        ("isSupportAuto", ctypes.c_int),  # POABool
        ("isWritable", ctypes.c_int),  # POABool
        ("isReadable", ctypes.c_int),  # POABool
        ("configID", ctypes.c_int),  # POAConfig
        ("valueType", ctypes.c_int),  # POAValueType
        ("maxValue_int", ctypes.c_long),
        ("minValue_int", ctypes.c_long),
        ("defaultValue_int", ctypes.c_long),
        ("szConfName", ctypes.c_char * 64),
        ("szDescription", ctypes.c_char * 128),
    ]


class POAConfigValue(ctypes.Union):
    """POAConfigValue — union for config get/set."""

    _fields_ = [
        ("intValue", ctypes.c_long),
        ("floatValue", ctypes.c_double),
        ("boolValue", ctypes.c_int),
    ]


class PlayerOneError(Exception):
    """Raised on Player One SDK errors."""

    def __init__(self, func: str, code: int):
        self.code = code
        try:
            name = POAErrors(code).name
        except ValueError:
            name = f"UNKNOWN({code})"
        super().__init__(f"{func} failed: {name}")


class PlayerOneSdk:
    """Thin ctypes wrapper around libPlayerOneCamera.so."""

    def __init__(self, lib_path: str | None = None):
        if lib_path:
            path = Path(lib_path)
        else:
            path = Path(__file__).resolve().parent.parent.parent.parent.parent / "lib" / "libPlayerOneCamera.so"

        if not path.exists():
            found = ctypes.util.find_library("PlayerOneCamera")
            if found:
                path = Path(found)
            else:
                raise FileNotFoundError(
                    f"libPlayerOneCamera.so not found at {path} or in system paths"
                )

        log.info("Loading Player One SDK from %s", path)
        self._lib = ctypes.cdll.LoadLibrary(str(path))
        self._setup_prototypes()
        log.info("Player One SDK version: %s", self.get_sdk_version())

    def _setup_prototypes(self) -> None:
        lib = self._lib

        lib.POAGetCameraCount.restype = ctypes.c_int
        lib.POAGetCameraCount.argtypes = []

        lib.POAGetCameraProperties.restype = ctypes.c_int
        lib.POAGetCameraProperties.argtypes = [ctypes.c_int, ctypes.POINTER(POACameraProperties)]

        lib.POAOpenCamera.restype = ctypes.c_int
        lib.POAOpenCamera.argtypes = [ctypes.c_int]

        lib.POAInitCamera.restype = ctypes.c_int
        lib.POAInitCamera.argtypes = [ctypes.c_int]

        lib.POACloseCamera.restype = ctypes.c_int
        lib.POACloseCamera.argtypes = [ctypes.c_int]

        lib.POASetImageSize.restype = ctypes.c_int
        lib.POASetImageSize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]

        lib.POASetImageStartPos.restype = ctypes.c_int
        lib.POASetImageStartPos.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]

        lib.POASetImageFormat.restype = ctypes.c_int
        lib.POASetImageFormat.argtypes = [ctypes.c_int, ctypes.c_int]

        lib.POASetImageBin.restype = ctypes.c_int
        lib.POASetImageBin.argtypes = [ctypes.c_int, ctypes.c_int]

        lib.POAGetImageBin.restype = ctypes.c_int
        lib.POAGetImageBin.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

        lib.POAStartExposure.restype = ctypes.c_int
        lib.POAStartExposure.argtypes = [ctypes.c_int, ctypes.c_int]  # cam_id, bSingleFrame

        lib.POAStopExposure.restype = ctypes.c_int
        lib.POAStopExposure.argtypes = [ctypes.c_int]

        lib.POAGetImageData.restype = ctypes.c_int
        lib.POAGetImageData.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_long,
            ctypes.c_int,  # timeout ms
        ]

        lib.POAGetConfigsCount.restype = ctypes.c_int
        lib.POAGetConfigsCount.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

        lib.POAGetConfigAttributes.restype = ctypes.c_int
        lib.POAGetConfigAttributes.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(POAConfigAttributes)
        ]

        lib.POASetConfig.restype = ctypes.c_int
        lib.POASetConfig.argtypes = [
            ctypes.c_int, ctypes.c_int, POAConfigValue, ctypes.c_int
        ]

        lib.POAGetConfig.restype = ctypes.c_int
        lib.POAGetConfig.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(POAConfigValue), ctypes.POINTER(ctypes.c_int)
        ]

        lib.POAGetSDKVersion.restype = ctypes.c_char_p
        lib.POAGetSDKVersion.argtypes = []

    def _check(self, func: str, ret: int) -> None:
        if ret != POAErrors.OK:
            raise PlayerOneError(func, ret)

    def get_sdk_version(self) -> str:
        return self._lib.POAGetSDKVersion().decode("ascii", errors="replace")

    def get_camera_count(self) -> int:
        return self._lib.POAGetCameraCount()

    def get_camera_properties(self, index: int) -> POACameraProperties:
        prop = POACameraProperties()
        ret = self._lib.POAGetCameraProperties(index, ctypes.byref(prop))
        self._check("POAGetCameraProperties", ret)
        return prop

    def open_camera(self, cam_id: int) -> None:
        self._check("POAOpenCamera", self._lib.POAOpenCamera(cam_id))

    def init_camera(self, cam_id: int) -> None:
        self._check("POAInitCamera", self._lib.POAInitCamera(cam_id))

    def close_camera(self, cam_id: int) -> None:
        self._check("POACloseCamera", self._lib.POACloseCamera(cam_id))

    def set_image_size(self, cam_id: int, width: int, height: int) -> None:
        self._check("POASetImageSize",
                     self._lib.POASetImageSize(cam_id, width, height))

    def set_image_start_pos(self, cam_id: int, x: int, y: int) -> None:
        self._check("POASetImageStartPos",
                     self._lib.POASetImageStartPos(cam_id, x, y))

    def set_image_format(self, cam_id: int, fmt: POAImgFormat) -> None:
        self._check("POASetImageFormat",
                     self._lib.POASetImageFormat(cam_id, int(fmt)))

    def set_image_bin(self, cam_id: int, bin_factor: int) -> None:
        self._check("POASetImageBin",
                     self._lib.POASetImageBin(cam_id, bin_factor))

    def start_exposure(self, cam_id: int, single_frame: bool = False) -> None:
        self._check("POAStartExposure",
                     self._lib.POAStartExposure(cam_id, int(single_frame)))

    def stop_exposure(self, cam_id: int) -> None:
        self._check("POAStopExposure", self._lib.POAStopExposure(cam_id))

    def get_image_data(self, cam_id: int, buf: ctypes.Array,
                       buf_size: int, timeout_ms: int) -> bool:
        ret = self._lib.POAGetImageData(cam_id, buf, buf_size, timeout_ms)
        if ret == POAErrors.OK:
            return True
        return False

    def get_configs_count(self, cam_id: int) -> int:
        count = ctypes.c_int(0)
        self._check("POAGetConfigsCount",
                     self._lib.POAGetConfigsCount(cam_id, ctypes.byref(count)))
        return count.value

    def get_config_attributes(self, cam_id: int, index: int) -> POAConfigAttributes:
        attr = POAConfigAttributes()
        self._check("POAGetConfigAttributes",
                     self._lib.POAGetConfigAttributes(cam_id, index, ctypes.byref(attr)))
        return attr

    def set_config(self, cam_id: int, config_id: POAConfig,
                   value: int, auto: bool = False) -> None:
        val = POAConfigValue()
        val.intValue = value
        self._check("POASetConfig",
                     self._lib.POASetConfig(cam_id, int(config_id), val, int(auto)))

    def get_config(self, cam_id: int, config_id: POAConfig) -> tuple[int, bool]:
        val = POAConfigValue()
        is_auto = ctypes.c_int(0)
        self._check("POAGetConfig",
                     self._lib.POAGetConfig(cam_id, int(config_id),
                                            ctypes.byref(val), ctypes.byref(is_auto)))
        return val.intValue, bool(is_auto.value)
