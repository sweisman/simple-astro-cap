"""ZWO ASI SDK constants — control types, image types, error codes."""

from enum import IntEnum


class ControlType(IntEnum):
    """ASI_CONTROL_TYPE values."""

    GAIN = 0
    EXPOSURE = 1  # microseconds
    GAMMA = 2
    WB_R = 3
    WB_B = 4
    OFFSET = 5  # aka BRIGHTNESS
    BANDWIDTHOVERLOAD = 6  # USB bandwidth
    OVERCLOCK = 7
    TEMPERATURE = 8  # read-only, x10 degrees C
    FLIP = 9
    AUTO_MAX_GAIN = 10
    AUTO_MAX_EXP = 11
    AUTO_TARGET_BRIGHTNESS = 12
    HARDWARE_BIN = 13
    HIGH_SPEED_MODE = 14
    COOLER_POWER_PERC = 15
    TARGET_TEMP = 16
    COOLER_ON = 17
    MONO_BIN = 18
    FAN_ON = 19
    PATTERN_ADJUST = 20
    ANTI_DEW_HEATER = 21


class ImgType(IntEnum):
    """ASI_IMG_TYPE values."""

    RAW8 = 0
    RGB24 = 1
    RAW16 = 2
    Y8 = 3
    END = -1


class BayerPattern(IntEnum):
    RG = 0
    BG = 1
    GR = 2
    GB = 3


class ErrorCode(IntEnum):
    SUCCESS = 0
    ERROR_INVALID_INDEX = 1
    ERROR_INVALID_ID = 2
    ERROR_INVALID_CONTROL_TYPE = 3
    ERROR_CAMERA_CLOSED = 4
    ERROR_CAMERA_REMOVED = 5
    ERROR_INVALID_PATH = 6
    ERROR_INVALID_FILEFORMAT = 7
    ERROR_INVALID_SIZE = 8
    ERROR_INVALID_IMGTYPE = 9
    ERROR_OUTOF_BOUNDARY = 10
    ERROR_TIMEOUT = 11
    ERROR_INVALID_SEQUENCE = 12
    ERROR_BUFFER_TOO_SMALL = 13
    ERROR_VIDEO_MODE_ACTIVE = 14
    ERROR_EXPOSURE_IN_PROGRESS = 15
    ERROR_GENERAL_ERROR = 16
    ERROR_INVALID_MODE = 17


class ExposureStatus(IntEnum):
    IDLE = 0
    WORKING = 1
    SUCCESS = 2
    FAILED = 3


ASI_SUCCESS = 0
