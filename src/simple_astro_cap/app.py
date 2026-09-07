"""Application entry point."""

from __future__ import annotations

import logging
import signal
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from simple_astro_cap.gui.main_window import MainWindow

log = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    debug = "--debug" in argv or "-d" in argv
    use_sim = "--sim" in argv

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    app = QApplication(argv)
    app.setApplicationName("Simple Astro Cap")
    app.setQuitOnLastWindowClosed(True)

    if use_sim:
        from simple_astro_cap.camera.sim.backend import SimCamera
        camera = SimCamera()
    else:
        from simple_astro_cap.camera.multi import MultiCamera
        camera = MultiCamera()

    try:
        window = MainWindow(camera)
    except Exception:
        log.exception("Failed to create main window")
        return 1

    window.show()

    # Ctrl+C: close the window cleanly (closeEvent finalises any recording
    # and saves settings) instead of aborting mid-write. Python signal
    # handlers only run while the interpreter executes Python code, so a
    # no-op timer gives Qt's event loop a chance to service them.
    signal.signal(signal.SIGINT, lambda *_: window.close())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)

    log.info("Window shown, entering event loop")
    ret = app.exec()
    log.info("Event loop exited with code %d", ret)
    return ret
