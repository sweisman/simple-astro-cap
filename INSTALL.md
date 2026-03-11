# Simple Astro Cap — Installation Guide

## Requirements

- Linux (tested on Arch Linux)
- Python 3.11+
- USB 3.0 port (recommended for full-speed capture)

### Supported Cameras

- **QHY** cameras (tested: QHY5III585M)
- **ZWO ASI** cameras (tested: ASI678MM)

---

## 1. Python Dependencies

```bash
cd simple-astro-cap
pip install -e .
```

This installs:
- PySide6 (Qt6 GUI)
- NumPy (frame processing)
- Pillow (PNG I/O)

### Optional

- **ffmpeg** — required for MKV (FFV1 lossless) recording:
  ```bash
  # Arch
  sudo pacman -S ffmpeg
  # Debian/Ubuntu
  sudo apt install ffmpeg
  ```

---

## 2. Camera SDK Libraries

The application requires camera SDK shared libraries in `lib/`:

| File | Purpose |
|------|---------|
| `libqhyccd.so` | QHY camera SDK |
| `libASICamera2.so` | ZWO ASI camera SDK |
| `libgcc_s.so.1` | GCC runtime (required by QHY SDK) |
| `libstdc++.so.6` | C++ stdlib (required by QHY SDK) |
| `libusb-1.0.so.0` | USB library (specific version required by QHY SDK) |

These are sourced from an [AstroDMx Capture](https://www.astrodmx-capture.org.uk/)
installation at `/opt/AstroDMx-Capture/lib/`. Copy or symlink them into the project's
`lib/` directory. They are loaded automatically at runtime.

**Important**: The QHY SDK requires its own `libusb-1.0.so.0`. The system libusb is a
different version and will cause silent failures. The application pre-loads the correct
version automatically.

---

## 3. USB Device Permissions (udev rules)

Cameras are USB devices. Without udev rules, only root can access them.

### ZWO ASI Cameras

Create `/etc/udev/rules.d/99-asi.rules`:

```
ACTION=="add", ATTR{idVendor}=="03c3", RUN+="/bin/sh -c '/bin/echo 200 >/sys/module/usbcore/parameters/usbfs_memory_mb'"
SUBSYSTEMS=="usb", ATTR{idVendor}=="03c3", MODE="0666"
```

### QHY Cameras

QHY cameras require both permissions AND firmware loading. Firmware must be uploaded
to the camera each time it is plugged in, using the `fxload` utility.

Create `/etc/udev/rules.d/99-qhyccd.rules`:

```
ACTION!="add", GOTO="qhy_end"
SUBSYSTEM!="usb", GOTO="qhy_end"

# ---- Firmware loading (FX3 cameras) ----
# QHY5III585
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0585", RUN+="/path/to/simple-astro-cap/bin/fxload -t fx3 -I /path/to/simple-astro-cap/firmware/qhy/QHY5III585.img -D $env{DEVNAME}"
# QHY5III178
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0178", RUN+="/path/to/simple-astro-cap/bin/fxload -t fx3 -I /path/to/simple-astro-cap/firmware/qhy/QHY5III178.img -D $env{DEVNAME}"
# QHY5III290
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0290", RUN+="/path/to/simple-astro-cap/bin/fxload -t fx3 -I /path/to/simple-astro-cap/firmware/qhy/QHY5III290.img -D $env{DEVNAME}"
# QHY5III462
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0462", RUN+="/path/to/simple-astro-cap/bin/fxload -t fx3 -I /path/to/simple-astro-cap/firmware/qhy/QHY5III462.img -D $env{DEVNAME}"
# QHY5III678
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0678", RUN+="/path/to/simple-astro-cap/bin/fxload -t fx3 -I /path/to/simple-astro-cap/firmware/qhy/QHY5III678.img -D $env{DEVNAME}"

# Add more cameras as needed — see firmware/qhy/ for available firmware files.
# The product ID is typically the model number (e.g., 0585 for QHY5III585).

# ---- Permissions for all QHY devices ----
ATTRS{idVendor}=="1618", MODE="0666"
ATTRS{idVendor}=="16c0", MODE="0666"
ATTRS{idVendor}=="1856", MODE="0666"
ATTRS{idVendor}=="04b4", MODE="0666"

LABEL="qhy_end"
```

**Replace `/path/to/simple-astro-cap/`** with the actual install location.

### Using AstroDMx udev rules instead

If [AstroDMx Capture](https://www.astrodmx-capture.org.uk/) is installed at
`/opt/AstroDMx-Capture/`, its udev rules already handle firmware loading and
permissions for all supported QHY cameras. No additional setup is needed for QHY.

You still need the ZWO ASI rules above if using ASI cameras.

### Applying udev rules

After creating or modifying rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the camera.

---

## 4. fxload Utility (QHY only)

The `fxload` utility uploads firmware to QHY cameras over USB. It is required for
QHY cameras to function.

**If AstroDMx is installed**: it provides fxload at `/opt/AstroDMx-Capture/bin/fxload`.

**Otherwise**, install fxload from your distribution:

```bash
# Arch (AUR)
yay -S fxload

# Debian/Ubuntu
sudo apt install fxload
```

If using a system-installed fxload, update the udev rules above to use `/usr/bin/fxload`
or `/sbin/fxload` instead of the project path.

---

## 5. QHY Firmware Files

QHY firmware files are needed in `firmware/qhy/`. These can be sourced from an
AstroDMx Capture installation (`/opt/AstroDMx-Capture/firmware/qhy/`) or from
the QHY SDK distribution.

If you have a QHY camera model not listed in the udev rules, check `firmware/qhy/`
for a matching `.img` (FX3) or `.HEX` (legacy FX2) file and add a rule following
the pattern above.

---

## 6. Running

```bash
# From the project directory
python run.py

# Or if installed via pip
simple-astro-cap

# Simulator mode (no camera required)
python run.py --sim
```

---

## 7. Verifying Camera Detection

1. Plug in the camera and wait 2-3 seconds (firmware upload)
2. Check that the device is accessible:
   ```bash
   lsusb | grep -i -E "qhy|zwo|1618|03c3"
   ```
3. Launch the application — the camera should appear in the dropdown

### Troubleshooting

**Camera not detected**:
- Check `dmesg` for USB errors after plugging in
- Verify udev rules are loaded: `udevadm test /sys/bus/usb/devices/<device>`
- For QHY: firmware must load successfully. Check `dmesg` for fxload output

**Permission denied**:
- Verify udev rules set `MODE="0666"` for the camera's vendor ID
- Run `ls -l /dev/bus/usb/XXX/YYY` to check device permissions

**QHY SDK fails silently**:
- The QHY SDK's `libusb-1.0.so.0` must be used (not the system version)
- This is handled automatically, but if you see connection failures, verify
  `lib/libusb-1.0.so.0` exists in the project directory

**ffmpeg not found (MKV recording)**:
- Install ffmpeg from your package manager
- Only required if you want to record in MKV format; PNG and SER work without it

---

## Summary of Dependencies

| Component | QHY Cameras | ZWO ASI Cameras | No Camera (Sim) |
|-----------|-------------|-----------------|-----------------|
| Python 3.11+ | Required | Required | Required |
| PySide6, NumPy, Pillow | Required | Required | Required |
| udev rules | Required | Required | Not needed |
| fxload | Required | Not needed | Not needed |
| Firmware files | Required | Not needed | Not needed |
| ffmpeg | Optional (MKV) | Optional (MKV) | Optional (MKV) |
| AstroDMx installed | Alternative to manual setup | No | No |
