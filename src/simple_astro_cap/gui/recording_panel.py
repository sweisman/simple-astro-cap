"""Recording options sidebar panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)


class RecordingPanel(QGroupBox):
    """Recording controls for the sidebar."""

    capture_single_requested = Signal()
    record_start_requested = Signal()
    record_stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Recording", parent)
        self._recording = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Output directory
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("~/astro-captures")
        self.output_dir_edit.setText(str(Path.home() / "astro-captures"))
        self.browse_btn = QPushButton("Browse...")
        dir_widget = QWidget()
        dir_layout = QFormLayout(dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addRow(self.output_dir_edit, self.browse_btn)
        layout.addRow("Output:", dir_widget)

        # Format
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "SER", "MKV"])
        layout.addRow("Format:", self.format_combo)

        # Time (seconds)
        self.time_spin = QSpinBox()
        self.time_spin.setRange(0, 999999)
        self.time_spin.setValue(0)
        self.time_spin.setSpecialValueText("--")
        self.time_spin.setSuffix(" s")
        self.time_spin.setToolTip("Recording duration in seconds (0 = no limit)")
        layout.addRow("Time:", self.time_spin)

        # Frame count
        self.frame_count_spin = QSpinBox()
        self.frame_count_spin.setRange(0, 999999)
        self.frame_count_spin.setValue(0)
        self.frame_count_spin.setSpecialValueText("--")
        self.frame_count_spin.setToolTip("Number of frames to record (0 = no limit)")
        layout.addRow("Frames:", self.frame_count_spin)

        # Snap format + button
        self.snap_format_combo = QComboBox()
        self.snap_format_combo.addItems(["PNG", "TIFF"])
        self.snap_format_combo.setToolTip("Snapshot image format")
        self.snap_btn = QPushButton("Snap [Space]")
        self.snap_btn.setToolTip("Capture a single frame")
        snap_widget = QWidget()
        snap_layout = QFormLayout(snap_widget)
        snap_layout.setContentsMargins(0, 0, 0, 0)
        snap_layout.addRow(self.snap_format_combo, self.snap_btn)
        layout.addRow("Snap:", snap_widget)

        # Record button
        self.record_btn = QPushButton("Record [R]")
        self.record_btn.setStyleSheet("")
        layout.addRow(self.record_btn)

    def _connect_signals(self) -> None:
        self.snap_btn.clicked.connect(self.capture_single_requested.emit)
        self.record_btn.clicked.connect(self._on_record_btn)
        self.browse_btn.clicked.connect(self._on_browse)

    def _on_record_btn(self) -> None:
        if self._recording:
            self.record_stop_requested.emit()
        else:
            self.record_start_requested.emit()

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.output_dir_edit.text()
        )
        if path:
            self.output_dir_edit.setText(path)

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        if recording:
            self.record_btn.setText("Stop [R]")
            self.record_btn.setStyleSheet("background-color: #cc3333; color: white;")
        else:
            self.record_btn.setText("Record [R]")
            self.record_btn.setStyleSheet("")
        # Lock settings that must not change during recording
        self.format_combo.setEnabled(not recording)
        self.output_dir_edit.setEnabled(not recording)
        self.browse_btn.setEnabled(not recording)
        self.time_spin.setEnabled(not recording)
        self.frame_count_spin.setEnabled(not recording)
        self.snap_btn.setEnabled(not recording)
        self.snap_format_combo.setEnabled(not recording)

    @property
    def output_dir(self) -> Path:
        return Path(self.output_dir_edit.text()).expanduser()

    @property
    def format_name(self) -> str:
        return self.format_combo.currentText()

    @property
    def max_time(self) -> float:
        """Recording duration in seconds, or 0 for no limit."""
        return float(self.time_spin.value())

    @property
    def snap_format(self) -> str:
        return self.snap_format_combo.currentText()

    @property
    def max_frames(self) -> int | None:
        v = self.frame_count_spin.value()
        return v if v > 0 else None
