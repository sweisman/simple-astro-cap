"""Camera options sidebar panel with keyboard navigation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QWidget,
)

from simple_astro_cap.camera.abc import CameraInfo, Param, ParamRange
from simple_astro_cap.util.units import ExposureUnit


@dataclass
class _Field:
    """A navigable field in the panel."""

    name: str
    label: QLabel | None  # row label (None for checkbox-only rows)
    widget: QWidget  # the interactive widget
    pre_connect: bool = False  # only visible before connect


class CameraPanel(QGroupBox):
    """Camera settings panel for the sidebar."""

    # Signals
    camera_selected = Signal(str)  # camera_id
    refresh_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    zoom_changed = Signal(object)  # float | None (None = fit)
    bin_changed = Signal(int)
    orientation_changed = Signal(bool)  # True = portrait
    exposure_changed = Signal(float)  # microseconds
    auto_exposure_toggled = Signal(bool)
    soft_auto_exposure_toggled = Signal(bool)
    gain_changed = Signal(float)
    auto_gain_toggled = Signal(bool)
    offset_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Camera", parent)
        self._fields: list[_Field] = []
        self._focus_idx: int = -1
        self._connected = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Helper to add a row and register it as a navigable field
        def add_field(name: str, label_text: str, widget: QWidget,
                      pre_connect: bool = False) -> QLabel | None:
            if label_text:
                lbl = QLabel(label_text)
                layout.addRow(lbl, widget)
            else:
                lbl = None
                layout.addRow("", widget)
            self._fields.append(_Field(name, lbl, widget, pre_connect))
            return lbl

        # --- Pre-connect settings ---

        cam_widget = QWidget()
        cam_layout = QHBoxLayout(cam_widget)
        cam_layout.setContentsMargins(0, 0, 0, 0)
        cam_layout.setSpacing(4)
        self.camera_combo = QComboBox()
        self.camera_combo.setToolTip("Select camera")
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(28)
        self.refresh_btn.setToolTip("Rescan for cameras")
        cam_layout.addWidget(self.camera_combo, 1)
        cam_layout.addWidget(self.refresh_btn)
        add_field("camera", "Camera:", cam_widget, pre_connect=True)
        self._camera_ids: list[str] = []
        self._has_placeholder: bool = False

        # Status + Connect button on one row
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: #cc4444; font-style: italic;")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setEnabled(False)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.connect_btn)
        layout.addRow(status_widget)

        self.bit_depth_combo = QComboBox()
        self.bit_depth_combo.addItems(["8", "16"])
        self.bit_depth_combo.setCurrentIndex(0)
        self.bit_depth_combo.setEnabled(False)
        add_field("bit_depth", "Bit depth:", self.bit_depth_combo, pre_connect=True)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setToolTip("Capture resolution (centered on sensor)")
        self.resolution_combo.addItem("Full (default)", None)
        self.resolution_combo.setEnabled(False)
        add_field("resolution", "Resolution:", self.resolution_combo, pre_connect=True)

        # --- Post-connect settings (disabled until connected) ---

        self.zoom_combo = QComboBox()
        self.zoom_combo.addItem("Fit", None)
        self.zoom_combo.setEnabled(False)
        self.zoom_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        add_field("zoom", "Zoom:", self.zoom_combo)

        self.bin_combo = QComboBox()
        self.bin_combo.setEnabled(False)
        self.bin_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        add_field("binning", "Binning:", self.bin_combo)

        orientation_widget = QWidget()
        orientation_layout = QHBoxLayout(orientation_widget)
        orientation_layout.setContentsMargins(0, 0, 0, 0)
        self.landscape_radio = QRadioButton("Landscape")
        self.portrait_radio = QRadioButton("Portrait")
        self.landscape_radio.setChecked(True)
        self.landscape_radio.setEnabled(False)
        self.portrait_radio.setEnabled(False)
        orientation_layout.addWidget(self.landscape_radio)
        orientation_layout.addWidget(self.portrait_radio)
        add_field("orientation", "Orientation:", orientation_widget)

        # Exposure
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(0)
        self.exposure_spin.setRange(0, 999)  # ms default range
        self.exposure_spin.setValue(5)
        self.exposure_spin.setKeyboardTracking(False)
        self.exposure_spin.setEnabled(False)

        self.exposure_unit_combo = QComboBox()
        for unit in ExposureUnit:
            self.exposure_unit_combo.addItem(unit.label, unit)
        self.exposure_unit_combo.setCurrentIndex(1)  # default ms
        self.exposure_unit_combo.setEnabled(False)

        exp_widget = QWidget()
        exp_layout = QFormLayout(exp_widget)
        exp_layout.setContentsMargins(0, 0, 0, 0)
        exp_layout.addRow(self.exposure_spin, self.exposure_unit_combo)
        add_field("exposure", "Exposure:", exp_widget)

        self.auto_exposure_check = QCheckBox("Auto-exposure (hardware)")
        self.auto_exposure_check.setEnabled(False)
        self.auto_exposure_check.setToolTip("Not supported by this camera")
        add_field("auto_exposure", "", self.auto_exposure_check)

        self.soft_auto_exposure_check = QCheckBox("Auto-exposure (software)")
        self.soft_auto_exposure_check.setEnabled(False)
        self.soft_auto_exposure_check.setToolTip("Software auto-exposure based on frame brightness")
        add_field("soft_auto_exposure", "", self.soft_auto_exposure_check)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(0)
        self.gain_spin.setRange(0, 100)
        self.gain_spin.setValue(50)
        self.gain_spin.setKeyboardTracking(False)
        self.gain_spin.setEnabled(False)
        add_field("gain", "Gain:", self.gain_spin)

        self.auto_gain_check = QCheckBox("Auto-gain")
        self.auto_gain_check.setEnabled(False)
        self.auto_gain_check.setToolTip("Not supported by this camera")
        add_field("auto_gain", "", self.auto_gain_check)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setDecimals(0)
        self.offset_spin.setRange(0, 255)
        self.offset_spin.setValue(10)
        self.offset_spin.setKeyboardTracking(False)
        self.offset_spin.setEnabled(False)
        self.offset_spin.setToolTip("ADC offset (black level)")
        add_field("offset", "Offset:", self.offset_spin)

        # Disable all labels except camera/status initially
        self._set_preconnect_labels_enabled(False)
        self._set_postconnect_labels_enabled(False)


    def _set_preconnect_labels_enabled(self, enabled: bool) -> None:
        """Enable/disable labels for pre-connect fields (bit depth, resolution, connect)."""
        for f in self._fields:
            if f.name in ("camera",):
                continue  # camera label always enabled
            if f.pre_connect or f.name == "connect":
                if f.label is not None:
                    f.label.setEnabled(enabled)

    def _set_postconnect_labels_enabled(self, enabled: bool) -> None:
        """Enable/disable labels for post-connect fields."""
        for f in self._fields:
            if f.name in ("camera",):
                continue
            if not f.pre_connect and f.name != "connect":
                if f.label is not None:
                    f.label.setEnabled(enabled)

    def _connect_signals(self) -> None:
        self.connect_btn.clicked.connect(self._on_connect_btn)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.camera_combo.currentIndexChanged.connect(self._on_camera_combo_changed)
        self.zoom_combo.currentIndexChanged.connect(
            lambda i: self.zoom_changed.emit(self.zoom_combo.currentData())
        )
        self.bin_combo.currentIndexChanged.connect(
            lambda i: self.bin_changed.emit(self.bin_combo.currentData()) if self.bin_combo.currentData() is not None else None
        )
        self.portrait_radio.toggled.connect(self.orientation_changed.emit)
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        self.exposure_unit_combo.currentIndexChanged.connect(self._on_exposure_changed)
        self.auto_exposure_check.toggled.connect(self._on_auto_exposure_toggled)
        self.soft_auto_exposure_check.toggled.connect(self._on_soft_auto_exposure_toggled)
        self.gain_spin.valueChanged.connect(lambda v: self.gain_changed.emit(v))
        self.auto_gain_check.toggled.connect(self._on_auto_gain_toggled)
        self.offset_spin.valueChanged.connect(lambda v: self.offset_changed.emit(v))

    # --- Keyboard navigation ---

    def _is_field_navigable(self, field: _Field) -> bool:
        """Can this field be focused right now?"""
        if field.pre_connect and self._connected:
            return False
        if not field.widget.isEnabled():
            return False
        return True

    def focus_field(self, name: str) -> None:
        """Jump focus to a named field."""
        for i, f in enumerate(self._fields):
            if f.name == name and self._is_field_navigable(f):
                self._set_focus(i)
                return

    def focus_next(self) -> None:
        """Move focus to next navigable field."""
        start = self._focus_idx + 1 if self._focus_idx >= 0 else 0
        for i in range(start, len(self._fields)):
            if self._is_field_navigable(self._fields[i]):
                self._set_focus(i)
                return

    def focus_prev(self) -> None:
        """Move focus to previous navigable field."""
        start = self._focus_idx - 1 if self._focus_idx >= 0 else len(self._fields) - 1
        for i in range(start, -1, -1):
            if self._is_field_navigable(self._fields[i]):
                self._set_focus(i)
                return

    def adjust_left(self) -> None:
        """Adjust current focused field to the left (decrease/previous)."""
        if self._focus_idx < 0:
            return
        field = self._fields[self._focus_idx]
        w = field.widget

        if field.name == "exposure":
            if not self.auto_exposure_check.isChecked():
                self._adjust_exposure(-1)
        elif field.name == "gain":
            if not self.auto_gain_check.isChecked():
                self.gain_spin.setValue(self.gain_spin.value() - self.gain_spin.singleStep())
        elif field.name == "connect":
            self.connect_btn.click()
        elif isinstance(w, QComboBox):
            if w.currentIndex() > 0:
                w.setCurrentIndex(w.currentIndex() - 1)
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(w.value() - w.singleStep())
        elif isinstance(w, QCheckBox):
            w.setChecked(not w.isChecked())

    def adjust_right(self) -> None:
        """Adjust current focused field to the right (increase/next)."""
        if self._focus_idx < 0:
            return
        field = self._fields[self._focus_idx]
        w = field.widget

        if field.name == "exposure":
            if not self.auto_exposure_check.isChecked():
                self._adjust_exposure(1)
        elif field.name == "gain":
            if not self.auto_gain_check.isChecked():
                self.gain_spin.setValue(self.gain_spin.value() + self.gain_spin.singleStep())
        elif field.name == "connect":
            self.connect_btn.click()
        elif isinstance(w, QComboBox):
            if w.currentIndex() < w.count() - 1:
                w.setCurrentIndex(w.currentIndex() + 1)
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(w.value() + w.singleStep())
        elif isinstance(w, QCheckBox):
            w.setChecked(not w.isChecked())

    def _adjust_exposure(self, direction: int) -> None:
        """Smart exposure stepping with automatic unit switching.

        us mode:  ±10us.  At >=1000us going up → switch to ms.
        ms mode:  ±1ms.   At <1ms going down → switch to us at 990us.
                           At >=1000ms going up → switch to s.
        s mode:   ±0.25s. At <1s going down → switch to ms at 990ms.
        """
        unit: ExposureUnit = self.exposure_unit_combo.currentData()
        val = self.exposure_spin.value()

        if unit == ExposureUnit.MICROSECONDS:
            new_val = val + direction * 10
            if direction > 0 and new_val >= 1000:
                # Switch to ms
                self._set_exposure_unit(ExposureUnit.MILLISECONDS, 1.0)
                return
            if new_val < 10:
                new_val = 10
            self.exposure_spin.setValue(new_val)

        elif unit == ExposureUnit.MILLISECONDS:
            new_val = val + direction * 1
            if direction < 0 and new_val < 1:
                # Switch to us
                self._set_exposure_unit(ExposureUnit.MICROSECONDS, 990.0)
                return
            if direction > 0 and new_val >= 1000:
                # Switch to s
                self._set_exposure_unit(ExposureUnit.SECONDS, 1.0)
                return
            self.exposure_spin.setValue(new_val)

        elif unit == ExposureUnit.SECONDS:
            new_val = val + direction * 0.25
            if direction < 0 and new_val < 1:
                # Switch to ms
                self._set_exposure_unit(ExposureUnit.MILLISECONDS, 990.0)
                return
            self.exposure_spin.setValue(new_val)

    def _set_exposure_unit(self, unit: ExposureUnit, display_val: float) -> None:
        """Switch exposure unit and set value, suppressing double-fire."""
        self.exposure_spin.blockSignals(True)
        self.exposure_unit_combo.blockSignals(True)

        # Find the combo index for this unit
        for i in range(self.exposure_unit_combo.count()):
            if self.exposure_unit_combo.itemData(i) == unit:
                self.exposure_unit_combo.setCurrentIndex(i)
                break

        # Set decimals and range per unit. Range allows hitting 0 at the
        # bottom so _on_exposure_changed can detect and trigger unit switch.
        if unit == ExposureUnit.MICROSECONDS:
            self.exposure_spin.setDecimals(0)
            self.exposure_spin.setRange(0, 1000)
        elif unit == ExposureUnit.MILLISECONDS:
            self.exposure_spin.setDecimals(0)
            self.exposure_spin.setRange(0, 1000)
        elif unit == ExposureUnit.SECONDS:
            self.exposure_spin.setDecimals(2)
            self.exposure_spin.setRange(0, 60000000)
        self.exposure_spin.setValue(display_val)

        self.exposure_spin.blockSignals(False)
        self.exposure_unit_combo.blockSignals(False)

        # Emit the change
        us = unit.to_us(display_val)
        self.exposure_changed.emit(us)

    def _set_focus(self, idx: int) -> None:
        """Set focus to field at index, updating label styling."""
        # Unbold previous
        if 0 <= self._focus_idx < len(self._fields):
            old = self._fields[self._focus_idx]
            self._set_label_bold(old, False)

        self._focus_idx = idx
        field = self._fields[idx]

        # Bold current
        self._set_label_bold(field, True)

        # Scroll the field into view
        self.ensureWidgetVisible(field.widget)

        # Give Qt focus to the interactive widget
        if field.name == "exposure":
            self.exposure_spin.setFocus()
        elif isinstance(field.widget, (QComboBox, QDoubleSpinBox, QCheckBox)):
            field.widget.setFocus()
        elif isinstance(field.widget, QPushButton):
            field.widget.setFocus()

    @staticmethod
    def _set_label_bold(field: _Field, bold: bool) -> None:
        """Bold or unbold the field's label (or the checkbox text)."""
        if field.label is not None:
            font = field.label.font()
            font.setBold(bold)
            field.label.setFont(font)
        elif isinstance(field.widget, QCheckBox):
            font = field.widget.font()
            font.setBold(bold)
            field.widget.setFont(font)

    def ensureWidgetVisible(self, widget: QWidget) -> None:
        """Scroll parent scroll area to make widget visible."""
        # Walk up to find QScrollArea
        parent = self.parent()
        while parent is not None:
            from PySide6.QtWidgets import QScrollArea
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget, 50, 50)
                return
            parent = parent.parent()

    # --- Signal handlers ---

    def _on_auto_exposure_toggled(self, checked: bool) -> None:
        if checked:
            # Mutual exclusion: disable software auto
            self.soft_auto_exposure_check.blockSignals(True)
            self.soft_auto_exposure_check.setChecked(False)
            self.soft_auto_exposure_check.blockSignals(False)
        self.exposure_spin.setEnabled(not checked and not self.soft_auto_exposure_check.isChecked())
        self.exposure_unit_combo.setEnabled(not checked and not self.soft_auto_exposure_check.isChecked())
        self.auto_exposure_toggled.emit(checked)

    def _on_soft_auto_exposure_toggled(self, checked: bool) -> None:
        if checked:
            # Mutual exclusion: disable hardware auto
            self.auto_exposure_check.blockSignals(True)
            self.auto_exposure_check.setChecked(False)
            self.auto_exposure_check.blockSignals(False)
        self.exposure_spin.setEnabled(not checked and not self.auto_exposure_check.isChecked())
        self.exposure_unit_combo.setEnabled(not checked and not self.auto_exposure_check.isChecked())
        self.soft_auto_exposure_toggled.emit(checked)

    def _on_auto_gain_toggled(self, checked: bool) -> None:
        self.gain_spin.setEnabled(not checked)
        self.auto_gain_toggled.emit(checked)

    def _on_connect_btn(self) -> None:
        if self.connect_btn.text() == "Connect":
            self.connect_requested.emit()
        else:
            self.disconnect_requested.emit()

    def _on_exposure_changed(self, _: object = None) -> None:
        unit: ExposureUnit = self.exposure_unit_combo.currentData()
        if unit is None:
            return
        val = self.exposure_spin.value()

        # Boundary detection for unit switching (handles native spin arrows)
        if unit == ExposureUnit.MICROSECONDS:
            if val <= 0:
                self.exposure_spin.setValue(10)
                return
            if val >= 1000:
                self._set_exposure_unit(ExposureUnit.MILLISECONDS, 1)
                return
        elif unit == ExposureUnit.MILLISECONDS:
            if val <= 0:
                self._set_exposure_unit(ExposureUnit.MICROSECONDS, 990)
                return
            if val >= 1000:
                self._set_exposure_unit(ExposureUnit.SECONDS, 1.0)
                return
        elif unit == ExposureUnit.SECONDS:
            if val <= 0:
                self._set_exposure_unit(ExposureUnit.MILLISECONDS, 990)
                return

        us = unit.to_us(val)
        self.exposure_changed.emit(us)

    # --- Public API ---

    def set_camera_list(self, cameras: list[CameraInfo]) -> None:
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        self._camera_ids = []
        self._has_placeholder = True
        self.camera_combo.addItem("-- Select camera --")
        for cam in cameras:
            self.camera_combo.addItem(cam.model)
            self._camera_ids.append(cam.camera_id)
        self.camera_combo.setCurrentIndex(0)
        self.connect_btn.setEnabled(False)
        self.camera_combo.blockSignals(False)

    def _on_camera_combo_changed(self, idx: int) -> None:
        if self._has_placeholder:
            if idx == 0:
                self.connect_btn.setEnabled(False)
                self.bit_depth_combo.setEnabled(False)
                self.resolution_combo.setEnabled(False)
                self._set_preconnect_labels_enabled(False)
                return
            self.camera_combo.blockSignals(True)
            self.camera_combo.removeItem(0)
            self._has_placeholder = False
            self.camera_combo.blockSignals(False)
            idx -= 1
        self.connect_btn.setEnabled(True)
        self.bit_depth_combo.setEnabled(True)
        self.resolution_combo.setEnabled(True)
        self._set_preconnect_labels_enabled(True)
        if 0 <= idx < len(self._camera_ids):
            self.camera_selected.emit(self._camera_ids[idx])

    def set_sensor_size(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        self.resolution_combo.clear()
        self.resolution_combo.addItem(f"{width}x{height} (Full)", (width, height))
        standard = [
            (3840, 2160), (3200, 1800), (2560, 1440), (1920, 1080),
            (1600, 900), (1280, 720), (1024, 768), (800, 600), (640, 480),
        ]
        for sw, sh in standard:
            if sw < width and sh < height:
                self.resolution_combo.addItem(f"{sw}x{sh}", (sw, sh))
        self.resolution_combo.setCurrentIndex(0)

    def set_auto_capabilities(
        self, auto_exposure: bool, auto_gain: bool,
    ) -> None:
        """Enable/disable auto checkboxes based on camera capabilities."""
        self.auto_exposure_check.setEnabled(auto_exposure)
        self.auto_gain_check.setEnabled(auto_gain)
        if not auto_exposure:
            self.auto_exposure_check.setChecked(False)
            self.auto_exposure_check.setToolTip("Not supported by this camera")
        else:
            self.auto_exposure_check.setToolTip("")
        if not auto_gain:
            self.auto_gain_check.setChecked(False)
            self.auto_gain_check.setToolTip("Not supported by this camera")
        else:
            self.auto_gain_check.setToolTip("")

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        self.status_label.setText("Connected" if connected else "Disconnected")
        self.status_label.setStyleSheet(
            "color: green;" if connected else "color: #cc4444; font-style: italic;"
        )
        # Pre-connect controls
        self.camera_combo.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        self.bit_depth_combo.setEnabled(not connected)
        self.resolution_combo.setEnabled(not connected)
        self._set_preconnect_labels_enabled(not connected)
        # Post-connect controls
        self.zoom_combo.setEnabled(connected)
        self.bin_combo.setEnabled(connected)
        self.landscape_radio.setEnabled(connected)
        self.portrait_radio.setEnabled(connected)
        self.exposure_spin.setEnabled(connected)
        self.exposure_unit_combo.setEnabled(connected)
        self.gain_spin.setEnabled(connected)
        self.offset_spin.setEnabled(connected)
        self.soft_auto_exposure_check.setEnabled(connected)
        self._set_postconnect_labels_enabled(connected)
        if not connected:
            # Reset auto checkboxes when disconnecting
            self.auto_exposure_check.setChecked(False)
            self.auto_exposure_check.setEnabled(False)
            self.auto_gain_check.setChecked(False)
            self.auto_gain_check.setEnabled(False)
            self.soft_auto_exposure_check.setChecked(False)

    def set_recording(self, recording: bool) -> None:
        self.connect_btn.setEnabled(not recording)
        self.bin_combo.setEnabled(not recording)
        self.landscape_radio.setEnabled(not recording)
        self.portrait_radio.setEnabled(not recording)

    def set_bin_modes(self, modes: list[int], sensor_w: int = 0, sensor_h: int = 0) -> None:
        self.bin_combo.blockSignals(True)
        self.bin_combo.clear()
        for m in sorted(modes):
            if sensor_w and sensor_h:
                label = f"{m}x{m} ({sensor_w // m}x{sensor_h // m})"
            else:
                label = f"{m}x{m}"
            self.bin_combo.addItem(label, m)
        self.bin_combo.setCurrentIndex(0)
        self.bin_combo.blockSignals(False)

    def set_zoom_levels(self, levels: list[tuple[str, float | None]]) -> None:
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.clear()
        for label, scale in levels:
            self.zoom_combo.addItem(label, scale)
        self.zoom_combo.setCurrentIndex(0)
        self.zoom_combo.blockSignals(False)

    def set_param_range(self, param: Param, prange: ParamRange) -> None:
        if param == Param.GAIN:
            self.gain_spin.blockSignals(True)
            self.gain_spin.setRange(prange.min_val, prange.max_val)
            self.gain_spin.setSingleStep(prange.step)
            self.gain_spin.blockSignals(False)
        elif param == Param.OFFSET:
            self.offset_spin.blockSignals(True)
            self.offset_spin.setRange(prange.min_val, prange.max_val)
            self.offset_spin.setSingleStep(prange.step)
            self.offset_spin.blockSignals(False)
        elif param == Param.EXPOSURE:
            # Range is managed by unit-switching logic in _set_exposure_unit.
            # Camera SDK enforces actual limits independently.
            pass

    @property
    def selected_bit_depth(self) -> int:
        t = self.bit_depth_combo.currentText()
        return int(t) if t else 8

    @property
    def selected_camera_id(self) -> str | None:
        idx = self.camera_combo.currentIndex()
        if 0 <= idx < len(self._camera_ids):
            return self._camera_ids[idx]
        return None

    @property
    def selected_resolution(self) -> tuple[int, int] | None:
        return self.resolution_combo.currentData()

    def get_exposure_us(self) -> float:
        unit: ExposureUnit = self.exposure_unit_combo.currentData()
        return unit.to_us(self.exposure_spin.value())

    def display_exposure_us(self, us: float) -> None:
        """Update the displayed exposure value without emitting signals."""
        unit: ExposureUnit = self.exposure_unit_combo.currentData()
        if unit is None:
            return
        display_val = unit.from_us(us)
        self.exposure_spin.blockSignals(True)
        self.exposure_spin.setValue(display_val)
        self.exposure_spin.blockSignals(False)

    def display_gain(self, value: float) -> None:
        """Update the displayed gain value without emitting signals."""
        self.gain_spin.blockSignals(True)
        self.gain_spin.setValue(value)
        self.gain_spin.blockSignals(False)
