from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from simple_astro_cap import settings
from simple_astro_cap.camera.sim.backend import SimCamera
from simple_astro_cap.gui.main_window import MainWindow
from simple_astro_cap.recording.png_recorder import PngRecorder


def wait_for(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "_SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(settings, "_SETTINGS_FILE", tmp_path / "settings.json")
    dialogs = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: dialogs.append(args[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: dialogs.append(args[2]))
    win = MainWindow(SimCamera())
    win._recording_panel.output_dir_edit.setText(str(tmp_path / "captures"))
    win._recording_panel.format_combo.setCurrentText("PNG")
    panel = win._camera_panel
    panel.camera_combo.setCurrentIndex(1)
    panel.resolution_combo.addItem("32x24 test", (32, 24))
    panel.resolution_combo.setCurrentIndex(panel.resolution_combo.count() - 1)
    win._on_connect()
    yield app, win, dialogs
    if win._recorder is not None:
        win._finish_recording()
        wait_for(app, lambda: win._recorder is None)
    win.close()
    app.processEvents()


@pytest.mark.parametrize("action", ["stop", "disconnect", "close"])
def test_stalled_writer_keeps_gui_responsive(window, monkeypatch, action):
    app, win, dialogs = window
    entered, release = threading.Event(), threading.Event()
    original = PngRecorder._write_frame

    def blocked(rec, frame):
        entered.set()
        assert release.wait(3)
        original(rec, frame)

    monkeypatch.setattr(PngRecorder, "_write_frame", blocked)
    win._on_start_recording()
    assert entered.wait(1)
    recorder = win._recorder
    try:
        {"stop": win._on_stop_recording, "disconnect": win._on_disconnect,
         "close": win.close}[action]()
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        wait_for(app, lambda: bool(heartbeat))
        assert win._finish_thread.is_alive()
        assert win._recorder is recorder
        assert not win._recording_panel.record_btn.isEnabled()
        win._on_start_recording()
        assert win._recorder is recorder
        if action != "stop":
            assert win._camera.is_connected()  # shutdown waits for file completion
    finally:
        release.set()
    wait_for(app, lambda: win._recorder is None)
    if action != "stop":
        assert not win._camera.is_connected()
    assert not dialogs


def test_auto_controls_and_shortcuts_stay_locked(window):
    app, win, dialogs = window
    panel = win._camera_panel
    panel.set_auto_capabilities(True, True)
    panel.soft_auto_exposure_check.setChecked(True)
    win._on_start_recording()
    checks = [panel.auto_exposure_check, panel.auto_gain_check, panel.soft_auto_exposure_check]
    before = [w.isChecked() for w in checks]
    assert all(not w.isEnabled() for w in checks)
    for key in (Qt.Key.Key_X, Qt.Key.Key_G):
        win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.ControlModifier))
    assert [w.isChecked() for w in checks] == before
    win._finish_recording()
    wait_for(app, lambda: win._recorder is None)
    assert all(w.isEnabled() for w in checks)
    assert [w.isChecked() for w in checks] == before


def test_duration_stops_even_without_incoming_frames(window, monkeypatch):
    app, win, dialogs = window
    def no_frame(timeout_ms=500):
        time.sleep(0.005)
        return None
    monkeypatch.setattr(win._camera, "get_live_frame", no_frame)
    win._recording_panel.time_spin.setValue(1)
    win._on_start_recording()
    win._recorder._capture_deadline_ns = time.monotonic_ns() - 1
    win._update_fps()
    wait_for(app, lambda: win._recorder is None)
    assert "Time limit reached" in win._status_rec.text()
    assert not dialogs


def test_finalization_error_never_claims_saved(window, monkeypatch):
    app, win, dialogs = window
    original = PngRecorder.stop
    def fail(rec):
        original(rec)
        raise OSError("finalization failed")
    monkeypatch.setattr(PngRecorder, "stop", fail)
    win._on_start_recording()
    win._finish_recording()
    wait_for(app, lambda: win._recorder is None)
    assert "Saved" not in win._status_rec.text()
    assert "STOPPED ON ERROR" in win._status_rec.text()
    assert len(dialogs) == 1 and "finalization failed" in dialogs[0]


def test_flush_timeout_remains_an_error_when_last_frame_completes(window, monkeypatch):
    app, win, dialogs = window
    entered, release = threading.Event(), threading.Event()
    original = PngRecorder._write_frame
    def blocked(rec, frame):
        entered.set()
        assert release.wait(3)
        original(rec, frame)
    monkeypatch.setattr(PngRecorder, "_write_frame", blocked)
    monkeypatch.setattr("simple_astro_cap.gui.main_window._RECORD_DRAIN_TIMEOUT_S", 0.02)
    win._recording_panel.frame_count_spin.setValue(1)
    win._on_start_recording()
    assert entered.wait(1)
    recorder = win._recorder
    try:
        win._finish_recording()
        wait_for(app, lambda: recorder.error is not None)
        assert recorder._cancel_io.is_set()
    finally:
        release.set()
    wait_for(app, lambda: win._recorder is None)
    assert recorder.stop_reason == "error"
    assert len(dialogs) == 1 and "flush timed out" in dialogs[0]
    assert "Saved" not in win._status_rec.text()
