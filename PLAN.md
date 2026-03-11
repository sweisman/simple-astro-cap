# Simple Astro Cap — Project Plan

## Goal

Build a minimal, keyboard-centric camera capture application for QHY and ZWO astronomy cameras, focused on simple terrestrial IR photography workflows.

## Phase 1: Core infrastructure (DONE)

Everything needed to capture frames from the camera and record them, without the GUI.

- [x] Camera abstraction (`CameraBase` ABC, `Frame`, `Param`, `ROI`, `CameraInfo`)
- [x] QHY SDK ctypes bindings (`sdk.py`, `constants.py`)
- [x] QHY camera backend (`QhyCamera`) with full lifecycle support
- [x] SDK dependency pre-loading (libusb, libstdc++, libgcc_s from AstroDMx install)
- [x] Pre-open pattern to avoid USB state corruption on close
- [x] Simulator backend (`SimCamera`) for testing without hardware
- [x] Pipeline abstractions (`FrameConsumer`, `FrameProducer`)
- [x] SimpleHarness — worker thread polls camera, dispatches to consumers
- [x] PNG recorder — saves frames as numbered PNG files
- [x] SER recorder — standard free-astro.org format with timestamps and metadata
- [x] Exposure unit conversion utility (us/ms/s)

## Phase 2: GUI (DONE)

PySide6 GUI with live view and sidebar controls.

- [x] MainWindow with splitter layout (live view + sidebar)
- [x] LiveViewWidget — QScrollArea with dynamic zoom (fit-to-viewport through 100%)
- [x] DisplayBridge — thread-safe worker-to-GUI signal bridge
- [x] CameraPanel — camera selection, bit depth, binning, exposure, gain, zoom, orientation
- [x] RecordingPanel — format selection (PNG/SER), output dir, basename, frame limit
- [x] Lens/Telescope description field (saved in SER metadata)
- [x] FPS counter in status bar
- [x] No-camera-selected placeholder on startup
- [x] Signal blocking during UI population to prevent spurious SDK calls

## Phase 3: Camera features (DONE)

- [x] Exposure control with smart stepping (µs ±10, ms ±1, s ±0.25, auto unit switching)
- [x] Gain control
- [x] Binning selection with safe stop/restart harness cycle
- [x] Bit depth selection (pre-connect)
- [x] Dynamic zoom levels computed from image size vs viewport
- [x] Portrait/landscape orientation toggle (frame transform in harness)
- [x] Recording locks — only zoom, exposure, gain adjustable during recording
- [x] ZWO ASI camera backend (`AsiCamera` via ctypes to `libASICamera2.so`)
- [x] MultiCamera aggregator (discovers and delegates across QHY + ZWO backends)
- [x] Libs and firmware in project `lib/` and `firmware/` directories (sourced from AstroDMx install)

## Phase 4: Keyboard navigation (DONE)

- [x] Field-based navigation system (`_Field` dataclass, focus tracking)
- [x] `X` / `G` / `Z` — jump to exposure / gain / zoom
- [x] `Up` / `Down` — navigate between fields
- [x] `Left` / `Right` — adjust focused value
- [x] `Space` — capture single frame
- [x] `R` — start/stop recording
- [x] `Ctrl+X` — toggle auto-exposure
- [x] `Ctrl+G` — toggle auto-gain
- [x] `Ctrl+Q` — quit
- [x] Focused field label bolded for visibility
- [x] Shortcuts defined in `shortcuts.py` registry

## Phase 5: Auto-exposure / auto-gain (PARTIALLY DONE)

Hardware auto-exposure/gain delegated to camera SDK when supported.

- [x] CameraBase ABC: capability query + set/get auto methods (default: not supported)
- [x] ZWO ASI backend: full support via `ASISetControlValue` auto flag + `IsAutoSupported` capability check
- [x] MultiCamera: delegates auto methods to active backend
- [x] GUI: auto checkboxes disabled by default, enabled per camera capability on connect
- [x] Keyboard: Ctrl+X / Ctrl+G toggle auto-exposure / auto-gain
- [x] QHY backend: control ID 88 (0x58) via `SetQHYCCDParam` — SDK manages exposure + gain together
- [x] Software auto-exposure: frame brightness analysis with proportional control, always available, mutually exclusive with hardware auto

## Phase 6: Polish and usability (IN PROGRESS)

- [x] Remember last-used settings (exposure, gain, bit depth, output dir, format, lens, orientation — NOT camera; always start disconnected)
- [x] Histogram display (toggleable via checkbox in sidebar, default off, updated every frame)
- [x] Recording limits: time (seconds), frame count, or both (FPS derived when both set)
- [x] Recording locks all settings (format, dir, time, frame count, snap)
- [x] Actual recording FPS displayed in status bar during and after recording
- [x] Session metadata: `.txt` summary per recording (times, frames, FPS, exposure, gain, resolution, camera)
- [x] PNG metadata: per-frame tEXt chunks
- [x] SER metadata: per-frame timestamps (actual FPS derivable)
- [x] Structured file layout: snapshots/, sessions/{date}/, monotonic sequence numbers
- [x] Offset (black level) control with persistence
- [x] Sensor temperature monitoring in status bar
- [ ] USB traffic control (currently hardcoded to 30)
- [x] Brightness/contrast display controls (keyboard B/C focus, left/right adjust, display-only)
- [x] Clean up test scripts (test_init*.py) — deleted, no longer needed
- [x] Error dialogs for connection failures, recording errors, and binning failures
- [x] Frame drop detection via sequence gap analysis (reported in session .txt and status bar)
- [ ] ROI display overlay on live view
- [ ] Crosshair overlay for focusing

## Future / deferred

- [ ] High-performance ring buffer pipeline (zero-copy, backpressure) — decouples camera polling from disk I/O via a pre-allocated circular buffer on separate threads, absorbing brief I/O stalls without dropping frames.  Unlikely to be needed for most astro cameras on SSD storage at 8-bit; current simple pipeline handles full-resolution 40+ FPS to SER without issues.  Consider only if frame drop detection reports losses in practice.
- [ ] Color camera support (debayer)
- [x] MKV recording — lossless FFV1 via ffmpeg subprocess (8/16-bit mono, metadata embedded)
- [x] Software auto-exposure (exposure-only, gain stays manual) — always available for any camera

---

## Current state (2026-03-09)

**The application is functional with full keyboard navigation and hardware auto-exposure/gain support.** Live camera view works with the QHY5III585M at 3856×2180, 8-bit. ZWO ASI backend is implemented but not yet tested with hardware. The GUI supports dynamic zoom, portrait/landscape orientation, binning with safe stop/restart, smart exposure stepping, and hardware auto-exposure/gain (where supported by the camera).

### What works

- Multi-camera enumeration (QHY + ZWO backends), selection, and connection
- Live frame display with dynamic zoom (fit-to-viewport through 100%, with scroll bars)
- Keyboard-driven field navigation and value adjustment
- Smart exposure stepping with automatic unit switching
- Hardware auto-exposure/gain for ZWO ASI cameras (checkboxes auto-enabled per camera capability)
- Portrait/landscape orientation toggle (rotation applied before display and recording)
- Binning mode selection with safe harness stop/restart cycle
- 8-bit and 16-bit capture modes
- PNG single-frame snapshots (snapshots/ subdir) and multi-frame sessions
- SER multi-frame recording with per-frame timestamps
- MKV lossless video recording (FFV1 via ffmpeg, 8/16-bit mono)
- Recording limits: time, frame count, or both (FPS derived automatically)
- Session metadata `.txt` written on recording stop
- Structured file layout with monotonic sequence numbers (snap + session, persisted)
- Recording locks all settings (format, dir, time, frame count, binning, orientation)
- Actual recording FPS shown in status bar
- Simulator mode for testing without hardware
- Libs and firmware sourced from AstroDMx install; udev rules handle firmware loading

### What needs testing

- ZWO ASI camera (ASI678MM) — backend written, awaiting hardware test
- ZWO auto-exposure/gain — wired up but untested
- Recording writes correct files (PNG, SER, and MKV)
- Recording with time/frame limits and derived FPS throttling
- 16-bit capture mode
- SER file compatibility with stacking software
- PNG metadata readable by standard tools
- Auto-stop at frame count limit (GUI state cleanup)
