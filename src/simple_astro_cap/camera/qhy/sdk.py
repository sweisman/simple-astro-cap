"""Thin ctypes wrapper around libqhyccd.so."""

from __future__ import annotations

import ctypes
import logging
from ctypes import (
    POINTER,
    byref,
    c_char_p,
    c_double,
    c_int,
    c_uint8,
    c_uint32,
    c_void_p,
)
from pathlib import Path

log = logging.getLogger(__name__)

from .constants import QHYCCD_SUCCESS


class QhyError(RuntimeError):
    """Error from QHY SDK call."""

    def __init__(self, func_name: str, ret: int):
        super().__init__(f"{func_name} failed with code 0x{ret:08X}")
        self.func_name = func_name
        self.ret = ret


# Opaque handle type
_Handle = c_void_p

# Project-local lib directory (lib/ next to src/)
_PROJECT_LIB_DIR = Path(__file__).resolve().parents[4] / "lib"

# Default search paths for the shared library (project-local first)
_DEFAULT_LIB_PATHS = [
    str(_PROJECT_LIB_DIR / "libqhyccd.so"),
    "/usr/local/lib/libqhyccd.so",
    "libqhyccd.so",  # system LD path
]


class QhySdk:
    """Low-level ctypes wrapper for libqhyccd.so.

    All methods correspond 1:1 to SDK C functions, with Python-friendly
    signatures and automatic error checking.
    """

    def __init__(self, lib_path: str | Path | None = None):
        self._lib = self._load_lib(lib_path)
        self._declare_functions()

    @staticmethod
    def _preload_bundled_deps(lib_dir: Path) -> None:
        """Pre-load bundled shared libs so libqhyccd.so uses them.

        The QHY SDK ships with specific versions of libusb, libstdc++, etc.
        Without pre-loading these, ctypes resolves them from the system which
        can cause SDK calls to fail silently.
        """
        for dep in ("libgcc_s.so.1", "libstdc++.so.6", "libusb-1.0.so.0"):
            dep_path = lib_dir / dep
            if dep_path.exists():
                try:
                    ctypes.CDLL(str(dep_path), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass

    @staticmethod
    def _load_lib(lib_path: str | Path | None) -> ctypes.CDLL:
        if lib_path is not None:
            lib_path = Path(lib_path)
            QhySdk._preload_bundled_deps(lib_path.parent)
            return ctypes.CDLL(str(lib_path))
        for path_str in _DEFAULT_LIB_PATHS:
            path = Path(path_str)
            try:
                QhySdk._preload_bundled_deps(path.parent)
                return ctypes.CDLL(str(path))
            except OSError:
                continue
        raise OSError(
            "Cannot find libqhyccd.so. Install the QHY SDK or pass lib_path."
        )

    def _declare_functions(self) -> None:
        lib = self._lib

        # --- Resource management ---
        lib.InitQHYCCDResource.argtypes = []
        lib.InitQHYCCDResource.restype = c_uint32

        lib.ReleaseQHYCCDResource.argtypes = []
        lib.ReleaseQHYCCDResource.restype = c_uint32

        # --- Enumeration ---
        lib.ScanQHYCCD.argtypes = []
        lib.ScanQHYCCD.restype = c_uint32

        lib.GetQHYCCDId.argtypes = [c_uint32, c_char_p]
        lib.GetQHYCCDId.restype = c_uint32

        # --- Open / close ---
        lib.OpenQHYCCD.argtypes = [c_char_p]
        lib.OpenQHYCCD.restype = _Handle

        lib.CloseQHYCCD.argtypes = [_Handle]
        lib.CloseQHYCCD.restype = c_uint32

        # --- Init ---
        lib.SetQHYCCDStreamMode.argtypes = [_Handle, c_uint8]
        lib.SetQHYCCDStreamMode.restype = c_uint32

        lib.SetQHYCCDReadMode.argtypes = [_Handle, c_uint32]
        lib.SetQHYCCDReadMode.restype = c_uint32

        lib.InitQHYCCD.argtypes = [_Handle]
        lib.InitQHYCCD.restype = c_uint32

        # --- Chip info ---
        lib.GetQHYCCDChipInfo.argtypes = [
            _Handle,
            POINTER(c_double),  # chipW mm
            POINTER(c_double),  # chipH mm
            POINTER(c_uint32),  # imageW
            POINTER(c_uint32),  # imageH
            POINTER(c_double),  # pixelW um
            POINTER(c_double),  # pixelH um
            POINTER(c_uint32),  # bpp
        ]
        lib.GetQHYCCDChipInfo.restype = c_uint32

        lib.GetQHYCCDEffectiveArea.argtypes = [
            _Handle,
            POINTER(c_uint32),  # startX
            POINTER(c_uint32),  # startY
            POINTER(c_uint32),  # sizeX
            POINTER(c_uint32),  # sizeY
        ]
        lib.GetQHYCCDEffectiveArea.restype = c_uint32

        # --- Control availability and range ---
        lib.IsQHYCCDControlAvailable.argtypes = [_Handle, c_uint32]
        lib.IsQHYCCDControlAvailable.restype = c_uint32

        lib.SetQHYCCDParam.argtypes = [_Handle, c_uint32, c_double]
        lib.SetQHYCCDParam.restype = c_uint32

        lib.GetQHYCCDParam.argtypes = [_Handle, c_uint32]
        lib.GetQHYCCDParam.restype = c_double

        lib.GetQHYCCDParamMinMaxStep.argtypes = [
            _Handle,
            c_uint32,
            POINTER(c_double),
            POINTER(c_double),
            POINTER(c_double),
        ]
        lib.GetQHYCCDParamMinMaxStep.restype = c_uint32

        # --- Resolution, binning, bit depth ---
        lib.SetQHYCCDResolution.argtypes = [
            _Handle,
            c_uint32,  # x
            c_uint32,  # y
            c_uint32,  # width
            c_uint32,  # height
        ]
        lib.SetQHYCCDResolution.restype = c_uint32

        lib.SetQHYCCDBinMode.argtypes = [_Handle, c_uint32, c_uint32]
        lib.SetQHYCCDBinMode.restype = c_uint32

        lib.SetQHYCCDBitsMode.argtypes = [_Handle, c_uint32]
        lib.SetQHYCCDBitsMode.restype = c_uint32

        # --- Memory ---
        lib.GetQHYCCDMemLength.argtypes = [_Handle]
        lib.GetQHYCCDMemLength.restype = c_uint32

        # --- Single frame ---
        lib.ExpQHYCCDSingleFrame.argtypes = [_Handle]
        lib.ExpQHYCCDSingleFrame.restype = c_uint32

        lib.GetQHYCCDSingleFrame.argtypes = [
            _Handle,
            POINTER(c_uint32),  # w
            POINTER(c_uint32),  # h
            POINTER(c_uint32),  # bpp
            POINTER(c_uint32),  # channels
            POINTER(c_uint8),  # data buffer
        ]
        lib.GetQHYCCDSingleFrame.restype = c_uint32

        lib.CancelQHYCCDExposingAndReadout.argtypes = [_Handle]
        lib.CancelQHYCCDExposingAndReadout.restype = c_uint32

        # --- Live streaming ---
        lib.BeginQHYCCDLive.argtypes = [_Handle]
        lib.BeginQHYCCDLive.restype = c_uint32

        lib.GetQHYCCDLiveFrame.argtypes = [
            _Handle,
            POINTER(c_uint32),  # w
            POINTER(c_uint32),  # h
            POINTER(c_uint32),  # bpp
            POINTER(c_uint32),  # channels
            POINTER(c_uint8),  # data buffer
        ]
        lib.GetQHYCCDLiveFrame.restype = c_uint32

        lib.StopQHYCCDLive.argtypes = [_Handle]
        lib.StopQHYCCDLive.restype = c_uint32

        # --- Auto-exposure ---
        lib.QHYCCD_SetAutoEXPmessureValue.argtypes = [_Handle, c_double]
        lib.QHYCCD_SetAutoEXPmessureValue.restype = c_uint32

        lib.QHYCCD_GetAutoEXPmessureValue.argtypes = [_Handle, POINTER(c_double)]
        lib.QHYCCD_GetAutoEXPmessureValue.restype = c_uint32

    # --- Python API ---

    def init_resource(self) -> None:
        ret = self._lib.InitQHYCCDResource()
        if ret != QHYCCD_SUCCESS:
            raise QhyError("InitQHYCCDResource", ret)

    def release_resource(self) -> None:
        ret = self._lib.ReleaseQHYCCDResource()
        if ret != QHYCCD_SUCCESS:
            raise QhyError("ReleaseQHYCCDResource", ret)

    def scan(self) -> int:
        return self._lib.ScanQHYCCD()

    def get_id(self, index: int) -> str:
        buf = ctypes.create_string_buffer(64)
        ret = self._lib.GetQHYCCDId(c_uint32(index), buf)
        if ret != QHYCCD_SUCCESS:
            raise QhyError("GetQHYCCDId", ret)
        return buf.value.decode("ascii")

    def open(self, camera_id: str) -> _Handle:
        handle = self._lib.OpenQHYCCD(camera_id.encode("ascii"))
        if handle is None or handle == 0:
            raise QhyError("OpenQHYCCD", 0)
        return handle

    def close(self, handle: _Handle) -> None:
        ret = self._lib.CloseQHYCCD(handle)
        if ret != QHYCCD_SUCCESS:
            raise QhyError("CloseQHYCCD", ret)

    def set_stream_mode(self, handle: _Handle, mode: int) -> None:
        ret = self._lib.SetQHYCCDStreamMode(handle, c_uint8(mode))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("SetQHYCCDStreamMode", ret)

    def set_read_mode(self, handle: _Handle, mode: int) -> None:
        ret = self._lib.SetQHYCCDReadMode(handle, c_uint32(mode))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("SetQHYCCDReadMode", ret)

    def init_camera(self, handle: _Handle) -> None:
        ret = self._lib.InitQHYCCD(handle)
        if ret != QHYCCD_SUCCESS:
            raise QhyError("InitQHYCCD", ret)

    def get_chip_info(
        self, handle: _Handle
    ) -> tuple[float, float, int, int, float, float, int]:
        """Returns (chipW_mm, chipH_mm, imageW, imageH, pixelW_um, pixelH_um, bpp)."""
        cw, ch = c_double(), c_double()
        iw, ih = c_uint32(), c_uint32()
        pw, ph = c_double(), c_double()
        bpp = c_uint32()
        ret = self._lib.GetQHYCCDChipInfo(
            handle, byref(cw), byref(ch), byref(iw), byref(ih),
            byref(pw), byref(ph), byref(bpp),
        )
        if ret != QHYCCD_SUCCESS:
            raise QhyError("GetQHYCCDChipInfo", ret)
        return (cw.value, ch.value, iw.value, ih.value, pw.value, ph.value, bpp.value)

    def get_effective_area(self, handle: _Handle) -> tuple[int, int, int, int]:
        """Returns (startX, startY, sizeX, sizeY)."""
        sx, sy, w, h = c_uint32(), c_uint32(), c_uint32(), c_uint32()
        ret = self._lib.GetQHYCCDEffectiveArea(
            handle, byref(sx), byref(sy), byref(w), byref(h),
        )
        if ret != QHYCCD_SUCCESS:
            raise QhyError("GetQHYCCDEffectiveArea", ret)
        return (sx.value, sy.value, w.value, h.value)

    def is_control_available(self, handle: _Handle, control_id: int) -> bool:
        ret = self._lib.IsQHYCCDControlAvailable(handle, c_uint32(control_id))
        return ret == QHYCCD_SUCCESS

    def set_param(self, handle: _Handle, control_id: int, value: float) -> None:
        ret = self._lib.SetQHYCCDParam(handle, c_uint32(control_id), c_double(value))
        if ret != QHYCCD_SUCCESS:
            raise QhyError(f"SetQHYCCDParam({control_id})", ret)

    def get_param(self, handle: _Handle, control_id: int) -> float:
        return self._lib.GetQHYCCDParam(handle, c_uint32(control_id))

    def get_param_min_max_step(
        self, handle: _Handle, control_id: int
    ) -> tuple[float, float, float] | None:
        mn, mx, step = c_double(), c_double(), c_double()
        ret = self._lib.GetQHYCCDParamMinMaxStep(
            handle, c_uint32(control_id), byref(mn), byref(mx), byref(step),
        )
        if ret != QHYCCD_SUCCESS:
            return None
        return (mn.value, mx.value, step.value)

    def set_resolution(
        self, handle: _Handle, x: int, y: int, w: int, h: int
    ) -> None:
        ret = self._lib.SetQHYCCDResolution(
            handle, c_uint32(x), c_uint32(y), c_uint32(w), c_uint32(h),
        )
        if ret != QHYCCD_SUCCESS:
            raise QhyError("SetQHYCCDResolution", ret)

    def set_bin_mode(self, handle: _Handle, bin_x: int, bin_y: int) -> None:
        ret = self._lib.SetQHYCCDBinMode(handle, c_uint32(bin_x), c_uint32(bin_y))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("SetQHYCCDBinMode", ret)

    def set_bits_mode(self, handle: _Handle, bits: int) -> None:
        ret = self._lib.SetQHYCCDBitsMode(handle, c_uint32(bits))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("SetQHYCCDBitsMode", ret)

    def get_mem_length(self, handle: _Handle) -> int:
        return self._lib.GetQHYCCDMemLength(handle)

    def exp_single_frame(self, handle: _Handle) -> None:
        ret = self._lib.ExpQHYCCDSingleFrame(handle)
        # QHYCCD_READ_DIRECTLY (0x2001) also means success for single frame
        if ret != QHYCCD_SUCCESS and ret != 0x2001:
            raise QhyError("ExpQHYCCDSingleFrame", ret)

    def get_single_frame(
        self, handle: _Handle, buf: ctypes.Array
    ) -> tuple[int, int, int, int]:
        """Returns (w, h, bpp, channels). Data is written to buf."""
        w, h, bpp, ch = c_uint32(), c_uint32(), c_uint32(), c_uint32()
        ret = self._lib.GetQHYCCDSingleFrame(
            handle, byref(w), byref(h), byref(bpp), byref(ch),
            ctypes.cast(buf, POINTER(c_uint8)),
        )
        if ret != QHYCCD_SUCCESS:
            raise QhyError("GetQHYCCDSingleFrame", ret)
        return (w.value, h.value, bpp.value, ch.value)

    def cancel_exposing(self, handle: _Handle) -> None:
        self._lib.CancelQHYCCDExposingAndReadout(handle)

    def begin_live(self, handle: _Handle) -> None:
        ret = self._lib.BeginQHYCCDLive(handle)
        if ret != QHYCCD_SUCCESS:
            raise QhyError("BeginQHYCCDLive", ret)

    def get_live_frame(
        self, handle: _Handle, buf: ctypes.Array
    ) -> tuple[int, int, int, int] | None:
        """Returns (w, h, bpp, channels) or None if no frame ready."""
        w, h, bpp, ch = c_uint32(), c_uint32(), c_uint32(), c_uint32()
        ret = self._lib.GetQHYCCDLiveFrame(
            handle, byref(w), byref(h), byref(bpp), byref(ch),
            ctypes.cast(buf, POINTER(c_uint8)),
        )
        if ret != QHYCCD_SUCCESS:
            return None
        return (w.value, h.value, bpp.value, ch.value)

    def stop_live(self, handle: _Handle) -> None:
        ret = self._lib.StopQHYCCDLive(handle)
        if ret != QHYCCD_SUCCESS:
            raise QhyError("StopQHYCCDLive", ret)

    # --- Auto-exposure ---

    def set_auto_exp_messure_value(self, handle: _Handle, value: float) -> None:
        """Set auto-exposure target brightness value."""
        ret = self._lib.QHYCCD_SetAutoEXPmessureValue(handle, c_double(value))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("QHYCCD_SetAutoEXPmessureValue", ret)

    def get_auto_exp_messure_value(self, handle: _Handle) -> float:
        """Get auto-exposure target brightness value."""
        val = c_double()
        ret = self._lib.QHYCCD_GetAutoEXPmessureValue(handle, byref(val))
        if ret != QHYCCD_SUCCESS:
            raise QhyError("QHYCCD_GetAutoEXPmessureValue", ret)
        return val.value
