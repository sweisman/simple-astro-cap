"""Player One SDK constants — config IDs, image formats, error codes."""

from enum import IntEnum


class POAConfig(IntEnum):
    """POA_CONFIG values (control/config parameter IDs)."""

    EXPOSURE = 0  # microseconds
    GAIN = 1
    HARDWARE_BIN = 2
    TEMPERATURE = 3  # read-only, x10 degrees C
    WB_R = 4
    WB_G = 5
    WB_B = 6
    OFFSET = 7
    AUTOEXPO_MAX_GAIN = 8
    AUTOEXPO_MAX_EXPOSURE = 9
    AUTOEXPO_BRIGHTNESS = 10
    GUIDE_NORTH = 11
    GUIDE_SOUTH = 12
    GUIDE_EAST = 13
    GUIDE_WEST = 14
    EGAIN = 15  # e/ADU, read-only
    COOLER_POWER = 16
    TARGET_TEMP = 17
    COOLER = 18
    HEATER = 19
    HEATER_POWER = 20
    FAN_POWER = 21
    FLIP_NONE = 22
    FLIP_HORI = 23
    FLIP_VERT = 24
    FLIP_BOTH = 25
    FRAME_LIMIT = 26
    HQI = 27
    USB_BANDWIDTH_LIMIT = 28
    PIXEL_BIN_SUM = 29
    MONO_BIN = 30


class POAImgFormat(IntEnum):
    """POAImgFormat values."""

    RAW8 = 0
    RAW16 = 1
    RGB24 = 2
    MONO8 = 3
    END = -1


class POAValueType(IntEnum):
    """POAValueType — config value data type."""

    INT = 0
    FLOAT = 1
    BOOL = 2


class POABool(IntEnum):
    FALSE = 0
    TRUE = 1


class POAErrors(IntEnum):
    OK = 0
    ERROR_INVALID_INDEX = 1
    ERROR_INVALID_ID = 2
    ERROR_INVALID_CONFIG = 3
    ERROR_INVALID_ARGU = 4
    ERROR_NOT_OPENED = 5
    ERROR_DEVICE_NOT_FOUND = 6
    ERROR_OUT_OF_LIMIT = 7
    ERROR_CLOSED = 8
    ERROR_REMOVED = 9
    ERROR_EXPOSING = 10
    ERROR_POINTER = 11
    ERROR_CONF_CANNOT_WRITE = 12
    ERROR_CONF_CANNOT_READ = 13
    ERROR_ACCESS_DENY = 14
    ERROR_NOT_IN_SUPPORTED_PLATFORMS = 15
    ERROR_MEMORY_FAILED = 16


class POACameraState(IntEnum):
    STATE_CLOSED = 0
    STATE_OPENED = 1
    STATE_EXPOSING = 2
