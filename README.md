# Simple Astro Cap

A simple, keyboard-centric camera capture application for QHY, ZWO, Player One, and Touptek astronomy cameras, built with Python and PySide6.

## Why

Most astronomy camera applications are designed for full astrophotography setups — filter wheels, automated tracking mounts, camera cooling, and complex session planning. For simple terrestrial infrared photography, all that gets in the way. Simple Astro Cap strips things down to the essentials: connect a camera, see the live feed, adjust exposure and gain, and record frames to PNG, SER, or lossless MKV files. It's designed for use with a QHY5III585M and ASI678MM, though the architecture supports other QHY and ZWO cameras.

## What

- **Multi-camera support** — QHY, ZWO ASI, Player One, and Touptek cameras via native SDK bindings
- **Live camera view** with dynamic zoom from fit-to-viewport through 100%, with scroll bars at higher zoom levels
- **Keyboard-centric controls** — field navigation, exposure/gain/zoom adjustment, capture, and recording all driven by keyboard
- **Smart exposure stepping** — automatic unit switching (µs ±10, ms ±1, s ±0.25) with seamless transitions at boundaries
- **Portrait/landscape orientation** — toggle frame rotation, affects both display and recordings
- **PNG/TIFF, SER, and MKV recording** — single-frame snapshots (PNG or TIFF), multi-frame sequences, or lossless video
- **SER file format** — standard free-astro.org format with timestamps and metadata, compatible with stacking software like AutoStakkert and RegiStax
- **MKV video** — lossless FFV1 encoding via ffmpeg (8/16-bit mono, metadata embedded)
- **Recording limits** — set time (seconds), frame count, or both; when both are set, FPS is derived automatically to fit frames into the time window
- **Session metadata** — each recording session writes a `.txt` summary (start/end time, frames, FPS, exposure, gain, etc.)
- **8-bit and 16-bit capture** — selectable before connecting
- **Binning support** — 1x1 (default), 2x2 depending on camera capabilities, with safe stop/restart cycle
- **Offset (black level) control** — ADC offset persisted across sessions; range set per camera
- **Sensor temperature** — live readout in the status bar (when supported by camera)
- **Hardware auto-exposure/gain** — enabled when the camera supports it (QHY and ZWO ASI); greyed out otherwise
- **Software auto-exposure** — always available; adjusts exposure based on frame brightness with proportional control; mutually exclusive with hardware auto
- **Brightness/contrast controls** — display-only adjustments (keyboard B/C to focus, left/right to adjust)
- **Histogram** — toggleable live histogram in sidebar
- **Recording locks** — only zoom, exposure, and gain are adjustable during recording; all other settings locked
- **Adjustable sidebar** — drag to resize, width persisted across sessions
- **Camera hotplug** — manual refresh button to detect newly connected cameras
- **Viewport downsampling** — automatic decimation at all sub-100% zoom levels for efficient display
- **Simulator backend** — test the GUI without a physical camera (`--sim` flag)
- **Mono only** for now

## Architecture

```
MultiCamera (aggregates QHY + ZWO + Player One + Touptek backends)
  |
  v
Camera (QHY / ZWO ASI / Player One / Touptek SDK via ctypes, or Simulator)
  |
  v
SimpleHarness (worker thread polls camera, dispatches frames)
  |  frame_transform (optional rotation for portrait mode)
  |
  +---> DisplayBridge (QObject, emits Qt signal for thread-safe GUI update)
  |       |
  |       v
  |     LiveViewWidget (QScrollArea + inner image widget, dynamic zoom)
  |
  +---> Recorder (PngRecorder, SerRecorder, or MkvRecorder)
```

The camera layer is abstracted behind `CameraBase` (ABC). A `MultiCamera` aggregator discovers cameras from all available backends (QHY, ZWO ASI, Player One, Touptek) and delegates to the appropriate one. The pipeline uses a simple worker thread that polls the camera, applies an optional frame transform (e.g., 90° rotation for portrait mode), and dispatches `Frame` objects to registered consumers. The `DisplayBridge` converts worker-thread callbacks into Qt signals so the GUI updates happen safely on the main thread.

### Module layout

```
src/simple_astro_cap/
├── camera/
│   ├── abc.py              # CameraBase, Frame, Param, ROI, CameraInfo
│   ├── multi.py            # MultiCamera aggregator (QHY + ZWO + Player One + Touptek)
│   ├── qhy/
│   │   ├── sdk.py          # ctypes bindings to libqhyccd.so
│   │   ├── constants.py    # QHY SDK control IDs and flags
│   │   └── backend.py      # QhyCamera implementation
│   ├── asi/
│   │   ├── sdk.py          # ctypes bindings to libASICamera2.so
│   │   ├── constants.py    # ZWO ASI control types and enums
│   │   └── backend.py      # AsiCamera implementation
│   ├── playerone/
│   │   ├── sdk.py          # ctypes bindings to libPlayerOneCamera.so
│   │   ├── constants.py    # Player One config IDs and enums
│   │   └── backend.py      # PlayerOneCamera implementation
│   ├── touptek/
│   │   ├── sdk.py          # ctypes bindings to libtoupcam.so
│   │   ├── constants.py    # Touptek option IDs and enums
│   │   └── backend.py      # ToupcamCamera implementation
│   └── sim/
│       └── backend.py      # SimCamera (test patterns)
├── pipeline/
│   ├── abc.py              # FrameConsumer, FrameProducer protocols
│   └── simple.py           # SimpleHarness (worker thread + frame transform)
├── recording/
│   ├── abc.py              # RecorderBase (FPS gating, frame/time limits)
│   ├── png_recorder.py     # PNG sequence recorder (tEXt metadata + summary JSON)
│   ├── ser_recorder.py     # SER video recorder (per-frame timestamps)
│   └── mkv_recorder.py     # MKV lossless video (FFV1 via ffmpeg)
├── gui/
│   ├── main_window.py      # MainWindow (orchestrates everything)
│   ├── display_bridge.py   # Worker thread -> Qt signal bridge
│   ├── live_view.py        # LiveViewWidget (QScrollArea + dynamic zoom)
│   ├── camera_panel.py     # Camera settings sidebar + keyboard navigation
│   ├── recording_panel.py  # Recording settings sidebar
│   ├── histogram.py        # Live histogram widget
│   └── shortcuts.py        # Keyboard shortcut definitions
├── util/
│   └── units.py            # Exposure unit conversion (us/ms/s)
└── app.py                  # Application entry point
```

## How to run

See [INSTALL.md](INSTALL.md) for full setup including udev rules, firmware, and dependencies.

### Quick start

```bash
cd simple-astro-cap
pip install -e .

# With a camera
python run.py

# Simulator (no camera needed)
python run.py --sim
```

### Requirements

- Python 3.11+
- Camera SDK libraries in `lib/` and firmware in `firmware/` (sourced from [AstroDMx Capture](https://www.astrodmx-capture.org.uk/) install)
- USB access to the camera (udev rules required)
- Optional: ffmpeg for MKV recording

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `X` | Focus exposure field |
| `G` | Focus gain field |
| `Z` | Focus zoom field |
| `B` | Focus brightness control |
| `C` | Focus contrast control |
| `Up` / `Down` | Navigate to previous / next field |
| `Left` / `Right` | Decrease / increase focused value |
| `Space` | Capture single frame (PNG) |
| `R` | Start / stop recording |
| `Ctrl+X` | Toggle auto-exposure |
| `Ctrl+G` | Toggle auto-gain |
| `Ctrl+Q` | Quit |

The focused field's label is bolded for visibility. Exposure stepping is smart: ±10 µs in microsecond range, ±1 ms in millisecond range, ±0.25 s in second range, with automatic unit switching at boundaries.

## QHY SDK notes

The QHY SDK has several quirks that required workarounds:

- **Bundled dependencies**: The SDK's bundled `libusb`, `libstdc++`, and `libgcc_s` must be pre-loaded with `RTLD_GLOBAL` before loading `libqhyccd.so`. System versions are incompatible.
- **USB state corruption**: Opening and then closing a camera handle corrupts the SDK's internal USB state. All subsequent calls fail until the camera is physically re-plugged. The app works around this by keeping the handle open after the initial probe (`pre_open`) and reusing it on `connect()`.
- **Init sequence**: `InitResource` -> `Scan` -> `GetId` -> `Open` -> `SetStreamMode(LIVE)` -> `InitQHYCCD` -> `SetBitsMode` -> `SetBinMode` -> `SetResolution` -> `SetParams` -> `BeginLive`. Deviating from this order causes failures.
- **Default parameters required**: The camera won't produce frames until exposure, gain, and USB traffic are explicitly set after `InitQHYCCD`.
- **SetQHYCCDReadMode**: Not called — AstroDMx doesn't call it and the camera works without it.
- **Auto-exposure**: Control ID 88 (0x58) via `SetQHYCCDParam` enables the SDK's internal 3A auto-exposure system, which manages both exposure and gain together. `QHYCCD_SetAutoEXPmessureValue` sets the target brightness. These signatures were reverse-engineered from the shared library as they're undocumented.

## License

PySide6 is used under the LGPL. No other restrictive licenses apply.
