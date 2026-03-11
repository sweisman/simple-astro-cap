"""Touptek camera SDK ctypes bindings.

Wraps libtoupcam.so (Touptek USB camera SDK).
Handle-based API with pull-mode image retrieval.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class ToupcamFrameInfoV3(ctypes.Structure):
    """Frame info returned by Toupcam_PullImageV3."""

    _fields_ = [
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
        ("flag", ctypes.c_uint),
        ("seq", ctypes.c_uint),
        ("timestamp", ctypes.c_longlong),
        ("shutterseq", ctypes.c_uint),
        ("expotime", ctypes.c_uint),  # microseconds
        ("expogain", ctypes.c_ushort),
        ("blacklevel", ctypes.c_ushort),
    ]


class ToupcamDeviceV2(ctypes.Structure):
    """Device info returned by Toupcam_EnumV2."""

    _fields_ = [
        ("displayname", ctypes.c_char * 64),
        ("id", ctypes.c_char * 64),
        ("model", ctypes.c_void_p),  # pointer to model struct — opaque
    ]


class ToupcamResolution(ctypes.Structure):
    """Resolution entry."""

    _fields_ = [
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
    ]


class ToupcamError(Exception):
    """Raised on Touptek SDK errors."""

    def __init__(self, func: str, code: int):
        self.code = code
        super().__init__(f"{func} failed: HRESULT 0x{code & 0xFFFFFFFF:08X}")


class ToupcamSdk:
    """Thin ctypes wrapper around libtoupcam.so."""

    def __init__(self, lib_path: str | None = None):
        if lib_path:
            path = Path(lib_path)
        else:
            path = Path(__file__).resolve().parent.parent.parent.parent.parent / "lib" / "libtoupcam.so"

        if not path.exists():
            found = ctypes.util.find_library("toupcam")
            if found:
                path = Path(found)
            else:
                raise FileNotFoundError(
                    f"libtoupcam.so not found at {path} or in system paths"
                )

        log.info("Loading Touptek SDK from %s", path)
        self._lib = ctypes.cdll.LoadLibrary(str(path))
        self._setup_prototypes()

    def _setup_prototypes(self) -> None:
        lib = self._lib

        # Toupcam_EnumV2 -> count
        lib.Toupcam_EnumV2.restype = ctypes.c_uint
        lib.Toupcam_EnumV2.argtypes = [ctypes.POINTER(ToupcamDeviceV2)]

        # Toupcam_Open -> handle (void*), NULL on failure
        lib.Toupcam_Open.restype = ctypes.c_void_p
        lib.Toupcam_Open.argtypes = [ctypes.c_char_p]  # device id

        # Toupcam_Close
        lib.Toupcam_Close.restype = None
        lib.Toupcam_Close.argtypes = [ctypes.c_void_p]

        # Toupcam_StartPullModeWithCallback -> HRESULT
        lib.Toupcam_StartPullModeWithCallback.restype = ctypes.c_int
        lib.Toupcam_StartPullModeWithCallback.argtypes = [
            ctypes.c_void_p,  # handle
            ctypes.c_void_p,  # callback (NULL for no callback)
            ctypes.c_void_p,  # context
        ]

        # Toupcam_PullImageV3 -> HRESULT
        lib.Toupcam_PullImageV3.restype = ctypes.c_int
        lib.Toupcam_PullImageV3.argtypes = [
            ctypes.c_void_p,  # handle
            ctypes.c_void_p,  # pImageData
            ctypes.c_int,     # bStill (0=preview, 1=still)
            ctypes.c_int,     # bits (8 or 16)
            ctypes.c_int,     # rowPitch (0 = auto)
            ctypes.POINTER(ToupcamFrameInfoV3),
        ]

        # Toupcam_Stop
        lib.Toupcam_Stop.restype = ctypes.c_int
        lib.Toupcam_Stop.argtypes = [ctypes.c_void_p]

        # Toupcam_put_Size -> HRESULT
        lib.Toupcam_put_Size.restype = ctypes.c_int
        lib.Toupcam_put_Size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]

        # Toupcam_get_Size -> HRESULT
        lib.Toupcam_get_Size.restype = ctypes.c_int
        lib.Toupcam_get_Size.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]

        # Toupcam_put_ExpoTime -> HRESULT (microseconds)
        lib.Toupcam_put_ExpoTime.restype = ctypes.c_int
        lib.Toupcam_put_ExpoTime.argtypes = [ctypes.c_void_p, ctypes.c_uint]

        # Toupcam_get_ExpoTime -> HRESULT
        lib.Toupcam_get_ExpoTime.restype = ctypes.c_int
        lib.Toupcam_get_ExpoTime.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
        ]

        # Toupcam_put_ExpoAGain -> HRESULT (analog gain, percentage 100=1x)
        lib.Toupcam_put_ExpoAGain.restype = ctypes.c_int
        lib.Toupcam_put_ExpoAGain.argtypes = [ctypes.c_void_p, ctypes.c_ushort]

        # Toupcam_get_ExpoAGain -> HRESULT
        lib.Toupcam_get_ExpoAGain.restype = ctypes.c_int
        lib.Toupcam_get_ExpoAGain.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort),
        ]

        # Toupcam_get_ExpoAGainRange -> HRESULT
        lib.Toupcam_get_ExpoAGainRange.restype = ctypes.c_int
        lib.Toupcam_get_ExpoAGainRange.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),  # min
            ctypes.POINTER(ctypes.c_ushort),  # max
            ctypes.POINTER(ctypes.c_ushort),  # default
        ]

        # Toupcam_put_AutoExpoEnable -> HRESULT
        lib.Toupcam_put_AutoExpoEnable.restype = ctypes.c_int
        lib.Toupcam_put_AutoExpoEnable.argtypes = [ctypes.c_void_p, ctypes.c_int]

        # Toupcam_get_AutoExpoEnable -> HRESULT
        lib.Toupcam_get_AutoExpoEnable.restype = ctypes.c_int
        lib.Toupcam_get_AutoExpoEnable.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
        ]

        # Toupcam_put_Option -> HRESULT
        lib.Toupcam_put_Option.restype = ctypes.c_int
        lib.Toupcam_put_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]

        # Toupcam_get_Option -> HRESULT
        lib.Toupcam_get_Option.restype = ctypes.c_int
        lib.Toupcam_get_Option.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_int),
        ]

        # Toupcam_get_Temperature -> HRESULT (tenths of degrees C)
        lib.Toupcam_get_Temperature.restype = ctypes.c_int
        lib.Toupcam_get_Temperature.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_short),
        ]

        # Toupcam_get_ExpTimeRange -> HRESULT
        lib.Toupcam_get_ExpTimeRange.restype = ctypes.c_int
        lib.Toupcam_get_ExpTimeRange.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),  # min
            ctypes.POINTER(ctypes.c_uint),  # max
            ctypes.POINTER(ctypes.c_uint),  # default
        ]

        # Toupcam_get_MaxBitDepth -> unsigned
        lib.Toupcam_get_MaxBitDepth.restype = ctypes.c_uint
        lib.Toupcam_get_MaxBitDepth.argtypes = [ctypes.c_void_p]

        # Toupcam_get_MonoMode -> HRESULT
        lib.Toupcam_get_MonoMode.restype = ctypes.c_int
        lib.Toupcam_get_MonoMode.argtypes = [ctypes.c_void_p]

        # Toupcam_get_Resolution -> HRESULT
        lib.Toupcam_get_Resolution.restype = ctypes.c_int
        lib.Toupcam_get_Resolution.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,  # index
            ctypes.POINTER(ctypes.c_int),  # width
            ctypes.POINTER(ctypes.c_int),  # height
        ]

        # Toupcam_get_ResolutionNumber -> unsigned
        lib.Toupcam_get_ResolutionNumber.restype = ctypes.c_uint
        lib.Toupcam_get_ResolutionNumber.argtypes = [ctypes.c_void_p]

        # Toupcam_get_PixelSize -> HRESULT
        lib.Toupcam_get_PixelSize.restype = ctypes.c_int
        lib.Toupcam_get_PixelSize.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,  # resolution index
            ctypes.POINTER(ctypes.c_float),  # x
            ctypes.POINTER(ctypes.c_float),  # y
        ]

    def _check(self, func: str, ret: int) -> None:
        if ret < 0:
            raise ToupcamError(func, ret)

    def enum_v2(self, max_devices: int = 16) -> list[ToupcamDeviceV2]:
        arr = (ToupcamDeviceV2 * max_devices)()
        count = self._lib.Toupcam_EnumV2(arr)
        return [arr[i] for i in range(count)]

    def open(self, device_id: bytes) -> ctypes.c_void_p:
        handle = self._lib.Toupcam_Open(device_id)
        if not handle:
            raise ToupcamError("Toupcam_Open", -1)
        return handle

    def close(self, handle) -> None:
        self._lib.Toupcam_Close(handle)

    def start_pull_mode(self, handle) -> None:
        ret = self._lib.Toupcam_StartPullModeWithCallback(handle, None, None)
        self._check("Toupcam_StartPullModeWithCallback", ret)

    def stop(self, handle) -> None:
        ret = self._lib.Toupcam_Stop(handle)
        self._check("Toupcam_Stop", ret)

    def pull_image_v3(self, handle, buf, bits: int) -> ToupcamFrameInfoV3 | None:
        info = ToupcamFrameInfoV3()
        ret = self._lib.Toupcam_PullImageV3(handle, buf, 0, bits, 0, ctypes.byref(info))
        if ret < 0:
            return None
        return info

    def put_size(self, handle, width: int, height: int) -> None:
        self._check("Toupcam_put_Size",
                     self._lib.Toupcam_put_Size(handle, width, height))

    def get_size(self, handle) -> tuple[int, int]:
        w = ctypes.c_int(0)
        h = ctypes.c_int(0)
        self._check("Toupcam_get_Size",
                     self._lib.Toupcam_get_Size(handle, ctypes.byref(w), ctypes.byref(h)))
        return w.value, h.value

    def put_expo_time(self, handle, microseconds: int) -> None:
        self._check("Toupcam_put_ExpoTime",
                     self._lib.Toupcam_put_ExpoTime(handle, microseconds))

    def get_expo_time(self, handle) -> int:
        val = ctypes.c_uint(0)
        self._check("Toupcam_get_ExpoTime",
                     self._lib.Toupcam_get_ExpoTime(handle, ctypes.byref(val)))
        return val.value

    def put_expo_again(self, handle, gain: int) -> None:
        self._check("Toupcam_put_ExpoAGain",
                     self._lib.Toupcam_put_ExpoAGain(handle, gain))

    def get_expo_again(self, handle) -> int:
        val = ctypes.c_ushort(0)
        self._check("Toupcam_get_ExpoAGain",
                     self._lib.Toupcam_get_ExpoAGain(handle, ctypes.byref(val)))
        return val.value

    def get_expo_again_range(self, handle) -> tuple[int, int, int]:
        mn = ctypes.c_ushort(0)
        mx = ctypes.c_ushort(0)
        df = ctypes.c_ushort(0)
        self._check("Toupcam_get_ExpoAGainRange",
                     self._lib.Toupcam_get_ExpoAGainRange(
                         handle, ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(df)))
        return mn.value, mx.value, df.value

    def put_auto_expo_enable(self, handle, enabled: bool) -> None:
        self._check("Toupcam_put_AutoExpoEnable",
                     self._lib.Toupcam_put_AutoExpoEnable(handle, int(enabled)))

    def get_auto_expo_enable(self, handle) -> bool:
        val = ctypes.c_int(0)
        self._check("Toupcam_get_AutoExpoEnable",
                     self._lib.Toupcam_get_AutoExpoEnable(handle, ctypes.byref(val)))
        return bool(val.value)

    def put_option(self, handle, option: int, value: int) -> None:
        self._check("Toupcam_put_Option",
                     self._lib.Toupcam_put_Option(handle, option, value))

    def get_option(self, handle, option: int) -> int:
        val = ctypes.c_int(0)
        self._check("Toupcam_get_Option",
                     self._lib.Toupcam_get_Option(handle, option, ctypes.byref(val)))
        return val.value

    def get_temperature(self, handle) -> float:
        val = ctypes.c_short(0)
        self._check("Toupcam_get_Temperature",
                     self._lib.Toupcam_get_Temperature(handle, ctypes.byref(val)))
        return val.value / 10.0

    def get_exp_time_range(self, handle) -> tuple[int, int, int]:
        mn = ctypes.c_uint(0)
        mx = ctypes.c_uint(0)
        df = ctypes.c_uint(0)
        self._check("Toupcam_get_ExpTimeRange",
                     self._lib.Toupcam_get_ExpTimeRange(
                         handle, ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(df)))
        return mn.value, mx.value, df.value

    def get_max_bit_depth(self, handle) -> int:
        return self._lib.Toupcam_get_MaxBitDepth(handle)

    def get_mono_mode(self, handle) -> bool:
        """Return True if camera is monochrome."""
        return bool(self._lib.Toupcam_get_MonoMode(handle))

    def get_resolution_number(self, handle) -> int:
        return self._lib.Toupcam_get_ResolutionNumber(handle)

    def get_resolution(self, handle, index: int) -> tuple[int, int]:
        w = ctypes.c_int(0)
        h = ctypes.c_int(0)
        self._check("Toupcam_get_Resolution",
                     self._lib.Toupcam_get_Resolution(
                         handle, index, ctypes.byref(w), ctypes.byref(h)))
        return w.value, h.value

    def get_pixel_size(self, handle, res_index: int) -> tuple[float, float]:
        x = ctypes.c_float(0)
        y = ctypes.c_float(0)
        self._check("Toupcam_get_PixelSize",
                     self._lib.Toupcam_get_PixelSize(
                         handle, res_index, ctypes.byref(x), ctypes.byref(y)))
        return x.value, y.value
