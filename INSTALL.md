# Simple Astro Cap — Installation Guide

## Requirements

- Linux (tested on Arch Linux)
- Python 3.11+
- USB 3.0 port (recommended for full-speed capture)

### Supported Cameras

- **QHY** cameras (tested: QHY5III585M)
- **ZWO ASI** cameras (tested: ASI678MM)
- **Player One** cameras
- **Touptek** cameras

---

## Quick Start

```bash
cd simple-astro-cap
pip install -e .

# Fetch vendor SDK libraries and QHY firmware from the vendors' own downloads
./scripts/fetch-deps.sh --qhy

# Generate and install udev rules with this checkout's real paths
sudo ./scripts/install-udev-rules.sh

# Unplug and replug the camera, then:
python run.py
```

No other astronomy software needs to be installed. Everything below is detail on what
those two scripts do and how to do it by hand.

---

## 1. Python Dependencies

```bash
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

## 2. Camera SDK Libraries and Firmware

`scripts/fetch-deps.sh` downloads the vendor SDKs and unpacks what the application needs
into `lib/` and `firmware/qhy/`. Both directories are gitignored — see
[Licensing](#licensing) for why.

```bash
./scripts/fetch-deps.sh              # every vendor
./scripts/fetch-deps.sh --qhy        # just QHY
./scripts/fetch-deps.sh --qhy --force   # re-fetch / upgrade SDK version
./scripts/fetch-deps.sh --clean-cache   # drop vendor-cache/
```

| Vendor | Automated? | Source |
|--------|-----------|--------|
| QHY | Yes | `sdk_linux64_<version>.tgz` from qhyccd.com |
| ZWO ASI | Yes (~112 MB — ZWO has no Linux-only endpoint) | ZWO download centre |
| Player One | No | <https://player-one-astronomy.com/service/software/> |
| Touptek | No | <https://www.touptek-astro.com/download/> |

SDK versions and URLs live in `scripts/deps.conf`. Bumping a vendor version is a one-line
edit there.

### The QHY archive covers everything QHY-related

One download provides `libqhyccd.so`, the complete firmware set (109 files), QHYCCD's
official udev rules, and the GPLv2 source for `fxload`. The extracted SDK stays in
`vendor-cache/`, where `install-udev-rules.sh` reads the rules and the fxload source.

### Player One and Touptek

These two backends resolve their library through `ctypes.util.find_library()` rather than
the project's `lib/` directory, so the supported path is a system-wide install using the
vendor's own installer. If you would rather keep them project-local, download the Linux
SDK archive by hand into `vendor-cache/` and re-run `fetch-deps.sh` — it will find and
unpack it.

Touptek OEMs cameras under many brand names (Altair, Omegon, Bresser, Celestron, …) —
these all use the same SDK and the same udev rules.

### Which libraries end up in `lib/`

| File | Purpose |
|------|---------|
| `libqhyccd.so` | QHY camera SDK |
| `libASICamera2.so` | ZWO ASI camera SDK |
| `libPlayerOneCamera.so` | Player One camera SDK (optional) |
| `libtoupcam.so` | Touptek camera SDK (optional) |

**Note on bundled runtime libraries.** Older QHY builds shipped their own
`libusb-1.0.so.0`, `libstdc++.so.6` and `libgcc_s.so.1`, because the system libusb was a
different version and caused silent failures. The application still pre-loads those three
with `RTLD_GLOBAL` from `lib/` if they are present (`camera/qhy/sdk.py`), and silently
carries on if they are not. Current QHY SDK builds link cleanly against system libraries,
so `fetch-deps.sh` does not install them. If you hit unexplained QHY connection failures,
dropping the SDK's own copies into `lib/` is the first thing to try.

---

## 3. USB Device Permissions (udev rules)

Cameras are USB devices. Without udev rules, only root can access them. QHY cameras
additionally need **firmware uploaded over USB every time they are plugged in**.

```bash
./scripts/install-udev-rules.sh --dry-run   # print the rules, install nothing
sudo ./scripts/install-udev-rules.sh        # install into /etc/udev/rules.d and reload
```

The script:

- resolves a usable `fxload` and checks it actually supports FX3 targets;
- generates `85-qhyccd.rules` from **QHYCCD's own rules file**, rewriting `/sbin/fxload`
  and `/lib/firmware/qhy` to this checkout's absolute paths — so every QHY model QHYCCD
  supports is covered, not a hand-maintained subset;
- warns about any firmware a rule references but that isn't present on disk;
- generates permission rules for ASI, Player One and Touptek;
- raises `usbfs_memory_mb` to 200 for QHY, ASI and Player One — the 16 MB default is not
  enough for large frames at high frame rates;
- reloads udev.

Run `fetch-deps.sh --qhy` first: the QHY rules are derived from the SDK in
`vendor-cache/`, and the script will skip them if it isn't there.

After installing, unplug and replug the camera.

### If you move the checkout

The installed rules contain absolute paths, baked in at generation time. Both scripts
work from any location and can be invoked from any working directory, but **if you move
or rename the checkout after installing, re-run `sudo ./scripts/install-udev-rules.sh`** —
otherwise the rules point at the old location and firmware will silently stop loading.

udev has no way to quote an argument inside `RUN+=`, so a checkout path containing a
space, a double quote or a backslash cannot produce working firmware rules. The script
refuses to generate them rather than installing rules that would never fire. Other
awkward characters (`&`, `|`, `+`, brackets) are handled correctly.

---

## 4. fxload

`fxload` uploads firmware to QHY cameras over USB. It is invoked by **udev at plug-in
time** — the application itself never calls it, and does not depend on it being present
while running.

Confusingly, two incompatible programs are both called `fxload`:

| Variant | Firmware flag | Device selector | Where it comes from |
|---------|---------------|-----------------|---------------------|
| **ezusb** (David Brownell's original, GPLv2) | `-I` | `-D $env{DEVNAME}` | QHY's SDK, `usr/local/fx3load/` |
| **libusb** (modern fork, `fxload` 1.x) | `-i` | `-p <bus>,<addr>` | distro packages |

Both support FX3. `install-udev-rules.sh` detects which one it found and emits matching
arguments, so either will work. It prefers the ezusb variant, because that is what QHY's
rules are written against and it talks to usbfs directly instead of rescanning USB from
inside a udev `add` event.

**Using your distro's package:**

```bash
# Arch (AUR)
yay -S fxload
# Debian/Ubuntu
sudo apt install fxload
```

**Building QHY's own copy** (no distro package needed; plain `cc`, no libusb headers):

```bash
./scripts/install-udev-rules.sh --build-fxload
```

This compiles the GPLv2 source from the QHY SDK into `bin/fxload` and keeps
`main.c`, `ezusb.c`, `ezusb.h`, `Makefile` and `COPYING` next to it.

If no `fxload` with FX3 support can be found, the script fails with these options rather
than writing rules that would silently never fire.

---

## 5. Running

```bash
# From the project directory
python run.py

# Or if installed via pip
simple-astro-cap

# Simulator mode (no camera required)
python run.py --sim
```

---

## 6. Verifying Camera Detection

1. Plug in the camera and wait 2-3 seconds (firmware upload)
2. Check that the device is accessible:
   ```bash
   lsusb | grep -i -E "qhy|zwo|playerone|touptek|1618|03c3"
   ```
3. Launch the application — the camera should appear in the dropdown

### Troubleshooting

**Camera not detected**:
- Check `dmesg` for USB errors after plugging in
- Verify udev rules are loaded: `udevadm test /sys/bus/usb/devices/<device>`
- For QHY: firmware must load successfully. Check `dmesg` for fxload output
- Confirm the generated rule points at a firmware file that exists:
  `./scripts/install-udev-rules.sh --dry-run | grep <your model>`

**Permission denied**:
- Verify udev rules set `MODE="0666"` for the camera's vendor ID
- Run `ls -l /dev/bus/usb/XXX/YYY` to check device permissions

**QHY firmware never uploads**:
- If you are on the libusb `fxload`, try the ezusb one:
  `./scripts/install-udev-rules.sh --build-fxload` then re-run with `sudo`

**QHY SDK fails silently**:
- See the note on bundled runtime libraries in §2

**ffmpeg not found (MKV recording)**:
- Install ffmpeg from your package manager
- Only required if you want to record in MKV format; PNG and SER work without it

---

## Licensing

`LICENSE` (GPL-3) covers the Python source in this repository only.

`lib/`, `firmware/`, `bin/` and `vendor-cache/` hold third-party binaries under their own
terms and are deliberately **never tracked in git**:

- **Vendor SDK libraries** (`libqhyccd.so`, `libASICamera2.so`, `libPlayerOneCamera.so`,
  `libtoupcam.so`) are proprietary. They are loaded at runtime via `ctypes` and are not
  redistributed by this project.
- **QHY firmware images** are QHYCCD's, with no public redistribution grant. This is why
  they are fetched from QHYCCD rather than vendored — the same approach distribution
  packagers take.
- **`fxload`** is GPLv2-or-later. If you build it with `--build-fxload`, the corresponding
  source and `COPYING` are placed alongside the binary so that copy stays compliant.

Fetching these from the vendors is your action as the installer, not redistribution by
this project.

---

## Summary of Dependencies

| Component | QHY | ZWO ASI | Player One | Touptek | Simulator |
|-----------|-----|---------|------------|---------|-----------|
| Python 3.11+ | Required | Required | Required | Required | Required |
| PySide6, NumPy, Pillow | Required | Required | Required | Required | Required |
| SDK library in `lib/` | Required | Required | System install | System install | Not needed |
| udev rules | Required | Required | Required | Required | Not needed |
| fxload | Required | Not needed | Not needed | Not needed | Not needed |
| Firmware files | Required | Not needed | Not needed | Not needed | Not needed |
| ffmpeg | Optional (MKV) | Optional (MKV) | Optional (MKV) | Optional (MKV) | Optional (MKV) |
