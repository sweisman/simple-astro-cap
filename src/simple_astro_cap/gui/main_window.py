"""Main application window."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from simple_astro_cap.camera.abc import CameraBase, Frame, Param, ROI
from simple_astro_cap.gui import shortcuts as sc
from simple_astro_cap.gui.camera_panel import CameraPanel
from simple_astro_cap.gui.display_bridge import DisplayBridge
from simple_astro_cap.gui.histogram import HistogramWidget
from simple_astro_cap.gui.live_view import LiveViewWidget, compute_zoom_steps
from simple_astro_cap.gui.recording_panel import RecordingPanel
from simple_astro_cap.settings import AppSettings, load_settings, save_settings
from simple_astro_cap.pipeline.auto_exposure import SoftwareAutoExposure
from simple_astro_cap.pipeline.simple import SimpleHarness
from simple_astro_cap.recording.abc import RecorderBase, utc_iso
from simple_astro_cap.recording.mkv_recorder import MkvRecorder
from simple_astro_cap.recording.png_recorder import PngRecorder
from simple_astro_cap.recording.ser_recorder import SerRecorder

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, camera: CameraBase):
        super().__init__()
        self._camera = camera
        self._harness: SimpleHarness | None = None
        self._display_bridge = DisplayBridge()
        self._recorder: RecorderBase | None = None
        self._rec_meta: dict | None = None  # metadata captured at recording start
        self._latest_seq = 0  # sequence of the newest frame seen, for fps
        self._fps_prev_seq = 0
        self._fps_display = 0.0
        self._portrait = False
        self._display_focus: str | None = None  # "brightness" or "contrast"
        self._histogram_counter = 0
        self._histogram_interval = 4  # update histogram every Nth frame
        self._snap_pending = False  # Space pressed; waiting for the next frame
        self._rec_baseline: dict[str, int] = {}  # loss counters at recording start
        self._rec_events: list[str] = []  # parameter changes made while recording
        self._soft_auto: SoftwareAutoExposure | None = None
        self._last_display_time = 0.0  # monotonic seconds, for battery saver

        self.setWindowTitle("Simple Astro Cap")
        self.setMinimumSize(1024, 600)
        self.showMaximized()

        self._settings = load_settings()
        self._build_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._setup_fps_timer()
        self._auto_poll_timer = QTimer(self)
        self._auto_poll_timer.timeout.connect(self._poll_auto_values)

        # Apply saved settings to UI
        self._apply_settings(self._settings)

        # Populate camera list and set default ROI
        self._refresh_cameras()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Splitter: live view | sidebar
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitter)

        # Live view
        self._live_view = LiveViewWidget()
        self._splitter.addWidget(self._live_view)

        # Sidebar (scrollable)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(2, 2, 2, 2)
        sidebar_layout.setSpacing(2)

        self._camera_panel = CameraPanel()
        sidebar_layout.addWidget(self._camera_panel)

        self._recording_panel = RecordingPanel()
        sidebar_layout.addSpacing(6)
        sidebar_layout.addWidget(self._recording_panel)

        # Lens/Telescope
        sidebar_layout.addSpacing(6)
        self._lens_group = QGroupBox("Lens/Telescope")
        lens_layout = QFormLayout(self._lens_group)
        lens_layout.setContentsMargins(4, 4, 4, 4)
        lens_layout.setSpacing(2)
        self._lens_edit = QLineEdit()
        self._lens_edit.setPlaceholderText("Optional description")
        self._lens_edit.setToolTip("Saved in SER file metadata")
        lens_layout.addRow("Description:", self._lens_edit)
        sidebar_layout.addWidget(self._lens_group)

        # Display options
        sidebar_layout.addSpacing(6)
        self._display_group = QGroupBox("Display")
        display_form = QFormLayout(self._display_group)
        display_form.setContentsMargins(4, 4, 4, 4)
        display_form.setSpacing(2)

        bc_widget = QWidget()
        bc_layout = QHBoxLayout(bc_widget)
        bc_layout.setContentsMargins(0, 0, 0, 0)
        bc_layout.setSpacing(2)
        self._brightness_label = QLabel("Brightness:")
        self._brightness_spin = QDoubleSpinBox()
        self._brightness_spin.setDecimals(0)
        self._brightness_spin.setRange(-100, 100)
        self._brightness_spin.setValue(0)
        self._brightness_spin.setSingleStep(5)
        self._brightness_spin.setMaximumWidth(60)
        self._brightness_spin.setToolTip("Display brightness offset [B]")
        self._contrast_label = QLabel("Contrast:")
        self._contrast_spin = QDoubleSpinBox()
        self._contrast_spin.setDecimals(0)
        self._contrast_spin.setRange(0, 100)
        self._contrast_spin.setValue(50)
        self._contrast_spin.setSingleStep(5)
        self._contrast_spin.setMaximumWidth(60)
        self._contrast_spin.setToolTip("Display contrast (50 = normal) [C]")
        self._display_reset_btn = QPushButton("Reset")
        self._display_reset_btn.setEnabled(False)
        self._display_reset_btn.setToolTip("Reset brightness and contrast to defaults")
        self._display_reset_btn.clicked.connect(self._reset_display_adjustments)
        self._brightness_spin.valueChanged.connect(self._update_display_reset_btn)
        self._contrast_spin.valueChanged.connect(self._update_display_reset_btn)
        bc_layout.addWidget(self._brightness_label)
        bc_layout.addWidget(self._brightness_spin)
        bc_layout.addSpacing(10)
        bc_layout.addWidget(self._contrast_label)
        bc_layout.addWidget(self._contrast_spin)
        bc_layout.addStretch()
        display_form.addRow(bc_widget)
        display_form.addRow(self._display_reset_btn)

        self._histogram_check = QCheckBox("Show histogram")
        self._histogram_check.setToolTip("Live brightness histogram")
        display_form.addRow(self._histogram_check)
        self._histogram = HistogramWidget()
        self._histogram.setVisible(False)
        display_form.addRow(self._histogram)
        sidebar_layout.addWidget(self._display_group)

        # Disable panels until camera is connected
        self._recording_panel.setEnabled(False)
        self._lens_group.setEnabled(False)
        self._display_group.setEnabled(False)

        sidebar_layout.addStretch()
        sidebar_scroll.setWidget(sidebar_widget)
        self._splitter.addWidget(sidebar_scroll)

        # Live view stretches, sidebar stays fixed width when resizing
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_fps = QLabel("-- fps")
        self._status_res = QLabel("")
        self._status_hdr = QLabel("")  # "HDR" while hardware HDR is live
        self._status_hdr.setStyleSheet("font-weight: bold;")
        self._status_cam = QLabel("Disconnected")
        self._status_rec = QLabel("")
        self._status_temp = QLabel("")
        self._status_bar.addWidget(self._status_cam)
        self._status_bar.addWidget(self._status_res)
        self._status_bar.addWidget(self._status_hdr)
        self._status_bar.addPermanentWidget(self._status_rec)
        self._status_bar.addPermanentWidget(self._status_temp)
        self._status_bar.addPermanentWidget(self._status_fps)

    def _setup_shortcuts(self) -> None:
        def _sc(key: str, slot: object) -> None:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(slot)

        _sc(sc.QUIT.key, self.close)

    def keyPressEvent(self, event) -> None:
        """Global keyboard handling for navigation and control."""
        key = event.key()
        mod = event.modifiers()
        ctrl = bool(mod & Qt.KeyboardModifier.ControlModifier)

        # Letter keys (only when no text widget has focus)
        focused = QApplication.focusWidget()
        in_text = isinstance(focused, (QLineEdit, QDoubleSpinBox))

        if not ctrl and not in_text:
            if key == Qt.Key.Key_X:
                self._clear_display_focus()
                self._camera_panel.focus_field("exposure")
                return
            if key == Qt.Key.Key_G:
                self._clear_display_focus()
                self._camera_panel.focus_field("gain")
                return
            if key == Qt.Key.Key_Z:
                self._clear_display_focus()
                self._camera_panel.focus_field("zoom")
                return
            if key == Qt.Key.Key_B:
                self._set_display_focus("brightness")
                return
            if key == Qt.Key.Key_C:
                self._set_display_focus("contrast")
                return
            if key == Qt.Key.Key_Space:
                self._on_capture_single()
                return
            if key == Qt.Key.Key_R:
                self._on_toggle_recording()
                return

        # Ctrl combos
        if ctrl:
            if key == Qt.Key.Key_X:
                if self._camera_panel.auto_exposure_check.isEnabled():
                    self._camera_panel.auto_exposure_check.toggle()
                else:
                    self._camera_panel.soft_auto_exposure_check.toggle()
                return
            if key == Qt.Key.Key_G:
                self._camera_panel.auto_gain_check.toggle()
                return

        # Arrow keys (always active)
        if key == Qt.Key.Key_Left:
            if self._display_focus:
                self._adjust_display_focus(-1)
            else:
                self._camera_panel.adjust_left()
            return
        if key == Qt.Key.Key_Right:
            if self._display_focus:
                self._adjust_display_focus(1)
            else:
                self._camera_panel.adjust_right()
            return
        if key == Qt.Key.Key_Up:
            self._clear_display_focus()
            self._camera_panel.focus_prev()
            return
        if key == Qt.Key.Key_Down:
            self._clear_display_focus()
            self._camera_panel.focus_next()
            return

        super().keyPressEvent(event)

    def _connect_signals(self) -> None:
        # Display bridge -> live view
        self._display_bridge.frame_ready.connect(self._on_display_frame)
        self._display_bridge.snapshot_ready.connect(self._save_snapshot)

        # Camera panel
        self._camera_panel.camera_selected.connect(self._on_camera_selected)
        self._camera_panel.refresh_requested.connect(self._refresh_cameras)
        self._camera_panel.connect_requested.connect(self._on_connect)
        self._camera_panel.disconnect_requested.connect(self._on_disconnect)
        self._camera_panel.zoom_changed.connect(self._on_zoom_changed)
        self._camera_panel.bin_changed.connect(self._on_bin_changed)
        self._camera_panel.orientation_changed.connect(self._on_orientation_changed)
        self._camera_panel.exposure_changed.connect(self._on_exposure_changed)
        self._camera_panel.gain_changed.connect(self._on_gain_changed)
        self._camera_panel.offset_changed.connect(self._on_offset_changed)
        self._camera_panel.auto_exposure_toggled.connect(self._on_auto_exposure_toggled)
        self._camera_panel.soft_auto_exposure_toggled.connect(self._on_soft_auto_exposure_toggled)
        self._camera_panel.auto_gain_toggled.connect(self._on_auto_gain_toggled)
        self._camera_panel.hdr_toggled.connect(self._on_hdr_toggled)

        # Recording panel
        self._recording_panel.capture_single_requested.connect(self._on_capture_single)
        self._recording_panel.record_start_requested.connect(self._on_start_recording)
        self._recording_panel.record_stop_requested.connect(self._on_stop_recording)

        # Display
        self._histogram_check.toggled.connect(self._histogram.setVisible)

    def _setup_fps_timer(self) -> None:
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

    # --- Camera lifecycle ---

    def _refresh_cameras(self) -> None:
        self._status_cam.setText("Scanning...")
        QApplication.processEvents()
        cameras = self._camera.enumerate()
        self._camera_panel.set_camera_list(cameras)
        self._status_cam.setText("Disconnected")

    def _on_camera_selected(self, camera_id: str) -> None:
        """Pre-open camera to get sensor info and populate resolution.

        The handle is kept open (closing corrupts QHY USB state).
        connect() will reuse it.
        """
        self._status_cam.setText("Loading camera info...")
        QApplication.processEvents()
        has_hdr = False
        try:
            if hasattr(self._camera, 'pre_open'):
                self._camera.pre_open(camera_id)
                info = self._camera.get_pre_open_info()
                if info:
                    self._camera_panel.set_sensor_size(info.sensor_width, info.sensor_height)
                    has_hdr = info.has_hdr
                    log.info("Camera %s: %dx%d", camera_id, info.sensor_width, info.sensor_height)
        except Exception as e:
            log.warning("Could not query camera info: %s", e)
        self._camera_panel.set_hdr_capability(has_hdr)
        self._status_cam.setText("Disconnected")

    def _on_connect(self) -> None:
        cam_id = self._camera_panel.selected_camera_id
        if not cam_id:
            return

        bit_depth = self._camera_panel.selected_bit_depth
        resolution = self._camera_panel.selected_resolution

        self._status_cam.setText("Connecting...")
        QApplication.processEvents()

        try:
            # Set pre-connect parameters if the backend supports it
            if hasattr(self._camera, 'set_connect_bit_depth'):
                self._camera.set_connect_bit_depth(bit_depth)
            if hasattr(self._camera, 'set_connect_roi') and resolution:
                roi_w, roi_h = resolution
                self._camera.set_connect_roi(ROI(0, 0, roi_w, roi_h))

            self._camera.connect(cam_id)
        except Exception as e:
            log.error("Failed to connect: %s", e)
            self._status_cam.setText("Connection failed")
            QMessageBox.critical(self, "Connection Failed", str(e))
            return

        info = self._camera.get_info()
        roi = self._camera.get_roi()
        self._camera_panel.set_connected(True)
        self._camera_panel.set_bin_modes(
            self._camera.get_supported_bin_modes(),
            roi.width, roi.height,
        )

        # Populate resolution options if not already set by pre_open
        if self._camera_panel.resolution_combo.count() <= 1:
            self._camera_panel.set_sensor_size(info.sensor_width, info.sensor_height)

        # Set param ranges
        for param in (Param.EXPOSURE, Param.GAIN, Param.OFFSET):
            prange = self._camera.get_param_range(param)
            if prange:
                self._camera_panel.set_param_range(param, prange)

        # Push the panel's exposure/gain to the camera: backends connect with
        # their own defaults, and the panel restored saved values silently.
        try:
            self._camera.set_exposure(self._camera_panel.get_exposure_us())
            self._camera.set_gain(self._camera_panel.gain_spin.value())
        except Exception as e:
            log.warning("Failed to apply saved exposure/gain: %s", e)

        # Apply saved offset to camera
        offset_range = self._camera.get_param_range(Param.OFFSET)
        if offset_range is not None:
            offset_val = self._camera_panel.offset_spin.value()
            try:
                self._camera.set_param(Param.OFFSET, offset_val)
            except Exception:
                pass

        # Enable auto checkboxes based on camera capabilities
        self._camera_panel.set_auto_capabilities(
            auto_exposure=self._camera.supports_auto_exposure(),
            auto_gain=self._camera.supports_auto_gain(),
        )
        # HDR: re-apply the saved mode (checks are cleared on disconnect)
        # HDR: row shown on capable cameras, usable in 16-bit; re-apply saved state
        native_hdr = self._camera.supports_hdr()
        self._camera_panel.set_hdr_capability(native_hdr)
        if native_hdr and bit_depth == 16 and self._settings.hdr:
            self._camera_panel.hdr_check.setChecked(True)  # emits hdr_toggled
        elif native_hdr:
            try:
                self._camera.set_hdr(False)  # don't inherit a stale sensor state
            except Exception as e:
                log.warning("Failed to clear HDR on connect: %s", e)
        self._status_cam.setText(f"{info.model}")
        self._status_res.setText(f"{roi.width}x{roi.height} {bit_depth}bit")

        # Compute zoom levels for this resolution (account for portrait)
        zw, zh = (roi.height, roi.width) if self._portrait else (roi.width, roi.height)
        self._update_zoom_levels(zw, zh)

        # Start live view
        self._harness = SimpleHarness(
            self._camera, queue_bytes=self._settings.record_queue_mb * 1024 * 1024)
        self._harness.add_consumer(self._display_bridge)
        self._harness.start()

        # Enable panels now that camera is live
        self._recording_panel.setEnabled(True)
        self._lens_group.setEnabled(True)
        self._display_group.setEnabled(True)

    def _on_disconnect(self) -> None:
        if self._auto_poll_timer.isActive():
            self._auto_poll_timer.stop()
        self._remove_soft_auto()
        if self._recorder is not None:
            self._finish_recording()
        if self._harness:
            self._harness.stop()
            self._harness = None
        self._display_bridge.cancel_snapshot()
        self._display_bridge.take()  # never show a frame from a previous session
        self._camera.disconnect()
        self._camera_panel.set_connected(False)
        self._recording_panel.setEnabled(False)
        self._lens_group.setEnabled(False)
        self._display_group.setEnabled(False)
        self._status_cam.setText("Disconnected")
        self._status_res.setText("")
        self._status_hdr.setText("")
        self._status_temp.setText("")

    # --- Display ---

    def _set_display_focus(self, name: str) -> None:
        """Focus a display control (brightness or contrast)."""
        self._clear_display_focus()
        self._display_focus = name
        if name == "brightness":
            self._brightness_label.setFont(self._bold_font())
            self._brightness_spin.setFocus()
        elif name == "contrast":
            self._contrast_label.setFont(self._bold_font())
            self._contrast_spin.setFocus()

    def _clear_display_focus(self) -> None:
        """Remove focus from display controls."""
        if self._display_focus:
            self._brightness_label.setFont(self._normal_font())
            self._contrast_label.setFont(self._normal_font())
            self._display_focus = None

    def _adjust_display_focus(self, direction: int) -> None:
        """Adjust the focused display control by one step."""
        if self._display_focus == "brightness":
            s = self._brightness_spin
            s.setValue(s.value() + direction * s.singleStep())
        elif self._display_focus == "contrast":
            s = self._contrast_spin
            s.setValue(s.value() + direction * s.singleStep())

    @staticmethod
    def _bold_font() -> QFont:
        f = QFont()
        f.setBold(True)
        return f

    @staticmethod
    def _normal_font() -> QFont:
        return QFont()

    def _update_display_reset_btn(self) -> None:
        changed = self._brightness_spin.value() != 0 or self._contrast_spin.value() != 50
        self._display_reset_btn.setEnabled(changed)

    def _reset_display_adjustments(self) -> None:
        """Reset brightness and contrast to defaults."""
        self._brightness_spin.setValue(0)
        self._contrast_spin.setValue(50)

    def _apply_display_adjustments(self, data: np.ndarray) -> np.ndarray:
        """Apply brightness/contrast to frame data for display only."""
        brightness = self._brightness_spin.value()
        contrast_val = self._contrast_spin.value()
        if brightness == 0 and contrast_val == 50:
            return data
        # Map 0-100 scale to multiplier: 0→0.0, 50→1.0, 100→2.0
        contrast = contrast_val / 50.0
        max_val = 65535.0 if data.dtype == np.uint16 else 255.0
        mid = max_val / 2.0
        adjusted = contrast * (data.astype(np.float32) - mid) + mid + brightness * (max_val / 255.0)
        return np.clip(adjusted, 0, max_val).astype(data.dtype)

    def _on_display_frame(self) -> None:
        frame = self._display_bridge.take()
        if frame is None:
            return
        # A frame left by a previous session's capture thread can arrive
        # after a reconnect; drop anything that doesn't match the camera.
        if not self._camera.is_connected() or frame.bit_depth != self._camera.get_bit_depth():
            return
        if frame.sequence == 1:
            log.info("First frame displayed: %dx%d %dbit min=%d max=%d",
                     frame.width, frame.height, frame.bit_depth,
                     frame.data.min(), frame.data.max())
        # The mailbox skips frames when the GUI is slower than the camera,
        # so count acquisition rate from the sequence, not from paints.
        self._latest_seq = frame.sequence

        # Battery saver: skip display updates to ~1 fps while recording
        if (self._recorder is not None
                and self._recording_panel.battery_saver_check.isChecked()):
            now = time.monotonic()
            if now - self._last_display_time < 1.0:
                return
            self._last_display_time = now

        # Histogram on full-res data, every Nth frame
        if self._histogram_check.isChecked():
            self._histogram_counter += 1
            if self._histogram_counter >= self._histogram_interval:
                self._histogram.update_histogram(frame.data)
                self._histogram_counter = 0

        # Downsample for display when zoom < 100%
        display_data = frame.data
        scale = self._live_view.zoom_scale
        if scale is None:
            # Fit-to-viewport: compute step from viewport size
            vp = self._live_view.viewport().size()
            h, w = display_data.shape
            step = max(1, max(h // max(vp.height(), 1), w // max(vp.width(), 1)))
        elif scale < 1.0:
            step = max(1, int(1.0 / scale))
        else:
            step = 1
        if step > 1:
            display_data = display_data[::step, ::step]
        if self._portrait:
            # Display-only: recordings and snaps keep native sensor
            # orientation so the Bayer pattern tag stays valid.
            display_data = np.rot90(display_data)
        display_data = np.ascontiguousarray(display_data)

        # Apply brightness/contrast on (potentially smaller) data
        display_data = self._apply_display_adjustments(display_data)
        dh, dw = display_data.shape
        display_frame = Frame(
            data=display_data,
            width=dw,
            height=dh,
            bit_depth=frame.bit_depth,
            capture_mono_ns=frame.capture_mono_ns,
            capture_utc_ns=frame.capture_utc_ns,
            sequence=frame.sequence,
        )
        self._live_view.update_frame(display_frame)

    def _update_fps(self) -> None:
        delta = self._latest_seq - self._fps_prev_seq
        if delta < 0:  # sequence restarted with live view
            delta = self._latest_seq
        self._fps_prev_seq = self._latest_seq
        self._fps_display = delta
        self._status_fps.setText(f"{self._fps_display:.0f} fps")
        if self._harness is not None and self._harness.error is not None:
            self._on_harness_error()
            return
        # Update sensor temperature
        if self._camera.is_connected():
            temp = self._camera.get_sensor_temperature()
            if temp is not None:
                self._status_temp.setText(f"{temp:.1f}°C")
            else:
                self._status_temp.setText("")
        else:
            self._status_temp.setText("")
        if self._recorder is not None:
            if self._recorder.is_recording():
                n = self._recorder.frames_written()
                fps = self._recorder.actual_fps
                lost = self._recording_losses()
                lost_txt = f" | LOST {lost}" if lost else ""
                self._status_rec.setText(f"REC: {n} frames | {fps:.1f} fps{lost_txt}")
            else:
                # Recorder auto-stopped (frame/time limit, low disk, or error)
                self._finish_recording()

    # --- Camera settings ---

    def _on_bin_changed(self, bin_factor: int) -> None:
        if not self._camera.is_connected():
            return
        # Must stop harness (which stops live) before changing bin mode
        was_running = self._harness and self._harness.is_running()
        if was_running:
            self._harness.stop()
        try:
            self._camera.set_bin_mode(bin_factor)
        except Exception as e:
            log.error("Failed to set bin mode %d: %s", bin_factor, e)
            QMessageBox.warning(self, "Binning Error",
                                f"Failed to set {bin_factor}x{bin_factor} binning:\n{e}")
            if was_running:
                self._harness.start()
            return
        # Update status bar and zoom levels for new resolution
        roi = self._camera.get_roi()
        bit_depth = self._camera.get_bit_depth()
        self._status_res.setText(f"{roi.width}x{roi.height} {bit_depth}bit")
        w, h = (roi.height, roi.width) if self._portrait else (roi.width, roi.height)
        self._update_zoom_levels(w, h)
        # Restart harness
        if was_running:
            self._harness.start()

    def _on_exposure_changed(self, us: float) -> None:
        if self._camera.is_connected():
            self._camera.set_exposure(us)
            self._log_rec_event(f"exposure_us={us:.0f}")

    def _on_gain_changed(self, value: float) -> None:
        if self._camera.is_connected():
            self._camera.set_gain(value)
            self._log_rec_event(f"gain={value:.0f}")

    def _on_offset_changed(self, value: float) -> None:
        if self._camera.is_connected():
            self._camera.set_param(Param.OFFSET, value)
            self._log_rec_event(f"offset={value:.0f}")

    def _log_rec_event(self, change: str) -> None:
        """Record a manual parameter change made mid-recording (session .txt).

        SER/MKV carry no per-frame exposure/gain, so this is the record of
        when the data's acquisition settings changed.
        """
        if self._recorder is not None and self._recorder.is_recording():
            stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            self._rec_events.append(f"{stamp} {change}")

    def _on_auto_exposure_toggled(self, enabled: bool) -> None:
        if self._camera.is_connected() and self._camera.supports_auto_exposure():
            # Disable software auto if hardware auto is being enabled
            if enabled and self._soft_auto is not None:
                self._remove_soft_auto()
            try:
                self._camera.set_auto_exposure(enabled)
            except Exception as e:
                log.warning("Failed to set auto-exposure: %s", e)
                self._status_rec.setText(f"Auto-exposure error: {e}")
                return
            # Sync gain checkbox when coupled
            if self._camera.auto_exposure_gain_coupled():
                self._camera_panel.auto_gain_check.blockSignals(True)
                self._camera_panel.auto_gain_check.setChecked(enabled)
                self._camera_panel.auto_gain_check.blockSignals(False)
        self._update_auto_poll_timer()

    def _on_soft_auto_exposure_toggled(self, enabled: bool) -> None:
        if not self._camera.is_connected() or not self._harness:
            return
        if enabled:
            # Disable hardware auto if it was on
            if self._camera_panel.auto_exposure_check.isChecked():
                self._camera_panel.auto_exposure_check.setChecked(False)
            self._soft_auto = SoftwareAutoExposure(self._camera)
            self._harness.add_consumer(self._soft_auto)
            log.info("Software auto-exposure enabled")
        else:
            self._remove_soft_auto()
        self._update_auto_poll_timer()

    def _remove_soft_auto(self) -> None:
        """Remove software auto-exposure controller from the pipeline."""
        if self._soft_auto is not None:
            if self._harness:
                self._harness.remove_consumer(self._soft_auto)
            self._soft_auto = None
            log.info("Software auto-exposure disabled")

    def _on_auto_gain_toggled(self, enabled: bool) -> None:
        if self._camera.is_connected() and self._camera.supports_auto_gain():
            try:
                self._camera.set_auto_gain(enabled)
            except Exception as e:
                log.warning("Failed to set auto-gain: %s", e)
                self._status_rec.setText(f"Auto-gain error: {e}")
                return
            # Sync exposure checkbox when coupled
            if self._camera.auto_exposure_gain_coupled():
                self._camera_panel.auto_exposure_check.blockSignals(True)
                self._camera_panel.auto_exposure_check.setChecked(enabled)
                self._camera_panel.auto_exposure_check.blockSignals(False)
        self._update_auto_poll_timer()

    def _update_auto_poll_timer(self) -> None:
        """Start or stop the auto-value polling timer based on checkbox state."""
        need_poll = (
            self._camera.is_connected()
            and (self._camera_panel.auto_exposure_check.isChecked()
                 or self._camera_panel.auto_gain_check.isChecked()
                 or self._soft_auto is not None)
        )
        if need_poll and not self._auto_poll_timer.isActive():
            self._auto_poll_timer.start(500)
        elif not need_poll and self._auto_poll_timer.isActive():
            self._auto_poll_timer.stop()

    def _poll_auto_values(self) -> None:
        """Read current exposure/gain from camera and update display."""
        if not self._camera.is_connected():
            return
        try:
            if (self._camera_panel.auto_exposure_check.isChecked()
                    or self._soft_auto is not None):
                us = self._camera.get_exposure()
                self._camera_panel.display_exposure_us(us)
            if self._camera_panel.auto_gain_check.isChecked():
                gain = self._camera.get_gain()
                self._camera_panel.display_gain(gain)
        except Exception:
            pass  # camera may be busy during live streaming

    # --- HDR ---

    def _on_hdr_toggled(self, enabled: bool) -> None:
        """Hardware HDR: set with live stopped, like a bin change."""
        if not self._camera.is_connected() or not self._camera.supports_hdr():
            return
        was_running = self._harness and self._harness.is_running()
        if was_running:
            self._harness.stop()
        try:
            self._camera.set_hdr(enabled)
            self._settings.hdr = enabled
        except Exception as e:
            log.warning("Failed to set HDR: %s", e)
            self._status_rec.setText(f"HDR error: {e}")
            enabled = not enabled
            self._camera_panel.hdr_check.blockSignals(True)
            self._camera_panel.hdr_check.setChecked(enabled)
            self._camera_panel.hdr_check.blockSignals(False)
        if was_running:
            self._harness.start()
        self._status_hdr.setText("HDR" if enabled else "")

    def _on_orientation_changed(self, portrait: bool) -> None:
        self._portrait = portrait
        # Recalculate zoom for new display dimensions
        if self._camera.is_connected():
            roi = self._camera.get_roi()
            w, h = (roi.height, roi.width) if portrait else (roi.width, roi.height)
            self._update_zoom_levels(w, h)

    def _on_zoom_changed(self, scale: float | None) -> None:
        self._live_view.zoom_scale = scale

    def _update_zoom_levels(self, image_w: int, image_h: int) -> None:
        """Recompute zoom steps for the current image and viewport size."""
        vp = self._live_view.viewport().size()
        levels = compute_zoom_steps(image_w, image_h, vp.width(), vp.height())
        self._camera_panel.set_zoom_levels(levels)
        # Default to 100% if image fits in viewport, otherwise Fit
        fits = (image_w <= vp.width() and image_h <= vp.height())
        if fits and len(levels) > 1:
            self._camera_panel.zoom_combo.setCurrentIndex(len(levels) - 1)
            self._live_view.zoom_scale = levels[-1][1]
        else:
            self._live_view.zoom_scale = None

    # --- Recording ---

    def _on_capture_single(self) -> None:
        """Arm a snapshot of the next frame acquired after this request."""
        if not self._camera.is_connected() or not self._harness or not self._harness.is_running():
            return
        self._snap_pending = True
        self._display_bridge.request_snapshot()
        self._status_rec.setText("Snap: waiting for next frame...")

    def _next_snap_stem(self, frame: Frame) -> str:
        """Allocate the next snapshot sequence number; stem uses capture time."""
        seq = self._settings.snap_sequence
        timestamp = datetime.fromtimestamp(frame.capture_utc_ns / 1e9).strftime("%Y-%m-%d-%H:%M:%S")
        self._settings.snap_sequence = seq + 1
        save_settings(self._settings)
        return f"{timestamp}-{seq:06d}"

    def _save_snapshot(self, frame: Frame) -> None:
        """Slot for DisplayBridge.snapshot_ready: write the frame to snapshots/."""
        if not self._snap_pending or not self._camera.is_connected():
            return
        self._snap_pending = False
        extra = {"Gain": f"{self._camera.get_gain():.0f}",
                 "ExposureUs": f"{self._camera.get_exposure():.0f}"}
        if self._camera_panel.hdr_check.isChecked():
            extra["Hdr"] = "hardware"
        try:
            filename = self._write_snapshot(frame, self._next_snap_stem(frame), extra)
        except Exception as e:
            log.error("Snapshot failed: %s", e)
            QMessageBox.warning(self, "Snapshot Error", f"Failed to save snapshot:\n{e}")
            return
        self._status_rec.setText(f"Snap saved: {filename}")

    def _write_snapshot(self, frame: Frame, stem: str, extra_meta: dict[str, str]) -> str:
        """Write one frame to snapshots/ as PNG or TIFF; returns the filename."""
        info = self._camera.get_info()
        snap_dir = self._recording_panel.output_dir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_fmt = self._recording_panel.snap_format

        if frame.bit_depth <= 8:
            img = Image.fromarray(frame.data, mode="L")
        else:
            img = Image.fromarray(frame.data.astype(np.uint16), mode="I;16")

        capture_utc = utc_iso(frame.capture_utc_ns)
        if snap_fmt == "TIFF":
            filename = f"{stem}.tiff"
            # TIFF tag 270 = ImageDescription
            desc_parts = ["Software=Simple Astro Cap", f"BitDepth={frame.bit_depth}",
                          f"CaptureUTC={capture_utc}"]
            if info.bayer_pattern:
                desc_parts.append(f"BayerPattern={info.bayer_pattern}")
            desc_parts += [f"{k}={v}" for k, v in extra_meta.items()]
            from PIL.TiffImagePlugin import ImageFileDirectory_v2
            ifd = ImageFileDirectory_v2()
            ifd[270] = "; ".join(desc_parts)
            img.save(snap_dir / filename, format="TIFF", tiffinfo=ifd)
        else:
            filename = f"{stem}.png"
            meta = PngInfo()
            meta.add_text("Software", "Simple Astro Cap")
            meta.add_text("BitDepth", str(frame.bit_depth))
            if info.bayer_pattern:
                meta.add_text("BayerPattern", info.bayer_pattern)
            meta.add_text("CaptureUTC", capture_utc)
            meta.add_text("CaptureUnixNs", str(frame.capture_utc_ns))
            for k, v in extra_meta.items():
                meta.add_text(k, v)
            img.save(snap_dir / filename, pnginfo=meta)
        return filename

    def _on_toggle_recording(self) -> None:
        if self._recorder and self._recorder.is_recording():
            self._on_stop_recording()
        else:
            self._on_start_recording()

    def _on_start_recording(self) -> None:
        if not self._camera.is_connected() or not self._harness:
            return

        fmt = self._recording_panel.format_name
        output_dir = self._recording_panel.output_dir
        max_frames = self._recording_panel.max_frames
        max_time = self._recording_panel.max_time
        info = self._camera.get_info()

        # Derive target FPS: when both frames and time are set, throttle to fit
        target_fps = 0.0
        if max_frames is not None and max_time > 0:
            target_fps = max_frames / max_time

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d-%H:%M:%S")
        seq = self._settings.session_sequence
        stem = f"{timestamp}-{seq:06d}"

        # Recordings are always in native sensor orientation (portrait is a
        # display-only rotation). get_roi() is already the binned output
        # size on every backend.
        roi = self._camera.get_roi()
        frame_w, frame_h = roi.width, roi.height
        bit_depth = self._camera.get_bit_depth()
        common_kw = dict(
            width=frame_w,
            height=frame_h,
            bit_depth=bit_depth,
            camera=info.model,
            telescope=self._lens_edit.text(),
            bayer_pattern=info.bayer_pattern,
            max_frames=max_frames,
            max_duration=max_time,
            target_fps=target_fps,
        )

        sessions_dir = output_dir / "sessions" / date_str

        try:
            if fmt == "SER":
                recorder = SerRecorder()
                path = sessions_dir / f"{stem}.ser"
                path.parent.mkdir(parents=True, exist_ok=True)
                recorder.start(path, **common_kw)
                txt_path = sessions_dir / f"{stem}.txt"
            elif fmt == "MKV":
                recorder = MkvRecorder()
                path = sessions_dir / f"{stem}.mkv"
                path.parent.mkdir(parents=True, exist_ok=True)
                recorder.start(path, **common_kw)
                txt_path = sessions_dir / f"{stem}.txt"
            else:
                recorder = PngRecorder()
                session_dir = sessions_dir / stem
                recorder.start(session_dir, start_sequence=seq, **common_kw)
                txt_path = session_dir / "session.txt"
        except Exception as e:
            log.error("Failed to start recording: %s", e)
            QMessageBox.warning(self, "Recording Error",
                                f"Failed to start {fmt} recording:\n{e}")
            return

        self._recorder = recorder
        self._rec_meta = dict(
            format=fmt,
            txt_path=txt_path,
            start_time=now,
            sequence=seq,
            start_exposure_us=self._camera_panel.get_exposure_us(),
            start_gain=self._camera_panel.gain_spin.value(),
            hdr=self._camera_panel.hdr_check.isChecked(),
            bit_depth=bit_depth,
            width=frame_w,
            height=frame_h,
            camera=info.model,
            telescope=self._lens_edit.text(),
            bayer_pattern=info.bayer_pattern,
            target_fps=target_fps,
            max_time=max_time,
            max_frames=max_frames,
        )
        self._rec_baseline = dict(
            queue_overflows=self._harness.queue_overflows,
            sdk_dropped=self._camera.sdk_dropped_frames() or 0,
        )
        self._harness.queue_peak_bytes = 0
        self._rec_events = []
        self._harness.add_consumer(recorder, queued=True)
        self._recording_panel.set_recording(True)
        self._camera_panel.set_recording(True)
        self._status_rec.setText("REC")
        log.info("Recording started: %s %s (frames=%s time=%s fps=%.1f)",
                 fmt, stem, max_frames or "unlimited",
                 f"{max_time:.0f}s" if max_time > 0 else "unlimited", target_fps)

    def _on_stop_recording(self) -> None:
        self._finish_recording()

    def _finish_recording(self) -> None:
        """Clean up after recording ends (manual stop or auto-stop)."""
        if self._recorder is None:
            return
        if self._harness:
            # Frames captured before the stop request are still queued;
            # let them reach the file before closing it.
            if self._recorder.is_recording() and not self._harness.drain():
                log.warning("Record queue did not drain; remaining frames discarded")
            self._harness.remove_consumer(self._recorder)
        if self._recorder.is_recording():
            self._recorder.stop()
        written = self._recorder.frames_written()
        fps = self._recorder.actual_fps
        offered = self._recorder.frames_offered
        dropped = self._recorder.frames_dropped
        stop_reason = self._recorder.stop_reason
        rec_error = self._recorder.error
        losses = self._loss_counters()

        # Advance session sequence: PNG uses one per frame, SER/MKV use one per session
        is_png = isinstance(self._recorder, PngRecorder)
        if is_png:
            self._settings.session_sequence = self._recorder.end_sequence
        else:
            self._settings.session_sequence += 1
        save_settings(self._settings)

        # Write session summary txt
        self._write_session_txt(written, fps, is_png, offered, dropped, losses, rec_error)

        self._rec_meta = None
        self._recorder = None
        self._recording_panel.set_recording(False)
        self._camera_panel.set_recording(False)
        # Queue overflows also show up as sequence gaps at the recorder.
        lost = max(dropped, losses["queue_overflows"]) + (losses["sdk_dropped"] or 0)
        drop_msg = f", {lost} LOST" if lost > 0 else ""
        reason_msg = {
            "frame_limit": "Frame limit reached. ",
            "time_limit": "Time limit reached. ",
            "disk_low": "STOPPED: disk nearly full. ",
            "error": "STOPPED ON ERROR. ",
        }.get(stop_reason, "")
        self._status_rec.setText(f"{reason_msg}Saved {written} frames ({fps:.1f} fps{drop_msg})")
        log.info("Recording finished: %d frames, %.1f fps, %d lost, reason=%s",
                 written, fps, lost, stop_reason or "manual")
        if stop_reason in ("error", "disk_low"):
            detail = (f"Write failed: {rec_error}" if rec_error
                      else "Free disk space fell below the safety margin.")
            QMessageBox.critical(
                self, "Recording Stopped",
                f"Recording stopped after {written} frames.\n\n{detail}\n\n"
                f"Frames written before the stop were saved.")

    def _loss_counters(self) -> dict[str, int | None]:
        """Frame losses since recording started, by where they happened."""
        base = self._rec_baseline
        sdk = self._camera.sdk_dropped_frames() if self._camera.is_connected() else None
        overflows = self._harness.queue_overflows if self._harness else base.get("queue_overflows", 0)
        return dict(
            sdk_dropped=None if sdk is None else max(0, sdk - base.get("sdk_dropped", 0)),
            queue_overflows=overflows - base.get("queue_overflows", 0),
        )

    def _recording_losses(self) -> int:
        """Total frames lost so far in the current recording (status bar)."""
        c = self._loss_counters()
        # Queue overflows also show up as sequence gaps at the recorder.
        return (c["sdk_dropped"] or 0) + max(c["queue_overflows"], self._recorder.frames_dropped)

    def _on_harness_error(self) -> None:
        """Capture thread died or would not stop: surface it, end recording."""
        err = self._harness.error
        log.error("Capture pipeline failed: %s", err)
        if self._recorder is not None:
            self._finish_recording()
        self._status_rec.setText(f"CAPTURE FAILED: {err}")
        self._harness.error = None  # report once
        QMessageBox.critical(self, "Capture Failed",
                             f"The camera capture thread stopped:\n{err}\n\n"
                             "Disconnect and reconnect the camera.")

    def _write_session_txt(self, frames: int, actual_fps: float,
                           is_png: bool, offered: int, dropped: int,
                           losses: dict[str, int | None],
                           error: BaseException | None) -> None:
        """Write a session summary text file."""
        meta = self._rec_meta
        if meta is None:
            return
        txt_path: Path = meta["txt_path"]
        end_time = datetime.now()
        end_exposure_us = self._camera_panel.get_exposure_us()
        end_gain = self._camera_panel.gain_spin.value()
        seq = meta["sequence"]

        lines = [
            f"format: {meta['format']}",
            f"start_time: {meta['start_time'].strftime('%Y-%m-%d %H:%M:%S')}",
            f"end_time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if is_png:
            end_seq = seq + frames
            lines.append(f"sequence_range: {seq:06d}-{end_seq - 1:06d}")
        else:
            lines.append(f"sequence: {seq:06d}")
        elapsed = (end_time - meta["start_time"]).total_seconds()
        skipped = offered - frames
        lines += [
            f"frames_written: {frames}",
            f"frames_offered: {offered}",
            # Where frames were lost: inside the SDK/camera (only if the SDK
            # reports it — invisible to the sequence check), and on the host
            # between SDK and file (sequence gaps; includes queue overflows,
            # i.e. the disk not keeping up).
            "frames_lost_sdk: " + ("n/a" if losses["sdk_dropped"] is None else str(losses["sdk_dropped"])),
            f"frames_lost_host: {dropped}",
            f"frames_lost_queue_overflow: {losses['queue_overflows']}",
            f"frames_skipped: {skipped}",
            f"duration_s: {elapsed:.1f}",
            f"actual_fps: {actual_fps:.2f}",
        ]
        if meta["target_fps"] > 0:
            lines.append(f"target_fps: {meta['target_fps']:.2f}")
        if meta["max_frames"] is not None:
            lines.append(f"max_frames: {meta['max_frames']}")
        if meta["max_time"] > 0:
            lines.append(f"max_time_s: {meta['max_time']:.0f}")
        lines += [
            f"start_exposure_us: {meta['start_exposure_us']:.0f}",
            f"end_exposure_us: {end_exposure_us:.0f}",
            f"start_gain: {meta['start_gain']:.0f}",
            f"end_gain: {end_gain:.0f}",
            f"bit_depth: {meta['bit_depth']}",
            f"resolution: {meta['width']}x{meta['height']}",
            f"camera: {meta['camera']}",
            f"telescope: {meta['telescope']}",
        ]
        if meta.get("bayer_pattern"):
            lines.append(f"bayer_pattern: {meta['bayer_pattern']}")
        if meta.get("hdr"):
            lines.append("hdr: hardware")
        if meta["format"] == "MKV" and isinstance(self._recorder, MkvRecorder):
            lines.append(f"frame_timestamps: {self._recorder.timestamps_path.name}")
        lines.append("timestamps: host time when the SDK returned each frame "
                     "(readout complete, not exposure midpoint)")
        if self._camera_panel.auto_exposure_check.isChecked() or self._soft_auto is not None:
            lines.append("auto_exposure: on (per-frame exposure not recorded)")
        if self._camera_panel.auto_gain_check.isChecked():
            lines.append("auto_gain: on (per-frame gain not recorded)")
        if error is not None:
            lines.append(f"error: {error}")
        lines += [f"change: {e}" for e in self._rec_events]
        try:
            txt_path.write_text("\n".join(lines) + "\n")
        except Exception as e:
            log.warning("Failed to write session txt: %s", e)

    # --- Settings ---

    def _apply_settings(self, s: AppSettings) -> None:
        """Apply saved settings to UI widgets (before any camera connection)."""
        from simple_astro_cap.util.units import ExposureUnit

        # Exposure: pick best unit for the saved value
        us = s.exposure_us
        if us >= 1_000_000:
            unit = ExposureUnit.SECONDS
        elif us >= 1000:
            unit = ExposureUnit.MILLISECONDS
        else:
            unit = ExposureUnit.MICROSECONDS

        self._camera_panel.exposure_spin.blockSignals(True)
        self._camera_panel.exposure_unit_combo.blockSignals(True)
        for i in range(self._camera_panel.exposure_unit_combo.count()):
            if self._camera_panel.exposure_unit_combo.itemData(i) == unit:
                self._camera_panel.exposure_unit_combo.setCurrentIndex(i)
                break
        self._camera_panel.exposure_spin.setValue(unit.from_us(us))
        self._camera_panel.exposure_spin.blockSignals(False)
        self._camera_panel.exposure_unit_combo.blockSignals(False)

        self._camera_panel.gain_spin.blockSignals(True)
        self._camera_panel.gain_spin.setValue(s.gain)
        self._camera_panel.gain_spin.blockSignals(False)

        self._camera_panel.offset_spin.blockSignals(True)
        self._camera_panel.offset_spin.setValue(s.offset)
        self._camera_panel.offset_spin.blockSignals(False)

        # Bit depth
        idx = self._camera_panel.bit_depth_combo.findText(str(s.bit_depth))
        if idx >= 0:
            self._camera_panel.bit_depth_combo.setCurrentIndex(idx)

        # Recording panel
        self._recording_panel.output_dir_edit.setText(s.output_dir)
        idx = self._recording_panel.format_combo.findText(s.format_name)
        if idx >= 0:
            self._recording_panel.format_combo.setCurrentIndex(idx)
        idx = self._recording_panel.snap_format_combo.findText(s.snap_format)
        if idx >= 0:
            self._recording_panel.snap_format_combo.setCurrentIndex(idx)

        # Battery saver
        self._recording_panel.battery_saver_check.setChecked(s.battery_saver)

        # Lens
        self._lens_edit.setText(s.lens_description)

        # Sidebar width
        total = self.width() or 1024
        sidebar_w = max(150, min(s.sidebar_width, total - 400))
        self._splitter.setSizes([total - sidebar_w, sidebar_w])

    def _gather_settings(self) -> AppSettings:
        """Collect current UI state into an AppSettings."""
        return AppSettings(
            exposure_us=self._camera_panel.get_exposure_us(),
            gain=self._camera_panel.gain_spin.value(),
            offset=self._camera_panel.offset_spin.value(),
            bit_depth=self._camera_panel.selected_bit_depth,
            output_dir=self._recording_panel.output_dir_edit.text(),
            format_name=self._recording_panel.format_name,
            snap_format=self._recording_panel.snap_format,
            battery_saver=self._recording_panel.battery_saver_check.isChecked(),
            lens_description=self._lens_edit.text(),
            sidebar_width=self._splitter.sizes()[1] if len(self._splitter.sizes()) > 1 else 250,
            snap_sequence=self._settings.snap_sequence,
            record_queue_mb=self._settings.record_queue_mb,
            session_sequence=self._settings.session_sequence,
            hdr=self._settings.hdr,
        )

    # --- Cleanup ---

    def closeEvent(self, event: object) -> None:
        save_settings(self._gather_settings())
        if self._recorder is not None:
            self._finish_recording()
        if self._harness and self._harness.is_running():
            self._harness.stop()
        if self._camera.is_connected():
            self._camera.disconnect()
        super().closeEvent(event)
