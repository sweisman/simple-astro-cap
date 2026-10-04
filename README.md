# Simple Astro Cap

A simple, keyboard-centric camera capture application for QHY, ZWO, Player One, and Touptek astronomy cameras, built with Python and PySide6. **Linux only** — see [Adding Windows support](#adding-windows-support) for porting notes.

## Why

Most astronomy camera applications are designed for full astrophotography setups — filter wheels, automated tracking mounts, camera cooling, and complex session planning. For simple terrestrial infrared photography, all that gets in the way. Simple Astro Cap strips things down to the essentials: connect a camera, see the live feed, adjust exposure and gain, and record frames to PNG, SER, or lossless MKV files. It's designed for use with a QHY5III585M and ASI678MM, though the architecture supports other QHY, ZWO, Player One, and Touptek cameras.

## Features

- **Multi-camera support** — QHY, ZWO ASI, Player One, and Touptek cameras via native SDK bindings
- **Live camera view** with dynamic zoom from fit-to-viewport through 100%, with scroll bars at higher zoom levels
- **Keyboard-centric controls** — field navigation, exposure/gain/zoom adjustment, capture, and recording all driven by keyboard
- **Smart exposure stepping** — automatic unit switching (µs ±10, ms ±0.25/±1, s ±0.25) with seamless transitions at boundaries; finer 0.25ms steps in the 1–10ms range
- **Portrait/landscape orientation** — rotates the live view only; recordings and snapshots always keep native sensor orientation (so Bayer metadata stays valid)
- **PNG/TIFF, SER, and MKV recording** — single-frame snapshots (PNG or TIFF), multi-frame sequences, or lossless video
- **SER file format** — standard free-astro.org format with per-frame capture timestamps and metadata, compatible with stacking software like AutoStakkert and RegiStax
- **MKV video** — lossless FFV1 encoding via ffmpeg (8/16-bit mono, metadata embedded); `mkvmerge` applies each frame's real capture time, and the timestamps are also kept in a `.timestamps.txt` sidecar
- **Capture timestamps** — every frame is stamped (monotonic + UTC) the moment the SDK hands it over, before any disk I/O; SER trailers, PNG `CaptureUTC` and MKV timestamps all use that stamp. It marks readout completion as seen by the host, not exposure midpoint
- **Recording limits** — set time (seconds), frame count, or both; when both are set, FPS is derived automatically to fit frames into the time window
- **Session metadata** — each recording session writes a `.txt` summary (start/end time, frames, FPS, exposure, gain, etc.)
- **8-bit and 16-bit capture** — selectable before connecting
- **Binning support** — 1x1 (default), 2x2 depending on camera capabilities, with safe stop/restart cycle
- **Offset (black level) control** — ADC offset persisted across sessions; range set per camera
- **Sensor temperature** — live readout in the status bar (when supported by camera)
- **Hardware auto-exposure/gain** — enabled when the camera supports it; greyed out otherwise
- **Software auto-exposure** — always available; adjusts exposure based on frame brightness with proportional control; mutually exclusive with hardware auto
- **HDR** — checkbox shown whenever the selected camera has native sensor HDR (QHY IMX585 bodies such as QHY5III585 and MiniCam8), enabled only when connected in 16-bit mode with 1x1 binning and hardware auto-exposure/gain off; while HDR is on, binning and the hardware auto controls are locked. A live sensor mode that applies to view, recordings and snaps; shown as an `HDR` badge in the status bar, `hdr: hardware` in the session `.txt`, and `Hdr=hardware` in snapshot metadata. Intended for planet-plus-stars fields (e.g. Mars parallax plate solving)
- **Brightness/contrast controls** — display-only adjustments (keyboard B/C to focus, left/right to adjust)
- **Histogram** — toggleable live histogram in sidebar
- **Battery saver mode** — throttles display to 1 fps during recording to reduce CPU/GPU load on small field devices; checkbox enabled only while recording, state persisted
- **Recording locks** — only zoom, orientation (display-only), exposure, and gain are adjustable during recording; all other settings locked. Exposure/gain/offset changes made while recording are logged with UTC timestamps in the session `.txt`
- **Frame loss accounting** — losses are counted where they happen and reported in the status bar (`LOST n`) and session `.txt`: inside the SDK/camera (ASI `ASIGetDroppedFrames`, Touptek SDK frame-sequence gaps, Player One `POAGetDroppedImagesCount`; `n/a` for QHY, whose SDK exposes no counter), record-queue overflow (disk not keeping up), and host-side sequence gaps
- **Record queue** — recorders run on their own writer thread behind a bounded RAM queue (`record_queue_mb` in settings, default 1024), so disk stalls never stop camera polling; on stop, queued frames are flushed before the file is closed
- **Recording failure handling** — free space is checked before and during recording (stops cleanly below 512 MB); a write error (e.g. disk full) stops the recording, finalises the file with the frames already written, and shows an error dialog
- **Raw Bayer metadata** — color cameras record raw (un-debayered) data with correct Bayer pattern metadata in SER headers, PNG/TIFF tags, MKV metadata, and session summaries; stacking software can debayer after the fact
- **Viewport downsampling** — automatic decimation at all sub-100% zoom levels for efficient display
- **Simulator backend** — test the GUI without a physical camera (`--sim` flag)

## How to run

See [INSTALL.md](INSTALL.md) for full setup including udev rules, firmware, and dependencies.

### Quick start

```bash
cd simple-astro-cap
pip install -e .

# One-time: fetch vendor SDK libraries + QHY firmware, install udev rules
./scripts/fetch-deps.sh --qhy
sudo ./scripts/install-udev-rules.sh

# With a camera
python run.py

# Simulator (no camera needed)
python run.py --sim
```

### Requirements

- Python 3.11+
- Camera SDK libraries in `lib/` and firmware in `firmware/` (fetched from the vendors by `./scripts/fetch-deps.sh`)
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
| `Space` | Snapshot the next frame acquired after the keypress (PNG/TIFF) |
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
SimpleHarness
  |  capture thread: get frame (backend copies + stamps it), nothing else
  |
  +---> inline consumers (must be cheap)
  |       DisplayBridge: one-frame mailbox -> Qt signal -> LiveViewWidget
  |                      (portrait rotation, zoom, brightness applied here)
  |       SoftwareAutoExposure (throttled)
  |
  +---> bounded record queue (byte budget; overflow counted)
          |
          v  writer thread
        Recorder (PngRecorder, SerRecorder, or MkvRecorder)
```

The camera layer is abstracted behind `CameraBase` (ABC). A `MultiCamera` aggregator discovers cameras from all available backends and delegates to the appropriate one. The capture thread polls the camera and hands each `Frame` to inline consumers and to the record queue; a separate writer thread feeds recorders, so disk I/O never blocks acquisition. The `DisplayBridge` is a latest-frame mailbox: at most one GUI update is pending at a time, so a slow GUI drops display frames instead of queueing them.

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
- Camera backends use ctypes to native SDK shared libraries in `lib/` (fetched by `scripts/fetch-deps.sh`)
- Tests: `python -m pytest tests/` (no hardware needed; MKV tests skip without ffmpeg/mkvmerge)

### Key patterns

- **Camera lifecycle**: Never open+close a QHY camera handle during enumeration — it corrupts USB state. The `pre_open` pattern keeps the handle alive for reuse on `connect()`.
- **Signal blocking**: Always use `blockSignals(True/False)` when programmatically setting Qt widget values to prevent recursive signal chains.
- **Thread safety**: Camera polling runs on the capture thread (`SimpleHarness`); recorders run on the writer thread (`add_consumer(..., queued=True)`). GUI updates must go through `DisplayBridge`. Anything added as an inline consumer runs on the capture thread and must not block.
- **Frame time**: use `Frame.capture_mono_ns` for intervals and `Frame.capture_utc_ns` for provenance; never take "now" at write time.
- **Recording gating**: `RecorderBase.on_frame()` handles FPS throttling, max-frames, and max-duration auto-stop. Subclasses only implement `_write_frame()`.
- **Sequence numbers**: `snap_sequence` and `session_sequence` in settings are monotonically increasing and never reset.

## QHY SDK notes

The QHY SDK has several quirks that required workarounds:

- **Bundled dependencies**: If `lib/` contains the SDK's own `libusb`, `libstdc++`, and `libgcc_s`, they are pre-loaded with `RTLD_GLOBAL` before `libqhyccd.so`; older SDK builds were incompatible with the system versions. Current SDK builds link cleanly against system libraries, so the preload silently no-ops when the files are absent.
- **USB state corruption**: Opening and then closing a camera handle corrupts the SDK's internal USB state. All subsequent calls fail until the camera is physically re-plugged. The app works around this by keeping the handle open after the initial probe (`pre_open`) and reusing it on `connect()`.
- **Init sequence**: `InitResource` -> `Scan` -> `GetId` -> `Open` -> `SetStreamMode(LIVE)` -> `InitQHYCCD` -> `SetBitsMode` -> `SetBinMode` -> `SetResolution` -> `SetParams` -> `BeginLive`. Deviating from this order causes failures.
- **Default parameters required**: The camera won't produce frames until exposure, gain, and USB traffic are explicitly set after `InitQHYCCD`.
- **SetQHYCCDReadMode**: Not called — AstroDMx doesn't call it and the camera works without it.
- **Auto-exposure**: Control ID 88 (0x58) via `SetQHYCCDParam` enables the SDK's internal 3A auto-exposure system, which manages both exposure and gain together. `QHYCCD_SetAutoEXPmessureValue` sets the target brightness. These signatures were reverse-engineered from the shared library as they're undocumented.
- **USB traffic**: Currently hardcoded to 30; not yet exposed as a user control.
- **Native HDR**: Control ID 1029 (`CONTROL_HDR` in `qhyccdstruct.h`) via `SetQHYCCDParam`; only the QHY5III585 and MiniCam8 classes in the bundled SDK implement it. The SDK fits `high = k*low + b` between its two 12-bit gain channels and re-aligns them into one 16-bit frame, so 16-bit mode must be selected — QHY document HDR as 16-bit only, not available for 8-bit. Only the *low* channel's k/b are exposed (1030/1031); the `_H_k`/`_H_b` entries are commented out in the header.
  - Take these IDs from a compiler, not from the `/*NNNN*/` comments in `qhyccdstruct.h` — five entries above HDR are commented out, so the annotations run five high (`CONTROL_HDR` is annotated 1034, compiles to 1029). They sit in the `//TEST id name list` block, which QHY call "custom controls provided by the QHY SDK"; the main enum ends at `CONTROL_MAX_ID = 94`.
  - `CONTROL_HDR` is tri-state, not boolean: `0` as-is output, `1` splice using the loaded k/b, `2` calculate k/b once. Enabling writes `2`, because `1` would splice with whatever k/b are left in the registers and QHY warn that bad k/b cause banding.
  - Gain and offset are driven by the camera in HDR mode and any values set in software have no effect, so the UI greys them out.
  - Not yet confirmed on hardware.

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
- [ ] Confirm SDK drop counters on real hardware (ASI678MM via `ASIGetDroppedFrames`; Player One/Touptek untested)
- [ ] SER `LittleEndian=0` interop check: open 16-bit test files in Siril, SER Player and AutoStakkert (0 follows the de-facto convention, opposite to the spec text)
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
