"""Touptek camera SDK constants — option IDs, error codes, image formats."""

from enum import IntEnum


class ToupOption(IntEnum):
    """TOUPCAM_OPTION values (control parameter IDs)."""

    NOFRAME_TIMEOUT = 0x01
    THREAD_PRIORITY = 0x02
    RAW = 0x04
    HISTOGRAM = 0x05
    BITDEPTH = 0x06  # 0=8bit, 1=16bit
    FAN = 0x07
    TEC = 0x08
    LINEAR = 0x09
    CURVE = 0x0A
    TRIGGER = 0x0B
    RGB = 0x0C
    COLORMATIX = 0x0D
    WBGAIN = 0x0E
    TECTARGET = 0x0F
    AUTOEXP_POLICY = 0x10
    FRAMERATE = 0x11
    DEMOSAIC = 0x12
    DEMOSAIC_VIDEO = 0x13
    DEMOSAIC_STILL = 0x14
    BLACKLEVEL = 0x15
    AUTO_FOCUS = 0x16
    FACTORY = 0x1F
    TEC_VOLTAGE = 0x20
    TEC_VOLTAGE_MAX = 0x21
    AGAIN = 0x22  # analog gain
    FRAMERATE_LIMIT = 0x23
    BANDWIDTH = 0x3E
    PIXEL_FORMAT = 0x41
    BINNING = 0x46


class ToupError(IntEnum):
    """Touptek SDK error codes (HRESULT style)."""

    OK = 0
    # Negative HRESULT values — SDK returns S_OK (0) on success
    # Specific codes vary; we just check != 0 for errors


class ToupEvent(IntEnum):
    """Touptek callback event IDs."""

    EXPOSURE = 0x0001
    TEMPTINT = 0x0002
    IMAGE = 0x0004
    STILLIMAGE = 0x0005
    WBGAIN = 0x0006
    TRIGGERFAIL = 0x0007
    BLACK = 0x0008
    FFC = 0x0009
    DFC = 0x000A
    ROI = 0x000B
    LEVELRANGE = 0x000C
    AUTOEXPO_CONV = 0x000D
    AUTOEXPO_CONVFAIL = 0x000E
    ERROR = 0x0080
    DISCONNECTED = 0x0081
    NOFRAMETIMEOUT = 0x0082
    AFFEEDBACK = 0x0083
    AFPOSITION = 0x0084
    NOPACKETTIMEOUT = 0x0085
    FACTORY = 0x8001
