# CLAUDE.md

## Project overview

Camera capture application for QHY and ZWO astronomy cameras. See README.md for features and architecture, PLAN.md for status and roadmap, INSTALL.md for setup.

## Code conventions

- Python 3.11+, PySide6 for GUI, no OpenCV dependency
- `from __future__ import annotations` in every module
- Mono cameras only (no color/debayer support yet)
- Exposure values always in microseconds internally; display conversion in `util/units.py`
- Camera backends use ctypes to native SDK shared libraries in `lib/` (sourced from AstroDMx install)
- No test suite — verify changes with `python -m py_compile` on all modified files

## Key patterns

- **Camera lifecycle**: Never open+close a QHY camera handle during enumeration — it corrupts USB state. The `pre_open` pattern keeps the handle alive for reuse on `connect()`.
- **Signal blocking**: Always use `blockSignals(True/False)` when programmatically setting Qt widget values to prevent recursive signal chains.
- **Thread safety**: Camera polling runs on a worker thread (`SimpleHarness`). GUI updates must go through `DisplayBridge` (QObject signal). Recorders receive frames on the worker thread.
- **Recording gating**: `RecorderBase.on_frame()` handles FPS throttling, max-frames, and max-duration auto-stop. Subclasses only implement `_write_frame()`.
- **Sequence numbers**: `snap_sequence` and `session_sequence` in settings are monotonically increasing and never reset. PNG sessions consume one sequence per frame; SER/MKV consume one per session. Both must be preserved in `_gather_settings()`.

## File layout for recordings

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

## QHY SDK gotchas

- Must pre-load bundled libgcc_s, libstdc++, libusb with RTLD_GLOBAL before libqhyccd.so
- System libusb is a different version and causes silent failures
- Auto-exposure (control ID 88/0x58) controls both exposure AND gain — `auto_exposure_gain_coupled()` returns True, and the GUI syncs both checkboxes
- USB traffic is hardcoded to 30 (not yet exposed as a control)
- Init sequence is strict — see README.md for the exact order

## SER format

The SER header's "Instrument" field (bytes 82-121) stores the camera name. This is per the SER spec — the field name is "Instrument" in the spec even though we call it "camera" internally.

## Settings

JSON at `~/.config/simple-astro-cap/settings.json`. The `AppSettings` dataclass handles forward/backward compatibility by filtering unknown keys on load. Camera is never persisted — always starts disconnected.

## Running

```bash
python run.py          # real camera
python run.py --sim    # simulator
```
