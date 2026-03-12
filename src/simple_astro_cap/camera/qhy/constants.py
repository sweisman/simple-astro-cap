"""QHY SDK constants — control IDs, error codes, stream modes."""

from enum import IntEnum


class ControlId(IntEnum):
    """QHYCCD control parameter identifiers from qhyccdcamdef.h."""

    BRIGHTNESS = 0
    CONTRAST = 1
    WBR = 2
    WBB = 3
    WBG = 4
    GAMMA = 5
    GAIN = 6
    OFFSET = 7
    EXPOSURE = 8  # microseconds
    SPEED = 9  # USB speed / readout speed
    TRANSFERBIT = 10  # 8 or 16
    CHANNELS = 11
    USBTRAFFIC = 12
    ROWNOISERE = 13
    CURTEMP = 14  # read-only: current sensor temperature
    CURPWM = 15  # read-only: current cooler PWM
    MANULPWM = 16
    CFWPORT = 17
    COOLER = 18  # target temperature
    ST4PORT = 19

    # Capability queries (IsQHYCCDControlAvailable)
    CAM_BIN1X1MODE = 20
    CAM_BIN2X2MODE = 21
    CAM_BIN3X3MODE = 22
    CAM_BIN4X4MODE = 23
    CAM_MECHANICALSHUTTER = 24
    CAM_TRIGER_INTERFACE = 25
    CAM_TECOVERPROTECT_INTERFACE = 26
    CAM_SINGNALCLAMP_INTERFACE = 27
    CAM_FINETONE_INTERFACE = 28
    CAM_SHUTTERMOTORHEATING_INTERFACE = 29
    CAM_CALIBRATEFPN_INTERFACE = 30
    CAM_CHIPTEMPERATURESENSOR_INTERFACE = 31
    CAM_USBREADOUTSLOWEST_INTERFACE = 32
    CAM_8BITS = 33
    CAM_16BITS = 34
    CAM_GPS = 35
    AMPV = 36
    DDR = 37
    HUMIDITY = 38
    PRESSURE = 39
    CAM_IS_COLOR = 46

    # Auto-exposure (SDK-internal 3A system manages exposure + gain together)
    CAM_AUTOEXPOSURE = 88  # 0x58: SetQHYCCDParam → SetAutoExposure


class StreamMode(IntEnum):
    SINGLE = 0
    LIVE = 1


# Return code for success
QHYCCD_SUCCESS = 0

# Error codes
QHYCCD_ERROR = 0xFFFFFFFF
QHYCCD_READ_DIRECTLY = 0x2001
