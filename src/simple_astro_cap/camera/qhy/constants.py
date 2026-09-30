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

    # Native HDR (IMX585-based bodies: QHY5III585, MiniCam8). The SDK fits
    # high = k*low + b between its two 12-bit gain channels and re-aligns them
    # into one 16-bit frame; only the low channel's k/b are exposed.
    #
    # These live in the "TEST id name list" block of qhyccdstruct.h, which QHY
    # documents as "custom controls provided by the QHY SDK". Take the values
    # from a compiler, not from the /*NNNN*/ comments in that header: five
    # entries above HDR are commented out, so the annotations run five high
    # (CONTROL_HDR is annotated 1034 but compiles to 1029). The main enum ends
    # at CONTROL_MAX_ID = 94, so the previous 97-103 addressed nothing at all
    # and IsQHYCCDControlAvailable never reported HDR as present.
    CONTROL_HDR = 1029
    CONTROL_HDR_L_K = 1030
    CONTROL_HDR_L_B = 1031
    CONTROL_HDR_X = 1032
    CONTROL_HDR_SHOWKB = 1033


class HdrMode(IntEnum):
    """Values for ControlId.CONTROL_HDR.

    Not a boolean. From qhyccdstruct.h: "HDR status 0:As-is output
    1:Splice according to k and b values 2:Calculate k and b, only once".

    CALIBRATE derives k/b from the sensor and then splices with them; SPLICE
    reuses whatever k/b are already loaded, which on a fresh session are unset.
    """

    OFF = 0
    SPLICE = 1
    CALIBRATE = 2


class StreamMode(IntEnum):
    SINGLE = 0
    LIVE = 1


# Return code for success
QHYCCD_SUCCESS = 0

# Error codes
QHYCCD_ERROR = 0xFFFFFFFF
QHYCCD_READ_DIRECTLY = 0x2001
