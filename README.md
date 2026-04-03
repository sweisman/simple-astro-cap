# Simple Astro Cap

A simple, keyboard-centric camera capture application for QHY, ZWO, Player One, and Touptek astronomy cameras, built with Python and PySide6. **Linux only** — see [Adding Windows support](#adding-windows-support) for porting notes.

## Why

Most astronomy camera applications are designed for full astrophotography setups — filter wheels, automated tracking mounts, camera cooling, and complex session planning. For simple terrestrial infrared photography, all that gets in the way. Simple Astro Cap strips things down to the essentials: connect a camera, see the live feed, adjust exposure and gain, and record frames to PNG, SER, or lossless MKV files. It's designed for use with a QHY5III585M and ASI678MM, though the architecture supports other QHY, ZWO, Player One, and Touptek cameras.

## Features

- **Multi-camera support** — QHY, ZWO ASI, Player One, and Touptek cameras via native SDK bindings
- **Live camera view** with dynamic zoom from fit-to-viewport through 100%, with scroll bars at higher zoom levels
- **Keyboard-centric controls** — field navigation, exposure/gain/zoom adjustment, capture, and recording all driven by keyboard
- **Smart exposure stepping** — automatic unit switching (µs ±10, ms ±0.25/±1, s ±0.25) with seamless transitions at boundaries; finer 0.25ms steps in the 1–10ms range
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
- **Hardware auto-exposure/gain** — enabled when the camera supports it; greyed out otherwise
- **Software auto-exposure** — always available; adjusts exposure based on frame brightness with proportional control; mutually exclusive with hardware auto
- **Brightness/contrast controls** — display-only adjustments (keyboard B/C to focus, left/right to adjust)
- **Histogram** — toggleable live histogram in sidebar
- **Battery saver mode** — throttles display to 1 fps during recording to reduce CPU/GPU load on small field devices; checkbox enabled only while recording, state persisted
- **Recording locks** — only zoom, exposure, and gain are adjustable during recording; all other settings locked
- **Frame drop detection** — sequence gap analysis reported in session `.txt` and status bar
- **Raw Bayer metadata** — color cameras record raw (un-debayered) data with correct Bayer pattern metadata in SER headers, PNG/TIFF tags, MKV metadata, and session summaries; stacking software can debayer after the fact
- **Viewport downsampling** — automatic decimation at all sub-100% zoom levels for efficient display
- **Simulator backend** — test the GUI without a physical camera (`--sim` flag)

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

The focused field's label is bolded for visibility. Exposure stepping is smart: ±10 µs in microsecond range, ±0.25 ms from 1–10 ms then ±1 ms above 10 ms, ±0.25 s in second range, with automatic unit switching at boundaries.

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

The camera layer is abstracted behind `CameraBase` (ABC). A `MultiCamera` aggregator discovers cameras from all available backends and delegates to the appropriate one. The pipeline uses a simple worker thread that polls the camera, applies an optional frame transform (e.g., 90° rotation for portrait mode), and dispatches `Frame` objects to registered consumers. The `DisplayBridge` converts worker-thread callbacks into Qt signals so the GUI updates happen safely on the main thread.

### Module layout

```
src/simple_astro_cap/
├── camera/
│   ├── abc.py              # CameraBase, Frame, Param, ROI, CameraInfo
│   ├── multi.py            # MultiCamera aggregator
│   ├── qhy/                # QHY backend (ctypes to libqhyccd.so)
│   ├── asi/                # ZWO ASI backend (ctypes to libASICamera2.so)
│   ├── playerone/          # Player One backend (ctypes to libPlayerOneCamera.so)
│   ├── touptek/            # Touptek backend (ctypes to libtoupcam.so)
│   └── sim/                # SimCamera (test patterns)
├── pipeline/
│   ├── abc.py              # FrameConsumer, FrameProducer protocols
│   └── simple.py           # SimpleHarness (worker thread + frame transform)
├── recording/
│   ├── abc.py              # RecorderBase (FPS gating, frame/time limits)
│   ├── png_recorder.py     # PNG sequence recorder (tEXt metadata)
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

### Recording file layout

```
{output_dir}/
  snapshots/
    YYYY-MM-DD-HH:MM:SS-NNNNNN.png
  sessions/
    YYYY-MM-DD/
      YYYY-MM-DD-HH:MM:SS-NNNNNN.ser   (+ .txt)
      YYYY-MM-DD-HH:MM:SS-NNNNNN.mkv   (+ .txt)
      YYYY-MM-DD-HH:MM:SS-NNNNNN/      (PNG session dir)
        YYYY-MM-DD-HH:MM:SS-MMMMMM-NNNNNN.png  (MMMMMM=start seq)
        session.txt
```

### Settings

JSON at `~/.config/simple-astro-cap/settings.json`. Camera is never persisted — always starts disconnected.

## Code conventions

- Python 3.11+, PySide6 for GUI, no OpenCV dependency
- `from __future__ import annotations` in every module
- Exposure values always in microseconds internally; display conversion in `util/units.py`
- Camera backends use ctypes to native SDK shared libraries in `lib/` (sourced from AstroDMx install)
- No test suite — verify changes with `python -m py_compile` on all modified files

### Key patterns

- **Camera lifecycle**: Never open+close a QHY camera handle during enumeration — it corrupts USB state. The `pre_open` pattern keeps the handle alive for reuse on `connect()`.
- **Signal blocking**: Always use `blockSignals(True/False)` when programmatically setting Qt widget values to prevent recursive signal chains.
- **Thread safety**: Camera polling runs on a worker thread (`SimpleHarness`). GUI updates must go through `DisplayBridge` (QObject signal). Recorders receive frames on the worker thread.
- **Recording gating**: `RecorderBase.on_frame()` handles FPS throttling, max-frames, and max-duration auto-stop. Subclasses only implement `_write_frame()`.
- **Sequence numbers**: `snap_sequence` and `session_sequence` in settings are monotonically increasing and never reset.

## QHY SDK notes

The QHY SDK has several quirks that required workarounds:

- **Bundled dependencies**: The SDK's bundled `libusb`, `libstdc++`, and `libgcc_s` must be pre-loaded with `RTLD_GLOBAL` before loading `libqhyccd.so`. System versions are incompatible.
- **USB state corruption**: Opening and then closing a camera handle corrupts the SDK's internal USB state. All subsequent calls fail until the camera is physically re-plugged. The app works around this by keeping the handle open after the initial probe (`pre_open`) and reusing it on `connect()`.
- **Init sequence**: `InitResource` -> `Scan` -> `GetId` -> `Open` -> `SetStreamMode(LIVE)` -> `InitQHYCCD` -> `SetBitsMode` -> `SetBinMode` -> `SetResolution` -> `SetParams` -> `BeginLive`. Deviating from this order causes failures.
- **Default parameters required**: The camera won't produce frames until exposure, gain, and USB traffic are explicitly set after `InitQHYCCD`.
- **SetQHYCCDReadMode**: Not called — AstroDMx doesn't call it and the camera works without it.
- **Auto-exposure**: Control ID 88 (0x58) via `SetQHYCCDParam` enables the SDK's internal 3A auto-exposure system, which manages both exposure and gain together. `QHYCCD_SetAutoEXPmessureValue` sets the target brightness. These signatures were reverse-engineered from the shared library as they're undocumented.
- **USB traffic**: Currently hardcoded to 30; not yet exposed as a user control.

## Testing needed

- ZWO ASI camera (ASI678MM) — backend written, awaiting hardware test
- Player One camera — backend written, awaiting hardware test
- Touptek camera — backend written, awaiting hardware test
- 16-bit capture mode
- SER file compatibility with stacking software

## TODO

- [ ] USB traffic control (currently hardcoded to 30)
- [ ] ROI display overlay on live view
- [ ] Crosshair overlay for focusing
- [ ] High-performance ring buffer pipeline — decouples camera polling from disk I/O via a pre-allocated circular buffer on separate threads, absorbing brief I/O stalls without dropping frames. Unlikely to be needed for most astro cameras on SSD storage at 8-bit; current simple pipeline handles full-resolution 40+ FPS to SER without issues. Consider only if frame drop detection reports losses in practice.
- [ ] Color camera display support (debayering) — raw Bayer recording already works

### Adding color camera support

Color cameras already work — they record raw Bayer data with correct metadata. What's missing is debayered display and color-aware recording. Two approaches:

**Hardware debayer (SDK-side)**: Request RGB24 format from the SDK instead of RAW8/RAW16. The SDK debayers internally and returns 3-channel data. Changes needed:
- Backends: request RGB24 image format for color cameras
- `Frame.data`: allow 3D arrays `(h, w, 3)` in addition to 2D
- `live_view.py`: use `QImage.Format_RGB888` instead of `Format_Grayscale8`
- Recorders: PNG mode `"RGB"`, SER ColorID `100` (RGB), MKV pix_fmt `"rgb24"`
- Histogram: compute per-channel or luminance
- Decimation/rotation: slice `data[::step, ::step, :]` and `np.rot90(data, axes=(0,1))`
- Software auto-exposure: compute brightness from luminance

**Software debayer (raw Bayer kept internally)**: Keep requesting RAW8/RAW16 and debayer in Python for display only. Recording stays raw Bayer (smaller files, no quality loss). Changes needed:
- All of the above for display path only
- Add a debayer step in `DisplayBridge` or `_on_new_frame` using scipy/numpy Bayer interpolation
- Recording path stays unchanged (already handles raw Bayer with correct metadata)
- New dependency: `scipy.ndimage` or a small Bayer interpolation routine

The software debayer approach is better for recording quality (no SDK color processing baked in), while hardware debayer is simpler and faster for display. A hybrid — raw Bayer for recording, SDK RGB for display — would require the SDK to deliver both formats simultaneously, which most SDKs don't support. The practical choice is software debayer for display with raw Bayer recording.

### Adding Windows support

The codebase is pure Python + PySide6 + ctypes, all cross-platform. The Linux-specific parts are:

- **SDK library loading**: Backends look for `.so` files. On Windows, use `.dll` equivalents (all four vendors provide Windows SDKs). Add `sys.platform` checks to select the right library name/extension.
- **QHY dependency pre-loading**: The `RTLD_GLOBAL` trick for pre-loading bundled libusb/libstdc++/libgcc_s is Linux-specific. On Windows, the QHY SDK bundles its own DLLs and handles dependencies internally — skip this step entirely.
- **Settings path**: Uses `~/.config/simple-astro-cap/`. On Windows, use `%APPDATA%` (e.g., via the `platformdirs` package or a `sys.platform` check).
- **udev rules**: Not applicable on Windows. USB cameras are accessible without special permissions. QHY firmware loading is handled by the vendor's Windows driver installer.

Everything else works unchanged: GUI, recording, pipeline, frame processing, keyboard shortcuts, ffmpeg for MKV.

## License

PySide6 is used under the LGPL. No other restrictive licenses apply.
